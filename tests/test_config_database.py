import tempfile
import unittest
from pathlib import Path

from iptv_auto.config import load_config
from iptv_auto.database import initialize_database, connect_database


class ConfigDatabaseTests(unittest.TestCase):
    def test_default_config_passes_release_invariants(self):
        config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
        self.assertEqual(config["release"]["max_lines_per_channel"], 3)

    def test_database_initializes_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fresh.sqlite3"
            initialize_database(path)
            with connect_database(path) as db:
                tables = {
                    row["name"] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertIn("runs", tables)
            self.assertIn("source_lines", tables)
            self.assertIn("deep_probes", tables)


if __name__ == "__main__":
    unittest.main()
