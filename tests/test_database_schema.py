import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iptv_auto.database import (
    SCHEMA_VERSION,
    DatabaseSchemaError,
    connect_database,
    database_session,
    initialize_database,
)


class DatabaseSchemaTests(unittest.TestCase):
    def _tables(self, path):
        with connect_database(path) as db:
            return {
                row["name"] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

    def _make_v1_database(self, path):
        """Create a genuine V1 database using the repository's historical schema."""
        with sqlite3.connect(path) as db:
            db.executescript("""
                PRAGMA foreign_keys = ON;
                CREATE TABLE runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
                    runner_identity TEXT NOT NULL,
                    environment_type TEXT NOT NULL DEFAULT 'cloud',
                    summary_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE sources (
                    source_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL UNIQUE, source_type TEXT NOT NULL DEFAULT 'discovered',
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE source_checks (
                    source_check_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES runs(run_id),
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    checked_at TEXT NOT NULL, status TEXT NOT NULL, http_status INTEGER,
                    duration_ms REAL, discovered_lines INTEGER NOT NULL DEFAULT 0,
                    accepted_lines INTEGER NOT NULL DEFAULT 0,
                    error_class TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE (run_id, source_id)
                );
                CREATE TABLE lines (
                    line_id TEXT PRIMARY KEY, url TEXT NOT NULL,
                    headers_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    blacklist_status TEXT NOT NULL DEFAULT 'clear'
                );
                CREATE TABLE channels (
                    channel_id TEXT PRIMARY KEY, category TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL
                );
                CREATE TABLE source_lines (
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    line_id TEXT NOT NULL REFERENCES lines(line_id),
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, line_id)
                );
                CREATE TABLE line_channels (
                    line_id TEXT NOT NULL REFERENCES lines(line_id),
                    channel_id TEXT NOT NULL REFERENCES channels(channel_id),
                    first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (line_id, channel_id)
                );
                CREATE TABLE measurements (
                    measurement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES runs(run_id),
                    line_id TEXT NOT NULL REFERENCES lines(line_id),
                    round_no INTEGER NOT NULL, measured_at TEXT NOT NULL,
                    runner_identity TEXT NOT NULL, environment_type TEXT NOT NULL,
                    status TEXT NOT NULL, latency_ms REAL, throughput_kbps REAL,
                    error_class TEXT NOT NULL DEFAULT '', evidence_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE (run_id, line_id, round_no, runner_identity, environment_type)
                );
                CREATE TABLE deep_probes (
                    probe_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES runs(run_id),
                    line_id TEXT NOT NULL REFERENCES lines(line_id),
                    probed_at TEXT NOT NULL, runner_identity TEXT NOT NULL,
                    environment_type TEXT NOT NULL, status TEXT NOT NULL,
                    has_video INTEGER, has_audio INTEGER, width INTEGER, height INTEGER,
                    video_codec TEXT, audio_codec TEXT, duration_seconds REAL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    UNIQUE (run_id, line_id, runner_identity, environment_type)
                );
                CREATE TABLE line_scores (
                    score_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES runs(run_id),
                    line_id TEXT NOT NULL REFERENCES lines(line_id),
                    scored_at TEXT NOT NULL, total_score REAL NOT NULL,
                    components_json TEXT NOT NULL,
                    UNIQUE (run_id, line_id)
                );
                CREATE TABLE source_scores (
                    source_score_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES runs(run_id),
                    source_id TEXT NOT NULL REFERENCES sources(source_id),
                    scored_at TEXT NOT NULL, total_score REAL NOT NULL,
                    components_json TEXT NOT NULL,
                    UNIQUE (run_id, source_id)
                );
                CREATE TABLE blacklists (
                    blacklist_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_type TEXT NOT NULL CHECK (target_type IN ('source', 'line', 'url')),
                    target_id TEXT NOT NULL, reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
                );
                CREATE TABLE publications (
                    publication_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES runs(run_id),
                    published_at TEXT NOT NULL, status TEXT NOT NULL,
                    playlist_path TEXT NOT NULL, content_sha256 TEXT,
                    entry_count INTEGER NOT NULL DEFAULT 0, previous_sha256 TEXT,
                    preserved_previous INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO runs (run_id, started_at, status, runner_identity)
                VALUES (7, '2026-11-01T00:00:00Z', 'completed', 'old-runner');
                INSERT INTO sources
                (source_id, name, url, first_seen_at, last_seen_at)
                VALUES ('src-1', 'source', 'https://source.example/list.m3u',
                        '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z');
                INSERT INTO lines
                (line_id, url, first_seen_at, last_seen_at)
                VALUES ('line-1', 'https://stream.example/live',
                        '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z');
                INSERT INTO channels (channel_id, category, name)
                VALUES ('channel-1', '体育', 'CCTV-5');
                INSERT INTO source_lines
                VALUES ('src-1', 'line-1', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z');
                INSERT INTO line_channels
                VALUES ('line-1', 'channel-1', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z');
                INSERT INTO measurements
                (run_id, line_id, round_no, measured_at, runner_identity,
                 environment_type, status)
                VALUES (7, 'line-1', 1, '2026-11-01T00:01:00Z',
                        'old-runner', 'cloud', 'ok');
                PRAGMA user_version = 1;
            """)

    def test_fresh_database_has_v2_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fresh.sqlite3"
            initialize_database(path)
            tables = self._tables(path)
            self.assertTrue({
                "runs", "sources", "source_checks", "lines", "channels",
                "source_lines", "line_channels", "measurements", "deep_probes",
                "line_scores", "source_scores", "blacklists", "publications",
                "run_candidates", "run_candidate_sources", "run_stages",
            }.issubset(tables))
            with connect_database(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_v1_migration_preserves_historical_records(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "v1.sqlite3"
            self._make_v1_database(path)
            initialize_database(path)
            with connect_database(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM lines").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM channels").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM measurements").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT run_id FROM runs").fetchone()[0], 7)
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_v1_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "v1.sqlite3"
            self._make_v1_database(path)
            initialize_database(path)
            initialize_database(path)
            with connect_database(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_failed_v1_migration_rolls_back_all_new_objects(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "v1-fail.sqlite3"
            self._make_v1_database(path)
            with patch(
                "iptv_auto.database._V1_TO_V2_STATEMENTS",
                (
                    "CREATE TABLE migration_probe (id INTEGER PRIMARY KEY)",
                    "THIS IS NOT VALID SQL",
                ),
            ):
                with self.assertRaises(sqlite3.OperationalError):
                    initialize_database(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                names = {
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertNotIn("migration_probe", names)
                self.assertNotIn("run_candidates", names)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_v1_with_missing_core_table_is_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken-v1.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE runs (run_id INTEGER PRIMARY KEY)")
                db.execute("PRAGMA user_version = 1")
            with self.assertRaises(DatabaseSchemaError):
                initialize_database(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertIsNone(db.execute(
                    "SELECT name FROM sqlite_master WHERE name='run_candidates'"
                ).fetchone())

    def test_initialize_closes_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "closed.sqlite3"
            real_connect = connect_database
            opened = []

            def tracked_connect(db_path):
                conn = real_connect(db_path)
                opened.append(conn)
                return conn

            with patch("iptv_auto.database.connect_database", side_effect=tracked_connect):
                initialize_database(path)
            self.assertEqual(len(opened), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                opened[0].execute("SELECT 1")

    def test_database_session_always_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "session.sqlite3"
            initialize_database(path)
            real_connect = connect_database
            opened = []

            def tracked_connect(db_path):
                conn = real_connect(db_path)
                opened.append(conn)
                return conn

            with patch("iptv_auto.database.connect_database", side_effect=tracked_connect):
                with database_session(path) as db:
                    db.execute("CREATE TABLE sample (id INTEGER)")
            self.assertEqual(len(opened), 1)
            with self.assertRaises(sqlite3.ProgrammingError):
                opened[0].execute("SELECT 1")

    def test_foreign_keys_and_candidate_pair_uniqueness(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "constraints.sqlite3"
            initialize_database(path)
            with connect_database(path) as db:
                db.execute("""
                    INSERT INTO runs (started_at, status, runner_identity)
                    VALUES ('2026-11-01T00:00:00Z', 'running', 'runner')
                """)
                db.execute("""
                    INSERT INTO sources
                    (source_id, url, first_seen_at, last_seen_at)
                    VALUES ('src', 'https://source.example/list',
                            '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')
                """)
                db.execute("""
                    INSERT INTO lines
                    (line_id, url, first_seen_at, last_seen_at)
                    VALUES ('line', 'https://stream.example/live',
                            '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')
                """)
                db.execute("""
                    INSERT INTO channels (channel_id, name)
                    VALUES ('channel', 'CCTV-5')
                """)
                candidate = (
                    1, "line", "channel", 1, "https://stream.example/live",
                    "{}", "CCTV-5", "体育", "passed", "2026-11-01T00:00:00Z"
                )
                sql = """INSERT INTO run_candidates
                    (run_id, line_id, channel_id, candidate_order, url_snapshot,
                     headers_json_snapshot, channel_name_snapshot, category_snapshot,
                     ipv4_admission_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
                db.execute(sql, candidate)
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql, candidate)
                db.execute("""
                    INSERT INTO run_candidate_sources
                    VALUES (1, 'line', 'channel', 'src', '2026-11-01T00:00:00Z')
                """)
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("""
                        INSERT INTO run_candidate_sources
                        VALUES (1, 'line', 'channel', 'missing', '2026-11-01T00:00:00Z')
                    """)

    def test_stage_status_constraint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "stages.sqlite3"
            initialize_database(path)
            with connect_database(path) as db:
                db.execute("""
                    INSERT INTO runs (started_at, status, runner_identity)
                    VALUES ('2026-11-01T00:00:00Z', 'running', 'runner')
                """)
                db.execute("""
                    INSERT INTO run_stages (run_id, stage_name, status)
                    VALUES (1, 'discovery', 'pending')
                """)
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("""
                        INSERT INTO run_stages (run_id, stage_name, status)
                        VALUES (1, 'bad-stage', 'finished-ish')
                    """)

    def test_unknown_existing_schema_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE old_table (id INTEGER)")
            with self.assertRaises(DatabaseSchemaError):
                initialize_database(path)


if __name__ == "__main__":
    unittest.main()
