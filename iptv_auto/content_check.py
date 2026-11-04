"""Conservative OCR-based IPTV content consistency checks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .database import database_session


MAX_CANDIDATES_PER_CHANNEL = 5
MAX_CONCURRENCY = 3
MAX_TIMEOUT_SECONDS = 15
SAMPLE_TIMES = (1, 4, 7)
SUPPORTED_ENVIRONMENTS = {"cloud"}

# 只有明确、重复出现的文字证据才会触发确认。
KEYWORDS = {
    "advertisement": (
        "广告",
        "广告时间",
        "广告中",
        "广告播放",
    ),
    "no_signal": (
        "无信号",
        "暂无信号",
        "没有信号",
        "信号中断",
        "信号丢失",
    ),
    "placeholder": (
        "测试频道",
        "测试信号",
        "占位频道",
        "暂无节目",
        "节目暂无",
    ),
}


@dataclass(frozen=True)
class ContentCheckRecord:
    channel_id: str
    line_id: str
    status: str
    category: str
    successful_ocr_frames: int
    evidence: dict[str, Any]


@dataclass(frozen=True)
class ContentCheckRunResult:
    run_id: int
    environment_type: str
    selected_count: int
    checked_count: int
    clean_count: int
    confirmed_count: int
    unknown_count: int
    blacklisted_count: int
    records: tuple[ContentCheckRecord, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _resolve_binary(value: str | Path | None, name: str) -> str | None:
    if value is None:
        return shutil.which(name)

    text = str(value).strip()
    if not text:
        return None

    path = Path(text)
    if path.is_absolute() or path.parent != Path("."):
        return str(path) if path.is_file() else None

    return shutil.which(text)


def _header_args(headers: dict[str, Any]) -> list[str]:
    lines = []

    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if not key.strip() or "\r" in key or "\n" in key:
            continue
        if "\r" in value or "\n" in value:
            continue
        lines.append(f"{key}: {value}")

    if not lines:
        return []

    return ["-headers", "\r\n".join(lines) + "\r\n"]


def _extract_frame(
    ffmpeg_binary: str,
    url: str,
    headers: dict[str, Any],
    second: int,
) -> tuple[bytes | None, str]:
    """Extract one small PNG frame; failures remain unknown."""
    command = [
        ffmpeg_binary,
        "-hide_banner",
        "-nostdin",
        "-loglevel", "error",
        "-rw_timeout", "8000000",
        "-i", url,
        "-ss", str(second),
        "-frames:v", "1",
        "-vf", "scale=640:-2",
        "-f", "image2pipe",
        "-vcodec", "png",
        *_header_args(headers),
        "pipe:1",
    ]

    # FFmpeg expects input headers before the input URL.
    header_args = _header_args(headers)
    if header_args:
        command.remove("-i")
        command.remove(url)
        insert_at = command.index("-rw_timeout") + 2
        command[insert_at:insert_at] = header_args
        insert_at = command.index("-rw_timeout") + 2 + len(header_args)
        command[insert_at:insert_at] = ["-i", url]

    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=MAX_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "ffmpeg_timeout"
    except OSError as exc:
        return None, f"ffmpeg_error_{type(exc).__name__}"

    if result.returncode != 0 or not result.stdout:
        return None, "frame_unavailable"

    return result.stdout, "ok"


def _recognize_text(
    tesseract_binary: str,
    frame: bytes,
) -> tuple[str, str]:
    """Chinese OCR. Missing language data is unknown, never clean."""
    command = [
        tesseract_binary,
        "stdin",
        "stdout",
        "-l",
        "chi_sim+eng",
        "--psm",
        "6",
    ]

    try:
        result = subprocess.run(
            command,
            input=frame,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", "ocr_timeout"
    except OSError as exc:
        return "", f"ocr_error_{type(exc).__name__}"

    if result.returncode != 0:
        return "", "ocr_failed"

    text = result.stdout.decode("utf-8", errors="replace").strip()
    return text[:2000], "ok"


def _classify_text(text: str) -> set[str]:
    normalized = "".join(text.split()).lower()
    found = set()

    for category, words in KEYWORDS.items():
        if any(word.lower() in normalized for word in words):
            found.add(category)

    return found


def _select_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select no more than five unique lines per channel."""
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        grouped.setdefault(row["channel_id"], []).append(row)

    selected = []
    seen: set[str] = set()

    for channel_id in sorted(grouped):
        items = sorted(
            grouped[channel_id],
            key=lambda item: item["line_id"],
        )
        count = 0

        for item in items:
            if count >= MAX_CANDIDATES_PER_CHANNEL:
                break

            line_id = item["line_id"]
            if line_id in seen:
                continue

            seen.add(line_id)
            selected.append(item)
            count += 1

    return selected


def _blacklist_confirmed(
    db,
    line_id: str,
    url: str,
    category: str,
    evidence: dict[str, Any],
) -> None:
    """Add line and URL blacklist entries only for confirmed content flags."""
    reason = f"confirmed_{category}_content"
    timestamp = _now()
    evidence_json = json.dumps(evidence, ensure_ascii=False)

    for target_type, target_id in (
        ("line", line_id),
        ("url", url),
    ):
        existing = db.execute(
            """
            SELECT 1
              FROM blacklists
             WHERE target_type = ?
               AND target_id = ?
               AND active = 1
             LIMIT 1
            """,
            (target_type, target_id),
        ).fetchone()

        if existing is None:
            db.execute(
                """
                INSERT INTO blacklists
                    (target_type, target_id, reason,
                     evidence_json, created_at, active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    target_type,
                    target_id,
                    reason,
                    evidence_json,
                    timestamp,
                ),
            )


def _check_one(
    item: dict[str, Any],
    *,
    ffmpeg_binary: str,
    tesseract_binary: str,
) -> ContentCheckRecord:
    try:
        headers = json.loads(item["headers_json"] or "{}")
    except (TypeError, ValueError):
        headers = {}

    if not isinstance(headers, dict):
        headers = {}

    frame_evidence = []
    category_counts = {
        "advertisement": 0,
        "no_signal": 0,
        "placeholder": 0,
    }
    successful_ocr = 0

    for second in SAMPLE_TIMES:
        frame, frame_state = _extract_frame(
            ffmpeg_binary,
            item["url"],
            headers,
            second,
        )

        if frame is None:
            frame_evidence.append({
                "second": second,
                "frame_state": frame_state,
                "ocr_state": "not_run",
                "text": "",
                "flags": [],
            })
            continue

        text, ocr_state = _recognize_text(tesseract_binary, frame)
        flags = sorted(_classify_text(text)) if ocr_state == "ok" else []

        if ocr_state == "ok":
            successful_ocr += 1
            for flag in flags:
                category_counts[flag] += 1

        frame_evidence.append({
            "second": second,
            "frame_state": frame_state,
            "ocr_state": ocr_state,
            "text": text[:1000],
            "flags": flags,
        })

    confirmed = [
        category
        for category, count in category_counts.items()
        if count >= 2
    ]

    evidence = {
        "engine": "ffmpeg_tesseract",
        "environment_type": "cloud",
        "sample_times_seconds": list(SAMPLE_TIMES),
        "successful_ocr_frames": successful_ocr,
        "required_matching_frames": 2,
        "frame_results": frame_evidence,
        "category_counts": category_counts,
        "checked_at": _now(),
    }

    if confirmed:
        category = sorted(confirmed)[0]
        status = "confirmed"
        evidence.update({
            "content_class": category,
            "ad_detected": category == "advertisement",
            "placeholder_detected": category in {
                "placeholder",
                "no_signal",
            },
        })
    elif successful_ocr >= 2:
        category = "none_detected"
        status = "no_flag_detected"
        evidence.update({
            "content_class": "clean",
            "ad_detected": False,
            "placeholder_detected": False,
            "note": (
                "未识别到明确异常关键词；这不等于人工确认画面完全正常"
            ),
        })
    else:
        category = "unknown"
        status = "unknown"
        evidence.update({
            "content_class": "unknown",
            "ad_detected": None,
            "placeholder_detected": None,
            "note": "有效OCR帧不足，不能判定线路内容正常或异常",
        })

    return ContentCheckRecord(
        channel_id=item["channel_id"],
        line_id=item["line_id"],
        status=status,
        category=category,
        successful_ocr_frames=successful_ocr,
        evidence=evidence,
    )


def run_content_checks(
    database_path: str | Path,
    run_id: int,
   
