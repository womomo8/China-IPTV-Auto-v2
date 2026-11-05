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
                row["name"]
                for row in db.execute(
                    """
                    SELECT name
                      FROM sqlite_master
                     WHERE type = 'table'
                    """
                )
            }

    def test_fresh_database_creates_v3_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fresh.sqlite3"
            initialize_database(path)

            tables = self._tables(path)

            expected = {
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

            self.assertTrue(expected.issubset(tables))

            with connect_database(path) as db:
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION,
                )

    def test_v3_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "v3.sqlite3"

            initialize_database(path)

            with database_session(path) as db:
                db.execute(
                    """
                    INSERT INTO runs
                        (started_at, status, runner_identity)
                    VALUES ('2026-11-05T00:00:00Z', 'running', 'test')
                    """
                )

            initialize_database(path)

            with connect_database(path) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    3,
                )

    def test_v2_database_is_rejected_without_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old-v2.sqlite3"

            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE old_data (id INTEGER PRIMARY KEY)"
                )
                db.execute("PRAGMA user_version = 2")

            with self.assertRaises(DatabaseSchemaError):
                initialize_database(path)

            with sqlite3.connect(path) as db:
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    2,
                )
                self.assertIsNotNone(
                    db.execute(
                        """
                        SELECT name FROM sqlite_master
                         WHERE name = 'old_data'
                        """
                    ).fetchone()
                )

    def test_v1_database_is_rejected_without_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old-v1.sqlite3"

            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE old_data (id INTEGER PRIMARY KEY)"
                )
                db.execute("PRAGMA user_version = 1")

            with self.assertRaises(DatabaseSchemaError):
                initialize_database(path)

            with sqlite3.connect(path) as db:
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    1,
                )

    def test_unversioned_nonempty_database_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "unknown.sqlite3"

            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE unknown_table (id INTEGER PRIMARY KEY)"
                )

            with self.assertRaises(DatabaseSchemaError):
                initialize_database(path)

    def test_initialize_closes_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "closed.sqlite3"
            real_connect = connect_database
            opened = []

            def tracked_connect(db_path):
                connection = real_connect(db_path)
                opened.append(connection)
                return connection

            with patch(
                "iptv_auto.database.connect_database",
                side_effect=tracked_connect,
            ):
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
                connection = real_connect(db_path)
                opened.append(connection)
                return connection

            with patch(
                "iptv_auto.database.connect_database",
                side_effect=tracked_connect,
            ):
                with database_session(path) as db:
                    db.execute(
                        "CREATE TABLE sample (id INTEGER)"
                    )

            self.assertEqual(len(opened), 1)

            with self.assertRaises(sqlite3.ProgrammingError):
                opened[0].execute("SELECT 1")

    def test_candidate_pool_pair_is_unique(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pool.sqlite3"
            initialize_database(path)

            with database_session(path) as db:
                db.execute(
                    """
                    INSERT INTO runs
                        (started_at, status, runner_identity)
                    VALUES ('2026-11-05T00:00:00Z', 'running', 'test')
                    """
                )
                db.execute(
                    """
                    INSERT INTO sources
                        (source_id, url, first_seen_at, last_seen_at)
                    VALUES (
                        'source-1',
                        'https://source.example/list.m3u',
                        '2026-11-05T00:00:00Z',
                        '2026-11-05T00:00:00Z'
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO lines
                        (line_id, url, first_seen_at, last_seen_at)
                    VALUES (
                        'line-1',
                        'https://stream.example/live',
                        '2026-11-05T00:00:00Z',
                        '2026-11-05T00:00:00Z'
                    )
                    """
                )
                db.execute(
                    """
                    INSERT INTO channels (channel_id, name)
                    VALUES ('channel-1', 'CCTV-5')
                    """
                )

                values = (
                    1,
                    "line-1",
                    "channel-1",
                    "https://stream.example/live",
                    "{}",
                    "CCTV-5",
                    "体育频道",
                    "passed",
                    "2026-11-05T00:00:00Z",
                )

                sql = """
                    INSERT INTO run_candidate_pool (
                        run_id, line_id, channel_id,
                        url_snapshot, headers_json_snapshot,
                        channel_name_snapshot, category_snapshot,
                        ipv4_admission_status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """

                db.execute(sql, values)

                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql, values)

                db.execute(
                    """
                    INSERT INTO run_candidate_pool_sources
                    VALUES (
                        1, 'line-1', 'channel-1',
                        'source-1', '2026-11-05T00:00:00Z'
                    )
                    """
                )

    def test_candidate_check_requires_frozen_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "check.sqlite3"
            initialize_database(path)

            with database_session(path) as db:
                db.execute(
                    """
                    INSERT INTO runs
                        (started_at, status, runner_identity)
                    VALUES ('2026-11-05T00:00:00Z', 'running', 'test')
                    """
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        """
                        INSERT INTO run_candidate_checks (
                            run_id, line_id, channel_id,
                            checked_at, runner_identity,
                            environment_type, status
                        )
                        VALUES (
                            1, 'missing-line', 'missing-channel',
                            '2026-11-05T00:00:00Z',
                            'test', 'cloud', 'passed'
                        )
                        """
                    )

    def test_stage_status_constraint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "stages.sqlite3"
            initialize_database(path)

            with database_session(path) as db:
                db.execute(
                    """
                    INSERT INTO runs
                        (started_at, status, runner_identity)
                    VALUES ('2026-11-05T00:00:00Z', 'running', 'test')
                    """
                )

                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(
                        """
                        INSERT INTO run_stages
                            (run_id, stage_name, status)
                        VALUES (1, 'bad-stage', 'finished-ish')
                        """
                    )

    def test_foreign_key_check_is_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "foreign-keys.sqlite3"
            initialize_database(path)

            with connect_database(path) as db:
                self.assertEqual(
                    db.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )


if __name__ == "__main__":
    unittest.main()
