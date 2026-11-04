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
from urllib.parse import urlsplit

from .database import database_session
from .ffmpeg_ipv4 import ffmpeg_ipv4_input_options
from .identity import normalize_url


MAX_CANDIDATES_PER_CHANNEL = 5
MAX_CONCURRENCY = 3
MAX_TIMEOUT_SECONDS = 15
MAX_OCR_TIMEOUT_SECONDS = 10
MAX_FRAME_BYTES = 4 * 1024 * 1024
SAMPLE_TIMES = (1, 4, 7)
SUPPORTED_ENVIRONMENTS = {"cloud"}

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


def _resolve_binary(
    value: str | Path | None,
    name: str,
) -> str | None:
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
    lines: list[str] = []

    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue

        if not key.strip():
            continue

        if any(char in key for char in "\r\n:"):
            continue

        if "\r" in value or "\n" in value:
            continue

        lines.append(f"{key}: {value}")

    if not lines:
        return []

    return [
        "-headers",
        "\r\n".join(lines) + "\r\n",
    ]


def _extract_frame(
    ffmpeg_binary: str,
    url: str,
    headers: dict[str, Any],
    second: int,
) -> tuple[bytes | None, str]:
    """Extract one scaled PNG frame; errors remain unknown."""
    ipv4_options = ffmpeg_ipv4_input_options(url)

    if ipv4_options is None:
        return None, "ipv4_transport_not_enforceable"

    command = [
        ffmpeg_binary,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-rw_timeout",
        "8000000",
        *_header_args(headers),
        *ipv4_options,
        "-i",
        url,
        "-ss",
        str(second),
        "-frames:v",
        "1",
        "-vf",
        "scale=640:-2",
        "-threads",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "pipe:1",
    ]

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

    if result.returncode != 0:
        return None, "frame_unavailable"

    if not result.stdout:
        return None, "empty_frame"

    if len(result.stdout) > MAX_FRAME_BYTES:
        return None, "frame_too_large"

    return result.stdout, "ok"


def _recognize_text(
    tesseract_binary: str,
    frame: bytes,
) -> tuple[str, str]:
    """Recognize Chinese and English text from one image."""
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
            timeout=MAX_OCR_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "", "ocr_timeout"
    except OSError as exc:
        return "", f"ocr_error_{type(exc).__name__}"

    if result.returncode != 0:
        return "", "ocr_failed"

    text = result.stdout.decode(
        "utf-8",
        errors="replace",
    ).strip()

    return text[:2000], "ok"


def _classify_text(text: str) -> set[str]:
    normalized = "".join(text.split()).lower()
    found: set[str] = set()

    for category, words in KEYWORDS.items():
        if any(word.lower() in normalized for word in words):
            found.add(category)

    return found


def _select_lines(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select the highest-scoring unique eligible lines per channel."""
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        grouped.setdefault(row["channel_id"], []).append(row)

    selected: list[dict[str, Any]] = []
    seen_line_ids: set[str] = set()

    for channel_id in sorted(grouped):
        items = sorted(
            grouped[channel_id],
            key=lambda item: (
                -float(item.get("total_score") or 0.0),
                item["line_id"],
            ),
        )

        count = 0

        for item in items:
            if count >= MAX_CANDIDATES_PER_CHANNEL:
                break

            line_id = item["line_id"]

            if line_id in seen_line_ids:
                continue

            seen_line_ids.add(line_id)
            selected.append(item)
            count += 1

    return selected


def _unknown_record(
    item: dict[str, Any],
    reason: str,
    *,
    missing_tools: list[str] | None = None,
) -> ContentCheckRecord:
    evidence: dict[str, Any] = {
        "engine": "ffmpeg_tesseract",
        "content_check_version": 1,
        "environment_type": "cloud",
        "status": "unknown",
        "content_class": "unknown",
        "ad_detected": None,
        "placeholder_detected": None,
        "sample_times_seconds": list(SAMPLE_TIMES),
        "successful_ocr_frames": 0,
        "required_matching_frames": 2,
        "frame_results": [],
        "category_counts": {
            "advertisement": 0,
            "no_signal": 0,
            "placeholder": 0,
        },
        "reason": reason,
        "checked_at": _now(),
    }

    if missing_tools:
        evidence["missing_tools"] = missing_tools

    return ContentCheckRecord(
        channel_id=item["channel_id"],
        line_id=item["line_id"],
        status="unknown",
        category="unknown",
        successful_ocr_frames=0,
        evidence=evidence,
    )


def _check_one(
    item: dict[str, Any],
    *,
    ffmpeg_binary: str,
    tesseract_binary: str,
) -> ContentCheckRecord:
    url = item["url"]
    ipv4_options = ffmpeg_ipv4_input_options(url)

    if ipv4_options is None:
        record = _unknown_record(
            item,
            "ipv4_transport_not_enforceable_for_protocol",
        )
        record.evidence["ipv4_transport"] = {
            "status": "not_enforceable",
            "protocol": urlsplit(url).scheme.lower(),
        }
        return record

    try:
        headers = json.loads(item["headers_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        headers = {}

    if not isinstance(headers, dict):
        headers = {}

    frame_evidence: list[dict[str, Any]] = []

    category_counts = {
        "advertisement": 0,
        "no_signal": 0,
        "placeholder": 0,
    }

    successful_ocr = 0

    for second in SAMPLE_TIMES:
        try:
            frame, frame_state = _extract_frame(
                ffmpeg_binary,
                url,
                headers,
                second,
            )
        except Exception as exc:
            frame = None
            frame_state = f"frame_exception_{type(exc).__name__}"

        if frame is None:
            frame_evidence.append({
                "second": second,
                "frame_state": frame_state,
                "ocr_state": "not_run",
                "text": "",
                "flags": [],
            })
            continue

        try:
            text, ocr_state = _recognize_text(
                tesseract_binary,
                frame,
            )
        except Exception as exc:
            text = ""
            ocr_state = f"ocr_exception_{type(exc).__name__}"

        flags = (
            sorted(_classify_text(text))
            if ocr_state == "ok"
            else []
        )

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

    evidence: dict[str, Any] = {
        "engine": "ffmpeg_tesseract",
        "content_check_version": 1,
        "environment_type": "cloud",
        "ipv4_transport": {
            "status": "configured",
            "method": "tcp_local_addr",
            "local_addr": "0.0.0.0",
            "protocol": urlsplit(url).scheme.lower(),
        },
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
                "未识别到明确异常关键词；"
                "这不等于人工确认画面完全正常"
            ),
        })

    else:
        category = "unknown"
        status = "unknown"

        evidence.update({
            "content_class": "unknown",
            "ad_detected": None,
            "placeholder_detected": None,
            "note": (
                "有效OCR帧不足，"
                "不能判定线路内容正常或异常"
            ),
        })

    evidence["status"] = status

    return ContentCheckRecord(
        channel_id=item["channel_id"],
        line_id=item["line_id"],
        status=status,
        category=category,
        successful_ocr_frames=successful_ocr,
        evidence=evidence,
    )


def _blacklist_confirmed(
    db,
    line_id: str,
    url: str,
    category: str,
    evidence: dict[str, Any],
) -> bool:
    """Blacklist confirmed content problems by line ID and URL identities."""
    if category not in {
        "advertisement",
        "no_signal",
        "placeholder",
    }:
        return False

    reason = f"confirmed_{category}_content"
    timestamp = _now()

    evidence_json = json.dumps(
        evidence,
        ensure_ascii=False,
    )

    # Save both URL forms so equivalent URL spellings cannot bypass
    # the blacklist during a later source ingestion.
    normalized = normalize_url(url)
    targets = [
        ("line", line_id),
        ("url", url),
        ("url", normalized),
    ]

    inserted = False
    processed: set[tuple[str, str]] = set()

    for target_type, target_id in targets:
        target = (target_type, target_id)

        # Avoid duplicate inserts when the raw and normalized URLs match.
        if target in processed:
            continue
        processed.add(target)

        existing = db.execute(
            """
            SELECT 1
              FROM blacklists
             WHERE target_type = ?
               AND target_id = ?
               AND active = 1
             LIMIT 1
            """,
            target,
        ).fetchone()

        if existing is not None:
            continue

        db.execute(
            """
            INSERT INTO blacklists
                (
                    target_type,
                    target_id,
                    reason,
                    evidence_json,
                    created_at,
                    active
                )
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

        inserted = True

    return inserted


def _already_checked(evidence_json: str) -> bool:
    """Skip only completed content checks; unknown results can be retried."""
    try:
        evidence = json.loads(evidence_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return False

    if not isinstance(evidence, dict):
        return False

    result = evidence.get("content_check")

    if not isinstance(result, dict):
        return False

    return result.get("status") in {
        "no_flag_detected",
        "confirmed",
    }


def _save_record(
    database_path: str | Path,
    run_id: int,
    runner_identity: str,
    item: dict[str, Any],
    record: ContentCheckRecord,
) -> bool:
    """Merge content evidence without overwriting FFprobe evidence."""
    blacklisted = False

    with database_session(database_path) as db:
        row = db.execute(
            """
            SELECT evidence_json
              FROM deep_probes
             WHERE run_id = ?
               AND line_id = ?
               AND runner_identity = ?
               AND environment_type = 'cloud'
               AND status = 'passed'
            """,
            (
                run_id,
                record.line_id,
                runner_identity,
            ),
        ).fetchone()

        if row is None:
            return False

        try:
            original = json.loads(row["evidence_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            original = {}

        if not isinstance(original, dict):
            original = {}

        # Keep completed results, but allow unknown results to be retried.
        existing = original.get("content_check")
        if isinstance(existing, dict) and existing.get("status") in {
            "no_flag_detected",
            "confirmed",
        }:
            return False

        original["content_check"] = record.evidence

        db.execute(
            """
            UPDATE deep_probes
               SET evidence_json = ?
             WHERE run_id = ?
               AND line_id = ?
               AND runner_identity = ?
               AND environment_type = 'cloud'
               AND status = 'passed'
            """,
            (
                json.dumps(original, ensure_ascii=False),
                run_id,
                record.line_id,
                runner_identity,
            ),
        )

        if record.status == "confirmed":
            blacklisted = _blacklist_confirmed(
                db,
                record.line_id,
                item["url"],
                record.category,
                record.evidence,
            )

    return blacklisted


def run_content_checks(
    database_path: str | Path,
    run_id: int,
    *,
    runner_identity: str,
    environment_type: str = "cloud",
    ffmpeg_binary: str | Path | None = None,
    tesseract_binary: str | Path | None = None,
    max_concurrency: int = MAX_CONCURRENCY,
) -> ContentCheckRunResult:
    """Check scored, deep-probe-passed lines from the current run.

    Results are merged into deep_probes.evidence_json under the
    'content_check' key. Existing FFprobe evidence is preserved.

    Only lines explicitly admitted by this run's scoring stage are
    considered. Active line and URL blacklists are excluded.

    Only explicit repeated OCR evidence can create a blacklist entry.
    Unknown results are not considered clean and are not blacklisted.
    """
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run_id 必须是正整数")

    if not isinstance(runner_identity, str) or not runner_identity.strip():
        raise ValueError("runner_identity 必须是非空文本")

    if environment_type not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(
            "内容检查目前只允许 cloud，"
            "不能冒充福建移动家庭实测"
        )

    if type(max_concurrency) is not int or not (
        1 <= max_concurrency <= MAX_CONCURRENCY
    ):
        raise ValueError(
            "内容检查并发数必须是1至3之间的整数"
        )

    selected: list[dict[str, Any]] = []

    with database_session(database_path) as db:
        run = db.execute(
            """
            SELECT runner_identity, environment_type
              FROM runs
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

        if run is None:
            raise ValueError(
                f"任务记录不存在：run_id={run_id}"
            )

        if run["runner_identity"] != runner_identity:
            raise ValueError(
                "runner_identity 与任务记录不一致"
            )

        if run["environment_type"] != environment_type:
            raise ValueError(
                "environment_type 与任务记录不一致"
            )

        rows = db.execute(
            """
            SELECT
                c.channel_id,
                lc.line_id,
                l.url,
                l.headers_json,
                dp.evidence_json,
                ls.total_score,
                ls.components_json
              FROM deep_probes AS dp
              JOIN lines AS l
                ON l.line_id = dp.line_id
              JOIN line_channels AS lc
                ON lc.line_id = dp.line_id
              JOIN channels AS c
                ON c.channel_id = lc.channel_id
              JOIN line_scores AS ls
                ON ls.line_id = dp.line_id
               AND ls.run_id = dp.run_id
             WHERE dp.run_id = ?
               AND dp.runner_identity = ?
               AND dp.environment_type = ?
               AND dp.status = 'passed'
             ORDER BY c.channel_id, ls.total_score DESC, lc.line_id
            """,
            (
                run_id,
                runner_identity,
                environment_type,
            ),
        ).fetchall()

        eligible = []

        for row in rows:
            item = dict(row)

            try:
                score_components = json.loads(
                    item.get("components_json") or "{}"
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

            if not isinstance(score_components, dict):
                continue

            # Only lines explicitly admitted to deep probing in this run.
            if score_components.get("eligible_for_deep_probe") is not True:
                continue

            if _already_checked(item["evidence_json"]):
                continue

            normalized_url = normalize_url(item["url"])

            blacklist = db.execute(
                """
                SELECT 1
                  FROM blacklists
                 WHERE active = 1
                   AND (
                        (target_type = 'line' AND target_id = ?)
                     OR (
                            target_type = 'url'
                        AND target_id IN (?, ?)
                     )
                   )
                 LIMIT 1
                """,
                (
                    item["line_id"],
                    item["url"],
                    normalized_url,
                ),
            ).fetchone()

            if blacklist is not None:
                continue

            eligible.append(item)

        selected = _select_lines(eligible)

    ffmpeg = _resolve_binary(ffmpeg_binary, "ffmpeg")
    tesseract = _resolve_binary(tesseract_binary, "tesseract")

    missing_tools = []

    if not ffmpeg:
        missing_tools.append("ffmpeg")

    if not tesseract:
        missing_tools.append("tesseract")

    records: list[ContentCheckRecord] = []

    if missing_tools:
        for item in selected:
            records.append(
                _unknown_record(
                    item,
                    "required_content_check_tool_missing",
                    missing_tools=missing_tools,
                )
            )
    else:
        with ThreadPoolExecutor(
            max_workers=max_concurrency
        ) as executor:
            future_map = {
                executor.submit(
                    _check_one,
                    item,
                    ffmpeg_binary=ffmpeg,
                    tesseract_binary=tesseract,
                ): item
                for item in selected
            }

            for future in as_completed(future_map):
                item = future_map[future]

                try:
                    record = future.result()
                except Exception as exc:
                    record = _unknown_record(
                        item,
                        f"content_check_exception_{type(exc).__name__}",
                    )

                records.append(record)

    blacklisted_count = 0

    item_by_line = {
        item["line_id"]: item
        for item in selected
    }

    for record in records:
        item = item_by_line[record.line_id]

        if _save_record(
            database_path,
            run_id,
            runner_identity,
            item,
            record,
        ):
            blacklisted_count += 1

    records.sort(
        key=lambda record: (
            record.channel_id,
            record.line_id,
        )
    )

    return ContentCheckRunResult(
        run_id=run_id,
        environment_type=environment_type,
        selected_count=len(selected),
        checked_count=len(records),
        clean_count=sum(
            record.status == "no_flag_detected"
            for record in records
        ),
        confirmed_count=sum(
            record.status == "confirmed"
            for record in records
        ),
        unknown_count=sum(
            record.status == "unknown"
            for record in records
        ),
        blacklisted_count=blacklisted_count,
        records=tuple(records),
    )
