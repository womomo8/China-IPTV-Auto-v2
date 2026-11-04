
"""Short stability retests for lines that passed deep probing and content checks."""
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
VALID_PROBE_STATUSES = {
    "success",
    "reachable",
    "probe_limited",
    "failed",
}


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


def _decode_evidence(value: object) -> dict[str, Any]:
    try:
        evidence = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    return evidence if isinstance(evidence, dict) else {}


def _is_stability_retest(evidence: dict[str, Any]) -> bool:
    return evidence.get("measurement_stage") == "stability_retest"


def _content_check_passed(evidence_json: str) -> bool:
    """Only explicit no-flag content checks may enter stability retesting."""
    evidence = _decode_evidence(evidence_json)
    content = evidence.get("content_check")

    if not isinstance(content, dict):
        return False

    return (
        content.get("status") == "no_flag_detected"
        and content.get("content_class") == "clean"
        and content.get("ad_detected") is False
        and content.get("placeholder_detected") is False
    )


def _select_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep at most five eligible unique lines per channel."""
    grouped: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        grouped.setdefault(row["channel_id"], []).append(row)

    selected: list[dict[str, Any]] = []
    seen_line_ids: set[str] = set()

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
    """Run or resume up to two stability checks on content-cleared lines.

    Only lines that passed deep probing and have an explicit clean content
    check are eligible. Cloud probing is never represented as a home-network
    or Fujian Mobile test.

    Pending reservations are resumed using their original measurement IDs
    and round numbers. Completed records are never repeated or overwritten.
    """

    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run_id 必须是正整数")

    if not isinstance(runner_identity, str) or not runner_identity.strip():
        raise ValueError("runner_identity 必须是非空文本")

    if environment_type not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(
            "当前只允许 cloud，不能冒充福建移动家庭实测"
        )

    if type(retests) is not int or not (1 <= retests <= MAX_RETESTS):
        raise ValueError("稳定性复测次数必须为1或2")

    if type(max_concurrency) is not int or not (
        1 <= max_concurrency <= MAX_CONCURRENCY
    ):
        raise ValueError("稳定性复测并发数必须是1至3之间的整数")

    timeout, concurrency = _validate_runtime_options(
        timeout_seconds,
        max_concurrency,
    )

    timestamp = _now()
    selected: list[dict[str, Any]] = []
    reservations: list[dict[str, Any]] = []
    skipped_existing = 0

    # Reserve or recover records under one SQLite write lock.
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

        rows = db.execute(
            """
            SELECT
                c.channel_id,
                lc.line_id,
                l.url,
                l.headers_json,
                dp.evidence_json
              FROM deep_probes AS dp
              JOIN lines AS l
                ON l.line_id = dp.line_id
              JOIN line_channels AS lc
                ON lc.line_id = dp.line_id
              JOIN channels AS c
                ON c.channel_id = lc.channel_id
             WHERE dp.run_id = ?
               AND dp.runner_identity = ?
               AND dp.environment_type = ?
               AND dp.status = 'passed'
               AND NOT EXISTS (
                    SELECT 1
                      FROM blacklists b
                     WHERE b.active = 1
                       AND (
                            (b.target_type = 'line'
                             AND b.target_id = l.line_id)
                         OR (b.target_type = 'url'
                             AND b.target_id = l.url)
                       )
               )
             ORDER BY c.channel_id, lc.line_id
            """,
            (
                run_id,
                runner_identity,
                environment_type,
            ),
        ).fetchall()

        eligible_rows = [
            dict(row)
            for row in rows
            if _content_check_passed(row["evidence_json"])
        ]

        selected = _select_lines(eligible_rows)

        for item in selected:
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
                    item["line_id"],
                    runner_identity,
                    environment_type,
                ),
            ).fetchall()

            existing_retests = [
                row
                for row in existing_rows
                if _is_stability_retest(
                    _decode_evidence(row["evidence_json"])
                )
            ]

            pending_retests = [
                row
                for row in existing_retests
                if row["status"] == "pending"
            ]

            # Resume every pending reservation without changing its ID
            # or round number.
            try:
                headers = json.loads(item["headers_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                headers = {}

            if not isinstance(headers, dict):
                headers = {}

            for pending in pending_retests:
                reservations.append({
                    "measurement_id": int(pending["measurement_id"]),
                    "line_id": item["line_id"],
                    "round_no": int(pending["round_no"]),
                    "url": item["url"],
                    "headers": headers,
                })

            # Existing completed and pending retests both count toward
            # the requested total. Never create duplicate reservations.
            remaining = max(0, retests - len(existing_retests))

            if remaining == 0:
                if not pending_retests:
                    skipped_existing += 1
                continue

            max_round = db.execute(
                """
                SELECT COALESCE(MAX(round_no), 0)
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
            ).fetchone()[0]

            next_round = int(max_round)

            for _ in range(remaining):
                next_round += 1

                evidence = {
                    "measurement_stage": "stability_retest",
                    "reserved_at": timestamp,
                    "media_playback_confirmed": False,
                    "environment_type": environment_type,
                }

                cursor = db.execute(
                    """
                    INSERT INTO measurements
                        (
                            run_id,
                            line_id,
                            round_no,
                            measured_at,
                            runner_identity,
                            environment_type,
                            status,
                            latency_ms,
                            throughput_kbps,
                            error_class,
                            evidence_json
                        )
                    VALUES (?, ?, ?, ?, ?, ?, 'pending',
                            NULL, NULL, '', ?)
                    """,
                    (
                        run_id,
                        item["line_id"],
                        next_round,
                        timestamp,
                        runner_identity,
                        environment_type,
                        json.dumps(evidence, ensure_ascii=False),
                    ),
                )

                reservations.append({
                    "measurement_id": int(cursor.lastrowid),
                    "line_id": item["line_id"],
                    "round_no": next_round,
                    "url": item["url"],
                    "headers": headers,
                })

    def probe(reservation: dict[str, Any]):
        return _probe_line(
            reservation["url"],
            reservation["headers"],
            timeout,
        )

    records: list[StabilityRecord] = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_map = {
            executor.submit(probe, reservation): reservation
            for reservation in reservations
        }

        for future in as_completed(future_map):
            reservation = future_map[future]

            try:
                result = future.result()

                status = str(result.status or "failed")
                if status not in VALID_PROBE_STATUSES:
                    status = "failed"

                latency = _finite_nonnegative(result.latency_ms)
                throughput = _finite_nonnegative(result.throughput_kbps)
                error_class = str(result.error_class or "")[:120]

                raw_evidence = result.evidence or {}
                if isinstance(raw_evidence, dict):
                    evidence = dict(raw_evidence)
                else:
                    evidence = {"invalid_probe_evidence": True}

            except Exception as exc:
                status = "failed"
                latency = None
                throughput = None
                error_class = "stability_probe_exception"
                evidence = {
                    "exception_type": type(exc).__name__,
                }

            # A short network probe never proves actual media playback.
            evidence.update({
                "measurement_stage": "stability_retest",
                "media_playback_confirmed": False,
                "environment_type": environment_type,
                "completed_at": _now(),
            })

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
                        json.dumps(evidence, ensure_ascii=False),
                        reservation["measurement_id"],
                    ),
                )

                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "稳定性复测记录未能从 pending 状态完成更新："
                        f"measurement_id={reservation['measurement_id']}"
                    )

            records.append(
                StabilityRecord(
                    line_id=reservation["line_id"],
                    round_no=reservation["round_no"],
                    status=status,
                    latency_ms=latency,
                    throughput_kbps=throughput,
                    error_class=error_class,
                )
            )

    records.sort(
        key=lambda record: (
            record.line_id,
            record.round_no,
        )
    )

    return StabilityRunResult(
        run_id=run_id,
        environment_type=environment_type,
        selected_count=len(selected),
        scheduled_count=len(reservations),
        skipped_existing_count=skipped_existing,
        success_count=sum(
            record.status == "success" for record in records
        ),
        reachable_count=sum(
            record.status == "reachable" for record in records
        ),
        probe_limited_count=sum(
            record.status == "probe_limited" for record in records
        ),
        failed_count=sum(
            record.status == "failed" for record in records
        ),
        records=tuple(records),
    )
