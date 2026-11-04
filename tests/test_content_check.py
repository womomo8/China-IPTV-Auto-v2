import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from iptv_auto.database import initialize_database
from iptv_auto import content_check


def _database(
    tmp_path=None,
    deep_status="passed",
    line_count=1,
    scores=None,
    eligible_line_ids=None,
):
    if tmp_path is None:
        tmp_path = Path(
            tempfile.mkdtemp(prefix="iptv-content-check-")
        )

    path = tmp_path / "content_check.sqlite3"
    initialize_database(path)

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

        for index in range(1, line_count + 1):
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
                    f"https://example.com/live-{index}.ts",
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
                    deep_status,
                    json.dumps({
                        "ffprobe": {
                            "video_codec": "h264",
                            "audio_codec": "aac",
                        }
                    }),
                ),
            )

            score = (
                scores.get(line_id, 80.0)
                if isinstance(scores, dict)
                else 80.0
            )
            eligible = (
                eligible_line_ids is None
                or line_id in eligible_line_ids
            )

            db.execute(
                """
                INSERT INTO line_scores
                    (
                        run_id,
                        line_id,
                        scored_at,
                        total_score,
                        components_json
                    )
                VALUES (?, ?, '2026-11-04T00:00:00Z', ?, ?)
                """,
                (
                    run_id,
                    line_id,
                    score,
                    json.dumps({
                        "eligible_for_deep_probe": eligible,
                    }),
                ),
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


def _set_ocr_texts(monkeypatch, texts):
    iterator = iter(texts)

    monkeypatch.setattr(
        content_check,
        "_recognize_text",
        lambda *_args: (next(iterator), "ok"),
    )


def test_two_matching_ad_frames_confirm_and_blacklist(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    _set_ocr_texts(
        monkeypatch,
        [
            "正在播放广告",
            "广告时间",
            "正常节目",
        ],
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 1
    assert result.checked_count == 1
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

    _set_ocr_texts(
        monkeypatch,
        [
            "广告",
            "正常节目",
            "正常节目",
        ],
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
            """
            SELECT COUNT(*)
              FROM blacklists
             WHERE active = 1
            """
        ).fetchone()[0]

    assert count == 0


def test_two_no_signal_frames_are_confirmed(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    _set_ocr_texts(
        monkeypatch,
        [
            "暂无信号",
            "无信号",
            "正常节目",
        ],
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.confirmed_count == 1
    assert result.records[0].category == "no_signal"
    assert result.blacklisted_count == 1


def test_two_placeholder_frames_are_confirmed(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    _set_ocr_texts(
        monkeypatch,
        [
            "测试频道",
            "测试信号",
            "正常节目",
        ],
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.confirmed_count == 1
    assert result.records[0].category == "placeholder"
    assert result.blacklisted_count == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("unknown", False),
        ("no_flag_detected", True),
        ("confirmed", True),
    ],
)
def test_already_checked_only_skips_completed_results(
    status,
    expected,
):
    evidence = json.dumps({
        "content_check": {
            "status": status,
        }
    })

    assert content_check._already_checked(evidence) is expected


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


def test_frame_extraction_failure_is_unknown_when_too_few_frames_work(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    monkeypatch.setattr(
        content_check,
        "_extract_frame",
        lambda *_args: (None, "frame_unavailable"),
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.unknown_count == 1
    assert result.clean_count == 0
    assert result.blacklisted_count == 0


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


def test_at_most_five_lines_per_channel(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(line_count=8)
    _enable_fake_tools(monkeypatch)

    _set_ocr_texts(
        monkeypatch,
        ["正常节目"] * 15,
    )

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 5
    assert result.checked_count == 5


def test_content_evidence_is_merged_without_overwriting_ffprobe(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    _set_ocr_texts(
        monkeypatch,
        [
            "正常节目",
            "正常节目",
            "正常节目",
        ],
    )

    content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    with sqlite3.connect(path) as db:
        row = db.execute(
            """
            SELECT evidence_json
              FROM deep_probes
             WHERE run_id = ?
               AND line_id = 'line-1'
            """,
            (run_id,),
        ).fetchone()

    evidence = json.loads(row[0])

    assert evidence["ffprobe"]["video_codec"] == "h264"
    assert evidence["ffprobe"]["audio_codec"] == "aac"
    assert evidence["content_check"]["status"] == "no_flag_detected"
    assert evidence["content_check"]["content_class"] == "clean"


def test_repeated_call_does_not_repeat_same_content_check(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()
    _enable_fake_tools(monkeypatch)

    _set_ocr_texts(
        monkeypatch,
        [
            "正常节目",
            "正常节目",
            "正常节目",
        ],
    )

    first = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    second = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert first.checked_count == 1
    assert second.selected_count == 0
    assert second.checked_count == 0


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


def test_missing_run_is_rejected(tmp_path):
    path, _ = _database(tmp_path)

    with pytest.raises(ValueError):
        content_check.run_content_checks(
            path,
            999,
            runner_identity="test-runner",
        )


def test_content_checks_select_highest_scoring_lines_not_line_id_order(
    tmp_path,
    monkeypatch,
):
    scores = {
        "line-1": 10,
        "line-2": 90,
        "line-3": 20,
        "line-4": 80,
        "line-5": 30,
        "line-6": 70,
    }
    path, run_id = _database(
        tmp_path,
        line_count=6,
        scores=scores,
    )
    _enable_fake_tools(monkeypatch)
    _set_ocr_texts(monkeypatch, ["正常节目"] * 15)

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 5
    with sqlite3.connect(path) as db:
        checked = {
            row[0]
            for row in db.execute(
                """
                SELECT line_id
                  FROM deep_probes
                 WHERE run_id = ?
                   AND evidence_json LIKE '%content_check%'
                """,
                (run_id,),
            ).fetchall()
        }

    assert checked == {
        "line-2",
        "line-3",
        "line-4",
        "line-5",
        "line-6",
    }
    assert "line-1" not in checked


@pytest.mark.parametrize(
    "target_type,target_id",
    [
        ("line", "line-1"),
        ("url", "https://example.com/live-1.ts"),
    ],
)
def test_active_blacklisted_line_or_url_is_not_selected(
    tmp_path,
    monkeypatch,
    target_type,
    target_id,
):
    path, run_id = _database(tmp_path, line_count=2)

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
            VALUES (?, ?, 'test_blacklist', '{}',
                    '2026-11-04T00:00:00Z', 1)
            """,
            (target_type, target_id),
        )

    _enable_fake_tools(monkeypatch)
    _set_ocr_texts(monkeypatch, ["正常节目"] * 3)

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 1
    assert result.checked_count == 1
    assert result.records[0].line_id == "line-2"


def test_line_without_current_run_deep_probe_eligibility_is_not_checked(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(
        tmp_path,
        line_count=2,
        eligible_line_ids={"line-2"},
    )
    _enable_fake_tools(monkeypatch)
    _set_ocr_texts(monkeypatch, ["正常节目"] * 3)

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 1
    assert result.checked_count == 1
    assert result.records[0].line_id == "line-2"


def test_score_join_is_scoped_to_current_run(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database(tmp_path, line_count=1)

    with sqlite3.connect(path) as db:
        cursor = db.execute(
            """
            INSERT INTO runs
                (started_at, status, runner_identity, environment_type)
            VALUES (
                '2026-11-04T01:00:00Z',
                'running',
                'test-runner',
                'cloud'
            )
            """
        )
        other_run_id = cursor.lastrowid

        # A score in another run must not be used as a substitute.
        db.execute(
            """
            DELETE FROM line_scores
             WHERE run_id = ? AND line_id = 'line-1'
            """,
            (run_id,),
        )
        db.execute(
            """
            INSERT INTO line_scores
                (
                    run_id,
                    line_id,
                    scored_at,
                    total_score,
                    components_json
                )
            VALUES (
                ?,
                'line-1',
                '2026-11-04T01:00:00Z',
                99,
                '{"eligible_for_deep_probe": true}'
            )
            """,
            (other_run_id,),
        )

    _enable_fake_tools(monkeypatch)

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 0
    assert result.checked_count == 0


def test_normalized_url_blacklist_blocks_equivalent_url(
    tmp_path,
    monkeypatch,
):
    path, run_id = _database()

    with sqlite3.connect(path) as db:
        db.execute(
            """
            UPDATE lines
               SET url = 'https://EXAMPLE.com:443/live-1.ts'
             WHERE line_id = 'line-1'
            """
        )
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
                'url',
                'https://example.com/live-1.ts',
                'test_normalized_blacklist',
                '{}',
                '2026-11-04T00:00:00Z',
                1
            )
            """
        )

    _enable_fake_tools(monkeypatch)

    result = content_check.run_content_checks(
        path,
        run_id,
        runner_identity="test-runner",
    )

    assert result.selected_count == 0
    assert result.checked_count == 0
