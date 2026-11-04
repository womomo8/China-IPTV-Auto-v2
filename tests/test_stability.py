import json
import sqlite3

import pytest

from iptv_auto.database import initialize_database
from iptv_auto.measurement import ProbeResult
from iptv_auto import stability


def _database(tmp_path):
    path = tmp_path / "stability.sqlite3"
    initialize_database(path)

    with sqlite3.connect(path) as db:
        cursor = db.execute(
            """
            INSERT INTO runs
                (started_at, status, runner_identity, environment_type)
            VALUES ('2026-11-04T00:00:00Z',
                    'running', 'test-runner', 'cloud')
            """
        )
        run_id = cursor.lastrowid

        db.execute(
            """
            INSERT INTO channels (channel_id, category, name)
            VALUES ('channel-1', '测试', '测试频道')
            """
        )

        for index in range(1, 8):
            line_id = f"line-{index}"
            db.execute(
                """
                INSERT INTO lines
                    (line_id, url, headers_json, first_seen_at, last_seen_at)
                VALUES (?, ?, '{}', '2026-11-04T00:00:00Z',
                        '2026-11-04T00:00:00Z')
                """,
                (line_id, f"https://example.com/{index}.ts"),
            )
            db.execute(
                """
                INSERT INTO line_channels
                    (line_id, channel_id, first_seen_at, last_seen_at)
                VALUES (?, 'channel-1', '2026-11-04T00:00:00Z',
                        '2026-11-04T00:00:00Z')
                """,
                (line_id,),
            )
            db.execute(
                """
                INSERT INTO deep_probes
                    (run_id, line_id, probed_at, runner_identity,
                     environment_type, status, has_video, has_audio,
                     evidence_json)
                VALUES (?, ?, '2026-11-04T00:00:00Z',
                        'test-runner', 'cloud', ?, 1, 1, '{}')
                """,
                (run_id, line_id, "passed" if index <= 6 else "unknown"),
            )

    return path, int(run_id)


def test_only_deep_probe_passed_lines_are_selected(tmp_path, monkeypatch):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        lambda *_args: ProbeResult(
            "success", 10.0, 1000.0, "",
            {"probe_kind": "http_small_body_read"},
        ),
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    # Six passed lines exist, but the per-channel limit is five.
    assert result.selected_count == 5
    assert result.scheduled_count == 10
    assert result.success_count == 10


def test_stability_retests_are_saved_with_stage_evidence(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        lambda *_args: ProbeResult(
            "success", 12.0, 800.0, "",
            {"probe_kind": "http_small_body_read"},
        ),
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
    assert all(
        json.loads(row[2])["measurement_stage"] == "stability_retest"
        for row in rows
    )


def test_repeated_call_does_not_repeat_reserved_retests(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        lambda *_args: ProbeResult(
            "success", 10.0, 1000.0, "", {},
        ),
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
            "SELECT COUNT(*) FROM measurements WHERE run_id = ?",
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
            "reachable", 5.0, None, "",
            {"probe_kind": "tcp_connect_only"},
        ),
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.success_count == 0
    assert result.reachable_count == 10


def test_udp_probe_limited_is_not_counted_as_success(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path)

    monkeypatch.setattr(
        stability,
        "_probe_line",
        lambda *_args: ProbeResult(
            "probe_limited", None, None,
            "udp_media_probe_requires_receiver",
            {"probe_kind": "udp_rtp_limited"},
        ),
    )

    result = stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.success_count == 0
    assert result.probe_limited_count == 10


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
