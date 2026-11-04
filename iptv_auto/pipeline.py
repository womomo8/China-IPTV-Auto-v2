"""Unified orchestration for the China-IPTV-Auto-v2 pipeline.

This module connects the existing processing stages into one resumable run.
It deliberately does not publish playlists; publication is handled by the
separate protected publisher stage.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
from typing import Any

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
PIPELINE_VERSION = 1


class PipelineError(RuntimeError):
    """Raised when a pipeline stage cannot safely continue."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _runner_identity() -> str:
    """Return a stable, non-personal identity for this cloud runner."""
    configured = os.environ.get("IPTV_RUNNER_ID", "").strip()
    if configured:
        return configured[:120]

    host = socket.gethostname().strip() or "github-actions"
    return f"cloud:{host}"[:120]


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return result if isinstance(result, dict) else {}


def _save_summary(
    database_path: Path,
    run_id: int,
    summary: dict[str, Any],
    *,
    status: str | None = None,
) -> None:
    """Persist a checkpoint after each completed stage."""
    with database_session(database_path) as db:
        row = db.execute(
            "SELECT summary_json FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()

        if row is None:
            raise PipelineError(f"任务记录不存在：run_id={run_id}")

        current = _json_object(row["summary_json"])
        current.update(summary)
        current["pipeline_version"] = PIPELINE_VERSION
        current["updated_at"] = _now()

        if status is None:
            db.execute(
                "UPDATE runs SET summary_json = ? WHERE run_id = ?",
                (
                    json.dumps(current, ensure_ascii=False, sort_keys=True),
                    run_id,
                ),
            )
        else:
            db.execute(
                """
                UPDATE runs
                   SET summary_json = ?, status = ?
                 WHERE run_id = ?
                """,
                (
                    json.dumps(current, ensure_ascii=False, sort_keys=True),
                    status,
                    run_id,
                ),
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
                    f"需要恢复的任务不存在：run_id={resume_run_id}"
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
                (started_at, finished_at, status,
                 runner_identity, environment_type, summary_json)
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


def _active_sources(
    database_path: Path,
) -> list[dict[str, str]]:
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


def _discover_and_ingest(
    config: dict[str, Any],
    database_path: Path,
    run_id: int,
) -> dict[str, int]:
    source_registry = SourceRegistry(
        database_path,
        pool_capacity=int(config["sources"]["pool_capacity"]),
        new_sources_per_run=int(config["sources"]["new_sources_per_run"]),
    )

    candidates = collect_source_candidates(config)
    sync_result = source_registry.sync_candidates(candidates)

    line_registry = LineRegistry(database_path)

    fetched_count = 0
    fetch_failed_count = 0
    parsed_count = 0
    accepted_count = 0
    rejected_count = 0

    for source in _active_sources(database_path):
        result = fetch_playlist(
            source["url"],
            timeout=float(config["discovery"]["request_timeout_seconds"]),
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
            continue

        fetched_count += 1
        entries = parse_m3u(result.text)
        unique_entries = deduplicate_entries(entries)

        ingest_result = line_registry.ingest(
            run_id=run_id,
            source_id=source["source_id"],
            entries=unique_entries,
        )

        parsed_count += len(entries)
        accepted_count += ingest_result.accepted_count
        rejected_count += len(ingest_result.rejected)

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
            },
        )

    source_scores = 0
    for source in _active_sources(database_path):
        score = source_registry.calculate_source_score(
            source["source_id"],
            run_id=run_id,
        )
        if score is not None:
            source_scores += 1

    return {
        "discovered_candidates": len(candidates),
        "accepted_sources": len(sync_result.accepted),
        "blacklisted_sources": len(sync_result.rejected_blacklist),
        "capacity_rejected_sources": len(sync_result.rejected_capacity),
        "evicted_sources": len(sync_result.evicted),
        "active_sources": len(_active_sources(database_path)),
        "fetched_sources": fetched_count,
        "failed_sources": fetch_failed_count,
        "parsed_entries": parsed_count,
        "accepted_entries": accepted_count,
        "rejected_entries": rejected_count,
        "scored_sources": source_scores,
    }


def run_pipeline(
    *,
    config_path: str | Path = "config.yaml",
    resume_run_id: int | None = None,
) -> dict[str, Any]:
    """Run or resume the complete pre-publication processing pipeline.

    Stages:
      1. source discovery and source-pool synchronization;
      2. source fetching, playlist parsing and line registration;
      3. three-round basic measurements;
      4. source and line scoring;
      5. bounded FFmpeg/FFprobe deep probes;
      6. OCR and content checks;
      7. up to two stability retests.

    Publishing is intentionally excluded until the protected publisher
    implementation is installed and reviewed.
    """
    config = load_config(config_path)

    database_path = Path(config["paths"]["database"])
    database_path.parent.mkdir(parents=True, exist_ok=T
