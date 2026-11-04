
import tempfile
import unittest
from pathlib import Path
from dataclasses import dataclass

from iptv_auto.database import database_session, initialize_database
from iptv_auto.identity import stable_source_id
from iptv_auto.source_registry import SourceRegistry


@dataclass
class Candidate:
    name: str
    url: str
    source_type: str = "discovered"

    @property
    def source_id(self):
        return stable_source_id(self.url)


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.sqlite3"
        initialize_database(self.db_path)
        self.registry = SourceRegistry(self.db_path)

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO runs
                    (started_at, status, runner_identity, environment_type)
                VALUES ('2026-11-04T00:00:00Z', 'running', 'test', 'cloud')
                """
            )

    def tearDown(self):
        self.temp.cleanup()

    def test_adds_manual_source(self):
        item = Candidate(
            "人工来源", "https://example.com/manual.m3u", "manual"
        )
        result = self.registry.sync_candidates([item])

        self.assertIn(item.source_id, result.accepted)

        with database_session(self.db_path) as db:
            row = db.execute(
                "SELECT source_type, active FROM sources WHERE source_id = ?",
                (item.source_id,),
            ).fetchone()

        self.assertEqual(row["source_type"], "manual")
        self.assertEqual(row["active"], 1)

    def test_blacklisted_source_is_rejected(self):
        item = Candidate("黑名单来源", "https://example.com/bad.m3u")

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO blacklists
                    (target_type, target_id, reason, created_at)
                VALUES ('source', ?, 'confirmed bad source',
                        '2026-11-04T00:00:00Z')
                """,
                (item.source_id,),
            )

        result = self.registry.sync_candidates([item])

        self.assertIn(item.source_id, result.rejected_blacklist)
        self.assertNotIn(item.source_id, result.accepted)

    def test_url_blacklist_is_rejected(self):
        item = Candidate("广告来源", "https://example.com/ad.m3u")

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO blacklists
                    (target_type, target_id, reason, created_at)
                VALUES ('url', ?, 'confirmed advertisement',
                        '2026-11-04T00:00:00Z')
                """,
                (item.url,),
            )

        result = self.registry.sync_candidates([item])
        self.assertIn(item.source_id, result.rejected_blacklist)

    def test_new_discovered_sources_are_capped_at_eight(self):
        items = [
            Candidate(f"来源{i}", f"https://example.com/{i}.m3u")
            for i in range(12)
        ]

        result = self.registry.sync_candidates(items)

        self.assertEqual(len(result.accepted), 8)
        self.assertEqual(len(result.rejected_capacity), 4)

        with database_session(self.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM sources WHERE active = 1"
            ).fetchone()[0]

        self.assertEqual(count, 8)

    def test_duplicate_source_is_not_added_twice(self):
        item = Candidate("重复来源", "https://example.com/same.m3u")

        first = self.registry.sync_candidates([item])
        second = self.registry.sync_candidates([item])

        self.assertEqual(len(first.accepted), 1)
        self.assertEqual(len(second.accepted), 1)

        with database_session(self.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM sources WHERE source_id = ?",
                (item.source_id,),
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_records_source_fetch_history(self):
        item = Candidate("测试来源", "https://example.com/test.m3u")
        self.registry.sync_candidates([item])

        self.registry.record_source_check(
            run_id=1,
            source_id=item.source_id,
            status="success",
            http_status=200,
            duration_ms=500,
            discovered_lines=20,
            accepted_lines=15,
        )

        with database_session(self.db_path) as db:
            row = db.execute(
                "SELECT * FROM source_checks WHERE source_id = ?",
                (item.source_id,),
            ).fetchone()

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["discovered_lines"], 20)
        self.assertEqual(row["accepted_lines"], 15)

    def test_no_history_means_no_score(self):
        item = Candidate("无历史来源", "https://example.com/no-history.m3u")
        self.registry.sync_candidates([item])

        score = self.registry.calculate_source_score(item.source_id)
        self.assertIsNone(score)

    def test_source_score_uses_fetch_history_not_line_quality(self):
        item = Candidate("有历史来源", "https://example.com/history.m3u")
        self.registry.sync_candidates([item])

        self.registry.record_source_check(
            run_id=1,
            source_id=item.source_id,
            status="success",
            discovered_lines=100,
            accepted_lines=75,
        )

        score = self.registry.calculate_source_score(item.source_id)

        self.assertIsNotNone(score)
        self.assertEqual(score.fetch_success_rate, 1.0)
        self.assertEqual(score.accepted_line_rate, 0.75)
        self.assertEqual(score.effective_checks, 1)
        self.assertEqual(score.total_score, 90.0)

        # Line measurements must not affect source reliability scoring.
        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO lines
                    (line_id, url, first_seen_at, last_seen_at)
                VALUES ('line-test', 'https://stream.example/live',
                        '2026-11-04T00:00:00Z',
                        '2026-11-04T00:00:00Z')
                """
            )
            db.execute(
                """
                INSERT INTO source_lines
                    (source_id, line_id, first_seen_at, last_seen_at)
                VALUES (?, 'line-test', '2026-11-04T00:00:00Z',
                        '2026-11-04T00:00:00Z')
                """,
                (item.source_id,),
            )
            db.execute(
                """
                INSERT INTO measurements
                    (run_id, line_id, round_no, measured_at,
                     runner_identity, environment_type, status)
                VALUES (1, 'line-test', 1, '2026-11-04T00:00:00Z',
                        'test', 'cloud', 'failed')
                """
            )

        score_after_measurement = self.registry.calculate_source_score(
            item.source_id
        )
        self.assertEqual(score_after_measurement.total_score, 90.0)

    def test_lowest_scored_manual_source_can_be_evicted(self):
        manual = Candidate(
            "人工来源", "https://example.com/manual.m3u", "manual"
        )
        self.registry.sync_candidates([manual])

        discovered = [
            Candidate(f"自动来源{i}", f"https://example.com/{i}.m3u")
            for i in range(29)
        ]

        for start in range(0, len(discovered), 8):
            self.registry.sync_candidates(discovered[start:start + 8])

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO source_scores
                    (run_id, source_id, scored_at, total_score, components_json)
                VALUES (1, ?, '2026-11-04T00:00:00Z', 10, '{}')
                """,
                (manual.source_id,),
            )

            for item in discovered:
                db.execute(
                    """
                    INSERT INTO source_scores
                        (run_id, source_id, scored_at,
                         total_score, components_json)
                    VALUES (1, ?, '2026-11-04T00:00:00Z', 50, '{}')
                    """,
                    (item.source_id,),
                )

        replacement = Candidate(
            "新发现来源", "https://example.com/replacement.m3u"
        )
        result = self.registry.sync_candidates([replacement])

        self.assertIn(manual.source_id, result.evicted)
        self.assertIn(replacement.source_id, result.accepted)

        with database_session(self.db_path) as db:
            manual_row = db.execute(
                "SELECT active FROM sources WHERE source_id = ?",
                (manual.source_id,),
            ).fetchone()
            replacement_row = db.execute(
                "SELECT active FROM sources WHERE source_id = ?",
                (replacement.source_id,),
            ).fetchone()
            count = db.execute(
                "SELECT COUNT(*) FROM sources WHERE active = 1"
            ).fetchone()[0]

        self.assertEqual(manual_row["active"], 0)
        self.assertEqual(replacement_row["active"], 1)
        self.assertEqual(count, 30)

    def test_reactivating_manual_source_keeps_pool_capacity(self):
        discovered = [
            Candidate(f"自动来源{i}", f"https://example.com/reactivate-{i}.m3u")
            for i in range(30)
        ]

        for start in range(0, len(discovered), 8):
            self.registry.sync_candidates(discovered[start:start + 8])

        manual = Candidate(
            "曾被淘汰的人工来源",
            "https://example.com/reactivated-manual.m3u",
            "manual",
        )

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO sources
                    (source_id, name, url, source_type,
                     first_seen_at, last_seen_at, active)
                VALUES (?, ?, ?, 'manual',
                        '2026-11-04T00:00:00Z',
                        '2026-11-04T00:00:00Z', 0)
                """,
                (manual.source_id, manual.name, manual.url),
            )

        result = self.registry.sync_candidates([manual])

        self.assertIn(manual.source_id, result.accepted)
        self.assertEqual(len(result.evicted), 1)

        with database_session(self.db_path) as db:
            active_count = db.execute(
                "SELECT COUNT(*) FROM sources WHERE active = 1"
            ).fetchone()[0]
            manual_row = db.execute(
                "SELECT active FROM sources WHERE source_id = ?",
                (manual.source_id,),
            ).fetchone()

        self.assertEqual(active_count, 30)
        self.assertEqual(manual_row["active"], 1)
if __name__ == "__main__":
    unittest.main()
