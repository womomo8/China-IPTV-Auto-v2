"""Bounded FFprobe and FFmpeg media decoding for selected IPTV lines."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import time
from typing import Any, Iterable
from urllib.parse import urlsplit

from .database import database_session
from .ffmpeg_ipv4 import ffmpeg_ipv4_input_options


MAX_CANDIDATES_PER_CHANNEL = 5
MAX_CONCURRENCY = 3
MAX_TIMEOUT_SECONDS = 60.0
MAX_READ_SECONDS = 8
MAX_READ_BYTES = 2 * 1024 * 1024
MIN_DECODED_BYTES = 1024
SUPPORTED_ENVIRONMENTS = {"cloud"}


@dataclass(frozen=True)
class DeepProbeRecord:
    channel_id: str
    line_id: str
    status: str
    has_video: bool | None
    has_audio: bool | None
    width: int | None
    height: int | None
    video_codec: str
    audio_codec: str
    duration_seconds: float | None
    evidence: dict[str, Any]


@dataclass(frozen=True)
class DeepProbeRunResult:
    run_id: int
    environment_type: str
    selected_count: int
    passed_count: int
    failed_count: int
    unknown_count: int
    records: tuple[DeepProbeRecord, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    number = float(value)

    if not math.isfinite(number) or number < 0:
        return None

    return number


def _positive_int(value: object) -> int | None:
    if type(value) is not int or value <= 0:
        return None

    return value


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


def _terminate_and_wait(process: subprocess.Popen) -> None:
    """Terminate a child process and always wait for it."""
    if process.poll() is None:
        process.kill()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _run_command(
    command: list[str],
    *,
    timeout_seconds: float,
    stdout_mode: int = subprocess.PIPE,
) -> tuple[int | None, str, str, str]:
    """Run a bounded text command, returning rc/stdout/stderr/state."""
    process = None

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_mode,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        stdout, stderr = process.communicate(
            timeout=timeout_seconds
        )

        return (
            process.returncode,
            stdout or "",
            stderr or "",
            "completed",
        )

    except subprocess.TimeoutExpired:
        if process is not None:
            _terminate_and_wait(process)

        return None, "", "process_timeout", "timeout"

    except FileNotFoundError:
        return None, "", "binary_not_found", "missing_binary"

    except (OSError, ValueError) as exc:
        if process is not None:
            _terminate_and_wait(process)

        return None, "", type(exc).__name__, "execution_error"


def _header_argument(headers: dict[str, Any]) -> list[str]:
    if not isinstance(headers, dict) or not headers:
        return []

    lines: list[str] = []

    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue

        if not key.strip() or any(char in key for char in "\r\n:"):
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


def _validate_url(url: str) -> bool:
    try:
        parts = urlsplit(url)

        return (
            parts.scheme.lower() in {
                "http",
                "https",
                "rtsp",
                "rtmp",
            }
            and bool(parts.hostname)
        )

    except (TypeError, ValueError):
        return False


def _unknown_record(
    channel_id: str,
    line_id: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> DeepProbeRecord:
    details = dict(evidence or {})
    details["result_reason"] = reason

    return DeepProbeRecord(
        channel_id=channel_id,
        line_id=line_id,
        status="unknown",
        has_video=None,
        has_audio=None,
        width=None,
        height=None,
        video_codec="",
        audio_codec="",
        duration_seconds=None,
        evidence=details,
    )


def _run_bounded_decode(
    command: list[str],
    *,
    timeout_seconds: float,
    max_bytes: int = MAX_READ_BYTES,
) -> tuple[int | None, int, str]:
    """Decode media while strictly limiting captured output bytes.

    FFmpeg writes a small, low-bitrate decoded/re-encoded NUT stream to
    stdout. The parent process reads no more than max_bytes and kills
    FFmpeg when that limit is reached. stderr is discarded to avoid
    an unread-pipe deadlock.
    """
    process = None
    selector = selectors.DefaultSelector()
    output_bytes = 0
    state = "execution_error"
    deadline = time.monotonic() + timeout_seconds

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

        if process.stdout is None:
            return None, 0, "stdout_unavailable"

        fd = process.stdout.fileno()
        os.set_blocking(fd, False)
        selector.register(process.stdout, selectors.EVENT_READ)

        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                state = "timeout"
                _terminate_and_wait(process)
                break

            events = selector.select(
                timeout=min(0.25, remaining)
            )

            if events:
                remaining_bytes = max_bytes - output_bytes

                if remaining_bytes <= 0:
                    state = "byte_limit_reached"
                    _terminate_and_wait(process)
                    break

                chunk = os.read(
                    fd,
                    min(65536, remaining_bytes + 1),
                )

                if not chunk:
                    if process.poll() is not None:
                        state = "completed"
                        break
                    continue

                output_bytes += len(chunk)

                if output_bytes > max_bytes:
                    output_bytes = max_bytes
                    state = "byte_limit_reached"
                    _terminate_and_wait(process)
                    break

                if output_bytes >= max_bytes:
                    state = "byte_limit_reached"
                    _terminate_and_wait(process)
                    break

            elif process.poll() is not None:
                # Drain any remaining pipe bytes before declaring EOF.
                try:
                    chunk = os.read(
                        fd,
                        min(65536, max_bytes - output_bytes),
                    )
                except BlockingIOError:
                    chunk = b""

                if chunk:
                    output_bytes += len(chunk)
                    if output_bytes >= max_bytes:
                        output_bytes = max_bytes
                        state = "byte_limit_reached"
                        _terminate_and_wait(process)
                        break
                else:
                    state = "completed"
                    break

        if process.poll() is None:
            process.wait(timeout=5)

        return process.returncode, output_bytes, state

    except subprocess.TimeoutExpired:
        if process is not None:
            _terminate_and_wait(process)

        return None, output_bytes, "timeout"

    except FileNotFoundError:
        return None, output_bytes, "missing_binary"

    except (OSError, ValueError, selectors.SelectorError) as exc:
        if process is not None:
            _terminate_and_wait(process)

        return None, output_bytes, f"execution_error_{type(exc).__name__}"

    finally:
        selector.close()

        if process is not None and process.stdout is not None:
            process.stdout.close()


def _probe_one(
    *,
    channel_id: str,
    line_id: str,
    url: str,
    headers: dict[str, Any],
    ffprobe_binary: str | None,
    ffmpeg_binary: str | None,
    timeout_seconds: float,
) -> DeepProbeRecord:
    evidence: dict[str, Any] = {
        "probe_type": "ffprobe_ffmpeg_bounded_decode",
        "environment_type": "cloud",
        "media_read_limit_bytes": MAX_READ_BYTES,
        "media_read_limit_seconds": MAX_READ_SECONDS,
        "minimum_decoded_output_bytes": MIN_DECODED_BYTES,
    }

    if not _validate_url(url):
        return DeepProbeRecord(
            channel_id=channel_id,
            line_id=line_id,
            status="failed",
            has_video=False,
            has_audio=False,
            width=None,
            height=None,
            video_codec="",
            audio_codec="",
            duration_seconds=None,
            evidence={
                **evidence,
                "result_reason": "unsupported_or_invalid_url",
            },
        )
    ipv4_options = ffmpeg_ipv4_input_options(url)

    if ipv4_options is None:
        scheme = urlsplit(url).scheme.lower()

        return _unknown_record(
            channel_id,
            line_id,
            "ipv4_transport_not_enforceable_for_protocol",
            {
                **evidence,
                "ipv4_transport": {
                    "status": "not_enforceable",
                    "protocol": scheme,
                },
            },
        )

    evidence["ipv4_transport"] = {
        "status": "configured",
        "method": "tcp_local_addr",
        "local_addr": "0.0.0.0",
        "protocol": urlsplit(url).scheme.lower(),
    }
    if not ffprobe_binary or not ffmpeg_binary:
        missing = []

        if not ffprobe_binary:
            missing.append("ffprobe")

        if not ffmpeg_binary:
            missing.append("ffmpeg")

        return _unknown_record(
            channel_id,
            line_id,
            "ffmpeg_tools_missing",
            {
                **evidence,
                "missing_tools": missing,
            },
        )

    header_args = _header_argument(headers)

    input_args = [
        "-rw_timeout",
        str(int(timeout_seconds * 1_000_000)),
        *header_args,
        "-i",
        url,
    ]

    ffprobe_command = [
        ffprobe_binary,
        "-v",
        "error",
        *input_args,
        "-show_streams",
        "-show_format",
        "-of",
        "json",
    ]

    probe_rc, probe_stdout, probe_stderr, probe_state = _run_command(
        ffprobe_command,
        timeout_seconds=timeout_seconds,
    )

    evidence["ffprobe"] = {
        "return_code": probe_rc,
        "state": probe_state,
        "stderr": probe_stderr[-2000:],
    }

    if probe_state != "completed" or probe_rc != 0:
        return _unknown_record(
            channel_id,
            line_id,
            "ffprobe_unavailable_or_stream_error",
            evidence,
        )

    try:
        probe_data = json.loads(probe_stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return _unknown_record(
            channel_id,
            line_id,
            "ffprobe_invalid_json",
            evidence,
        )

    if not isinstance(probe_data, dict):
        return _unknown_record(
            channel_id,
            line_id,
            "ffprobe_result_invalid",
            evidence,
        )

    streams = probe_data.get("streams", [])

    if not isinstance(streams, list):
        return _unknown_record(
            channel_id,
            line_id,
            "ffprobe_stream_list_invalid",
            evidence,
        )

    video_streams = [
        item for item in streams
        if isinstance(item, dict)
        and item.get("codec_type") == "video"
    ]

    audio_streams = [
        item for item in streams
        if isinstance(item, dict)
        and item.get("codec_type") == "audio"
    ]

    video = video_streams[0] if video_streams else {}
    audio = audio_streams[0] if audio_streams else {}

    has_video = bool(video)
    has_audio = bool(audio)

    width = _positive_int(video.get("width"))
    height = _positive_int(video.get("height"))

    video_codec = str(
        video.get("codec_name") or ""
    )[:80]

    audio_codec = str(
        audio.get("codec_name") or ""
    )[:80]

    duration = None
    format_info = probe_data.get("format")

    if isinstance(format_info, dict):
        try:
            duration = _finite_nonnegative(
                float(format_info.get("duration"))
            )
        except (TypeError, ValueError):
            duration = None

    evidence["ffprobe"].update({
        "stream_count": len(streams),
        "video_stream_count": len(video_streams),
        "audio_stream_count": len(audio_streams),
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "width": width,
        "height": height,
        "frame_rate": str(
            video.get("avg_frame_rate")
            or video.get("r_frame_rate")
            or ""
        )[:40],
        "duration_seconds": duration,
    })

    if not has_video or not has_audio:
        return DeepProbeRecord(
            channel_id=channel_id,
            line_id=line_id,
            status="failed",
            has_video=has_video,
            has_audio=has_audio,
            width=width,
            height=height,
            video_codec=video_codec,
            audio_codec=audio_codec,
            duration_seconds=duration,
            evidence={
                **evidence,
                "result_reason": "missing_video_or_audio_stream",
            },
        )

    # Decode a short sample and re-encode to a small output stream.
    # The Python parent process enforces the actual output byte cap.
    ffmpeg_command = [
        ffmpeg_binary,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-rw_timeout",
        str(int(timeout_seconds * 1_000_000)),
        *header_args,
        "-i",
        url,
        "-t",
        str(MAX_READ_SECONDS),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-vf",
        "scale=320:-2",
        "-threads",
        "1",
        "-c:v",
        "mpeg2video",
        "-b:v",
        "256k",
        "-c:a",
        "mp2",
        "-b:a",
        "64k",
        "-f",
        "nut",
        "pipe:1",
    ]

    ffmpeg_rc, decoded_bytes, ffmpeg_state = _run_bounded_decode(
        ffmpeg_command,
        timeout_seconds=timeout_seconds,
    )

    evidence["ffmpeg"] = {
        "return_code": ffmpeg_rc,
        "state": ffmpeg_state,
        "decoded_output_bytes": decoded_bytes,
        "byte_limit": MAX_READ_BYTES,
        "time_limit_seconds": MAX_READ_SECONDS,
        "video_output": "320px_mpeg2video",
        "audio_output": "mp2_64kbps",
    }

    enough_output = decoded_bytes >= MIN_DECODED_BYTES

    successful_decode = (
        enough_output
        and (
            (
                ffmpeg_state == "completed"
                and ffmpeg_rc == 0
            )
            or ffmpeg_state == "byte_limit_reached"
        )
    )

    if successful_decode:
        evidence["result_reason"] = "bounded_media_decode_passed"

        return DeepProbeRecord(
            channel_id=channel_id,
            line_id=line_id,
            status="passed",
            has_video=True,
            has_audio=True,
            width=width,
            height=height,
            video_codec=video_codec,
            audio_codec=audio_codec,
            duration_seconds=duration,
            evidence=evidence,
        )

    return _unknown_record(
        channel_id,
        line_id,
        "ffmpeg_bounded_decode_not_confirmed",
        evidence,
    )


def _candidate_value(
    candidate: Any,
    key: str,
    default: Any = None,
) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key, default)

    return getattr(candidate, key, default)


def _select_candidates(
    candidates: Iterable[Any],
) -> list[dict[str, Any]]:
    """Select the five highest-scoring unique lines per channel."""
    grouped: dict[str, list[dict[str, Any]]] = {}

    for candidate in candidates:
        channel_id = str(
            _candidate_value(candidate, "channel_id", "") or ""
        ).strip()

        line_id = str(
            _candidate_value(candidate, "line_id", "") or ""
        ).strip()

        if not channel_id or not line_id:
            continue

        score = _finite_nonnegative(
            _candidate_value(candidate, "total_score", 0.0)
        )

        item = {
            "channel_id": channel_id,
            "line_id": line_id,
            "total_score": score if score is not None else 0.0,
        }

        grouped.setdefault(channel_id, []).append(item)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for channel_id in sorted(grouped):
        items = sorted(
            grouped[channel_id],
            key=lambda item: (
                -item["total_score"],
                item["line_id"],
            ),
        )

        count = 0

        for item in items:
            if count >= MAX_CANDIDATES_PER_CHANNEL:
                break

            if item["line_id"] in seen:
                continue

            seen.add(item["line_id"])
            selected.append(item)
            count += 1

    return selected


def run_deep_probes(
    database_path: str | Path,
    run_id: int,
    candidates: Iterable[Any],
    *,
    runner_identity: str,
    environment_type: str = "cloud",
    ffprobe_path: str | Path | None = None,
    ffmpeg_path: str | Path | None = None,
    timeout_seconds: float = 30.0,
    max_concurrency: int = MAX_CONCURRENCY,
) -> DeepProbeRunResult:
    """Probe no more than five candidates per channel.

    A pending database reservation prevents overlapping calls from
    probing the same line twice in the same run.
    """
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run_id 必须是正整数")

    if not isinstance(runner_identity, str) or not runner_identity.strip():
        raise ValueError("runner_identity 必须是非空文本")

    if environment_type not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(
            "深度检测目前只允许 cloud，"
            "不能冒充福建移动家庭实测"
        )

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(float(timeout_seconds))
        or not (1 <= float(timeout_seconds) <= MAX_TIMEOUT_SECONDS)
    ):
        raise ValueError("深度检测超时必须在1至60秒之间")

    if type(max_concurrency) is not int or not (
        1 <= max_concurrency <= MAX_CONCURRENCY
    ):
        raise ValueError("深度检测并发数必须是1至3之间的整数")

    timeout = float(timeout_seconds)
    selected = _select_candidates(candidates)

    ffprobe_binary = _resolve_binary(ffprobe_path, "ffprobe")
    ffmpeg_binary = _resolve_binary(ffmpeg_path, "ffmpeg")

    reservations: list[dict[str, Any]] = []

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

        for candidate in selected:
            row = db.execute(
                """
                SELECT l.url, l.headers_json
                  FROM lines AS l
                  JOIN line_channels AS lc
                    ON lc.line_id = l.line_id
                 WHERE l.line_id = ?
                   AND lc.channel_id = ?
                """,
                (
                    candidate["line_id"],
                    candidate["channel_id"],
                ),
            ).fetchone()

            if row is None:
                continue

            try:
                headers = json.loads(row["headers_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                headers = {}

            if not isinstance(headers, dict):
                headers = {}

            existing = db.execute(
                """
                SELECT probe_id, status
                  FROM deep_probes
                 WHERE run_id = ?
                   AND line_id = ?
                   AND runner_identity = ?
                   AND environment_type = ?
                """,
                (
                    run_id,
                    candidate["line_id"],
                    runner_identity,
                    environment_type,
                ),
            ).fetchone()

            if existing is not None:
                if existing["status"] != "pending":
                    continue
                probe_id = existing["probe_id"]
            else:
                timestamp = _now()
                cursor = db.execute(
                    """
                    INSERT INTO deep_probes
                        (
                            run_id,
                            line_id,
                            probed_at,
                            runner_identity,
                            environment_type,
                            status,
                            evidence_json
                        )
                    VALUES (?, ?, ?, ?, ?, 'pending', ?)
                    ON CONFLICT(
                        run_id,
                        line_id,
                        runner_identity,
                        environment_type
                    ) DO NOTHING
                    """,
                    (
                        run_id,
                        candidate["line_id"],
                        timestamp,
                        runner_identity,
                        environment_type,
                        json.dumps({
                            "probe_state": "pending",
                            "environment_type": environment_type,
                        }),
                    ),
                )

                if cursor.rowcount == 1:
                    probe_id = cursor.lastrowid
                else:
                    existing = db.execute(
                        """
                        SELECT probe_id, status
                          FROM deep_probes
                         WHERE run_id = ?
                           AND line_id = ?
                           AND runner_identity = ?
                           AND environment_type = ?
                        """,
                        (
                            run_id,
                            candidate["line_id"],
                            runner_identity,
                            environment_type,
                        ),
                    ).fetchone()

                    if (
                        existing is None
                        or existing["status"] != "pending"
                    ):
                        continue

                    probe_id = existing["probe_id"]

            reservations.append({
                "probe_id": probe_id,
                "channel_id": candidate["channel_id"],
                "line_id": candidate["line_id"],
                "url": row["url"],
                "headers": headers,
            })
    records: list[DeepProbeRecord] = []

    def execute_probe(item: dict[str, Any]) -> DeepProbeRecord:
        return _probe_one(
            channel_id=item["channel_id"],
            line_id=item["line_id"],
            url=item["url"],
            headers=item["headers"],
            ffprobe_binary=ffprobe_binary,
            ffmpeg_binary=ffmpeg_binary,
            timeout_seconds=timeout,
        )

    with ThreadPoolExecutor(
        max_workers=max_concurrency
    ) as executor:
        future_map = {
            executor.submit(execute_probe, item): item
            for item in reservations
        }

        for future in as_completed(future_map):
            item = future_map[future]

            try:
                record = future.result()
            except Exception as exc:
                record = _unknown_record(
                    item["channel_id"],
                    item["line_id"],
                    f"deep_probe_exception_{type(exc).__name__}",
                )

            records.append(record)

            with database_session(database_path) as db:
                db.execute(
                    """
                    UPDATE deep_probes
                       SET probed_at = ?,
                           status = ?,
                           has_video = ?,
                           has_audio = ?,
                           width = ?,
                           height = ?,
                           video_codec = ?,
                           audio_codec = ?,
                           duration_seconds = ?,
                           evidence_json = ?
                     WHERE probe_id = ?
                    """,
                    (
                        _now(),
                        record.status,
                        (
                            int(record.has_video)
                            if record.has_video is not None
                            else None
                        ),
                        (
                            int(record.has_audio)
                            if record.has_audio is not None
                            else None
                        ),
                        record.width,
                        record.height,
                        record.video_codec,
                        record.audio_codec,
                        record.duration_seconds,
                        json.dumps(
                            record.evidence,
                            ensure_ascii=False,
                        ),
                        item["probe_id"],
                    ),
                )

    records.sort(
        key=lambda item: (
            item.channel_id,
            item.line_id,
        )
    )

    return DeepProbeRunResult(
        run_id=run_id,
        environment_type=environment_type,
        selected_count=len(selected),
        passed_count=sum(
            item.status == "passed" for item in records
        ),
        failed_count=sum(
            item.status == "failed" for item in records
        ),
        unknown_count=sum(
            item.status == "unknown" for item in records
        ),
        records=tuple(records),
    )
