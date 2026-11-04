import json
import sqlite3

from iptv_auto.database import initialize_database
from iptv_auto.measurement import ProbeResult
from iptv_auto import stability


def _database(
    tmp_path,
    scores=None,
    eligible_line_ids=None,
):
    path = tmp_path / "stability_scoring.sqlite3"
    initialize_database(path)

    if scores is None:
        scores = {}

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
        run_id = int(cursor.lastrowid)

        db.execute(
            """
            INSERT INTO channels
                (channel_id, category, name)
            VALUES ('channel-1', '测试', '测试频道')
            """
        )

        for index in range(1, 7):
            line_id = f"line-{index}"
            url = f"https://example.com/{index}.ts"

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
                (line_id, url),
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

            evidence = {
                "content_check": {
                    "status": "no_flag_detected",
                    "content_class": "clean",
                    "ad_detected": False,
                    "placeholder_detected": False,
                }
            }

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
                    'passed',
                    1,
                    1,
                    ?
                )
                """,
                (
                    run_id,
                    line_id,
                    json.dumps(evidence),
                ),
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
                    float(scores.get(line_id, 80)),
                    json.dumps({
                        "eligible_for_deep_probe": eligible,
                    }),
                ),
            )

    return path, run_id


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


def _run(path, run_id, monkeypatch):
    monkeypatch.setattr(
        stability,
        "_probe_line",
        _successful_probe,
    )

    return stability.run_stability_retests(
        path,
        run_id,
        runner_identity="test-runner",
    )


def _scheduled_line_ids(path, run_id):
    with sqlite3.connect(path) as db:
        rows = db.execute(
            """
            SELECT DISTINCT line_id
              FROM measurements
             WHERE run_id = ?
               AND evidence_json LIKE '%stability_retest%'
            """,
            (run_id,),
        ).fetchall()

    return {row[0] for row in rows}


def test_stability_selects_highest_scoring_five_lines(
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
        scores=scores,
    )

    result = _run(path, run_id, monkeypatch)

    assert result.selected_count == 5
    assert result.scheduled_count == 10

    assert _scheduled_line_ids(path, run_id) == {
        "line-2",
        "line-3",
        "line-4",
        "line-5",
        "line-6",
    }


def test_stability_excludes_lines_without_deep_probe_eligibility(
    tmp_path,
    monkeypatch,
):
    scores = {
        "line-1": 10,
        "line-2": 100,
        "line-3": 90,
        "line-4": 80,
        "line-5": 70,
        "line-6": 60,
    }

    path, run_id = _database(
        tmp_path,
        scores=scores,
        eligible_line_ids={
            "line-1",
            "line-3",
            "line-4",
            "line-5",
            "line-6",
        },
    )

    result = _run(path, run_id, monkeypatch)

    assert result.selected_count == 5
    assert result.scheduled_count == 10

    selected = _scheduled_line_ids(path, run_id)

    assert "line-2" not in selected
    assert selected == {
        "line-1",
        "line-3",
        "line-4",
        "line-5",
        "line-6",
    }


def test_stability_does_not_use_scores_from_another_run(
    tmp_path,
    monkeypatch,
):
    scores = {
        "line-1": 100,
        "line-2": 90,
        "line-3": 80,
        "line-4": 70,
        "line-5": 60,
        "line-6": 50,
    }

    path, run_id = _database(
        tmp_path,
        scores=scores,
    )

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
        other_run_id = int(cursor.lastrowid)

        db.execute(
            """
            DELETE FROM line_scores
             WHERE run_id = ?
               AND line_id = 'line-1'
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
                100,
                '{"eligible_for_deep_probe": true}'
            )
            """,
            (other_run_id,),
        )

    result = _run(path, run_id, monkeypatch)

    selected = _scheduled_line_ids(path, run_id)

    assert result.selected_count == 5
    assert "line-1" not in selected
    assert selected == {
        "line-2",
        "line-3",
        "line-4",
        "line-5",
        "line-6",
  }
