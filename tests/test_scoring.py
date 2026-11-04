import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from iptv_auto.database import database_session, initialize_database
from iptv_auto.scoring import (
    MAX_DEEP_CANDIDATES_PER_CHANNEL,
    _finite_number,
    score_lines,
)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "scoring.sqlite3"
        initialize_database(self.db_path)

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO runs
                    (run_id, started_at, status,
                     runner_identity, environment_type)
                VALUES (1, '2026-11-04T00:00:00Z',
                        'running', 'score-test', 'cloud')
                """
            )

    def tearDown(self):
        self.temp.cleanup()

    def _add_line(self, line_id, channel_id="channel-1", channel_name="CCTV-5"):
        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO lines
                    (line_id, url, first_seen_at, last_seen_at, blacklist_status)
                VALUES (?, ?, '2026-11-01T00:00:00Z',
                        '2026-11-04T00:00:00Z', 'clear')
                """,
                (line_id, f"https://example.com/{line_id}.ts"),
            )
            db.execute(
                """
                INSERT INTO channels (channel_id, category, name)
                VALUES (?, '体育', ?)
                ON CONFLICT(channel_id) DO NOTHING
                """,
                (channel_id, channel_name),
            )
            db.execute(
                """
                INSERT INTO line_channels
                    (line_id, channel_id, first_seen_at, last_seen_at)
                VALUES (?, ?, '2026-11-01T00:00:00Z',
                        '2026-11-04T00:00:00Z')
                """,
                (line_id, channel_id),
            )

    def _add_measurement(
        self,
        line_id,
        round_no,
        *,
        status="success",
        latency=20.0,
        throughput=3000.0,
        measured_at="2026-11-04T00:00:00+00:00",
    ):
        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO measurements
                    (run_id, line_id, round_no, measured_at,
                     runner_identity, environment_type, status,
                     latency_ms, throughput_kbps, error_class, evidence_json)
                VALUES (1, ?, ?, ?, 'score-test', 'cloud', ?,
                        ?, ?, '', '{}')
                """,
                (
                    line_id,
                    round_no,
                    measured_at,
                    status,
                    latency,
                    throughput,
                ),
            )

    def _score(self, now="2026-11-04T01:00:00+00:00"):
        return score_lines(
            self.db_path,
            1,
            runner_identity="score-test",
            environment_type="cloud",
            now=datetime.fromisoformat(now),
        )

    def test_two_successful_rounds_can_become_deep_candidate(self):
        self._add_line("line-good")
        self._add_measurement("line-good", 1)
        self._add_measurement("line-good", 2)

        result = self._score()

        self.assertEqual(result.scored_count, 1)
        self.assertEqual(result.eligible_line_count, 1)
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.candidates[0].line_id, "line-good")
        self.assertEqual(result.candidates[0].grade, "A")

    def test_only_one_round_is_not_enough_for_deep_candidate(self):
        self._add_line("line-one")
        self._add_measurement("line-one", 1)

        result = self._score()

        self.assertEqual(result.eligible_line_count, 0)
        self.assertEqual(result.candidate_count, 0)

    def test_failure_reduces_success_rate_and_blocks_candidate(self):
        self._add_line("line-mixed")
        self._add_measurement("line-mixed", 1, status="success")
        self._add_measurement("line-mixed", 2, status="failed")

        result = self._score()

        self.assertEqual(result.eligible_line_count, 0)
        self.assertEqual(result.scores[0].components["success_rate"], 50.0)

    def test_reachable_is_not_counted_as_media_success(self):
        self._add_line("line-reachable")
        self._add_measurement("line-reachable", 1, status="reachable")
        self._add_measurement("line-reachable", 2, status="reachable")

        result = self._score()

        self.assertEqual(result.eligible_line_count, 0)
        self.assertEqual(result.scores[0].successful_rounds, 0)
        self.assertEqual(result.scores[0].components["success_rate"], 0.0)

    def test_blacklisted_line_cannot_be_candidate(self):
        self._add_line("line-blocked")
        self._add_measurement("line-blocked", 1)
        self._add_measurement("line-blocked", 2)

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO blacklists
                    (target_type, target_id, reason, created_at)
                VALUES ('line', 'line-blocked', 'confirmed advertisement',
                        '2026-11-04T00:00:00Z')
                """
            )

        result = self._score()

        self.assertEqual(result.eligible_line_count, 0)
        self.assertEqual(result.candidate_count, 0)

    def test_confirmed_ad_evidence_reduces_ad_component(self):
        self._add_line("line-ad")
        self._add_measurement("line-ad", 1)
        self._add_measurement("line-ad", 2)

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO deep_probes
                    (run_id, line_id, probed_at, runner_identity,
                     environment_type, status, evidence_json)
                VALUES (1, 'line-ad', '2026-11-04T00:30:00Z',
                        'score-test', 'cloud', 'failed', ?)
                """,
                (json.dumps({"ad_detected": True}),),
            )

        result = self._score()

        self.assertEqual(
            result.scores[0].components["ad_placeholder_risk"],
            0.0,
        )
        self.assertEqual(result.eligible_line_count, 0)

    def test_explicit_clean_content_evidence_improves_ad_component(self):
        self._add_line("line-clean")
        self._add_measurement("line-clean", 1)
        self._add_measurement("line-clean", 2)

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO deep_probes
                    (run_id, line_id, probed_at, runner_identity,
                     environment_type, status, evidence_json)
                VALUES (1, 'line-clean', '2026-11-04T00:30:00Z',
                        'score-test', 'cloud', 'passed', ?)
                """,
                (
                    json.dumps({
                        "ad_detected": False,
                        "content_class": "live_program",
                    }),
                ),
            )

        result = self._score()

        self.assertEqual(
            result.scores[0].components["ad_placeholder_risk"],
            100.0,
        )

    def test_stale_measurement_loses_freshness_points(self):
        self._add_line("line-old")
        self._add_measurement(
            "line-old",
            1,
            measured_at="2026-10-20T00:00:00+00:00",
        )
        self._add_measurement(
            "line-old",
            2,
            measured_at="2026-10-20T01:00:00+00:00",
        )

        result = self._score()

        self.assertEqual(result.scores[0].components["freshness"], 0.0)

    def test_deep_candidates_are_limited_to_five_per_channel(self):
        for index in range(7):
            line_id = f"line-{index}"
            self._add_line(line_id)
            self._add_measurement(line_id, 1)
            self._add_measurement(line_id, 2)

        result = self._score()

        self.assertEqual(result.eligible_line_count, 7)
        self.assertEqual(
            result.candidate_count,
            MAX_DEEP_CANDIDATES_PER_CHANNEL,
        )
        self.assertEqual(
            len({item.line_id for item in result.candidates}),
            MAX_DEEP_CANDIDATES_PER_CHANNEL,
        )

    def test_scores_are_persisted_and_repeatable_for_same_run(self):
        self._add_line("line-repeat")
        self._add_measurement("line-repeat", 1)
        self._add_measurement("line-repeat", 2)

        first = self._score()
        second = self._score()

        self.assertEqual(first.scores[0].total_score, second.scores[0].total_score)

        with database_session(self.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM line_scores "
                "WHERE run_id = 1 AND line_id = 'line-repeat'"
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_environment_identity_is_protected(self):
        with self.assertRaises(ValueError):
            score_lines(
                self.db_path,
                1,
                runner_identity="score-test",
                environment_type="fujian_mobile_home",
            )

        with self.assertRaises(ValueError):
            score_lines(
                self.db_path,
                1,
                runner_identity="other-runner",
                environment_type="cloud",
            )

    def test_missing_run_is_rejected(self):
        with self.assertRaises(ValueError):
            score_lines(
                self.db_path,
                999,
                runner_identity="score-test",
            )

    def test_nonfinite_values_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf"), True, -1):
            self.assertIsNone(_finite_number(value))

        self.assertEqual(_finite_number(12.5), 12.5)


if __name__ == "__main__":
    unittest.main()
