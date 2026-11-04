"""Persistent source pool, fetch history and evidence-based source scoring."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable

from .database import database_session
from .identity import normalize_url, stable_source_id


POOL_CAPACITY = 30
NEW_SOURCES_PER_RUN = 8
SUCCESS_STATUSES = {"ok", "success", "passed"}
SOURCE_SCORE_HISTORY_LIMIT = 20


@dataclass(frozen=True)
class RegistryResult:
    accepted: tuple[str, ...]
    rejected_blacklist: tuple[str, ...]
    rejected_capacity: tuple[str, ...]
    evicted: tuple[str, ...]


@dataclass(frozen=True)
class SourceScore:
    source_id: str
    total_score: float
    fetch_success_rate: float
    accepted_line_rate: float
    effective_checks: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_success(status: str) -> bool:
    return str(status or "").strip().lower() in SUCCESS_STATUSES


def _candidate_value(candidate, field: str, default=""):
    if isinstance(candidate, dict):
        value = candidate.get(field, default)
    else:
        value = getattr(candidate, field, default)
    return value if value is not None else default


class SourceRegistry:
    """Manage the persistent 30-source pool using the existing v2 schema."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        pool_capacity: int = POOL_CAPACITY,
        new_sources_per_run: int = NEW_SOURCES_PER_RUN,
    ):
        if type(pool_capacity) is not int or pool_capacity != POOL_CAPACITY:
            raise ValueError("来源池容量必须保持为30")
        if type(new_sources_per_run) is not int or new_sources_per_run != NEW_SOURCES_PER_RUN:
            raise ValueError("每轮新增来源上限必须保持为8")
        self.database_path = Path(database_path)
        self.pool_capacity = pool_capacity
        self.new_sources_per_run = new_sources_per_run

    @staticmethod
    def _candidate_identity(candidate) -> tuple[str, str, str, str]:
        url = str(_candidate_value(candidate, "url")).strip()
        if not url:
            return "", "", "", ""
        source_id = str(
            _candidate_value(candidate, "source_id") or stable_source_id(url)
        ).strip()
        name = str(_candidate_value(candidate, "name", "未命名来源")).strip()
        source_type = str(
            _candidate_value(candidate, "source_type", "discovered")
        ).strip().lower()
        if source_type not in {"manual", "discovered"}:
            source_type = "discovered"
        return source_id, url, name or "未命名来源", source_type

    def _is_blacklisted(self, db, source_id: str, url: str) -> bool:
        normalized = normalize_url(url)
        row = db.execute(
            """
            SELECT 1
              FROM blacklists
             WHERE active = 1
               AND (
                    (target_type = 'source' AND target_id = ?)
                 OR (target_type = 'url' AND target_id IN (?, ?))
               )
             LIMIT 1
            """,
            (source_id, url, normalized),
        ).fetchone()
        return row is not None

    @staticmethod
    def _active_count(db) -> int:
        return int(
            db.execute(
                "SELECT COUNT(*) FROM sources WHERE active = 1"
            ).fetchone()[0]
        )

    @staticmethod
    def _lowest_scored_source(db) -> str | None:
        """Choose the weakest active source regardless of how it was added."""
        row = db.execute(
            """
            SELECT s.source_id,
                   COALESCE((
                       SELECT ss.total_score
                         FROM source_scores ss
                        WHERE ss.source_id = s.source_id
                        ORDER BY ss.scored_at DESC,
                                 ss.source_score_id DESC
                        LIMIT 1
                   ), 0) AS score
              FROM sources s
             WHERE s.active = 1
             ORDER BY score ASC, s.first_seen_at ASC, s.source_id ASC
             LIMIT 1
            """
        ).fetchone()
        return str(row["source_id"]) if row else None

    def _deactivate_weakest(self, db) -> str | None:
        source_id = self._lowest_scored_source(db)
        if source_id is None:
            return None
        db.execute(
            "UPDATE sources SET active = 0 WHERE source_id = ?",
            (source_id,),
        )
        return source_id

    def sync_candidates(
        self,
        candidates: Iterable,
        *,
        checked_at: str | None = None,
    ) -> RegistryResult:
        """Merge manual and discovered sources without deleting history."""
        timestamp = checked_at or _now()
        incoming = list(candidates)
        manual = []
        discovered = []

        for candidate in incoming:
            identity = self._candidate_identity(candidate)
            if not identity[0] or not identity[1]:
                continue
            if identity[3] == "manual":
                manual.append((candidate, identity))
            else:
                discovered.append((candidate, identity))

        accepted: list[str] = []
        rejected_blacklist: list[str] = []
        rejected_capacity: list[str] = []
        evicted: list[str] = []
        accepted_seen: set[str] = set()
        rejected_seen: set[str] = set()
        evicted_seen: set[str] = set()

        def add_unique(target: list[str], seen: set[str], value: str) -> None:
            if value and value not in seen:
                target.append(value)
                seen.add(value)

        with database_session(self.database_path) as db:
            # Manual sources are processed first, but use the same eviction rules.
            for _candidate, identity in manual:
                source_id, url, name, _kind = identity

                if self._is_blacklisted(db, source_id, url):
                    add_unique(rejected_blacklist, rejected_seen, source_id)
                    continue

                existing = db.execute(
                    "SELECT source_id, active FROM sources WHERE source_id = ? OR url = ?",
                    (source_id, url),
                ).fetchone()

                if existing:
                    actual_id = str(existing["source_id"])
                    if int(existing["active"]) == 0:
                        while self._active_count(db) >= self.pool_capacity:
                            removed = self._deactivate_weakest(db)
                            if removed is None:
                                add_unique(rejected_capacity, rejected_seen, source_id)
                                break
                            add_unique(evicted, evicted_seen, removed)
                        else:
                            db.execute(
                                """
                                UPDATE sources
                                   SET name = ?, source_type = 'manual',
                                       last_seen_at = ?, active = 1
                                 WHERE source_id = ?
                                """,
                                (name, timestamp, actual_id),
                            )
                            add_unique(accepted, accepted_seen, actual_id)
                        continue

                    db.execute(
                        """
                        UPDATE sources
                           SET name = ?, source_type = 'manual',
                               last_seen_at = ?, active = 1
                         WHERE source_id = ?
                        """,
                        (name, timestamp, actual_id),
                    )
                    add_unique(accepted, accepted_seen, actual_id)
                    continue

                while self._active_count(db) >= self.pool_capacity:
                    removed = self._deactivate_weakest(db)
                    if removed is None:
                        add_unique(rejected_capacity, rejected_seen, source_id)
                        break
                    add_unique(evicted, evicted_seen, removed)
                else:
                    db.execute(
                        """
                        INSERT INTO sources
                            (source_id, name, url, source_type,
                             first_seen_at, last_seen_at, active)
                        VALUES (?, ?, ?, 'manual', ?, ?, 1)
                        """,
                        (source_id, name, url, timestamp, timestamp),
                    )
                    add_unique(accepted, accepted_seen, source_id)

            # Existing active discovered sources do not consume the new-source cap.
            new_count = 0
            seen_discovered: set[str] = set()

            for _candidate, identity in discovered:
                source_id, url, name, _kind = identity
                if source_id in seen_discovered:
                    continue
                seen_discovered.add(source_id)

                if self._is_blacklisted(db, source_id, url):
                    add_unique(rejected_blacklist, rejected_seen, source_id)
                    continue

                existing = db.execute(
                    "SELECT source_id, active FROM sources WHERE source_id = ? OR url = ?",
                    (source_id, url),
                ).fetchone()

                if existing and int(existing["active"]) == 1:
                    actual_id = str(existing["source_id"])
                    db.execute(
                        "UPDATE sources SET last_seen_at = ? WHERE source_id = ?",
                        (timestamp, actual_id),
                    )
                    add_unique(accepted, accepted_seen, actual_id)
                    continue

                if new_count >= self.new_sources_per_run:
                    add_unique(rejected_capacity, rejected_seen, source_id)
                    continue

                while self._active_count(db) >= self.pool_capacity:
                    removed = self._deactivate_weakest(db)
                    if removed is None:
                        add_unique(rejected_capacity, rejected_seen, source_id)
                        break
                    add_unique(evicted, evicted_seen, removed)
                else:
                    if existing:
                        actual_id = str(existing["source_id"])
                        db.execute(
                            """
                            UPDATE sources
                               SET name = ?, source_type = 'discovered',
                                   last_seen_at = ?, active = 1
                             WHERE source_id = ?
                            """,
                            (name, timestamp, actual_id),
                        )
                    else:
                        actual_id = source_id
                        db.execute(
                            """
                            INSERT INTO sources
                                (source_id, name, url, source_type,
                                 first_seen_at, last_seen_at, active)
                            VALUES (?, ?, ?, 'discovered', ?, ?, 1)
                            """,
                            (source_id, name, url, timestamp, timestamp),
                        )
                    add_unique(accepted, accepted_seen, actual_id)
                    new_count += 1

        return RegistryResult(
            accepted=tuple(accepted),
            rejected_blacklist=tuple(rejected_blacklist),
            rejected_capacity=tuple(rejected_capacity),
            evicted=tuple(evicted),
        )

    def record_source_check(
        self,
        *,
        run_id: int,
        source_id: str,
        status: str,
        http_status: int | None = None,
        duration_ms: float | None = None,
        discovered_lines: int = 0,
        accepted_lines: int = 0,
        error_class: str = "",
        evidence: dict | None = None,
        checked_at: str | None = None,
    ) -> None:
        """Persist one fetch result per run and source."""
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("run_id 必须是正整数")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id 不能为空")
        if type(discovered_lines) is not int or discovered_lines < 0:
            raise ValueError("discovered_lines 必须是非负整数")
        if type(accepted_lines) is not int or accepted_lines < 0:
            raise ValueError("accepted_lines 必须是非负整数")
        if accepted_lines > discovered_lines:
            raise ValueError("accepted_lines 不能大于 discovered_lines")
        if http_status is not None and (
            type(http_status) is not int or not 100 <= http_status <= 599
        ):
            raise ValueError("http_status 必须是有效HTTP状态码")
        if duration_ms is not None and (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, (int, float))
            or duration_ms < 0
        ):
            raise ValueError("duration_ms 必须是非负数字")
        if evidence is not None and not isinstance(evidence, dict):
            raise ValueError("evidence 必须是对象")

        timestamp = checked_at or _now()
        safe_status = str(status or "failed").strip().lower()
        safe_error = str(error_class or "")[:160]
        evidence_json = json.dumps(
            evidence or {}, ensure_ascii=False, sort_keys=True
        )

        with database_session(self.database_path) as db:
            if db.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone() is None:
                raise ValueError(f"任务记录不存在：run_id={run_id}")
            if db.execute(
                "SELECT 1 FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone() is None:
                raise ValueError(f"来源尚未登记：source_id={source_id}")

            db.execute(
                """
                INSERT INTO source_checks
                    (run_id, source_id, checked_at, status, http_status,
                     duration_ms, discovered_lines, accepted_lines,
                     error_class, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, source_id) DO UPDATE SET
                    checked_at = excluded.checked_at,
                    status = excluded.status,
                    http_status = excluded.http_status,
                    duration_ms = excluded.duration_ms,
                    discovered_lines = excluded.discovered_lines,
                    accepted_lines = excluded.accepted_lines,
                    error_class = excluded.error_class,
                    evidence_json = excluded.evidence_json
                """,
                (
                    run_id, source_id, timestamp, safe_status, http_status,
                    duration_ms, discovered_lines, accepted_lines,
                    safe_error, evidence_json,
                ),
            )

    def calculate_source_score(
        self,
        source_id: str,
        *,
        run_id: int | None = None,
        scored_at: str | None = None,
    ) -> SourceScore | None:
        """Score source reliability using only its 20 most recent fetch checks."""
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id 不能为空")

        timestamp = scored_at or _now()

        with database_session(self.database_path) as db:
            source = db.execute(
                "SELECT source_id FROM sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if source is None:
                return None

            checks = db.execute(
                """
                SELECT run_id, status, discovered_lines, accepted_lines
                  FROM source_checks
                 WHERE source_id = ?
                 ORDER BY checked_at DESC, source_check_id DESC
                 LIMIT ?
                """,
                (source_id, SOURCE_SCORE_HISTORY_LIMIT),
            ).fetchall()

            if not checks:
                return None

            effective_checks = len(checks)
            fetch_successes = sum(
                _is_success(row["status"]) for row in checks
            )
            fetch_rate = fetch_successes / effective_checks

            discovered_total = sum(
                max(0, int(row["discovered_lines"] or 0))
                for row in checks
            )
            accepted_total = sum(
                max(0, int(row["accepted_lines"] or 0))
                for row in checks
            )
            accepted_rate = (
                accepted_total / discovered_total
                if discovered_total > 0
                else 0.0
            )

            total = round(
                fetch_rate * 60.0 + accepted_rate * 40.0,
                2,
            )

            score = SourceScore(
                source_id=source_id,
                total_score=total,
                fetch_success_rate=round(fetch_rate, 4),
                accepted_line_rate=round(accepted_rate, 4),
                effective_checks=effective_checks,
            )

            selected_run_id = run_id
            if selected_run_id is None:
                selected_run_id = int(checks[0]["run_id"])

            if db.execute(
                "SELECT 1 FROM runs WHERE run_id = ?",
                (selected_run_id,),
            ).fetchone() is None:
                raise ValueError(f"任务记录不存在：run_id={selected_run_id}")

            components = {
                "fetch_success_rate": score.fetch_success_rate,
                "accepted_line_rate": score.accepted_line_rate,
                "effective_checks": score.effective_checks,
                "history_limit": SOURCE_SCORE_HISTORY_LIMIT,
                "fetch_weight": 60,
                "accepted_line_weight": 40,
            }

            db.execute(
                """
                INSERT INTO source_scores
                    (run_id, source_id, scored_at, total_score, components_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id, source_id) DO UPDATE SET
                    scored_at = excluded.scored_at,
                    total_score = excluded.total_score,
                    components_json = excluded.components_json
                """,
                (
                    selected_run_id,
                    source_id,
                    timestamp,
                    total,
                    json.dumps(components, ensure_ascii=False, sort_keys=True),
                ),
            )

            return score


def sync_candidates(
    database_path: str | Path,
    candidates: Iterable,
    *,
    checked_at: str | None = None,
) -> RegistryResult:
    return SourceRegistry(database_path).sync_candidates(
        candidates, checked_at=checked_at
    )


def record_source_check(
    database_path: str | Path,
    **kwargs,
) -> None:
    SourceRegistry(database_path).record_source_check(**kwargs)


def calculate_source_score(
    database_path: str | Path,
    source_id: str,
    **kwargs,
) -> SourceScore | None:
    return SourceRegistry(database_path).calculate_source_score(
        source_id, **kwargs
    )
