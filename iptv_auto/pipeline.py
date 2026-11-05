"""Unified orchestration for the China-IPTV-Auto-v2 pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

from .channel_catalog import load_channel_catalog
from .config import load_config
from .content_check import run_content_checks
from .database import database_session, initialize_database
from .deep_probe import run_deep_probes
from .line_registry import LineRegistry
from .measurement import run_basic_measurements
from .playlist import deduplicate_entries, parse_m3u
from .scoring import score_lines
from .source_registry import SourceRegistry
from .sources import collect_source_candidates, fetch_playlist
from .stability import run_stability_retests


ENVIRONMENT_TYPE = "cloud"
PIPELINE_VERSION = 3
DEFAULT_RUNNER_IDENTITY = "cloud:github-actions-v1"
DEFAULT_MAX_STAGE_SECONDS = 480
DEFAULT_MAX_CANDIDATE_LINES = 36


class PipelineError(RuntimeError):
    """Raised when a pipeline stage cannot safely continue."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _runner_identity() -> str:
    configured = os.environ.get("IPTV_RUNNER_ID", "").strip()
    return configured[:120] if configured else DEFAULT_RUNNER_IDENTITY


def _json_object(value: object) -> dict[str, Any]:
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _save_summary(
    database_path: Path,
    run_id: int,
    summary: dict[str, Any],
    *,
    status: str | None = None,
) -> None:
    with database_session(database_path) as db:
        row = db.execute(
            "SELECT summary_json FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

        if row is None:
            raise PipelineError(f"任务记录不存在：{run_id}")

        current = _json_object(row["summary_json"])
        current.update(summary)
        current["pipeline_version"] = PIPELINE_VERSION
        current["updated_at"] = _now()

        serialized = json.dumps(
            current,
            ensure_ascii=False,
            sort_keys=True,
        )

        if status is None:
            db.execute(
                "UPDATE runs SET summary_json = ? WHERE run_id = ?",
                (serialized, run_id),
            )
        elif status in {
            "awaiting_publication",
            "failed",
            "completed_no_candidates",
        }:
            db.execute(
                """
                UPDATE runs
                   SET summary_json = ?, status = ?, finished_at = ?
                 WHERE run_id = ?
                """,
                (serialized, status, _now(), run_id),
            )
        else:
            db.execute(
                "UPDATE runs SET summary_json = ?, status = ? WHERE run_id = ?",
                (serialized, status, run_id),
            )


def _create_or_resume_run(
    database_path: Path,
    *,
    runner_identity: str,
    resume_run_id: int | None,
) -> int:
    with database_session(database_path) as db:
        if resume_run_id is not None:
            if type(resume_run_id) is not int or resume_run_id <= 0:
                raise ValueError("resume_run_id 必须是正整数")

            row = db.execute(
                """
                SELECT status, runner_identity, environment_type
                  FROM runs
                 WHERE run_id = ?
                """,
                (resume_run_id,),
            ).fetchone()

            if row is None:
                raise PipelineError(
                    f"需要恢复的任务不存在：{resume_run_id}"
                )

            if row["runner_identity"] != runner_identity:
                raise PipelineError("恢复任务的 runner_identity 不一致")

            if row["environment_type"] != ENVIRONMENT_TYPE:
                raise PipelineError("恢复任务的环境标识不是 cloud")

            if row["status"] not in {
                "running",
                "failed",
                "awaiting_publication",
            }:
                raise PipelineError(
                    f"任务状态不允许恢复：{row['status']}"
                )

            db.execute(
                """
                UPDATE runs
                   SET status = ?, finished_at = NULL
                 WHERE run_id = ?
                """,
                ("running", resume_run_id),
            )
            return resume_run_id

        cursor = db.execute(
            """
            INSERT INTO runs
                (
                    started_at, finished_at, status,
                    runner_identity, environment_type, summary_json
                )
            VALUES (?, NULL, ?, ?, ?, ?)
            """,
            (
                _now(),
                "running",
                runner_identity,
                ENVIRONMENT_TYPE,
                json.dumps(
                    {
                        "pipeline_version": PIPELINE_VERSION,
                        "current_stage": "created",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        return int(cursor.lastrowid)


def _active_sources(database_path: Path) -> list[dict[str, str]]:
    with database_session(database_path) as db:
        rows = db.execute(
            """
            SELECT source_id, name, url, source_type
              FROM sources
             WHERE active = 1
             ORDER BY
                CASE source_type WHEN 'manual' THEN 0 ELSE 1 END,
                source_id
            """
        ).fetchall()

    return [
        {
            "source_id": str(row["source_id"]),
            "name": str(row["name"]),
            "url": str(row["url"]),
            "source_type": str(row["source_type"]),
        }
        for row in rows
    ]


def _take_candidate_entries(
    entries,
    seen_candidate_keys=None,
    limit=None,
):
    """Deduplicate within one source; final capacity is applied after discovery."""
    seen = set()
    selected = []

    for entry in deduplicate_entries(entries):
        key = (entry.line_id, entry.channel_id)

        if key in seen:
            continue

        seen.add(key)
        selected.append(entry)

    if seen_candidate_keys is not None:
        seen_candidate_keys.clear()
        seen_candidate_keys.update(seen)

    return selected, 0


def _freeze_run_candidates(
    database_path: Path,
    run_id: int,
    limit: int = DEFAULT_MAX_CANDIDATE_LINES,
) -> dict[str, int]:
    """Freeze a deterministic top-N candidate list after source discovery."""
    if limit <= 0:
        raise PipelineError("最终候选上限必须大于0")

    with database_session(database_path) as db:
        existing = db.execute(
            """
            SELECT COUNT(*)
              FROM run_candidates
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()[0]

        if existing:
            pool_count = db.execute(
                """
                SELECT COUNT(*)
                  FROM run_candidate_pool
                 WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]

            return {
                "pool_count": int(pool_count),
                "frozen_count": int(existing),
                "rejected_count": max(
                    0,
                    int(pool_count) - int(existing),
                ),
                "already_frozen": 1,
            }

        rows = db.execute(
            """
            SELECT
                p.run_id,
                p.line_id,
                p.channel_id,
                p.url_snapshot,
                p.headers_json_snapshot,
                p.channel_name_snapshot,
                p.category_snapshot,
                p.ipv4_admission_status,
                p.created_at,
                COUNT(DISTINCT ps.source_id) AS source_count,
                COALESCE(AVG(ss.total_score), 0) AS source_score
            FROM run_candidate_pool AS p
            LEFT JOIN run_candidate_pool_sources AS ps
              ON ps.run_id = p.run_id
             AND ps.line_id = p.line_id
             AND ps.channel_id = p.channel_id
            LEFT JOIN source_scores AS ss
              ON ss.run_id = p.run_id
             AND ss.source_id = ps.source_id
            WHERE p.run_id = ?
            GROUP BY p.run_id, p.line_id, p.channel_id
            ORDER BY
                source_count DESC,
                source_score DESC,
                p.line_id ASC,
                p.channel_id ASC
            LIMIT ?
            """,
            (run_id, limit),
        ).fetchall()

        for order, row in enumerate(rows, start=1):
            db.execute(
                """
                INSERT INTO run_candidates
                    (
                        run_id, line_id, channel_id, candidate_order,
                        url_snapshot, headers_json_snapshot,
                        channel_name_snapshot, category_snapshot,
                        ipv4_admission_status, created_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["run_id"],
                    row["line_id"],
                    row["channel_id"],
                    order,
                    row["url_snapshot"],
                    row["headers_json_snapshot"],
                    row["channel_name_snapshot"],
                    row["category_snapshot"],
                    row["ipv4_admission_status"],
                    row["created_at"],
                ),
            )

            db.execute(
                """
                INSERT INTO run_candidate_sources
                    (run_id, line_id, channel_id, source_id, created_at)
                SELECT
                    run_id, line_id, channel_id, source_id, created_at
                  FROM run_candidate_pool_sources
                 WHERE run_id = ?
                   AND line_id = ?
                   AND channel_id = ?
                """,
                (
                    run_id,
                    row["line_id"],
                    row["channel_id"],
                ),
            )

        pool_count = db.execute(
            """
            SELECT COUNT(*)
              FROM run_candidate_pool
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()[0]

        frozen_count = len(rows)

    return {
        "pool_count": int(pool_count),
        "frozen_count": frozen_count,
        "rejected_count": max(
            0,
            int(pool_count) - frozen_count,
        ),
        "already_frozen": 0,
    }
 def _discover_and_ingest(
    config: dict[str, Any],
    database_path: Path,
    run_id: int,
    channel_catalog: Any | None = None,
) -> dict[str, Any]:
    """Process all available sources before freezing the candidate list."""
    stage_started = time.monotonic()

    discovery_cfg = config["discovery"]
    max_seconds = float(
        discovery_cfg.get("max_seconds", DEFAULT_MAX_STAGE_SECONDS)
    )
    max_candidate_lines = int(
        discovery_cfg.get(
            "max_candidate_lines",
            DEFAULT_MAX_CANDIDATE_LINES,
        )
    )
    request_timeout = float(
        discovery_cfg["request_timeout_seconds"]
    )

    if max_seconds <= 0:
        raise PipelineError("第一阶段最大运行时间必须大于0")

    if max_candidate_lines <= 0:
        raise PipelineError("最终候选上限必须大于0")

    if request_timeout <= 0:
        raise PipelineError("来源请求超时必须大于0")

    deadline = stage_started + max_seconds

    source_registry = SourceRegistry(
        database_path,
        pool_capacity=int(config["sources"]["pool_capacity"]),
        new_sources_per_run=int(
            config["sources"]["new_sources_per_run"]
        ),
    )

    discovery_config = dict(config)
    discovery_config["discovery"] = dict(discovery_cfg)
    discovery_config["discovery"]["max_seconds"] = max(
        0.1,
        deadline - time.monotonic(),
    )

    candidates = collect_source_candidates(discovery_config)
    sync_result = source_registry.sync_candidates(candidates)

    line_registry = LineRegistry(
        database_path,
        channel_catalog=channel_catalog,
    )

    fetched_count = 0
    fetch_failed_count = 0
    parsed_count = 0
    accepted_count = 0
    rejected_count = 0
    catalog_rejected_count = 0
    catalog_rejected_names = {}

    ipv4_passed_count = 0
    ipv4_excluded_count = 0
    ipv4_temporary_failure_count = 0

    stop_reason = "all_sources_processed"

    for source in _active_sources(database_path):
        remaining = deadline - time.monotonic()

        if remaining <= 0:
            stop_reason = "time_limit_reached"
            break

        result = fetch_playlist(
            source["url"],
            timeout=min(request_timeout, remaining),
        )

        if not result.ok:
            fetch_failed_count += 1

            source_registry.record_source_check(
                run_id=run_id,
                source_id=source["source_id"],
                status="failed",
                http_status=result.status_code,
                duration_ms=result.duration_ms,
                error_class=result.error_class,
                evidence={
                    "environment_type": ENVIRONMENT_TYPE,
                    "source_type": source["source_type"],
                },
            )

            if time.monotonic() >= deadline:
                stop_reason = "time_limit_reached"
                break

            continue

        fetched_count += 1

        source_catalog_rejections = {}

        entries = parse_m3u(
            result.text,
            catalog=channel_catalog,
            rejected_channels=source_catalog_rejections,
        )

        # 每个来源独立去重，不提前占用全局36个名额。
        selected_entries, _ = _take_candidate_entries(entries)

        ingest_result = line_registry.ingest(
            run_id=run_id,
            source_id=source["source_id"],
            entries=selected_entries,
        )

        parsed_count += len(entries)
        accepted_count += ingest_result.accepted_count
        rejected_count += len(ingest_result.rejected)

        source_catalog_rejected = sum(
            source_catalog_rejections.values()
        )
        catalog_rejected_count += source_catalog_rejected

        for name, count in source_catalog_rejections.items():
            catalog_rejected_names[name] = (
                catalog_rejected_names.get(name, 0) + count
            )

        ipv4_passed_count += ingest_result.ipv4_passed_count
        ipv4_excluded_count += ingest_result.ipv4_excluded_count
        ipv4_temporary_failure_count += (
            ingest_result.ipv4_temporary_failure_count
        )

        source_registry.record_source_check(
            run_id=run_id,
            source_id=source["source_id"],
            status="success",
            http_status=result.status_code,
            duration_ms=result.duration_ms,
            discovered_lines=len(entries),
            accepted_lines=ingest_result.accepted_count,
            evidence={
                "environment_type": ENVIRONMENT_TYPE,
                "source_type": source["source_type"],
                "duplicate_count": ingest_result.duplicate_count,
                "rejected_count": len(ingest_result.rejected),
                "catalog_rejected_count": source_catalog_rejected,
                "catalog_rejected_names": source_catalog_rejections,
                "candidate_lines_selected": len(selected_entries),
                "candidate_limit_rejected": 0,
                "ipv4_admission": {
                    "passed": ingest_result.ipv4_passed_count,
                    "excluded": ingest_result.ipv4_excluded_count,
                    "temporary_failure": (
                        ingest_result.ipv4_temporary_failure_count
                    ),
                },
            },
        )

        if time.monotonic() >= deadline:
            stop_reason = "time_limit_reached"
            break

    # 所有本轮来源处理结束后，统一计算来源评分。
    source_scores = 0

    for source in _active_sources(database_path):
        if source_registry.calculate_source_score(
            source["source_id"],
            run_id=run_id,
        ) is not None:
            source_scores += 1

    # 唯一冻结点：按来源数量、来源评分、稳定ID排序。
    frozen = _freeze_run_candidates(
        database_path,
        run_id,
        max_candidate_lines,
    )

    pool_count = frozen["pool_count"]
    no_candidates = frozen["frozen_count"] == 0

    elapsed_seconds = round(
        time.monotonic() - stage_started,
        3,
    )

    return {
        "stage_status": (
            "completed_no_candidates"
            if no_candidates
            else "completed"
        ),
        "stop_reason": stop_reason,
        "elapsed_seconds": elapsed_seconds,
        "max_seconds": max_seconds,
        "candidate_line_limit": max_candidate_lines,
        "candidate_lines_considered": pool_count,
        "candidate_limit_rejected": frozen["rejected_count"],
        "frozen_candidate_pairs": frozen["frozen_count"],
        "official_channel_count": (
            channel_catalog.total_channels
            if channel_catalog is not None
            else None
        ),
        "discovered_candidates": len(candidates),
        "accepted_sources": len(sync_result.accepted),
        "blacklisted_sources": len(sync_result.rejected_blacklist),
        "capacity_rejected_sources": len(sync_result.rejected_capacity),
        "evicted_sources": len(sync_result.evicted),
        "active_sources": len(_active_sources(database_path)),
        "fetched_sources": fetched_count,
        "failed_sources": fetch_failed_count,
        "parsed_entries": parsed_count,
        "accepted_entries": frozen["frozen_count"],
        "accepted_source_pair_entries": accepted_count,
        "rejected_entries": rejected_count,
        "catalog_rejected_entries": catalog_rejected_count,
        "catalog_rejected_names": catalog_rejected_names,
        "ipv4_admission": {
            "passed": ipv4_passed_count,
            "excluded": ipv4_excluded_count,
            "temporary_failure": ipv4_temporary_failure_count,
        },
        "scored_sources": source_scores,
    }


def run_pipeline(
    *,
    config_path: str | Path = "config.yaml",
    resume_run_id: int | None = None,
) -> dict[str, Any]:
    """Run the complete pre-publication processing pipeline."""
    config = load_config(config_path)

    resolved_config_path = Path(config_path).expanduser().resolve()
    catalog_path = (
        resolved_config_path.parent / "config" / "channels.yaml"
    )

    try:
        channel_catalog = load_channel_catalog(catalog_path)
    except (OSError, ValueError) as exc:
        raise PipelineError(
            f"正式38频道目录加载或校验失败，程序已停止：{exc}"
        ) from exc

    if channel_catalog.total_channels != 38:
        raise PipelineError(
            "正式频道目录数量不是38，程序已停止。"
        )

    database_path = Path(config["paths"]["database"])
    database_path.parent.mkdir(parents=True, exist_ok=True)

    initialize_database(database_path)

    runner_identity = _runner_identity()

    run_id = _create_or_resume_run(
        database_path,
        runner_identity=runner_identity,
        resume_run_id=resume_run_id,
    )

    summary = {
        "environment_type": ENVIRONMENT_TYPE,
        "runner_identity": runner_identity,
        "official_channel_catalog": {
            "path": str(catalog_path),
            "total_channels": channel_catalog.total_channels,
            "status": "validated",
        },
        "current_stage": "source_discovery_and_ingest",
    }

    try:
        _save_summary(database_path, run_id, summary)

        source_summary = _discover_and_ingest(
            config,
            database_path,
            run_id,
            channel_catalog=channel_catalog,
        )

        summary["source_stage"] = source_summary

        if int(source_summary.get("accepted_entries", 0)) == 0:
            summary["current_stage"] = "completed_no_candidates"
            summary["publication_ready"] = False
            summary["completion_reason"] = "no_eligible_candidates"
            summary["note"] = (
                "第一阶段没有合格线路，本轮正常结束，未启动后续检测。"
            )

            _save_summary(
                database_path,
                run_id,
                summary,
                status="completed_no_candidates",
            )

            return {
                "run_id": run_id,
                "status": "completed_no_candidates",
                "summary": summary,
            }

        summary["current_stage"] = "basic_measurements"
        _save_summary(database_path, run_id, summary)

        measurement_result = run_basic_measurements(
            database_path,
            run_id,
            runner_identity=runner_identity,
            environment_type=ENVIRONMENT_TYPE,
            timeout_seconds=float(
                config["measurement"]["basic_timeout_seconds"]
            ),
            max_concurrency=int(
                config["measurement"]["max_concurrency"]
            ),
            required_rounds=3,
        )

        summary["basic_measurements"] = {
            "scheduled": measurement_result.scheduled_count,
            "skipped_existing": measurement_result.skipped_existing_count,
            "success": measurement_result.success_count,
            "reachable": measurement_result.reachable_count,
            "probe_limited": measurement_result.probe_limited_count,
            "failed": measurement_result.failed_count,
        }

        summary["current_stage"] = "line_scoring"
        _save_summary(database_path, run_id, summary)

        scoring_result = score_lines(
            database_path,
            run_id,
            runner_identity=runner_identity,
            environment_type=ENVIRONMENT_TYPE,
        )

        summary["line_scoring"] = {
            "scored": scoring_result.scored_count,
            "eligible": scoring_result.eligible_line_count,
            "deep_candidates": scoring_result.candidate_count,
        }

        summary["current_stage"] = "deep_probe"
        _save_summary(database_path, run_id, summary)

        deep_result = run_deep_probes(
            database_path,
            run_id,
            scoring_result.candidates,
            runner_identity=runner_identity,
            environment_type=ENVIRONMENT_TYPE,
            timeout_seconds=float(
                config["measurement"]["deep_timeout_seconds"]
            ),
            max_concurrency=3,
        )

        summary["deep_probe"] = {
            "selected": deep_result.selected_count,
            "passed": deep_result.passed_count,
            "failed": deep_result.failed_count,
            "unknown": deep_result.unknown_count,
        }

        summary["current_stage"] = "content_check"
        _save_summary(database_path, run_id, summary)

        content_result = run_content_checks(
            database_path,
            run_id,
            runner_identity=runner_identity,
            environment_type=ENVIRONMENT_TYPE,
            max_concurrency=3,
        )

        summary["content_check"] = {
            "selected": content_result.selected_count,
            "checked": content_result.checked_count,
            "clean": content_result.clean_count,
            "confirmed_bad": content_result.confirmed_count,
            "unknown": content_result.unknown_count,
            "blacklisted": content_result.blacklisted_count,
        }

        summary["current_stage"] = "stability_retest"
        _save_summary(database_path, run_id, summary)

        stability_result = run_stability_retests(
            database_path,
            run_id,
            runner_identity=runner_identity,
            environment_type=ENVIRONMENT_TYPE,
            retests=int(
                config["measurement"]["stability_retests"]
            ),
            timeout_seconds=float(
                config["measurement"]["basic_timeout_seconds"]
            ),
            max_concurrency=3,
        )

        summary["stability_retest"] = {
            "selected": stability_result.selected_count,
            "scheduled": stability_result.scheduled_count,
            "skipped_existing": stability_result.skipped_existing_count,
            "success": stability_result.success_count,
            "reachable": stability_result.reachable_count,
            "probe_limited": stability_result.probe_limited_count,
            "failed": stability_result.failed_count,
        }

        summary["current_stage"] = "awaiting_protected_publication"
        summary["publication_ready"] = False
        summary["note"] = (
            "检测阶段已完成；正式发布必须等待受保护的发布模块。"
        )

        _save_summary(
            database_path,
            run_id,
            summary,
            status="awaiting_publication",
        )

        return {
            "run_id": run_id,
            "status": "awaiting_publication",
            "summary": summary,
        }

    except Exception as exc:
        summary["current_stage"] = "failed"
        summary["error"] = {
            "type": type(exc).__name__,
            "message": str(exc)[:1000],
        }

        try:
            _save_summary(
                database_path,
                run_id,
                summary,
                status="failed",
            )
        except Exception:
            pass

        raise PipelineError(
            f"自动处理管道失败，run_id={run_id}："
            f"{type(exc).__name__}: {exc}"
        ) from exc


if __name__ == "__main__":
    result = run_pipeline()
    print(json.dumps(result, ensure_ascii=False, indent=2))   
