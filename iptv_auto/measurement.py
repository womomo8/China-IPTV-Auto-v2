
"""Bounded IPv4-first basic stream measurements with persistent history."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import ipaddress
import json
import math
from pathlib import Path
import socket
import ssl
import time
from typing import Any
from urllib.parse import urlsplit

from .database import database_session


MAX_READ_BYTES = 4096
MAX_ALLOWED_CONCURRENCY = 12
MAX_ALLOWED_TIMEOUT_SECONDS = 8.0
SUPPORTED_ENVIRONMENTS = {"cloud"}
VALID_STATUSES = {"success", "reachable", "probe_limited", "failed"}
BASIC_ROUNDS_REQUIRED = 3


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
    if isinstance(exc, socket.gaierror):
        return "dns_error"
    if isinstance(exc, (ConnectionError, OSError)):
        return "network_error"
    return "probe_error"


def _decode_evidence(value: object) -> dict[str, Any]:
    try:
        evidence = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return evidence if isinstance(evidence, dict) else {}


def _is_stability_retest(evidence: dict[str, Any]) -> bool:
    return evidence.get("measurement_stage") == "stability_retest"


def _connect_ipv4(
    host: str, port: int, timeout: float
) -> tuple[socket.socket, str]:
    """Create a direct IPv4 socket; never silently fall back to IPv6."""
    addresses = socket.getaddrinfo(
        host, port, family=socket.AF_INET, type=socket.SOCK_STREAM
    )
    if not addresses:
        raise OSError("no_ipv4_address")

    last_error = None
    for family, socktype, proto, _canonname, sockaddr in addresses:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            return sock, str(sock.getpeername()[0])
        except OSError as exc:
            last_error = exc
            sock.close()

    if last_error:
        raise last_error
    raise OSError("no_ipv4_address")


def _probe_http(
    url: str, headers: dict[str, str], timeout_seconds: float
) -> ProbeResult:
    """Read at most 4096 bytes over a forced IPv4 connection."""
    started = time.monotonic()
    connection = None
    peer_ip = None

    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("unsupported_http_url")

        host = parts.hostname
        port = parts.port or (443 if scheme == "https" else 80)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query

        class IPv4HTTPConnection(http.client.HTTPConnection):
            def connect(self):
                self.sock, peer = _connect_ipv4(
                    host, port, timeout_seconds
                )
                self.peer_ipv4 = peer

        class IPv4HTTPSConnection(http.client.HTTPSConnection):
            def connect(self):
                raw, peer = _connect_ipv4(
                    host, port, timeout_seconds
                )
                context = ssl.create_default_context()
                try:
                    self.sock = context.wrap_socket(
                        raw, server_hostname=host
                    )
                except Exception:
                    raw.close()
                    raise
                self.peer_ipv4 = peer

        if scheme == "https":
            connection = IPv4HTTPSConnection(
                host, port, timeout=timeout_seconds
            )
        else:
            connection = IPv4HTTPConnection(
                host, port, timeout=timeout_seconds
            )

        request_headers = dict(headers or {})
        request_headers.setdefault(
            "User-Agent", "China-IPTV-Auto-v2/1.0"
        )
        request_headers.setdefault(
            "Range", f"bytes=0-{MAX_READ_BYTES - 1}"
        )
        request_headers.setdefault(
            "Host",
            host if port in (80, 443) else f"{host}:{port}",
        )

        connection.request("GET", target, headers=request_headers)
        response = connection.getresponse()
        peer_ip = getattr(connection, "peer_ipv4", None)
        body = response.read(MAX_READ_BYTES)
        status_code = int(response.status)
        content_type = response.getheader("Content-Type", "")

        elapsed = max(time.monotonic() - started, 0.000001)
        latency = _finite_nonnegative(elapsed * 1000.0)

        evidence = {
            "probe_kind": "http_small_body_read",
            "http_status": status_code,
            "content_type": str(content_type)[:200],
            "bytes_read": len(body),
            "byte_limit": MAX_READ_BYTES,
            "range_requested": True,
            "ip_version": 4,
            "connected_ipv4": peer_ip,
            "media_playback_confirmed": False,
        }

        if not 200 <= status_code < 300:
            return ProbeResult(
                "failed", latency, None, "http_status_error", evidence
            )

        if not body:
            return ProbeResult(
                "failed", latency, None, "empty_response", evidence
            )

        throughput = _finite_nonnegative(
            (len(body) / elapsed) / 1024.0
        )
        return ProbeResult(
            "success", latency, throughput, "", evidence
        )

    except Exception as exc:
        elapsed = max(time.monotonic() - started, 0.000001)
        error = _safe_error_class(exc)
        if isinstance(exc, OSError) and str(exc) == "no_ipv4_address":
            error = "no_ipv4_address"

        return ProbeResult(
            "failed",
            _finite_nonnegative(elapsed * 1000.0),
            None,
            error,
            {
                "probe_kind": "http_small_body_read",
                "ip_version": 4,
                "connected_ipv4": peer_ip,
                "bytes_read": 0,
                "byte_limit": MAX_READ_BYTES,
                "exception_type": type(exc).__name__,
                "media_playback_confirmed": False,
            },
        )
    finally:
        if connection is not None:
            connection.close()


def _probe_tcp_reachability(
    url: str, timeout_seconds: float
) -> ProbeResult:
    """TCP reachability only; it is never counted as media success."""
    started = time.monotonic()
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if not host:
            raise ValueError("missing_host")

        default_ports = {"rtsp": 554, "rtmp": 1935}
        port = parts.port or default_ports[parts.scheme.lower()]
        sock, peer_ip = _connect_ipv4(
            host, port, timeout_seconds
        )
        sock.close()

        elapsed = max(time.monotonic() - started, 0.000001)
        return ProbeResult(
            "reachable",
            _finite_nonnegative(elapsed * 1000.0),
            None,
            "",
            {
                "probe_kind": "tcp_connect_only",
                "ip_version": 4,
                "connected_ipv4": peer_ip,
                "media_playback_confirmed": False,
                "counts_as_measurement_success": False,
            },
        )
    except Exception as exc:
        elapsed = max(time.monotonic() - started, 0.000001)
        return ProbeResult(
            "failed",
            _finite_nonnegative(elapsed * 1000.0),
            None,
            _safe_error_class(exc),
            {
                "probe_kind": "tcp_connect_only",
                "ip_version": 4,
                "exception_type": type(exc).__name__,
                "media_playback_confirmed": False,
            },
        )


def _probe_line(
    url: str, headers: dict[str, str], timeout_seconds: float
) -> ProbeResult:
    try:
        scheme = urlsplit(url).scheme.lower()
        if scheme in {"http", "https"}:
            return _probe_http(url, headers, timeout_seconds)
        if scheme in {"rtsp", "rtmp"}:
            return _probe_tcp_reachability(url, timeout_seconds)
        if scheme in {"udp", "rtp"}:
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
                },
            )
        return ProbeResult(
            "failed",
            None,
            None,
            "unsupported_protocol",
            {"probe_kind": "unsupported", "scheme": scheme},
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
    timeout_seconds: float, max_concurrency: int
) -> tuple[float, int]:
    timeout = _finite_nonnegative(timeout_seconds)
    if timeout is None or timeout <= 0 or timeout > MAX_ALLOWED_TIMEOUT_SECONDS:
        raise ValueError("基础测速超时必须大于0且不能超过8秒")
    if (
        type(max_concurrency) is not int
        or not 1 <= max_concurrency <= MAX_ALLOWED_CONCURRENCY
    ):
        raise ValueError("基础测速并发数必须是1至12之间的整数")
    return timeout, max_concurrency


def _load_candidates_and_reserve_rounds(
    database_path: Path,
    run_id: int,
    runner_identity: str,
    environment_type: str,
    required_rounds: int = BASIC_ROUNDS_REQUIRED,
) -> tuple[list[dict[str, Any]], int]:
    """
    Reserve missing basic rounds or resume pending records.

    A write lock is acquired before checking existing reservations. This
    prevents concurrent invocations from allocating duplicate rounds.
    """
    candidates: list[dict[str, Any]] = []
    skipped = 0
    timestamp = _now()

    with database_session(database_path) as db:
        db.execute("BEGIN IMMEDIATE")

        run = db.execute(
            """
            SELECT runner_identity, environment_type
              FROM runs
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

        if run is None:
            raise ValueError(f"任务记录不存在：run_id={run_id}")
        if run["runner_identity"] != runner_identity:
            raise ValueError("runner_identity 与任务记录不一致")
        if run["environment_type"] != environment_type:
            raise ValueError("environment_type 与任务记录不一致")
        if environment_type not in SUPPORTED_ENVIRONMENTS:
            raise ValueError(
                "基础测速目前只允许 cloud，不能冒充国内家庭实测"
            )

        rows = db.execute(
            """
            SELECT l.line_id, l.url, l.headers_json
              FROM lines AS l
             WHERE NOT EXISTS (
                   SELECT 1 FROM blacklists b
                    WHERE b.active = 1
                      AND (
                           (b.target_type = 'line'
                            AND b.target_id = l.line_id)
                        OR (b.target_type = 'url'
                            AND b.target_id = l.url)
                      )
             )
             ORDER BY l.line_id
            """
        ).fetchall()

        for row in rows:
            line_id = str(row["line_id"])

            existing_rows = db.execute(
                """
                SELECT measurement_id, round_no, status, evidence_json
                  FROM measurements
                 WHERE run_id = ?
                   AND line_id = ?
                   AND runner_identity = ?
                   AND environment_type = ?
                 ORDER BY round_no, measurement_id
                """,
                (
                    run_id,
                    line_id,
                    runner_identity,
                    environment_type,
                ),
            ).fetchall()

            basic_existing = [
                item for item in existing_rows
                if not _is_stability_retest(
                    _decode_evidence(item["evidence_json"])
                )
            ]

            try:
                headers = json.loads(row["headers_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                headers = {}
            if not isinstance(headers, dict):
                headers = {}

            # Resume pending reservations first. Terminal records (including
            # failed attempts) count as completed attempts for this run.
            pending_records = [
                item for item in basic_existing
                if item["status"] == "pending"
            ]
            for pending in pending_records:
                candidates.append({
                    "measurement_id": int(pending["measurement_id"]),
                    "line_id": line_id,
                    "round_no": int(pending["round_no"]),
                    "url": row["url"],
                    "headers": headers,
                })

            remaining = max(0, required_rounds - len(basic_existing))
            if remaining == 0:
                skipped += 1
                continue

            history = db.execute(
                """
                SELECT round_no, evidence_json
                  FROM measurements
                 WHERE line_id = ?
                   AND runner_identity = ?
                   AND environment_type = ?
                """,
                (line_id, runner_identity, environment_type),
            ).fetchall()


            occupied_rounds = set()
            for historical in history:
                occupied_rounds.add(int(historical["round_no"]))

            # Fill the lowest unused round numbers first.
            # Stability retests occupy their numbers but do not count
            # toward the required basic measurement rounds.
            next_round = 1

            # Complete the three basic attempts in this run. A failed attempt
            # remains a failed attempt; it is not silently retried as success.
            for _ in range(remaining):
                while next_round in occupied_rounds:
                    next_round += 1

                cursor = db.execute(
                    """
                    INSERT INTO measurements
                        (run_id, line_id, round_no, measured_at,
                         runner_identity, environment_type, status,
                         latency_ms, throughput_kbps, error_class,
                         evidence_json)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending',
                            NULL, NULL, '', ?)
                    """,
                    (
                        run_id,
                        line_id,
                        next_round,
                        timestamp,
                        runner_identity,
                        environment_type,
                        json.dumps({
                            "measurement_stage": "basic",
                            "reserved_at": timestamp,
                            "environment_type": environment_type,
                            "media_playback_confirmed": False,
                        }),
                    ),
                )

                measurement_id = int(cursor.lastrowid)
                candidates.append({
                    "measurement_id": measurement_id,
                    "line_id": line_id,
                    "round_no": next_round,
                    "url": row["url"],
                    "headers": headers,
                })
                occupied_rounds.add(next_round)
                basic_rounds.append(next_round)
                next_round += 1

    return candidates, skipped


def run_basic_measurements(
    database_path: str | Path,
    run_id: int,
    *,
    runner_identity: str,
    environment_type: str = "cloud",
    timeout_seconds: float = 8.0,
    max_concurrency: int = 12,
    required_rounds: int = BASIC_ROUNDS_REQUIRED,
) -> MeasurementRunResult:
    """Run or resume three bounded basic measurement rounds per eligible line."""

    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run_id 必须是正整数")
    if not isinstance(runner_identity, str) or not runner_identity.strip():
        raise ValueError("runner_identity 必须是非空文本")

    timeout, concurrency = _validate_runtime_options(
        timeout_seconds, max_concurrency
    )
    if type(required_rounds) is not int or required_rounds != BASIC_ROUNDS_REQUIRED:
        raise ValueError("基础测速轮数必须固定为3轮")

    reservations, skipped = _load_candidates_and_reserve_rounds(
        Path(database_path),
        run_id,
        runner_identity,
        environment_type,
        required_rounds,
    )

    def probe(item: dict[str, Any]) -> ProbeResult:
        return _probe_line(item["url"], item["headers"], timeout)

    records: list[MeasurementRecord] = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(probe, item): item
            for item in reservations
        }

        for future in as_completed(futures):
            item = futures[future]

            try:
                result = future.result()
            except Exception as exc:
                result = ProbeResult(
                    "failed",
                    None,
                    None,
                    f"probe_exception_{type(exc).__name__}",
                    {"exception_type": type(exc).__name__},
                )

            status = (
                result.status
                if result.status in VALID_STATUSES
                else "failed"
            )

            latency = _finite_nonnegative(result.latency_ms)
            throughput = _finite_nonnegative(result.throughput_kbps)
            error_class = str(result.error_class or "")[:120]

            evidence = (
                result.evidence
                if isinstance(result.evidence, dict)
                else {}
            )

            evidence = dict(evidence)
            evidence.update({
                "measurement_stage": "basic",
                "environment_type": environment_type,
                "completed_at": _now(),
                "media_playback_confirmed": False,
            })

            evidence_json = json.dumps(
                evidence,
                ensure_ascii=False,
                default=str,
            )

            with database_session(database_path) as db:
                cursor = db.execute(
                    """
                    UPDATE measurements
                       SET measured_at = ?,
                           status = ?,
                           latency_ms = ?,
                           throughput_kbps = ?,
                           error_class = ?,
                           evidence_json = ?
                     WHERE measurement_id = ?
                       AND status = 'pending'
                    """,
                    (
                        _now(),
                        status,
                        latency,
                        throughput,
                        error_class,
                        evidence_json,
                        item["measurement_id"],
                    ),
                )

                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "测速记录未能从 pending 状态完成更新："
                        f"measurement_id={item['measurement_id']}"
                    )

            records.append(MeasurementRecord(
                line_id=item["line_id"],
                round_no=item["round_no"],
                status=status,
                latency_ms=latency,
                throughput_kbps=throughput,
                error_class=error_class,
            ))

    records.sort(
        key=lambda item: (item.line_id, item.round_no)
    )

    return MeasurementRunResult(
        run_id=run_id,
        environment_type=environment_type,
        scheduled_count=len(reservations),
        skipped_existing_count=skipped,
        success_count=sum(
            item.status == "success" for item in records
        ),
        reachable_count=sum(
            item.status == "reachable" for item in records
        ),
        probe_limited_count=sum(
            item.status == "probe_limited" for item in records
        ),
        failed_count=sum(
            item.status == "failed" for item in records
        ),
        records=tuple(records),
    )
