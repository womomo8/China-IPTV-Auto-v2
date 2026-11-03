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

    def test_fresh_database_has_pipeline_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fresh.sqlite3"
            initialize_database(path)
            tables = self._tables(path)
            self.assertTrue({
                "runs", "sources", "source_checks", "lines", "channels",
                "source_lines", "line_channels", "measurements", "deep_probes",
                "line_scores", "source_scores", "blacklists", "publications",
            }.issubset(tables))
            with connect_database(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

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

    def test_foreign_keys_are_enforced(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fk.sqlite3"
            initialize_database(path)
            with connect_database(path) as db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        """INSERT INTO source_checks
                           (run_id, source_id, checked_at, status)
                           VALUES (999, 'missing', '2026-01-01T00:00:00Z', 'failed')"""
                    )

    def test_measurement_rounds_are_not_duplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unique.sqlite3"
            initialize_database(path)
            with connect_database(path) as db:
                db.execute(
                    """INSERT INTO runs
                       (started_at, status, runner_identity, environment_type)
                       VALUES ('2026-01-01T00:00:00Z', 'running', 'runner-1', 'cloud')"""
                )
                db.execute(
                    """INSERT INTO lines
                       (line_id, url, first_seen_at, last_seen_at)
                       VALUES ('line-1', 'https://example.com/live',
                               '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"""
                )
                args = (1, "line-1", 1, "2026-01-01T00:01:00Z", "runner-1", "cloud", "ok")
                db.execute(
                    """INSERT INTO measurements
                       (run_id, line_id, round_no, measured_at, runner_identity,
                        environment_type, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""", args
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        """INSERT INTO measurements
                           (run_id, line_id, round_no, measured_at, runner_identity,
                            environment_type, status)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""", args
                    )

    def test_unknown_existing_schema_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE old_table (id INTEGER)")
            with self.assertRaises(DatabaseSchemaError):
                initialize_database(path)


if __name__ == "__main__":
    unittest.main()
