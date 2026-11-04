import json
import sqlite3

import pytest

from iptv_auto.database import initialize_database
from iptv_auto import content_check


def _database(tmp_path, deep_status="passed"):
    path = tmp_path / "content_check.sqlite3"
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

        db.execute(
            """
            INSERT INTO lines
                (line_id, url, headers_json, first_seen_at, last_seen_at)
            VALUES (
                'line-1',
                'https://example.com/live.ts',
                '{}',
                '2026-11-04T00:00:00Z',
                '2026-11-04T00:00:00Z'
            )
            """
        )

        db.execute(
            """
            INSERT INTO line_channels
                (line_id, channel_id, first_seen_at, last_seen_at)
            VALUES (
                'line-1', 'channel-1',
                '2026-11-04T00:00:00Z',
                '2026-11-04T00:00:00Z'
            )
            """
        )

        db.execute(
            """
            INSERT INTO deep_probes
                (run_id, line_id, probed_at, runner_identity,
                 environment_type, status, has_video, has_audio,
                 evidence_json)
            VALUES (
                ?, 'line-1', '2026-11-04T00:00:00Z',
                'test-runner', 'cloud', ?, 1, 1, '{}'
            )
            """,
            (run_id, deep_status),
        )

    return path, int(run_id)


def _enable_fake_tools(monkeypatch):
    monkeypatch.setattr(
        content_check,
        "_resolve_binary",
        lambda value, name: name,
    )
    monkeypatch.setattr(
        content_check,
        "_extract_frame",
        lambda *_args: (b"fake-png", "ok"),
    )


def test_two_matching_ad_frames_confirm_and_blacklist(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    texts = iter([
        "正在播放广告",
        "广告时间",
        "正常节目",
    ])
    monkeypatch.setattr(
        content_check,
        "_recognize_text",
        lambda *_args: (next(texts), "ok"),
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.confirmed_count == 1
    assert result.blacklisted_count == 1
    assert result.unknown_count == 0

    with sqlite3.connect(path) as db:
        rows = db.execute(
            """
            SELECT target_type, target_id, reason
              FROM blacklists
             WHERE active = 1
            """
        ).fetchall()

    assert len(rows) == 2
    assert {row[0] for row in rows} == {"line", "url"}
    assert all(
        row[2] == "confirmed_advertisement_content"
        for row in rows
    )


def test_one_ad_frame_does_not_blacklist(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    texts = iter([
        "广告",
        "正常节目",
        "正常节目",
    ])
    monkeypatch.setattr(
        content_check,
        "_recognize_text",
        lambda *_args: (next(texts), "ok"),
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.confirmed_count == 0
    assert result.clean_count == 1
    assert result.blacklisted_count == 0

    with sqlite3.connect(path) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM blacklists WHERE active = 1"
        ).fetchone()[0]

    assert count == 0


def test_two_no_signal_frames_are_confirmed(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    texts = iter([
        "暂无信号",
        "无信号",
        "正常节目",
    ])
    monkeypatch.setattr(
        content_check,
        "_recognize_text",
        lambda *_args: (next(texts), "ok"),
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.confirmed_count == 1
    assert result.records[0].category == "no_signal"


def test_ocr_failure_is_unknown_not_clean(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    monkeypatch.setattr(
        content_check,
        "_recognize_text",
        lambda *_args: ("", "ocr_failed"),
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.unknown_count == 1
    assert result.clean_count == 0
    assert result.blacklisted_count == 0


def test_missing_tools_is_unknown(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()

    monkeypatch.setattr(
        content_check,
        "_resolve_binary",
        lambda value, name: None,
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.unknown_count == 1
    assert result.blacklisted_count == 0
    assert "ffmpeg" in result.records[0].evidence["missing_tools"]
    assert "tesseract" in result.records[0].evidence["missing_tools"]


def test_only_deep_probe_passed_lines_are_checked(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(deep_status="unknown")

    _enable_fake_tools(monkeypatch)

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 0
    assert result.checked_count == 0


def test_runner_identity_must_match(tmp_path):
    path, run_id = _database()

    with pytest.raises(ValueError):
        content_check.run_content_checks(
            path,
            run_id,
            runner_identity="different-runner",
        )


def test_home_network_cannot_be_claimed(tmp_path):
    path, run_id = _database()

    with pytest.raises(ValueError):
        content_check.run_content_checks(
            path,
            run_id,
            runner_identity="test-runner",
            environment_type="fujian_mobile_home",
        )


def test_concurrency_cannot_exceed_three(tmp_path):
    path, run_id = _database()

    with pytest.raises(ValueError):
        content_check.run_content_checks(
            path,
            run_id,
            runner_identity="test-runner",
            max_concurrency=4,
        )
