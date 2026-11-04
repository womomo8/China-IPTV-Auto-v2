import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from iptv_auto.database import initialize_database
from iptv_auto import deep_probe


def _database(tmp_path: Path) -> tuple[Path, int]:
    database_path = tmp_path / "test.sqlite3"
    initialize_database(database_path)

    with sqlite3.connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO runs
                (started_at, status, runner_identity, environment_type)
            VALUES (?, 'running', 'test-runner', 'cloud')
            """,
            ("2026-01-01T00:00:00+00:00",),
        )
        run_id = cursor.lastrowid

        for index in range(1, 9):
            line_id = f"line-{index}"
            channel_id = "channel-a" if index <= 6 else "channel-b"
            db.execute(
                """
                INSERT INTO lines
                    (line_id, url, headers_json, first_seen_at, last_seen_at)
                VALUES (?, ?, '{}', ?, ?)
                """,
                (
                    line_id,
                    f"https://example.com/{index}.m3u8",
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            db.execute(
                """
                INSERT INTO channels
                    (channel_id, category, name)
                VALUES (?, '测试', ?)
                """,
                (channel_id, channel_id),
            )
            db.execute(
                """
                INSERT INTO line_channels
                    (line_id, channel_id, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    line_id,
                    channel_id,
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )

    return database_path, int(run_id)


def test_select_candidates_caps_at_five_per_channel():
    candidates = [
        {
            "channel_id": "channel-a",
            "line_id": f"line-{index}",
            "total_score": float(index),
        }
        for index in range(1, 7)
    ]

    selected = deep_probe._select_candidates(candidates)

    assert len(selected) == 5
    assert {
        item["line_id"] for item in selected
    } == {
        "line-2", "line-3", "line-4", "line-5", "line-6"
    }


def test_select_candidates_sorts_by_score_and_keeps_channel_limits():
    candidates = []
    for index in range(1, 9):
        candidates.append({
            "channel_id": "channel-a" if index <= 6 else "channel-b",
            "line_id": f"line-{index}",
            "total_score": index,
        })

    selected = deep_probe._select_candidates(candidates)

    channel_a = [
        item for item in selected
        if item["channel_id"] == "channel-a"
    ]
    channel_b = [
        item for item in selected
        if item["channel_id"] == "channel-b"
    ]

    assert len(channel_a) == 5
    assert len(channel_b) == 2
    assert channel_a[0]["total_score"] == 6


def test_missing_ffmpeg_tools_are_unknown():
    result = deep_probe._probe_one(
        channel_id="channel-a",
        line_id="line-a",
        url="https://example.com/live.m3u8",
        headers={},
        ffprobe_binary=None,
        ffmpeg_binary=None,
        timeout_seconds=5,
    )

    assert result.status == "unknown"
    assert result.evidence["result_reason"] == "ffmpeg_tools_missing"


def test_invalid_url_is_failed_without_running_tools():
    result = deep_probe._probe_one(
        channel_id="channel-a",
        line_id="line-a",
        url="file:///etc/passwd",
        headers={},
        ffprobe_binary="/not/used/ffprobe",
        ffmpeg_binary="/not/used/ffmpeg",
        timeout_seconds=5,
    )

    assert result.status == "failed"
    assert result.evidence["result_reason"] == "unsupported_or_invalid_url"


def test_timeout_kills_and_waits_for_child_process(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.communicate.side_effect = subprocess.TimeoutExpired(
        cmd=["ffprobe"], timeout=1
    )
    process.wait.return_value = 0

    monkeypatch.setattr(
        deep_probe.subprocess,
        "Popen",
        Mock(return_value=process),
    )

    result = deep_probe._run_command(
        ["ffprobe", "-version"],
        timeout_seconds=1,
    )

    assert result[3] == "timeout"
    process.kill.assert_called_once()
    process.wait.assert_called()


def test_run_deep_probes_persists_evidence_and_limits_candidates(
    tmp_path,
    monkeypatch,
):
    database_path, run_id = _database(tmp_path)

    candidates = [
        {
            "channel_id": "channel-a",
            "line_id": f"line-{index}",
            "total_score": float(index),
        }
        for index in range(1, 7)
    ]

    def fake_probe(**kwargs):
        return deep_probe.DeepProbeRecord(
            channel_id=kwargs["channel_id"],
            line_id=kwargs["line_id"],
            status="passed",
            has_video=True,
            has_audio=True,
            width=1920,
            height=1080,
            video_codec="h264",
            audio_codec="aac",
            duration_seconds=10.0,
            evidence={"test_evidence": True},
        )

    monkeypatch.setattr(deep_probe, "_probe_one", fake_probe)

    result = deep_probe.run_deep_probes(
        database_path,
        run_id,
        candidates,
        runner_identity="test-runner",
        ffprobe_path="/not/required/ffprobe",
        ffmpeg_path="/not/required/ffmpeg",
        timeout_seconds=5,
        max_concurrency=2,
    )

    assert result.selected_count == 5
    assert result.passed_count == 5
    assert result.failed_count == 0
    assert result.unknown_count == 0

    with sqlite3.connect(database_path) as db:
        rows = db.execute(
            """
            SELECT status, has_video, has_audio, width, height, evidence_json
              FROM deep_probes
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()

    assert len(rows) == 5
    assert all(row[0] == "passed" for row in rows)
    assert all(row[1] == 1 and row[2] == 1 for row in rows)
    assert all(row[3] == 1920 and row[4] == 1080 for row in rows)
    assert all(
        json.loads(row[5])["test_evidence"] is True
        for row in rows
    )


def test_environment_cannot_claim_fujian_mobile_home_test(tmp_path):
    database_path, run_id = _database(tmp_path)

    with pytest.raises(ValueError):
        deep_probe.run_deep_probes(
            database_path,
            run_id,
            [],
            runner_identity="test-runner",
            environment_type="fujian_mobile_home",
        )


def test_concurrency_is_limited_to_three(tmp_path):
    database_path, run_id = _database(tmp_path)

    with pytest.raises(ValueError):
        deep_probe.run_deep_probes(
            database_path,
            run_id,
            [],
            runner_identity="test-runner",
            max_concurrency=4,
        )
def test_run_deep_probes_resumes_existing_pending_record(
    tmp_path,
    monkeypatch,
):
    database_path, run_id = _database(tmp_path)

    with sqlite3.connect(database_path) as db:
        cursor = db.execute(
            """
            INSERT INTO deep_probes
                (
                    run_id,
                    line_id,
                    probed_at,
                    runner_identity,
                    environment_type,
                    status,
                    evidence_json
                )
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                run_id,
                "line-1",
                "2026-01-01T00:00:00+00:00",
                "test-runner",
                "cloud",
                json.dumps({"probe_state": "pending"}),
            ),
        )
        original_probe_id = cursor.lastrowid

    def fake_probe(**kwargs):
        return deep_probe.DeepProbeRecord(
            channel_id=kwargs["channel_id"],
            line_id=kwargs["line_id"],
            status="passed",
            has_video=True,
            has_audio=True,
            width=1920,
            height=1080,
            video_codec="h264",
            audio_codec="aac",
            duration_seconds=10.0,
            evidence={"resumed": True},
        )

    monkeypatch.setattr(deep_probe, "_probe_one", fake_probe)

    result = deep_probe.run_deep_probes(
        database_path,
        run_id,
        [
            {
                "channel_id": "channel-a",
                "line_id": "line-1",
                "total_score": 90,
            }
        ],
        runner_identity="test-runner",
        timeout_seconds=5,
    )

    assert result.passed_count == 1

    with sqlite3.connect(database_path) as db:
        rows = db.execute(
            """
            SELECT probe_id, status
              FROM deep_probes
             WHERE run_id = ?
               AND line_id = 'line-1'
            """,
            (run_id,),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == original_probe_id
    assert rows[0][1] == "passed"

def test_timeout_is_limited_to_sixty_seconds(tmp_path):
    database_path, run_id = _database(tmp_path)

    with pytest.raises(ValueError):
        deep_probe.run_deep_probes(
            database_path,
            run_id,
            [],
            runner_identity="test-runner",
            timeout_seconds=61,
        )
