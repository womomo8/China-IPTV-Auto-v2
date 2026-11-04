"""Bounded FFprobe/FFmpeg media probing for selected IPTV lines.

A line passes only when FFprobe finds both video and audio streams and
FFmpeg successfully reads media for a short bounded period.
Transient failures and missing local tools are recorded as "unknown".
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable
from urllib.parse import urlsplit

from .database import database_session


MAX_CANDIDATES_PER_CHANNEL = 5
MAX_CONCURRENCY = 3
MAX_TIMEOUT_SECONDS = 60.0
MAX_READ_SECONDS = 8
MAX_READ_BYTES = 2 * 1024 * 1024
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


def _resolve_binary(value: str | Path | None, name: str) -> str | None:
    if value is None:
        return shutil.which(name)

    text = str(value).strip()
    if not text:
        return None

    path = Path(text)
    if path.parent != Path(".") or path.is_absolute():
        return str(path) if path.is_file() else None

    return shutil.which(text)


def _terminate_and_wait(process: subprocess.Popen) -> None:
    """Never leave a timed-out FFmpeg/FFprobe child process running."""
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
    """Return (return code, stdout, stderr, execution state)."""
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
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return process.returncode, stdout or "", stderr or "", "completed"
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
        if not key.strip() or "\r" in key or "\n" in key:
            continue
        if "\r" in value or "\n" in value:
            continue
        lines.append(f"{key}: {value}")

    if not lines:
        return []

    return ["-headers", "\r\n".join(lines) + "\r\n"]


def _validate_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme.lower() in {"http", "https", "rtsp", "rtmp"}
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
        "probe_type": "ffprobe_ffmpeg_short_read",
        "environment_type": "cloud",
        "media_read_limit_bytes": MAX_READ_BYTES,
        "media_read_limit_seconds": MAX_READ_SECONDS,
    }

    if not _validate_url(url):
        return DeepProbeRecord(
            channel_id, line_id, "failed", False, False,
            None, None, "", "", None,
            {**evidence, "result_reason": "unsupported_or_invalid_url"},
        )

    if not ffprobe_binary or not ffmpeg_binary:
        missing = []
        if not ffprobe_binary:
            missing.append("ffprobe")
        if not ffmpeg_binary:
            missing.append("ffmpeg")
        return _unknown_record(
            channel_id, line_id, "ffmpeg_tools_missing",
            {**evidence, "missing_tools": missing},
        )

    header_args = _header_argument(headers)
    input_args = ["-rw_timeout", str(int(timeout_seconds * 1_000_000))]
    input_args.extend(header_args)
    input_args.extend(["-i", url])

    ffprobe_command = [
        ffprobe_binary,
        "-v", "error",
        *input_args,
        "-show_streams",
        "-show_format",
        "-of", "json",
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

    if probe_state == "missing_binary":
        return _unknown_record(
            channel_id, line_id, "ffprobe_missing",
            evidence,
        )

    if probe_state == "timeout":
        return _unknown_record(
            channel_id, line_id, "ffprobe_timeout",
            evidence,
        )

    if probe_state != "completed" or probe_rc != 0:
        return _unknown_record(
            channel_id, line_id, "ffprobe_unavailable_or_stream_error",
            evidence,
        )

    try:
        probe_data = json.loads(probe_stdout)
    except (TypeError, ValueError):
        return _unknown_record(
            channel_id, line_id, "ffprobe_invalid_json",
            evidence,
        )

    streams = probe_data.get("streams", [])
    if not isinstance(streams, list):
        return _unknown_record(
            channel_id, line_id, "ffprobe_stream_list_invalid",
            evidence,
        )

    video_streams = [
        item for item in streams
        if isinstance(item, dict) and item.get("codec_type") == "video"
    ]
    audio_streams = [
        item for item in streams
        if isinstance(item, dict) and item.get("codec_type") == "audio"
    ]

    video = video_streams[0] if video_streams else {}
    audio = audio_streams[0] if audio_streams else {}

    has_video = bool(video)
    has_audio = bool(audio)

    width = _positive_int(video.get("width"))
    height = _positive_int(video.get("height"))
    video_codec = str(video.get("codec_name") or "")[:80]
    audio_codec = str(audio.get("codec_name") or "")[:80]

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
        "frame_rate": (
            str(video.get("avg_frame_rate") or
                video.get("r_frame_rate") or "")[:40]
        ),
        "duration_seconds": duration,
    })

    if not has_video or not has_audio:
        return DeepProbeRecord(
            channel_id, line_id, "failed",
            has_video, has_audio, width, height,
            video_codec, audio_codec, duration,
            {**evidence, "result_reason": "missing_video_or_audio_stream"},
        )

    # FFmpeg performs a short real media read. -fs and -t jointly cap work.
    ffmpeg_command = [
        ffmpeg_binary,
        "-hide_banner",
        "-nostdin",
        "-v", "error",
        "-rw_timeout", str(int(timeout_seconds * 1_000_000)),
        *header_args,
        "-i", url,
        "-t", str(MAX_READ_SECONDS),
        "-fs", str(MAX_READ_BYTES),
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-f", "null",
        "-",
    ]

    ffmpeg_rc, _, ffmpeg_stderr, ffmpeg_state = _run_command(
        ffmpeg_command,
        timeout_seconds=timeout_seconds,
        stdout_mode=subprocess.DEVNULL,
    )

    evidence["ffmpeg"] = {
        "return_code": ffmpeg_rc,
        "state": ffmpeg_state,
        "stderr": ffmpeg
