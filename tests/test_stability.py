
import json
import sqlite3

import pytest

from iptv_auto.database import initialize_database
from iptv_auto.measurement import ProbeResult
from iptv_auto import stability


def _database(
    tmp_path,
    deep_status="passed",
    content_status="no_flag_detected",
):
    path = tmp_path / "stability.sqlite3"
    initialize_database(path)

    content_evidence = {}

    if content_status is not None:
        if content_status == "no_flag_detected":
            content_evidence = {
                "content_check": {
                    "status": "no_flag_detected",
                    "content_class": "clean",
                    "ad_detected": False,
                    "placeholder_detected": False,
                }
            }
        else:
            content_evidence = {
                "content_check": {
                    "status": content_status,
                    "content_class": "unknown",
                    "ad_detected": None,
                    "placeholder_detected": None,
                }
            }

    with sqlite3.connect(path) as db:
        cursor = db.execute(
            """
            INSERT INTO runs
                (started_at, status, runner_identity, environment_type)
            VALUES (
                '2026-11-04T00:00:00Z',
                'running',
                'test-runner',
                'cloud'
            )
            """
        )
        run_id = cursor.lastrowid

        db.execute(
            """
            INSERT INTO channels
                (channel_id, category, name)
            VALUES ('channel-1', '测试', '测试频道')
            """
        )

        for index in range(1, 8):
            line_id = f"line-{index}"

            db.execute(
                """
                INSERT INTO lines
                    (
                        line_id,
                        url,
                        headers_json,
                        first_seen_at,
                        last_seen_at
                    )
                VALUES (
                    ?,
                    ?,
                    '{}',
                    '2026-11-04T00:00:00Z',
                    '2026-11-04T00:00:00Z'
                )
                """,
                (
                    line_id,
                    f"https://example.com/{index}.ts",
                ),
            )

            db.execute(
                """
                INSERT INTO line_channels
                    (
                        line_id,
                        channel_id,
                        first_seen_at,
                        last_seen_at
                    )
                VALUES (
                    ?,
                    'channel-1',
                    '2026-11-04T00:00:00Z',
                    '2026-11-04T00:00:00Z'
                )
                """,
                (line_id,),
            )

            line_deep_status = (
                "passed" if index <= 6 else "unknown"
            )

            if deep_status != "passed":
                line_deep_status = deep_status

            db.execute(
                """
                INSERT INTO deep_probes
                    (
                        run_id,
                        line_id,
                        probed_at,
                        runner_identity,
                        environment_type,
                        status,
                        has_video,
                        has_audio,
                        evidence_json
                    )
                VALUES (
                    ?,
                    ?,
                    '2026-11-04T00:00:00Z',
                    'test-runner',
                    'cloud',
                    ?,
                    1,
                    1,
                    ?
                )
                """,
                (
                    run_id,
                    line_id,
                    line_deep_status,
                    json.dumps(
                        content_evidence,
                        ensure_ascii=False,
                    ),
                ),
            )

    return path, int(run_id)


def _successful_probe(*_args):
    return ProbeResult(
        "success",
        10.0,
        1000.0,
        "",
        {
            "probe_kind": "http_small_body_read",
            "media_playback_confirmed": False,
        },
    )


def _insert_stability_measurement(
    path,
    run_id,
    line_id,
    round_no,
    status,
    latency_ms=123.0,
):
    evidence = {
        "measurement_stage": "stability_retest",
        "environment_type": "cloud",
        "media_playback_confirmed": False,
    }

    with sqlite3.connect(path) as db:
        cursor = db.execute(
            """
            INSERT INTO measurements
                (
                    run_id,
                    line_id,
                    round_no,
                    measured_at,
                    runner_identity,
                    environment_type,
                    status,
                    latency_ms,
                    throughput_kbps,
                    error_class,
                    evidence_json
                )
            VALUES (
                ?, ?, ?, '2026-11-04T00:00:00Z',
                'test-runner', 'cloud', ?, ?,
                NULL, '', ?
            )
            """,
            (
                run_id,
                line_id,
                round_no,
                status,
                latency_ms,
                json.dumps(evidence),
            ),
        )
        return int(cursor.lastrowid)


def test_only_deep_and_content_passed_lines_are_selected(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    # 六条深度检测通过，但每频道最多选五条。
    assert result.selected_count == 5
    assert result.scheduled_count == 10
    assert result.success_count == 10


def test_unknown_content_is_not_retested(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(
        tmp_path,
        content_status="unknown",
    )

    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 0
    assert result.scheduled_count == 0
    assert result.success_count == 0


def test_missing_content_check_is_not_retested(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(
        tmp_path,
        content_status=None,
    )

    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 0
    assert result.scheduled_count == 0


def test_stability_retests_are_saved_with_stage_evidence(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.success_count == 10

    with sqlite3.connect(path) as db:
        rows = db.execute(
            """
            SELECT status, round_no, evidence_json
              FROM measurements
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()

    assert len(rows) == 10
    assert all(row[0] == "success" for row in rows)
    assert len({row[1] for row in rows}) == 10

    for row in rows:
        evidence = json.loads(row[2])
        assert evidence["measurement_stage"] == "stability_retest"
        assert evidence["media_playback_confirmed"] is False
        assert evidence["environment_type"] == "cloud"


def test_repeated_call_does_not_repeat_reserved_retests(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    first = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    second = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert first.scheduled_count == 10
    assert second.scheduled_count == 0
    assert second.skipped_existing_count == 5

    with sqlite3.connect(path) as db:
        count = db.execute(
            """
            SELECT COUNT(*)
              FROM measurements
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()[0]

    assert count == 10


def test_tcp_reachable_is_not_counted_as_success(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        lambda *_args: ProbeResult(
            "reachable",
            5.0,
            None,
            "",
            {
                "probe_kind": "tcp_connect_only",
                "media_playback_confirmed": False,
            },
        ),
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.success_count == 0
    assert result.reachable_count == 10
    assert result.failed_count == 0


def test_udp_probe_limited_is_not_counted_as_success(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        lambda *_args: ProbeResult(
            "probe_limited",
            None,
            None,
            "udp_media_probe_requires_receiver",
            {
                "probe_kind": "udp_rtp_limited",
                "media_playback_confirmed": False,
            },
        ),
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.success_count == 0
    assert result.probe_limited_count == 10
    assert result.failed_count == 0


def test_probe_exception_is_recorded_as_failed(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    def raise_error(*_args):
        raise RuntimeError("test exception")

    monkeypatch.setattr(
        stability,
        "_probe_line",
        raise_error,
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.failed_count == 10
    assert result.success_count == 0


def test_cloud_environment_cannot_claim_home_network(tmp_path):
    path, run_id = _database(tmp_path)

    with pytest.raises(ValueError):
        stability.run_stability_retests(
            path,
            run_id,
            runner_identity="test-runner",
            environment_type="fujian_mobile_home",
        )


def test_runner_identity_must_match_run(tmp_path):
    path, run_id = _database(tmp_path)

    with pytest.raises(ValueError):
        stability.run_stability_retests(
            path,
            run_id,
            runner_identity="different-runner",
        )


def test_missing_run_is_rejected(tmp_path):
    path, _ = _database(tmp_path)

    with pytest.raises(ValueError):
        stability.run_stability_retests(
            path,
            999,
            runner_identity="test-runner",
        )


def test_retest_count_cannot_exceed_two(tmp_path):
    path, run_id = _database(tmp_path)

    with pytest.raises(ValueError):
        stability.run_stability_retests(
            path,
            run_id,
            runner_identity="test-runner",
            retests=3,
        )


def test_concurrency_cannot_exceed_three(tmp_path):
    path, run_id = _database(tmp_path)

    with pytest.raises(ValueError):
        stability.run_stability_retests(
            path,
            run_id,
            runner_identity="test-runner",
            max_concurrency=4,
        )


def test_timeout_cannot_exceed_eight_seconds(tmp_path):
    path, run_id = _database(tmp_path)

    with pytest.raises(ValueError):
        stability.run_stability_retests(
            path,
            run_id,
            runner_identity="test-runner",
            timeout_seconds=9,
        )


def test_pending_stability_retest_is_resumed_without_duplicate(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    original_id = _insert_stability_measurement(
        path,
        run_id,
        "line-1",
        20,
        "pending",
        latency_ms=None,
    )

    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

assert result.scheduled_count == 10

    with sqlite3.connect(path) as db:
        rows = db.execute(
            """
            SELECT measurement_id, round_no, status
              FROM measurements
             WHERE run_id = ?
               AND line_id = 'line-1'
             ORDER BY round_no
            """,
            (run_id,),
        ).fetchall()

    assert len(rows) == 2
    assert rows[0][0] == original_id
    assert rows[0][1] == 20
    assert rows[0][2] == "success"


def test_completed_stability_retest_is_not_overwritten(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    original_id = _insert_stability_measurement(
        path,
        run_id,
        "line-1",
        20,
        "success",
        latency_ms=123.0,
    )

    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.scheduled_count == 9

    with sqlite3.connect(path) as db:
        row = db.execute(
            """
            SELECT status, latency_ms, round_no
              FROM measurements
             WHERE measurement_id = ?
            """,
            (original_id,),
        ).fetchone()

    assert row == ("success", 123.0, 20)


def test_blacklisted_line_is_excluded_from_stability_retests(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    with sqlite3.connect(path) as db:
        db.execute(
            """
            INSERT INTO blacklists
                (
                    target_type,
                    target_id,
                    reason,
                    evidence_json,
                    created_at,
                    active
                )
            VALUES (
                'line',
                'line-1',
                'test blacklist',
                '{}',
                '2026-11-04T00:00:00Z',
                1
            )
            """
        )

    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 5
    assert result.scheduled_count == 10

    with sqlite3.connect(path) as db:
        count = db.execute(
            """
            SELECT COUNT(*)
              FROM measurements
             WHERE run_id = ?
               AND line_id = 'line-1'
            """,
            (run_id,),
        ).fetchone()[0]

    assert count == 0
