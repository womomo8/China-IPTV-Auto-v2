"""Evidence-based line scoring and bounded deep-probe candidate selection."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from .database import database_session


WEIGHTS = {
    "success_rate": 30,
    "stability": 25,
    "throughput": 15,
    "freshness": 15,
    "ad_placeholder_risk": 10,
    "source_reliability": 5,
}
MAX_DEEP_CANDIDATES_PER_CHANNEL = 5
SUPPORTED_ENVIRONMENTS = {"cloud"}
TERMINAL_HTTP_STATUSES = {"success", "failed"}
CLEAN_CONTENT_CLASSES = {"clean", "normal", "live_program"}
BAD_CONTENT_CLASSES = {"advertisement", "no_signal", "placeholder"}


@dataclass(frozen=True)
class LineScore:
    line_id: str
    total_score: float
    grade: str
    components: dict[str, float]
    measurement_rounds: int
    successful_rounds: int
    eligible_for_deep_probe: bool


@dataclass(frozen=True)
class DeepProbeCandidate:
    channel_id: str
    channel_name: str
    line_id: str
    total_score: float
    grade: str
    measurement_rounds: int
    successful_rounds: int


@dataclass(frozen=True)
class ScoringRunResult:
    run_id: int
    environment_type: str
    scored_count: int
    eligible_line_count: int
    candidate_count: int
    scores: tuple[LineScore, ...]
    candidates: tuple[DeepProbeCandidate, ...]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _clamp_score(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(max(0.0, min(100.0, value)), 2)


def _grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _success_rate_score(
    measurements: list[dict[str, Any]],
) -> tuple[float, int, int]:
    completed = [
        item for item in measurements
        if item["status"] in TERMINAL_HTTP_STATUSES
    ]
    successes = sum(item["status"] == "success" for item in completed)
    if not completed:
        return 0.0, 0, 0
    return (
        _clamp_score(successes / len(completed) * 100),
        len(completed),
        successes,
    )


def _stability_score(measurements: list[dict[str, Any]]) -> float:
    successful = [
        item for item in measurements if item["status"] == "success"
    ]
    if len(successful) < 2:
        return 0.0

    latencies = [
        value for item in successful
        if (value := _finite_number(item["latency_ms"])) is not None
    ]
    throughputs = [
        value for item in successful
        if (value := _finite_number(item["throughput_kbps"])) is not None
        and value > 0
    ]
    if len(latencies) < 2 or len(throughputs) < 2:
        return 0.0

    latency_mean = mean(latencies)
    throughput_mean = mean(throughputs)
    latency_cv = pstdev(latencies) / latency_mean if latency_mean > 0 else 1.0
    throughput_cv = (
        pstdev(throughputs) / throughput_mean
        if throughput_mean > 0 else 1.0
    )
    return _clamp_score(
        100.0 - 50.0 * throughput_cv - 30.0 * latency_cv
    )


def _throughput_score(measurements: list[dict[str, Any]]) -> float:
    values = [
        value for item in measurements
        if item["status"] == "success"
        and (value := _finite_number(item["throughput_kbps"])) is not None
        and value > 0
    ]
    if not values:
        return 0.0
    return _clamp_score(mean(values) / 3000.0 * 100.0)


def _freshness_score(
    measurements: list[dict[str, Any]],
    now: datetime,
) -> float:
    times = [
        parsed for item in measurements
        if (parsed := _parse_time(item["measured_at"])) is not None
    ]
    if not times:
        return 0.0

    age_hours = max(0.0, (now - max(times)).total_seconds() / 3600.0)
    if age_hours <= 6:
        return 100.0
    if age_hours >= 72:
        return 0.0
    return _clamp_score(100.0 * (72.0 - age_hours) / 66.0)


def _load_content_evidence(evidence_json: object) -> dict[str, Any]:
    """Read both current nested evidence and legacy top-level evidence."""
    try:
        evidence = (
            json.loads(evidence_json or "{}")
            if isinstance(evidence_json, (str, bytes))
            else evidence_json
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(evidence, dict):
        return {}

    nested = evidence.get("content_check")
    if isinstance(nested, dict):
        # The nested content-check record is authoritative when present.
        return nested
    return evidence


def _content_verdict(evidence_json: object) -> str:
    """Return bad, clean or unknown; never treat missing evidence as clean."""
    evidence = _load_content_evidence(evidence_json)
    if not evidence:
        return "unknown"

    status = str(evidence.get("status", "")).strip().lower()
    content_class = str(
        evidence.get("content_class", "")
    ).strip().lower()

    ad_detected = evidence.get("ad_detected")
    placeholder_detected = evidence.get("placeholder_detected")

    if (
        ad_detected is True
        or placeholder_detected is True
        or content_class in BAD_CONTENT_CLASSES
        or status == "confirmed"
    ):
        return "bad"

    if (
        ad_detected is False
        and placeholder_detected is False
        and content_class in CLEAN_CONTENT_CLASSES
        and status in {"no_flag_detected", "clean", "passed"}
    ):
        return "clean"

    return "unknown"


def _ad_placeholder_score(deep_rows: list[dict[str, Any]]) -> float:
    """Confirmed bad content is zero; clean evidence is 100; unknown is neutral."""
    if not deep_rows:
        return 50.0

    verdicts = [
        _content_verdict(row.get("evidence_json"))
        for row in deep_rows
    ]
    if "bad" in verdicts:
        return 0.0
    if "clean" in verdicts:
        return 100.0
    return 50.0


def _source_reliability_score(source_scores: list[float]) -> float:
    if not source_scores:
        return 50.0
    return _clamp_score(mean(source_scores))


def _weighted_total(components: dict[str, float]) -> float:
    total = sum(
        components[key] * weight / 100.0
        for key, weight in WEIGHTS.items()
    )
    return round(_clamp_score(total), 2)


def _is_blacklisted(db, line_id: str, url: str) -> bool:
    row = db.execute(
        """
        SELECT 1
          FROM blacklists
         WHERE active = 1
           AND (
                (target_type = 'line' AND target_id = ?)
             OR (target_type = 'url' AND target_id = ?)
           )
         LIMIT 1
        """,
        (line_id, url),
    ).fetchone()
    return row is not None


def _load_source_scores(db, line_id: str) -> list[float]:
    rows = db.execute(
        """
        SELECT ss.source_id, ss.total_score, ss.scored_at,
               ss.source_score_id
          FROM source_lines AS sl
          JOIN source_scores AS ss ON ss.source_id = sl.source_id
         WHERE sl.line_id = ?
         ORDER BY ss.scored_at DESC, ss.source_score_id DESC
        """,
        (line_id,),
    ).fetchall()

    latest: dict[str, float] = {}
    for row in rows:
        source_id = str(row["source_id"])
        score = _finite_number(row["total_score"])
        if score is not None and source_id not in latest:
            latest[source_id] = score
    return list(latest.values())


def _score_one_line(
    db,
    *,
    run_id: int,
    line_id: str,
    url: str,
    runner_identity: str,
    environment_type: str,
    now: datetime,
) -> LineScore:
    measurement_rows = db.execute(
        """
        SELECT status, latency_ms, throughput_kbps, measured_at,
               round_no, error_class, evidence_json
          FROM measurements
         WHERE run_id = ?
           AND line_id = ?
           AND runner_identity = ?
           AND environment_type = ?
         ORDER BY measured_at DESC, measurement_id DESC
        """,
        (run_id, line_id, runner_identity, environment_type),
    ).fetchall()

    # Stability retests are additional evidence, never basic rounds.
    measurements = []
    for row in measurement_rows:
        item = dict(row)
        try:
            evidence = json.loads(item.get("evidence_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence = {}
        if (
            isinstance(evidence, dict)
            and evidence.get("measurement_stage") == "stability_retest"
        ):
            continue
        measurements.append(item)

    deep_rows = db.execute(
        """
        SELECT status, evidence_json, probed_at
          FROM deep_probes
         WHERE run_id = ?
           AND line_id = ?
           AND runner_identity = ?
           AND environment_type = ?
         ORDER BY probed_at DESC, probe_id DESC
        """,
        (run_id, line_id, runner_identity, environment_type),
    ).fetchall()

    success_score, completed_rounds, successful_rounds = (
        _success_rate_score(measurements)
    )
    source_scores = _load_source_scores(db, line_id)

    ad_score = _ad_placeholder_score([dict(row) for row in deep_rows])
    components = {
        "success_rate": success_score,
        "stability": _stability_score(measurements),
        "throughput": _throughput_score(measurements),
        "freshness": _freshness_score(measurements, now),
        "ad_placeholder_risk": ad_score,
        "source_reliability": _source_reliability_score(source_scores),
    }
    total = _weighted_total(components)

    latest = measurements[0] if measurements else None
    latest_success = bool(latest and latest["status"] == "success")
    not_blacklisted = not _is_blacklisted(db, line_id, url)

    # A confirmed ad/no-signal/placeholder can never enter deep probing.
    no_confirmed_bad_content = ad_score > 0.0

    eligible = (
        completed_rounds >= 2
        and successful_rounds >= 2
        and success_score >= 90.0
        and latest_success
        and total >= 70.0
        and not_blacklisted
        and no_confirmed_bad_content
    )

    return LineScore(
        line_id=line_id,
        total_score=total,
        grade=_grade(total),
        components=components,
        measurement_rounds=completed_rounds,
        successful_rounds=successful_rounds,
        eligible_for_deep_probe=eligible,
    )


def score_lines(
    database_path: str | Path,
    run_id: int,
    *,
    runner_identity: str,
    environment_type: str = "cloud",
    now: datetime | None = None,
) -> ScoringRunResult:
    """Score registered lines and select no more than five per channel."""
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run_id 必须是正整数")
    if not isinstance(runner_identity, str) or not runner_identity.strip():
        raise ValueError("runner_identity 必须是非空文本")
    if environment_type not in SUPPORTED_ENVIRONMENTS:
        raise ValueError("当前只允许cloud评分，不能冒充福建移动家庭实测")

    current_time = now or _now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)

    score_results: list[LineScore] = []
    candidates: list[DeepProbeCandidate] = []

    with database_session(database_path) as db:
        run = db.execute(
            """
            SELECT runner_identity, environment_type
              FROM runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if run is None:
            raise ValueError(f"任务记录不存在：run_id={run_id}")
        if run["runner_identity"] != runner_identity:
            raise ValueError("runner_identity 与任务记录不一致")
        if run["environment_type"] != environment_type:
            raise ValueError("environment_type 与任务记录不一致")

        lines = db.execute(
            "SELECT line_id, url FROM lines ORDER BY line_id"
        ).fetchall()

        for line in lines:
            result = _score_one_line(
                db,
                run_id=run_id,
                line_id=line["line_id"],
                url=line["url"],
                runner_identity=runner_identity,
                environment_type=environment_type,
                now=current_time,
            )
            score_results.append(result)

            db.execute(
                """
                INSERT INTO line_scores
                    (run_id, line_id, scored_at, total_score, components_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, line_id) DO UPDATE SET
                    scored_at = excluded.scored_at,
                    total_score = excluded.total_score,
                    components_json = excluded.components_json
                """,
                (
                    run_id,
                    result.line_id,
                    current_time.isoformat(timespec="seconds"),
                    result.total_score,
                    json.dumps(
                        {
                            "grade": result.grade,
                            "components": result.components,
                            "measurement_rounds": result.measurement_rounds,
                            "successful_rounds": result.successful_rounds,
                            "eligible_for_deep_probe": result.eligible_for_deep_probe,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )

        eligible_by_line = {
            item.line_id: item
            for item in score_results
            if item.eligible_for_deep_probe
        }

        channel_rows = db.execute(
            """
            SELECT c.channel_id, c.name, lc.line_id
              FROM channels c
              JOIN line_channels lc ON lc.channel_id = c.channel_id
             ORDER BY c.channel_id, lc.line_id
            """
        ).fetchall()

        grouped: dict[str, list[DeepProbeCandidate]] = {}
        for row in channel_rows:
            scored = eligible_by_line.get(row["line_id"])
            if scored is None:
                continue
            grouped.setdefault(row["channel_id"], []).append(
                DeepProbeCandidate(
                    channel_id=row["channel_id"],
                    channel_name=row["name"],
                    line_id=scored.line_id,
                    total_score=scored.total_score,
                    grade=scored.grade,
                    measurement_rounds=scored.measurement_rounds,
                    successful_rounds=scored.successful_rounds,
                )
            )

        for items in grouped.values():
            items.sort(
                key=lambda item: (
                    -item.total_score,
                    -item.successful_rounds,
                    item.line_id,
                )
            )
            candidates.extend(items[:MAX_DEEP_CANDIDATES_PER_CHANNEL])

    score_results.sort(key=lambda item: (-item.total_score, item.line_id))
    candidates.sort(
        key=lambda item: (
            item.channel_id,
            -item.total_score,
            item.line_id,
        )
    )

    return ScoringRunResult(
        run_id=run_id,
        environment_type=environment_type,
        scored_count=len(score_results),
        eligible_line_count=sum(
            item.eligible_for_deep_probe for item in score_results
        ),
        candidate_count=len(candidates),
        scores=tuple(score_results),
        candidates=tuple(candidates),
    )
