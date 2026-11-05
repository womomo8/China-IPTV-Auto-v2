"""V3 unified SQLite database schema. No V1/V2 migration."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA_VERSION = 3

SCHEMA = r"""
BEGIN IMMEDIATE;

CREATE TABLE runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    runner_identity TEXT NOT NULL,
    environment_type TEXT NOT NULL DEFAULT 'cloud',
    summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL DEFAULT 'discovered',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE source_checks (
    source_check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    http_status INTEGER,
    duration_ms REAL,
    discovered_lines INTEGER NOT NULL DEFAULT 0,
    accepted_lines INTEGER NOT NULL DEFAULT 0,
    error_class TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, source_id)
);

CREATE TABLE lines (
    line_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    headers_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    blacklist_status TEXT NOT NULL DEFAULT 'clear'
);

CREATE TABLE channels (
    channel_id TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL
);

CREATE TABLE source_lines (
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (source_id, line_id)
);

CREATE TABLE line_channels (
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (line_id, channel_id)
);

CREATE TABLE source_scores (
    source_score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    scored_at TEXT NOT NULL,
    total_score REAL NOT NULL,
    components_json TEXT NOT NULL,
    UNIQUE (run_id, source_id)
);

CREATE TABLE blacklists (
    blacklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL
        CHECK (target_type IN ('source', 'line', 'url')),
    target_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
        CHECK (active IN (0, 1))
);

CREATE TABLE publications (
    publication_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    published_at TEXT NOT NULL,
    status TEXT NOT NULL,
    playlist_path TEXT NOT NULL,
    content_sha256 TEXT,
    entry_count INTEGER NOT NULL DEFAULT 0,
    previous_sha256 TEXT,
    preserved_previous INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE run_stages (
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending', 'running', 'completed',
            'completed_no_candidates', 'failed', 'timeout', 'skipped'
        )
    ),
    runner_identity TEXT NOT NULL DEFAULT '',
    environment_type TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (attempt_count >= 0),
    summary_json TEXT NOT NULL DEFAULT '{}',
    error_class TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, stage_name)
);

-- 本轮临时候选池：所有来源采集完成前，不占用最终36个名额。
CREATE TABLE run_candidate_pool (
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
    url_snapshot TEXT NOT NULL,
    headers_json_snapshot TEXT NOT NULL DEFAULT '{}',
    channel_name_snapshot TEXT NOT NULL,
    category_snapshot TEXT NOT NULL DEFAULT '',
    ipv4_admission_status TEXT NOT NULL DEFAULT 'passed',
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, line_id, channel_id)
);

-- 一个候选配对可以来自多个来源。
CREATE TABLE run_candidate_pool_sources (
    run_id INTEGER NOT NULL,
    line_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, line_id, channel_id, source_id),
    FOREIGN KEY (run_id, line_id, channel_id)
        REFERENCES run_candidate_pool(run_id, line_id, channel_id)
        ON DELETE CASCADE
);

-- 所有来源处理完毕后，统一冻结最终候选名单。
CREATE TABLE run_candidates (
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
    candidate_order INTEGER NOT NULL CHECK (candidate_order > 0),
    url_snapshot TEXT NOT NULL,
    headers_json_snapshot TEXT NOT NULL DEFAULT '{}',
    channel_name_snapshot TEXT NOT NULL,
    category_snapshot TEXT NOT NULL DEFAULT '',
    ipv4_admission_status TEXT NOT NULL DEFAULT 'passed',
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, line_id, channel_id),
    UNIQUE (run_id, candidate_order)
);

CREATE TABLE run_candidate_sources (
    run_id INTEGER NOT NULL,
    line_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, line_id, channel_id, source_id),
    FOREIGN KEY (run_id, line_id, channel_id)
        REFERENCES run_candidates(run_id, line_id, channel_id)
        ON DELETE CASCADE
);

-- 测速按物理线路保存，不能把线路测速误当成频道匹配结果。
CREATE TABLE measurements (
    measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    round_no INTEGER NOT NULL,
    measured_at TEXT NOT NULL,
    runner_identity TEXT NOT NULL,
    environment_type TEXT NOT NULL,
    status TEXT NOT NULL,
    latency_ms REAL,
    throughput_kbps REAL,
    error_class TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (
        run_id, line_id, round_no,
        runner_identity, environment_type
    )
);

CREATE TABLE line_scores (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    scored_at TEXT NOT NULL,
    total_score REAL NOT NULL,
    components_json TEXT NOT NULL,
    UNIQUE (run_id, line_id)
);

CREATE TABLE deep_probes (
    probe_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    probed_at TEXT NOT NULL,
    runner_identity TEXT NOT NULL,
    environment_type TEXT NOT NULL,
    status TEXT NOT NULL,
    has_video INTEGER,
    has_audio INTEGER,
    width INTEGER,
    height INTEGER,
    video_codec TEXT,
    audio_codec TEXT,
    duration_seconds REAL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, line_id, runner_identity, environment_type)
);

-- 频道内容检查必须精确到线路+频道配对。
CREATE TABLE run_candidate_checks (
    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    line_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    runner_identity TEXT NOT NULL,
    environment_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('passed', 'failed', 'unknown')
    ),
    content_match INTEGER CHECK (
        content_match IN (0, 1) OR content_match IS NULL
    ),
    ad_placeholder INTEGER CHECK (
        ad_placeholder IN (0, 1) OR ad_placeholder IS NULL
    ),
    invalid_content INTEGER CHECK (
        invalid_content IN (0, 1) OR invalid_content IS NULL
    ),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (run_id, line_id, channel_id)
        REFERENCES run_candidates(run_id, line_id, channel_id)
        ON DELETE CASCADE
);

CREATE INDEX idx_source_checks_source_time
    ON source_checks(source_id, checked_at);
CREATE INDEX idx_source_checks_run
    ON source_checks(run_id);
CREATE INDEX idx_source_lines_line
    ON source_lines(line_id);
CREATE INDEX idx_blacklists_target_active
    ON blacklists(target_type, target_id, active);
CREATE INDEX idx_publications_run_time
    ON publications(run_id, published_at);
CREATE INDEX idx_run_stages_status
    ON run_stages(status);
CREATE INDEX idx_candidate_pool_run
    ON run_candidate_pool(run_id);
CREATE INDEX idx_candidate_pool_line
    ON run_candidate_pool(line_id);
CREATE INDEX idx_candidate_pool_sources_source
    ON run_candidate_pool_sources(source_id);
CREATE INDEX idx_run_candidates_line_channel
    ON run_candidates(line_id, channel_id);
CREATE INDEX idx_run_candidate_sources_source
    ON run_candidate_sources(source_id);
CREATE INDEX idx_measurements_run_line
    ON measurements(run_id, line_id);
CREATE INDEX idx_measurements_line_time
    ON measurements(line_id, measured_at);
CREATE INDEX idx_deep_probes_line_time
    ON deep_probes(line_id, probed_at);
CREATE INDEX idx_scores_line_time
    ON line_scores(line_id, scored_at);
CREATE INDEX idx_source_scores_source_time
    ON source_scores(source_id, scored_at);
CREATE INDEX idx_candidate_checks_pair
    ON run_candidate_checks(run_id, line_id, channel_id);

PRAGMA user_version = 3;
COMMIT;
"""

REQUIRED_TABLES = {
    "runs",
    "sources",
    "source_checks",
    "lines",
    "channels",
    "source_lines",
    "line_channels",
    "source_scores",
    "blacklists",
    "publications",
    "run_stages",
    "run_candidate_pool",
    "run_candidate_pool_sources",
    "run_candidates",
    "run_candidate_sources",
    "measurements",
    "line_scores",
    "deep_probes",
    "run_candidate_checks",
}

REQUIRED_COLUMNS = {
    "runs": {
        "run_id", "started_at", "status", "runner_identity",
        "environment_type", "summary_json",
    },
    "sources": {
        "source_id", "name", "url", "source_type",
        "first_seen_at", "last_seen_at", "active",
    },
    "source_checks": {
        "source_check_id", "run_id", "source_id",
        "checked_at", "status", "evidence_json",
    },
    "lines": {
        "line_id", "url", "headers_json",
        "first_seen_at", "last_seen_at", "blacklist_status",
    },
    "channels": {"channel_id", "category", "name"},
    "source_lines": {"source_id", "line_id"},
    "line_channels": {"line_id", "channel_id"},
    "source_scores": {
        "source_score_id", "run_id", "source_id",
        "scored_at", "total_score", "components_json",
    },
    "blacklists": {
        "blacklist_id", "target_type", "target_id",
        "reason", "active",
    },
    "publications": {
        "publication_id", "run_id", "published_at",
        "status", "playlist_path",
    },
    "run_stages": {
        "run_id", "stage_name", "status",
        "runner_identity", "environment_type",
        "attempt_count", "summary_json",
    },
    "run_candidate_pool": {
        "run_id", "line_id", "channel_id",
        "url_snapshot", "headers_json_snapshot",
        "channel_name_snapshot", "category_snapshot",
        "ipv4_admission_status", "created_at",
    },
    "run_candidate_pool_sources": {
        "run_id", "line_id", "channel_id",
        "source_id", "created_at",
    },
    "run_candidates": {
        "run_id", "line_id", "channel_id",
        "candidate_order", "url_snapshot",
        "headers_json_snapshot", "channel_name_snapshot",
        "category_snapshot", "ipv4_admission_status",
        "created_at",
    },
    "run_candidate_sources": {
        "run_id", "line_id", "channel_id",
        "source_id", "created_at",
    },
    "measurements": {
        "measurement_id", "run_id", "line_id",
        "round_no", "measured_at", "status",
    },
    "line_scores": {
        "score_id", "run_id", "line_id",
        "scored_at", "total_score", "components_json",
    },
    "deep_probes": {
        "probe_id", "run_id", "line_id",
        "probed_at", "status", "evidence_json",
    },
    "run_candidate_checks": {
        "check_id", "run_id", "line_id", "channel_id",
        "checked_at", "status", "content_match",
        "ad_placeholder", "invalid_content", "evidence_json",
    },
}


class DatabaseSchemaError(RuntimeError):
    """Raised when the existing database is not a valid V3 database."""


def connect_database(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(db_path, timeout=30)

    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection
    except Exception:
        connection.close()
        raise


@contextmanager
def database_session(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open one transaction and always close its connection."""
    connection = connect_database(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _validate_v3_database(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT name
          FROM sqlite_master
         WHERE type = 'table'
           AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()

    existing_tables = {row["name"] for row in rows}
    missing_tables = REQUIRED_TABLES - existing_tables

    if missing_tables:
        raise DatabaseSchemaError(
            "数据库标记为V3，但缺少必要数据表："
            + ", ".join(sorted(missing_tables))
        )

    for table, required in REQUIRED_COLUMNS.items():
        rows = connection.execute(
            f'PRAGMA table_info("{table}")'
        ).fetchall()
        actual = {row["name"] for row in rows}
        missing = required - actual

        if missing:
            raise DatabaseSchemaError(
                f"V3数据表 {table} 缺少字段："
                + ", ".join(sorted(missing))
            )

    violations = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()

    if violations:
        raise DatabaseSchemaError(
            f"V3数据库存在外键异常：{len(violations)}项"
        )


def initialize_database(path: str | Path) -> None:
    """
    Create a new V3 database.

    Existing V1/V2 databases are deliberately rejected.
    No migration, automatic repair, or historical data import is performed.
    """
    connection = connect_database(path)

    try:
        version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]

        existing = connection.execute(
            """
            SELECT name
              FROM sqlite_master
             WHERE type = 'table'
               AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()

        if version == SCHEMA_VERSION:
            _validate_v3_database(connection)
            return

        if version != 0 or existing:
            raise DatabaseSchemaError(
                f"发现非V3数据库（版本 {version}）。"
                "本系统不迁移V1/V2数据。"
                "请按施工方案移除旧数据库Artifact，"
                "再由V3程序创建全新数据库。"
            )

        connection.executescript(SCHEMA)
        _validate_v3_database(connection)

    finally:
        connection.close()
