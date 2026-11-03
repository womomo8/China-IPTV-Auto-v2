"""Versioned SQLite schema for the single v2 processing pipeline."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


SCHEMA_VERSION = 1

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

PRAGMA user_version = 1;
COMMIT;
"""


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


def initialize_database(path: str | Path) -> None:
    """Create a fresh v2 database; never silently migrate an unknown schema."""
    connection = connect_database(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        existing_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

        if version == SCHEMA_VERSION:
            connection.executescript(SCHEMA)
            return

        if version != 0 or existing_tables:
            raise DatabaseSchemaError(
                f"数据库结构版本不匹配（当前版本 {version}，目标版本 {SCHEMA_VERSION}）。"
                "为避免破坏历史数据，本程序不会自动覆盖或猜测迁移。"
            )

        connection.executescript(SCHEMA)
    finally:
        connection.close()
