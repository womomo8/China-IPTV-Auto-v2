"""Short stability retests for lines that passed deep media probing."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from .database import database_session
from .measurement import _probe_line, _validate_runtime_options


MAX_RETESTS = 2
MAX_CANDIDATES_PER_CHANNEL = 5
MAX_CONCURRENCY = 3
SUPPORTED_ENVIRONMENTS = {"cloud"}


@dataclass(frozen=True)
class StabilityRecord:
    line_id: str
    round_no: int
    status: str
    latency_ms: float | None
    throughput_kbps: float | None
    error_class: str


@dataclass(frozen=True)
class StabilityRunResult:
    run_id: int
    environment_type: str
    selected_count: int
    scheduled_count: int
    skipped_existing_count: int
    success_count: int
    reachable_count: int
    probe_limited_count: int
    failed_count: int
    records: tuple[StabilityRecord, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _select_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep at most five deep-probed lines per channel; deduplicate line IDs."""
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        grouped.setdefault(row["channel_id"], []).append(row)

    selected: list[dict[str, Any]] = []
    seen_line_ids: set[str] = set()

    for channel_id in sorted(grouped):
        items = grouped[channel_id]
        items.sort(key=lambda item: item["line_id"])

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


def run_stability_retests(
    database_path: str | Path,
    run_id: int,
    *,
    runner_identity: str,
    environment_type: str = "cloud",
    retests: int = MAX_RETESTS,
    timeout_seconds: float = 8.0,
    max_concurrency: int = MAX_CONCURRENCY,
) -> StabilityRunResult:
    """Run up to two additional bounded measurements on deep-probe passes.

    Retests are saved in the existing measurements table with explicit
    measurement_stage evidence. Re-running this function does not repeat
    already reserved retests for the same run and line.
    """
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run_id 必须是正整数")
    if not isinstance(runner_identity, str) or not runner_identity.strip():
        raise ValueError("runner_identity 必须是非空文本")
    if environment_type not in SUPPORTED_ENVIRONMENTS:
        raise ValueError("当前只允许 cloud，不能冒充福建移动家庭实测")
    if type(retests) is not int or not (1 <= retests <= MAX_RETESTS):
        raise ValueError("稳定性复测次数必须为1或2")

    timeout, concurrency = _validate_runtime_options(
        timeout_seconds,
        max_concurrency,
    )

    timestamp = _now()
    selected: list[dict[str, Any]] = []
    reservations: list[dict[str, Any]] = []
    skipped_existing = 0

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
            raise ValueError(f"任务记录不存在：run_id={run_id}")
        if run["runner_identity"] != runner_identity:
            raise ValueError("runner_identity 与任务记录不一致")
        if run["environment_type"] != environment_type:
            raise ValueError("environment_type 与任务记录不一致")

        rows = db.execute(
            """
            SELECT c.channel_id, lc.line_id, l.url, l.headers_json
              FROM deep_probes AS dp
              JOIN lines AS l ON l.line_id = dp.line_id
              JOIN line_channels AS lc ON lc.line_id = dp.line_id
              JOIN channels AS c ON c.channel_id = lc.channel_id
             WHERE dp.run_id = ?
               AND dp.runner_identity = ?
               AND dp.environment_type = ?
               AND dp.status = 'passed'
             ORDER BY c.channel_id, lc.line_id
            """,
            (run_id, runner_identity, environment_type),
        ).fetchall()

        selected = _select_lines([dict(row) for row in rows])

        for item in selected:
            existing_rows = db.execute(
                """
                SELECT round_no, status, evidence_json
                  FROM measurements
                 WHERE run_id = ?
                   AND line_id = ?
                   AND runner_identity = ?
                   AND environment_type = ?
                """,
                (
                    run_id,
                    item["line_id"],
                    runner_identity,
                    environment_type,
                ),
            ).fetchall()

            existing_retests = 0
            for row in existing_rows:
                try:
                    evidence = json.loads(row["evidence_json"] or "{}")
                except (TypeError, ValueError):
                    evidence = {}
                if (
                    isinstance(evidence, dict)
                    and evidence.get("measurement_stage") == "stability_retest"
                ):
                    existing_retests += 1

            remaining = max(0, retests - existing_retests)
            if remaining == 0:
                skipped_existing += 1
                continue

            max_round = db.execute(
                """
                SELECT COALESCE(MAX(round_no), 0)
                  FROM measurements
                 WHERE line_id = ?
                   AND runner_identity = ?
                   AND environment_type = ?
                """,
                (item["line_id"], runner_identity, environment_type),
            ).fetchone()[0]

            try:
                headers = json.loads(item["headers_json"] or "{}")
            except (TypeError, ValueError):
                headers = {}
            if not isinstance(headers, dict):
                headers = {}

            for offset in range(1, remaining + 1):
                round_no = int(max_round) + offset
                evidence = {
                    "measurement_stage": "stability_retest",
                    "reserved_at": timestamp,
                    "media_playback_confirmed": False,
                }
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
                        item["line_id"],
                        round_no,
                        timestamp,
                        runner_identity,
                        environment_type,
                        json.dumps(evidence, ensure_ascii=False),
                    ),
                )
                reservations.append({
                    "measurement_id": cursor.lastrowid,
                    "line_id": item["line_id"],
                    "round_no": round_no,
                    "url": item["url"],
                    "headers": headers,
                })

    records: list[StabilityRecord] = []

    def probe(reservation: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        result = _probe_line(
            reservation["url"],
            reservation["headers"],
            timeout,
        )
        return reservation, result

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(probe, item)
            for item in reservations
        ]

        for future in as_completed(futures):
            reservation = None
            try:
                reservation, result = future.result()
                status = result.status
                latency = _finite_nonnegative(result.latency_ms)
                throughput = _finite_nonnegative(result.throughput_kbps)
                error_class = str(result.error_class or "")[:120]
                evidence = dict(result.evidence or {})
            except Exception as exc:
                status = "failed"
                latency = None
                throughput = None
                error_class = "stability_probe_exception"
                evidence = {"exception_type": type(exc).__name__}

            if reservation is None:
                continue

            evidence.update({
                "measurement_stage": "stability_retest",
                "media_playback_confirmed": False,
                "environment_type": environment_type,
            })

            with database_session(database_path) as db:
                db.execute(
                    """
                    UPDATE measurements
                       SET measured_at = ?,
                           status = ?,
                           latency_ms = ?,
                           throughput_kbps = ?,
                           error_class = ?,
                           evidence_json = ?
                     WHERE measurement_id = ?
                    """,
                    (
                        _now(),
                        status,
                        latency,
                        throughput
