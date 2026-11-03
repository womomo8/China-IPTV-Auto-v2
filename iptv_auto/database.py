"""Fresh SQLite schema for v2. No legacy database migration is performed."""
from __future__ import annotations
from pathlib import Path
import sqlite3

SCHEMA = r"""PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS runs (
 run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
 finished_at TEXT, status TEXT NOT NULL, runner_identity TEXT NOT NULL,
 summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS sources (
 source_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', url TEXT NOT NULL UNIQUE,
 source_type TEXT NOT NULL DEFAULT 'discovered', first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS lines (
 line_id TEXT PRIMARY KEY, url TEXT NOT NULL, headers_json TEXT NOT NULL DEFAULT '{}',
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 blacklist_status TEXT NOT NULL DEFAULT 'clear'
);
CREATE TABLE IF NOT EXISTS channels (
 channel_id TEXT PRIMARY KEY, category TEXT NOT NULL DEFAULT '', name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_lines (
 source_id TEXT NOT NULL REFERENCES sources(source_id),
 line_id TEXT NOT NULL REFERENCES lines(line_id), first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL, PRIMARY KEY (source_id, line_id)
);
CREATE TABLE IF NOT EXISTS line_channels (
 line_id TEXT NOT NULL REFERENCES lines(line_id),
 channel_id TEXT NOT NULL REFERENCES channels(channel_id), first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL, PRIMARY KEY (line_id, channel_id)
);
CREATE TABLE IF NOT EXISTS measurements (
 measurement_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs(run_id),
 line_id TEXT NOT NULL REFERENCES lines(line_id), measured_at TEXT NOT NULL,
 runner_identity TEXT NOT NULL, status TEXT NOT NULL, latency_ms REAL,
 throughput_kbps REAL, error_class TEXT NOT NULL DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS deep_probes (
 probe_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs(run_id),
 line_id TEXT NOT NULL REFERENCES lines(line_id), probed_at TEXT NOT NULL,
 status TEXT NOT NULL, has_video INTEGER, has_audio INTEGER, width INTEGER, height INTEGER,
 video_codec TEXT, audio_codec TEXT, duration_seconds REAL, evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS line_scores (
 score_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL REFERENCES runs(run_id),
 line_id TEXT NOT NULL REFERENCES lines(line_id), scored_at TEXT NOT NULL,
 total_score REAL NOT NULL, components_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blacklists (
 blacklist_id INTEGER PRIMARY KEY AUTOINCREMENT, target_type TEXT NOT NULL,
 target_id TEXT NOT NULL, reason TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_measurements_line_time ON measurements(line_id, measured_at);
CREATE INDEX IF NOT EXISTS idx_measurements_run ON measurements(run_id);
CREATE INDEX IF NOT EXISTS idx_scores_line_time ON line_scores(line_id, scored_at);
CREATE INDEX IF NOT EXISTS idx_source_lines_line ON source_lines(line_id);
"""

def connect_database(path: str | Path) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def initialize_database(path: str | Path) -> None:
    """Create missing v2 tables and always close the connection afterwards."""
    connection = connect_database(path)
    try:
        # SQLite's connection context manager commits/rolls back; it does not close.
        with connection:
            connection.executescript(SCHEMA)
    finally:
        connection.close()
