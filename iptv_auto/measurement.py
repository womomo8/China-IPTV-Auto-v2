"""Bounded basic stream measurements with persistent round history.

Only an actual HTTP(S) response body read is recorded as "success".
TCP reachability and UDP/RTP probe limitations are deliberately not counted
as successful media reads and can never satisfy the release success gate.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import socket
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .database import database_session


MAX_READ_BYTES = 4096
MAX_ALLOWED_CONCURRENCY = 12
MAX_ALLOWED_TIMEOUT_SECONDS = 8.0
SUPPORTED_ENVIRONMENTS = {"cloud"}


@dataclass(frozen=True)
class ProbeResult:
    status: str
    latency_ms: float | None
    throughput_kbps: float | None
    error_class: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class MeasurementRecord:
    line_id: str
    round_no: int
    status: str
    latency_ms: float | None
    throughput_kbps: float | None
    error_class: str


@dataclass(frozen=True)
class MeasurementRunResult:
    run_id: int
    environment_type: str
    scheduled_count: int
    skipped_existing_count: int
    success_count: int
    reachable_count: int
    probe_limited_count: int
    failed_count: int
    records: tuple[MeasurementRecord, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _safe_error_class(exc: BaseException) -> str:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, HTTPError):
        return "http_error"
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout"
        return "network_error"
    if isinstance(exc, (ConnectionError, OSError, socket.gaierror)):
        return "network_error"
    return "probe_error"


def _probe_http(
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> ProbeResult:
    """Read at most MAX_READ_BYTES from an HTTP(S) endpoint."""
    request_headers = dict(headers)
    request_headers.setdefault("User-Agent", "China-IPTV-Auto-v2/1.0")
    request_headers.setdefault("Range", f"bytes=0-{MAX_READ_BYTES - 1}")

    request = Request(url, headers=request_headers, method="GET")
    started = time.monotonic()

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.getcode() or 0)
            content_type = response.headers.get("Content-Type", "")
            # A strict read cap applies even when the server ignores Range.
            body = response.read(MAX_READ_BYTES)

        elapsed = max(time.monotonic() - started, 0.000001)
        latency_ms = _finite_nonnegative(elapsed * 1000.0)
        byte_count = len(body)

        evidence = {
            "probe_kind": "http_small_body_read",
            "http_status": status_code,
            "content_type": content_type[:200],
            "bytes_read": byte_count,
            "byte_limit": MAX_READ_BYTES,
            "range_requested": True,
            "media_playback_confirmed": False,
        }

        if not 200 <= status_code < 300:
            return ProbeResult(
                "failed", latency_ms, None, "http_status_error", evidence
            )

        if byte_count == 0:
            return ProbeResult(
                "failed", latency_ms, None, "empty_response", evidence
            )

        throughput = _finite_nonnegative(
            (byte_count / elapsed) / 1024.0
        )

        return ProbeResult(
            "success",
            latency_ms,
            throughput,
            "",
            evidence,
        )

    except HTTPError as exc:
        elapsed = max(time.monotonic() - started, 0.000001)
        return ProbeResult(
            "failed",
            _finite_nonnegative(elapsed * 1000.0),
            None,
            "http_status_error",
            {
                "probe_kind": "http_small_body_read",
                "http_status": int(exc.code),
                "bytes_read": 0,
                "byte_limit": MAX_READ_BYTES,
                "media_playback_confirmed": False,
            },
        )
    except BaseException as exc:
        elapsed = max(time.monotonic() - started, 0.000001)
        return ProbeResult(
            "failed",
            _finite_nonnegative(elapsed * 1000.0),
            None,
            _safe_error_class(exc),
            {
                "probe_kind": "http_small_body_read",
                "bytes_read": 0,
                "byte_limit": MAX_READ_BYTES,
                "exception_type": type(exc).__name__,
                "media_playback_confirmed": False,
            },
        )


def _probe_tcp_reachability(
    url: str,
    timeout_seconds: float,
) -> ProbeResult:
    """Check only TCP connection establishment; never call it media success."""
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        return ProbeResult(
            "failed", None, None, "missing_host",
            {"probe_kind": "tcp_connect"},
        )

    default_ports = {"rtsp": 554, "rtmp": 1935}
    try:
        port = parts.port or default_ports[parts.scheme.lower()]
    except (ValueError, KeyError):
        return ProbeResult(
            "failed", None, None, "invalid_or_missing_port",
            {"probe_kind": "tcp_connect"},
        )

    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            elapsed = max(time.monotonic() - started, 0.000001)
        return ProbeResult(
            "reachable",
            _finite_nonnegative(elapsed * 1000.0),
            None,
            "",
            {
                "probe_kind": "tcp_connect_only",
                "host": host,
                "port": port,
                "media_playback_confirmed": False,
                "counts_as_measurement_success": False,
            },
        )
    except BaseException as exc:
        elapsed = max(time.monotonic() - started, 0.000001)
        return ProbeResult(
            "failed",
            _finite_nonnegative(elapsed * 1000.0),
            None,
            _safe_error_class(exc),
            {
                "probe_kind": "tcp_connect_only",
                "host": host,
                "port": port,
                "exception_type": type(exc).__name__,
                "media_playback_confirmed": False,
            },
        )


def _probe_line(
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> ProbeResult:
    """Select a conservative probe according to the stream protocol."""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()

        if scheme in {"http", "https"}:
            return _probe_http(url, headers, timeout_seconds)

        if scheme in {"rtsp", "rtmp"}:
            return _probe_tcp_reachability(url, timeout_seconds)

        if scheme in {"udp", "rtp"}:
            # UDP has no connection handshake. A cloud-side socket operation
            # cannot prove that a multicast stream is arriving or playable.
            return ProbeResult(
                "probe_limited",
                None,
                None,
                "udp_media_probe_requires_receiver",
                {
                    "probe_kind": "udp_rtp_limited",
                    "scheme": scheme,
                    "media_playback_confirmed": False,
                    "counts_as_measurement_success": False,
                    "note": (
                        "需要实际接收端/合适网络环境才能验证组播媒体流；"
                        "本次云端基础测速不将其判为成功或永久损坏"
                    ),
                },
            )

        return ProbeResult(
            "failed",
            None,
            None,
            "unsupported_protocol",
            {
                "probe_kind": "unsupported",
                "scheme": scheme,
                "media_playback_confirmed": False,
            },
        )

    except (TypeError, ValueError) as exc:
        return ProbeResult(
            "failed",
            None,
            None,
            "malformed_url",
            {"exception_type": type(exc).__name__},
        )


def _validate_runtime_options(
    timeout_seconds: float,
    max_concurrency: int,
) -> tuple[float, int]:
    timeout = _finite_nonnegative(timeout_seconds)
    if timeout is None or timeout <= 0 or timeout > MAX_ALLOWED_TIMEOUT_SECONDS:
        raise ValueError("基础测速超时必须大于0且不能超过8秒")

    if type(max_concurrency) is not int or not (
        1 <= max_concurrency <= MAX_ALLOWED_CONCURRENCY
    ):
        raise ValueError("基础测速并发数必须是1至12之间的整数")

    return timeout, max_concurrency


def _load_candidates_and_reserve_rounds(
    database_path: Path,
    run_id: int,
    runner_identity: str,
    environment_type: str,
) -> tuple[list[dict[str, Any]], int]:
    """Reserve one unique measurement row per eligible line before probing.

    Reserving first prevents two overlapping invocations from probing the same
    line in the same run. A process interruption leaves a pending row; it is
    not silently counted as success and is not measured twice in that run.
    """
    candidates: list[dict[str, Any]] = []
    skipped = 0
    timestamp = _now()

    with database_session(database_path) as db:
        run = db.execute(
            """
            SELECT runner_identity, environment_type
              FROM runs
             WHERE run_id = ?
            """,
        
