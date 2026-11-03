import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iptv_auto.database import initialize_database, connect_database

class DatabaseConnectionTests(unittest.TestCase):
    def test_database_initializes_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fresh.sqlite3"
            initialize_database(path)
            with connect_database(path) as db:
                names = {r["name"] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
            self.assertTrue({"runs", "source_lines", "deep_probes"}.issubset(names))

    def test_initialize_database_closes_connection(self):
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

if __name__ == "__main__":
    unittest.main()
