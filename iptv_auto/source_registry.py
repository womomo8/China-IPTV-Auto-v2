"""Persistent source pool, blacklist filtering and evidence-based source scoring."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .database import database_session
from .identity import normalize_url, stable_source_id


POOL_CAPACITY = 30
NEW_SOURCES_PER_RUN = 8
SUCCESS_STATUSES = {"ok", "success", "passed"}
FULL_COVERAGE_CHANNELS = 20


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
    line_success_rate: float
    fetch_success_rate: float
    effective_rounds: int
    channel_count: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_success(status: str) -> bool:
    return str(status or "").strip().lower() in SUCCESS_STATUSES


def _candidate_value(candidate, field: str, default=""):
    value = getattr(candidate, field, default)
    return value if value is not None else default


class SourceRegistry:
    """Manage the persistent source pool using the existing v2 database."""

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

    def _active_count(self, db) -> int:
        return int(db.execute(
            "SELECT COUNT(*) FROM sources WHERE active = 1"
        ).fetchone()[0])

    def _lowest_scored_source(self, db) -> str | None:
        """Return the weakest active non-manual source.

        Sources without historical scores rank below scored sources.
        Ties are resolved by oldest first-seen time.
        """
        row = db.execute(
            """
            SELECT s.source_id,
                   COALESCE((
                       SELECT ss.total_score
                         FROM source_scores ss
                        WHERE ss.source_id = s.source_id
                        ORDER BY ss.scored_at DESC, ss.source_score_id DESC
                        LIMIT 1
                   ), 0) AS score
              FROM sources s
             WHERE s.active = 1
               AND s.source_type != 'manual'
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

    def sync_candidates(self, candidates: Iterable, *, checked_at: str | None = None) -> RegistryResult:
        """Merge manual and discovered candidates into the persistent pool.

        Manual sources are processed first and are never evicted.
        Existing active sources do not count against the per-run new-source cap.
        """
        timestamp = checked_at or _now()
        incoming = list(candidates)

        manual = []
        discovered = []
        for candidate in incoming:
            source_type = str(_candidate_value(candidate, "source_type", "discovered"))
            if source_type == "manual":
                manual.append(candidate)
            else:
                discovered.append(candidate)

        accepted: list[str] = []
        rejected_blacklist: list[str] = []
        rejected_capacity: list[str] = []
        evicted: list[str] = []

        with database_session(self.database_path) as db:
            # Existing manual sources are never removed. Config validation
            # separately prevents more manual sources than pool capacity.
            for candidate in manual:
                source_id = str(_candidate_value(candidate, "source_id"))
                url = str(_candidate_value(candidate, "url")).strip()
                name = str(_candidate_value(candidate, "name", "未命名来源")).strip()

                if not source_id or not url:
                    continue
                if self._is_blacklisted(db, source_id, url):
                    rejected_blacklist.append(source_id)
                    continue

                existing = db.execute(
                    "SELECT source_id FROM sources WHERE source_id = ? OR url = ?",
                    (source_id, url),
                ).fetchone()

                if existing:
                    actual_id = str(existing["source_id"])
                    db.execute(
                        """
                        UPDATE sources
                           SET name = ?, source_type = 'manual',
                               last_seen_at = ?, active = 1
                         WHERE source_id = ?
                        """,
                        (name or "未命名来源", timestamp, actual_id),
                    )
                    accepted.append(actual_id)
                    continue

                while self._active_count(db) >= self.pool_capacity:
                    removed = self._deactivate_weakest(db)
                    if removed is None:
                        rejected_capacity.append(source_id)
                        break
                    evicted.append(removed)
                else:
                    db.execute(
                        """
                        INSERT INTO sources
                            (source_id, name, url, source_type,
                             first_seen_at, last_seen_at, active)
                        VALUES (?, ?, ?, 'manual', ?, ?, 1)
                        """,
                        (source_id, name or "未命名来源", url, timestamp, timestamp),
                    )
                    accepted.append(source_id)

            # Only genuinely new discovered sources count toward the limit.
            new_count = 0
            seen_this_run: set[str] = set()

            for candidate in discovered:
                source_id = str(_candidate_value(candidate, "source_id"))
                url = str(_candidate_value(candidate, "url")).strip()
                name = str(_candidate_value(candidate, "name", "未命名来源")).strip()

                if not source_id or not url or source_id in seen_this_run:
                    continue
                seen_this_run.add(source_id)

                if self._is_blacklisted(db, source_id, url):
                    rejected_blacklist.append(source_id)
                    continue

                existing = db.execute(
                    "SELECT source_id, active FROM sources WHERE source_id = ? OR url = ?",
                    (source_id, url),
                ).fetchone()

                if existing:
                    actual_id = str(existing["source_id"])
                    if int(existing["active"]) == 1:
                        db.execute(
                            "UPDATE sources SET last_seen_at = ? WHERE source_id = ?",
                            (timestamp, actual_id),
                        )
                        accepted.append(actual_id)
                        continue

                if new_count >= self.new_sources_per_run:
                    rejected_capacity.append(source_id)
                    continue

                # Make room only when necessary. Historical records remain
                # in the database; eviction only sets active=0.
                while self._active_count(db) >= self.pool_capacity:
                    removed = self._deactivate_weakest(db)
                    if removed is None:
                        rejected_capacity.append(source_id)
                        break
                    evicted.append(removed)
                else:
                    if existing:
                        db.execute(
                            """
                            UPDATE sources
                               SET name = ?, source_type = 'discovered',
                                   last_seen_at = ?, active = 1
                             WHERE source_id = ?
                            """,
                            (name or "未命名来源", timestamp, str(existing["source_id"])),
                        )
                    else:
                        db.execute(
                            """
                            INSERT INTO sources
                                (source_id, name, url, source_type,
                                 first_seen_at, last_seen_at, active)
                            VALUES (?, ?, ?, 'discovered', ?, ?, 1)
                            """,
                            (source_id, name or "未命名来源", url, timestamp, timestamp),
                        )
                    accepted.append(source_id)
                    new_count += 1

        return RegistryResult(
            accepted=tuple(accepted),
         
