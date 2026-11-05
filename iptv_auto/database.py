"""Versioned SQLite schema and safe migrations for the IPTV pipeline."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA_VERSION = 2

# Fresh databases are created directly at the current schema version.
SCHEMA = r"""
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    runner_identity TEXT NOT NULL,
    environment_type TEXT NOT NULL DEFAULT 'cloud',
    summary_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL DEFAULT 'discovered',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS source_checks (
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

CREATE TABLE IF NOT EXISTS lines (
    line_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    headers_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    blacklist_status TEXT NOT NULL DEFAULT 'clear'
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_lines (
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (source_id, line_id)
);

CREATE TABLE IF NOT EXISTS line_channels (
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (line_id, channel_id)
);

CREATE TABLE IF NOT EXISTS measurements (
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
    UNIQUE (run_id, line_id, round_no, runner_identity, environment_type)
);

CREATE TABLE IF NOT EXISTS deep_probes (
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

CREATE TABLE IF NOT EXISTS line_scores (
    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    line_id TEXT NOT NULL REFERENCES lines(line_id),
    scored_at TEXT NOT NULL,
    total_score REAL NOT NULL,
    components_json TEXT NOT NULL,
    UNIQUE (run_id, line_id)
);

CREATE TABLE IF NOT EXISTS source_scores (
    source_score_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(run_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    scored_at TEXT NOT NULL,
    total_score REAL NOT NULL,
    components_json TEXT NOT NULL,
    UNIQUE (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS blacklists (
    blacklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL CHECK (target_type IN ('source', 'line', 'url')),
    target_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS publications (
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

CREATE TABLE IF NOT EXISTS run_candidates (
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

CREATE TABLE IF NOT EXISTS run_candidate_sources (
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

CREATE TABLE IF NOT EXISTS run_stages (
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
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    summary_json TEXT NOT NULL DEFAULT '{}',
    error_class TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, stage_name)
);

CREATE INDEX IF NOT EXISTS idx_source_checks_source_time
    ON source_checks(source_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_source_checks_run
    ON source_checks(run_id);
CREATE INDEX IF NOT EXISTS idx_measurements_line_time
    ON measurements(line_id, measured_at);
CREATE INDEX IF NOT EXISTS idx_measurements_run
    ON measurements(run_id);
CREATE INDEX IF NOT EXISTS idx_measurements_env_line
    ON measurements(environment_type, line_id, measured_at);
CREATE INDEX IF NOT EXISTS idx_deep_probes_line_time
    ON deep_probes(line_id, probed_at);
CREATE INDEX IF NOT EXISTS idx_scores_line_time
    ON line_scores(line_id, scored_at);
CREATE INDEX IF NOT EXISTS idx_source_scores_source_time
    ON source_scores(source_id, scored_at);
CREATE INDEX IF NOT EXISTS idx_source_lines_line
    ON source_lines(line_id);
CREATE INDEX IF NOT EXISTS idx_blacklists_target_active
    ON blacklists(target_type, target_id, active);
CREATE INDEX IF NOT EXISTS idx_publications_run_time
    ON publications(run_id, published_at);
CREATE INDEX IF NOT EXISTS idx_run_candidates_line_channel
    ON run_candidates(line_id, channel_id);
CREATE INDEX IF NOT EXISTS idx_run_candidate_sources_source
    ON run_candidate_sources(source_id);
CREATE INDEX IF NOT EXISTS idx_run_stages_status
    ON run_stages(status);

PRAGMA user_version = 2;
COMMIT;
"""

# Each item is a single SQL statement so the migration remains inside the
# explicit transaction (sqlite3.Connection.executescript can commit implicitly).
_V1_TO_V2_STATEMENTS = (
    """CREATE TABLE run_candidates (
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
    )""",
    """CREATE TABLE run_candidate_sources (
        run_id INTEGER NOT NULL,
        line_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        source_id TEXT NOT NULL REFERENCES sources(source_id),
        created_at TEXT NOT NULL,
        PRIMARY KEY (run_id, line_id, channel_id, source_id),
        FOREIGN KEY (run_id, line_id, channel_id)
            REFERENCES run_candidates(run_id, line_id, channel_id)
            ON DELETE CASCADE
    )""",
    """CREATE TABLE run_stages (
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
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        summary_json TEXT NOT NULL DEFAULT '{}',
        error_class TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (run_id, stage_name)
    )""",
    "CREATE INDEX idx_run_candidates_line_channel ON run_candidates(line_id, channel_id)",
    "CREATE INDEX idx_run_candidate_sources_source ON run_candidate_sources(source_id)",
    "CREATE INDEX idx_run_stages_status ON run_stages(status)",
)

_V1_REQUIRED_COLUMNS = {
    "runs": {"run_id", "started_at", "status", "runner_identity"},
    "sources": {"source_id", "url", "first_seen_at", "last_seen_at"},
    "source_checks": {"source_check_id", "run_id", "source_id", "checked_at"},
    "lines": {"line_id", "url", "first_seen_at", "last_seen_at"},
    "channels": {"channel_id", "name", "category"},
    "source_lines": {"source_id", "line_id"},
    "line_channels": {"line_id", "channel_id"},
    "measurements": {"measurement_id", "run_id", "line_id", "round_no"},
    "deep_probes": {"probe_id", "run_id", "line_id"},
    "line_scores": {"score_id", "run_id", "line_id"},
    "source_scores": {"source_score_id", "run_id", "source_id"},
    "blacklists": {"blacklist_id", "target_type", "target_id"},
    "publications": {"publication_id", "run_id", "published_at"},
}


class DatabaseSchemaError(RuntimeError):
    """Raised when an existing database cannot safely use this schema version."""


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
    """Transaction scope that always closes the SQLite connection."""
    connection = connect_database(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _validate_v1_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing_tables = set(_V1_REQUIRED_COLUMNS) - tables
    if missing_tables:
        raise DatabaseSchemaError(
            "检测到 user_version=1，但缺少必要的数据表，拒绝自动迁移："
            + ", ".join(sorted(missing_tables))
        )

    for table, required in _V1_REQUIRED_COLUMNS.items():
        columns = {
            row["name"] for row in connection.execute(
                f'PRAGMA table_info("{table}")'
            )
        }
        missing = required - columns
        if missing:
            raise DatabaseSchemaError(
                f"检测到 V1 数据库表 {table} 结构不完整，缺少字段："
                + ", ".join(sorted(missing))
            )


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    _validate_v1_schema(connection)
    try:
        connection.execute("BEGIN IMMEDIATE")
        # Re-check the version after obtaining the write lock.
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            connection.commit()
            return
        if version != 1:
            raise DatabaseSchemaError(
                f"迁移期间数据库版本发生变化：{version}"
            )

        for statement in _V1_TO_V2_STATEMENTS:
            connection.execute(statement)

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise DatabaseSchemaError(
                f"V1 数据库存在外键异常，拒绝迁移（{len(violations)} 项）"
            )

        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


def initialize_database(path: str | Path) -> None:
    """Create a fresh V2 database or safely migrate a recognized V1 database."""
    connection = connect_database(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        existing_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

        if version == SCHEMA_VERSION:
            # Idempotent validation/creation for the current version only.
            required = set(_V1_REQUIRED_COLUMNS) | {
                "run_candidates", "run_candidate_sources", "run_stages"
            }
            table_names = {row["name"] for row in existing_tables}
            if not required.issubset(table_names):
                raise DatabaseSchemaError(
                    "数据库标记为 V2，但缺少必要数据表；为保护历史数据，拒绝自动修补。"
                )
            return

        if version == 1:
            _migrate_v1_to_v2(connection)
            return

        if version != 0 or existing_tables:
            raise DatabaseSchemaError(
                f"数据库结构版本不匹配（当前版本 {version}，目标版本 {SCHEMA_VERSION}）。"
                "为避免破坏历史数据，本程序不会自动覆盖或猜测迁移。"
            )

        connection.executescript(SCHEMA)
    finally:
        connection.close()
