
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from iptv_auto.database import database_session, initialize_database
from iptv_auto.measurement import (
    MAX_READ_BYTES,
    ProbeResult,
    _finite_nonnegative,
    _probe_http,
    run_basic_measurements,
)


class _TestHandler(BaseHTTPRequestHandler):
    body = b"x" * 12000
    response_status = 200
    delay_seconds = 0
    bytes_sent = 0

    def do_GET(self):
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

        self.send_response(self.response_status)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()

        try:
            self.wfile.write(self.body)
            type(self).bytes_sent = len(self.body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "measurement.sqlite3"
        initialize_database(self.db_path)
        self._create_run(1)

    def tearDown(self):
        self.temp.cleanup()

    def _create_run(self, run_id, runner="test-runner", environment="cloud"):
        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO runs
                    (run_id, started_at, status,
                     runner_identity, environment_type)
                VALUES (?, '2026-11-04T00:00:00Z',
                        'running', ?, ?)
                """,
                (run_id, runner, environment),
            )

    def _add_line(self, line_id, url, headers=None):
        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO lines
                    (line_id, url, headers_json,
                     first_seen_at, last_seen_at, blacklist_status)
                VALUES (?, ?, ?, '2026-11-04T00:00:00Z',
                        '2026-11-04T00:00:00Z', 'clear')
                """,
                (line_id, url, json.dumps(headers or {})),
            )

    def _add_pending_measurement(self, line_id, round_no=1, run_id=1):
        with database_session(self.db_path) as db:
            cursor = db.execute(
                """
                INSERT INTO measurements
                    (run_id, line_id, round_no, measured_at,
                     runner_identity, environment_type, status,
                     latency_ms, throughput_kbps, error_class,
                     evidence_json)
                VALUES (?, ?, ?, '2026-11-04T00:00:00Z',
                        'test-runner', 'cloud', 'pending',
                        NULL, NULL, '', ?)
                """,
                (
                    run_id,
                    line_id,
                    round_no,
                    json.dumps({
                        "measurement_stage": "basic",
                        "environment_type": "cloud",
                    }),
                ),
            )
            return cursor.lastrowid

    def _server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _TestHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server, f"http://127.0.0.1:{server.server_port}/live.ts"

    def _run(self, run_id=1, **kwargs):
        return run_basic_measurements(
            self.db_path,
            run_id,
            runner_identity="test-runner",
            **kwargs,
        )

    def test_http_body_read_is_success_and_limited(self):
        server, url = self._server()
        _TestHandler.bytes_sent = 0

        result = _probe_http(url, {}, 2)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.evidence["bytes_read"], MAX_READ_BYTES)
        self.assertEqual(result.evidence["byte_limit"], MAX_READ_BYTES)
        self.assertEqual(result.evidence["probe_kind"], "http_small_body_read")
        self.assertGreaterEqual(result.throughput_kbps, 0)

    def test_http_failure_is_not_success(self):
        server, url = self._server()
        _TestHandler.response_status = 503
        self.addCleanup(setattr, _TestHandler, "response_status", 200)

        result = _probe_http(url, {}, 2)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_class, "http_status_error")

    def test_http_timeout_is_recorded_as_failure(self):
        server, url = self._server()
        _TestHandler.delay_seconds = 0.3
        self.addCleanup(setattr, _TestHandler, "delay_seconds", 0)

        result = _probe_http(url, {}, 0.05)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_class, "timeout")

    def test_measurement_is_saved_to_database(self):
        server, url = self._server()
        self._add_line("line-http", url)

        result = self._run()

        self.assertEqual(result.scheduled_count, 1)
        self.assertEqual(result.success_count, 1)

        with database_session(self.db_path) as db:
            row = db.execute(
                "SELECT status, round_no, environment_type "
                "FROM measurements WHERE line_id = 'line-http'"
            ).fetchone()

        self.assertEqual(row["status"], "success")
        self.assertEqual(row["round_no"], 1)
        self.assertEqual(row["environment_type"], "cloud")

    def test_same_run_does_not_measure_same_line_twice(self):
        server, url = self._server()
        self._add_line("line-once", url)

        first = self._run()
        second = self._run()

        self.assertEqual(first.scheduled_count, 1)
        self.assertEqual(second.scheduled_count, 0)
        self.assertEqual(second.skipped_existing_count, 1)

        with database_session(self.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM measurements "
                "WHERE run_id = 1 AND line_id = 'line-once'"
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_round_numbers_accumulate_across_runs(self):
        server, url = self._server()
        self._add_line("line-rounds", url)

        self._run()
        self._create_run(2)
        self._run(run_id=2)
        self._create_run(3)
        self._run(run_id=3)

        with database_session(self.db_path) as db:
            rounds = [
                row[0] for row in db.execute(
                    "SELECT round_no FROM measurements "
                    "WHERE line_id = 'line-rounds' ORDER BY round_no"
                )
            ]

        self.assertEqual(rounds, [1, 2, 3])

    def test_environment_must_match_run_and_cloud_only(self):
        with self.assertRaises(ValueError):
            self._run(environment_type="fujian_mobile_home")

        with self.assertRaises(ValueError):
            run_basic_measurements(
                self.db_path,
                1,
                runner_identity="another-runner",
                environment_type="cloud",
            )

    def test_udp_multicast_is_not_counted_as_success(self):
        self._add_line("line-udp", "udp://239.1.1.1:8000")

        result = self._run()

        self.assertEqual(result.scheduled_count, 1)
        self.assertEqual(result.success_count, 0)
        self.assertEqual(result.probe_limited_count, 1)
        self.assertEqual(result.records[0].status, "probe_limited")

    def test_tcp_reachability_is_not_counted_as_media_success(self):
        self._add_line("line-rtsp", "rtsp://127.0.0.1:554/live")

        with patch(
            "iptv_auto.measurement._probe_tcp_reachability",
            return_value=ProbeResult(
                "reachable", 2.0, None, "",
                {"probe_kind": "tcp_connect_only"},
            ),
        ):
            result = self._run()

        self.assertEqual(result.success_count, 0)
        self.assertEqual(result.reachable_count, 1)

    def test_blacklisted_line_is_not_measured(self):
        self._add_line("line-blocked", "https://example.com/live.ts")

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO blacklists
                    (target_type, target_id, reason, created_at)
                VALUES ('line', 'line-blocked', 'confirmed ad',
                        '2026-11-04T00:00:00Z')
                """
            )

        result = self._run()

        self.assertEqual(result.scheduled_count, 0)

    def test_invalid_nonfinite_measurement_values_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf"), True, -1):
            self.assertIsNone(_finite_nonnegative(value))

        self.assertEqual(_finite_nonnegative(0), 0.0)
        self.assertEqual(_finite_nonnegative(12.5), 12.5)

    def test_concurrency_limit_is_enforced(self):
        self._add_line("line-a", "https://example.com/a.ts")
        self._add_line("line-b", "https://example.com/b.ts")
        self._add_line("line-c", "https://example.com/c.ts")

        active = 0
        maximum_active = 0
        lock = threading.Lock()

        def fake_probe(_url, _headers, _timeout):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return ProbeResult(
                "success", 10.0, 100.0, "",
                {
                    "probe_kind": "http_small_body_read",
                    "bytes_read": 100,
                },
            )

        with patch("iptv_auto.measurement._probe_line", side_effect=fake_probe):
            result = self._run(max_concurrency=2)

        self.assertEqual(result.scheduled_count, 3)
        self.assertLessEqual(maximum_active, 2)

    def test_concurrency_and_timeout_cannot_exceed_limits(self):
        with self.assertRaises(ValueError):
            self._run(max_concurrency=13)

        with self.assertRaises(ValueError):
            self._run(timeout_seconds=9)

    def test_pending_measurement_is_resumed_without_new_round(self):
        server, url = self._server()
        self._add_line("line-resume", url)

        original_id = self._add_pending_measurement(
            "line-resume", round_no=2
        )

        result = self._run()

        self.assertEqual(result.scheduled_count, 1)
        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.records[0].round_no, 2)

        with database_session(self.db_path) as db:
            rows = db.execute(
                """
                SELECT measurement_id, round_no, status
                  FROM measurements
                 WHERE run_id = 1 AND line_id = 'line-resume'
                """
            ).fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["measurement_id"], original_id)
        self.assertEqual(rows[0]["round_no"], 2)
        self.assertEqual(rows[0]["status"], "success")

    def test_pending_and_completed_lines_are_handled_independently(self):
        server, url = self._server()
        self._add_line("line-completed", url)
        self._add_line("line-pending", url)

        completed = self._add_pending_measurement(
            "line-completed", round_no=1
        )
        pending = self._add_pending_measurement(
            "line-pending", round_no=1
        )

        with database_session(self.db_path) as db:
            db.execute(
                """
                UPDATE measurements
                   SET status = 'success'
                 WHERE measurement_id = ?
                """,
                (completed,),
            )

        result = self._run()

        self.assertEqual(result.scheduled_count, 1)
        self.assertEqual(result.skipped_existing_count, 1)
        self.assertEqual(result.success_count, 1)

        with database_session(self.db_path) as db:
            completed_row = db.execute(
                """
                SELECT status FROM measurements
                 WHERE measurement_id = ?
                """,
                (completed,),
            ).fetchone()
            pending_row = db.execute(
                """
                SELECT status FROM measurements
                 WHERE measurement_id = ?
                """,
                (pending,),
            ).fetchone()

        self.assertEqual(completed_row["status"], "success")
        self.assertEqual(pending_row["status"], "success")

    def test_stability_retest_does_not_consume_basic_round(self):
        server, url = self._server()
        self._add_line("line-stability", url)

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO measurements
                    (run_id, line_id, round_no, measured_at,
                     runner_identity, environment_type, status,
                     latency_ms, throughput_kbps, error_class,
                     evidence_json)
                VALUES (1, 'line-stability', 99,
                        '2026-11-04T00:00:00Z',
                        'test-runner', 'cloud', 'success',
                        10, 100, '', ?)
                """,
                (json.dumps({
                    "measurement_stage": "stability_retest",
                    "environment_type": "cloud",
                }),),
            )

        result = self._run()

        self.assertEqual(result.scheduled_count, 1)
        self.assertEqual(result.records[0].round_no, 1)

        with database_session(self.db_path) as db:
            basic_row = db.execute(
                """
                SELECT round_no, status
                  FROM measurements
                 WHERE run_id = 1
                   AND line_id = 'line-stability'
                   AND round_no = 1
                """
            ).fetchone()

        self.assertEqual(basic_row["round_no"], 1)
        self.assertEqual(basic_row["status"], "success")

    def test_missing_run_is_rejected(self):
        with self.assertRaises(ValueError):
            self._run(run_id=999)


if __name__ == "__main__":
    unittest.main()
