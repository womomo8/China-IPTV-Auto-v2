"""Strict first-stage line validation, IPv4 admission and database registration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable, Any

from .database import database_session
from .identity import normalize_url, stable_channel_id, stable_result_id
from .ipv4 import check_ipv4_url
from .playlist import PlaylistEntry


SUPPORTED_SCHEMES = {"http", "https", "rtsp", "rtmp", "rtp", "udp"}
PLACEHOLDER_WORDS = (
    "广告", "测试频道", "无信号", "暂无信号", "信号中断", "占位",
    "advertisement", "no signal", "test channel",
)


@dataclass(frozen=True)
class EntryRejection:
    line_id: str
    channel_id: str
    reason: str


@dataclass(frozen=True)
class LineIngestResult:
    accepted_count: int
    accepted_line_ids: tuple[str, ...]
    rejected: tuple[EntryRejection, ...]
    duplicate_count: int
    ipv4_passed_count: int = 0
    ipv4_excluded_count: int = 0
    ipv4_temporary_failure_count: int = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_headers(headers: object) -> str | None:
    if headers is None:
        return None
    if not isinstance(headers, dict):
        return "invalid_headers"

    for key, value in headers.items():
        if not isinstance(key, str) or not key.strip():
            return "invalid_header_name"
        if not isinstance(value, str):
            return "invalid_header_value"
        if any(c in key or c in value for c in ("\r", "\n")):
            return "invalid_header_characters"

    return None


def validate_entry(
    entry: PlaylistEntry,
    channel_catalog: Any | None = None,
) -> str | None:
    """Validate playlist structure and official channel identity."""
    if not isinstance(entry, PlaylistEntry):
        return "invalid_entry_type"

    name = str(entry.name or "").strip()
    category = str(entry.category or "").strip()
    url = str(entry.url or "").strip()

    if not name:
        return "empty_channel_name"

    if any(
        word.casefold() in f"{name} {category}".casefold()
        for word in PLACEHOLDER_WORDS
    ):
        return "placeholder_channel"

    if not url:
        return "empty_url"

    try:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        if parts.scheme.lower() not in SUPPORTED_SCHEMES:
            return "unsupported_protocol"
        if not parts.hostname:
            return "missing_host"
        port = parts.port
        if port is not None and not (1 <= port <= 65535):
            return "invalid_port"
    except (TypeError, ValueError):
        return "malformed_url"

    header_error = _validate_headers(entry.headers)
    if header_error:
        return header_error

    if entry.line_id != stable_result_id(url, entry.headers or {}):
        return "line_identity_mismatch"

    if channel_catalog is not None:
        official = channel_catalog.resolve(name)
        if official is None:
            return "channel_not_in_catalog"
        if name != official.name or category != official.category:
            return "noncanonical_channel_identity"
        if entry.channel_id != official.channel_id:
            return "channel_identity_mismatch"
    elif entry.channel_id != stable_channel_id(category, name):
        return "channel_identity_mismatch"

    return None


class LineRegistry:
    """Persist validated lines, this-run pair snapshots and source relationships."""

    def __init__(
        self,
        database_path: str | Path,
        channel_catalog: Any | None = None,
    ):
        self.database_path = Path(database_path)
        self.channel_catalog = channel_catalog

    @staticmethod
    def _is_blacklisted(db, line_id: str, url: str) -> bool:
        normalized = normalize_url(url)
        row = db.execute(
            """
            SELECT 1 FROM blacklists
             WHERE active = 1
               AND (
                    (target_type = 'line' AND target_id = ?)
                 OR (target_type = 'url' AND target_id IN (?, ?))
               )
             LIMIT 1
            """,
            (line_id, url, normalized),
        ).fetchone()
        return row is not None

    def ingest(
        self,
        *,
        run_id: int,
        source_id: str,
        entries: Iterable[PlaylistEntry],
        ingested_at: str | None = None,
    ) -> LineIngestResult:
        """Validate one source and retain every source-to-pair relationship."""
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("run_id 必须是已存在的正整数")

        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError("source_id 不能为空")

        timestamp = ingested_at or _now()

        accepted_ids = []
        rejected = []
        seen_pairs = set()
        duplicate_count = 0

        ipv4_passed_count = 0
        ipv4_excluded_count = 0
        ipv4_temporary_failure_count = 0

        eligible_entries = []

        for entry in entries:
            line_id = str(getattr(entry, "line_id", "") or "")
            channel_id = str(getattr(entry, "channel_id", "") or "")

            reason = validate_entry(
                entry,
                channel_catalog=self.channel_catalog,
            )

            if reason:
                rejected.append(
                    EntryRejection(line_id, channel_id, reason)
                )
                continue

            admission = check_ipv4_url(entry.url)

            if not admission.allowed:
                if admission.status == "dns_temporary_failure":
                    ipv4_temporary_failure_count += 1
                else:
                    ipv4_excluded_count += 1

                rejected.append(
                    EntryRejection(
                        line_id,
                        channel_id,
                        f"ipv4_{admission.status}",
                    )
                )
                continue

            ipv4_passed_count += 1
            eligible_entries.append(entry)

        with database_session(self.database_path) as db:
            run = db.execute(
                "SELECT run_id FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()

            if run is None:
                raise ValueError(f"任务记录不存在：run_id={run_id}")

            source = db.execute(
                "SELECT source_id, active FROM sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()

            if source is None:
                raise ValueError(f"来源尚未登记：source_id={source_id}")

            if int(source["active"]) != 1:
                raise ValueError(
                    f"来源已停用，不能登记线路：source_id={source_id}"
                )

            for entry in eligible_entries:
                line_id = str(entry.line_id)
                channel_id = str(entry.channel_id)
                pair = (line_id, channel_id)

                # 只在当前来源内部去重。
                # 不同来源发现同一配对，仍分别保留来源关系。
                if pair in seen_pairs:
                    duplicate_count += 1
                    continue

                seen_pairs.add(pair)

                if self._is_blacklisted(db, line_id, entry.url):
                    rejected.append(
                        EntryRejection(
                            line_id,
                            channel_id,
                            "blacklisted",
                        )
                    )
                    continue

                headers_json = json.dumps(
                    entry.headers or {},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )

                db.execute(
                    """
                    INSERT INTO lines
                        (
                            line_id, url, headers_json,
                            first_seen_at, last_seen_at,
                            blacklist_status
                        )
                    VALUES (?, ?, ?, ?, ?, 'clear')
                    ON CONFLICT(line_id) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        line_id,
                        entry.url.strip(),
                        headers_json,
                        timestamp,
                        timestamp,
                    ),
                )

                db.execute(
                    """
                    INSERT INTO channels
                        (channel_id, category, name)
                    VALUES (?, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        category = excluded.category,
                        name = excluded.name
                    """,
                    (
                        channel_id,
                        entry.category.strip(),
                        entry.name.strip(),
                    ),
                )

                db.execute(
                    """
                    INSERT INTO source_lines
                        (source_id, line_id, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(source_id, line_id) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        source_id,
                        line_id,
                        timestamp,
                        timestamp,
                    ),
                )

                db.execute(
                    """
                    INSERT INTO line_channels
                        (line_id, channel_id, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(line_id, channel_id) DO UPDATE SET
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        line_id,
                        channel_id,
                        timestamp,
                        timestamp,
                    ),
                )

                # 本轮候选池：同一配对只保留一份快照。
                db.execute(
                    """
                    INSERT INTO run_candidate_pool
                        (
                            run_id, line_id, channel_id,
                            url_snapshot, headers_json_snapshot,
                            channel_name_snapshot, category_snapshot,
                            ipv4_admission_status, created_at
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'passed', ?)
                    ON CONFLICT(run_id, line_id, channel_id)
                    DO NOTHING
                    """,
                    (
                        run_id,
                        line_id,
                        channel_id,
                        entry.url.strip(),
                        headers_json,
                        entry.name.strip(),
                        entry.category.strip(),
                        timestamp,
                    ),
                )

                # 同一个配对来自多个来源时，每个来源都留下记录。
                db.execute(
                    """
                    INSERT INTO run_candidate_pool_sources
                        (
                            run_id, line_id, channel_id,
                            source_id, created_at
                        )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(
                        run_id, line_id, channel_id, source_id
                    ) DO NOTHING
                    """,
                    (
                        run_id,
                        line_id,
                        channel_id,
                        source_id,
                        timestamp,
                    ),
                )

                accepted_ids.append(line_id)

        return LineIngestResult(
            accepted_count=len(accepted_ids),
            accepted_line_ids=tuple(accepted_ids),
            rejected=tuple(rejected),
            duplicate_count=duplicate_count,
            ipv4_passed_count=ipv4_passed_count,
            ipv4_excluded_count=ipv4_excluded_count,
            ipv4_temporary_failure_count=ipv4_temporary_failure_count,
        )
