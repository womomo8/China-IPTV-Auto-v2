from pathlib import Path

from iptv_auto import pipeline
from iptv_auto.database import database_session, initialize_database
from iptv_auto.playlist import PlaylistEntry


def _entry(index: int, channel_id: str = "official-cctv5") -> PlaylistEntry:
    url = f"https://stream.example/{index}.m3u8"

    return PlaylistEntry(
        name="CCTV-5",
        url=url,
        category="体育频道",
        headers={},
        line_id=f"line-{index}",
        channel_id=channel_id,
    )


def test_candidate_selection_deduplicates_only_within_one_source():
    entries = [_entry(index) for index in range(40)]
    entries.insert(5, entries[4])

    seen = set()

    selected, overflow = pipeline._take_candidate_entries(
        entries,
        seen,
        36,
    )

    assert len(selected) == 40
    assert len(seen) == 40
    assert overflow == 0
    assert selected[0].line_id == "line-0"
    assert selected[-1].line_id == "line-39"


def test_candidate_selection_keeps_same_url_for_different_channel_identity():
    first = PlaylistEntry(
        name="CCTV-5",
        url="https://stream.example/shared.m3u8",
        category="体育频道",
        headers={},
        line_id="same-line",
        channel_id="cctv5",
    )

    second = PlaylistEntry(
        name="CCTV-5+",
        url="https://stream.example/shared.m3u8",
        category="体育频道",
        headers={},
        line_id="same-line",
        channel_id="cctv5plus",
    )

    selected, overflow = pipeline._take_candidate_entries(
        [first, second],
        set(),
        36,
    )

    assert len(selected) == 2
    assert overflow == 0


def test_freeze_ranks_by_source_count_then_source_score(tmp_path: Path):
    db_path = tmp_path / "test.sqlite3"
    initialize_database(db_path)

    with database_session(db_path) as db:
        db.execute(
            """
            INSERT INTO runs
                (started_at, status, runner_identity, environment_type)
            VALUES ('now', 'running', 'test', 'cloud')
            """
        )

        for sid in ("s1", "s2", "s3"):
            db.execute(
                """
                INSERT INTO sources
                    (
                        source_id, name, url, source_type,
                        first_seen_at, last_seen_at, active
                    )
                VALUES (?, ?, ?, 'manual', 'now', 'now', 1)
                """,
                (
                    sid,
                    sid,
                    f"https://{sid}.example/list.m3u",
                ),
            )

        for idx, lid in enumerate(("line-a", "line-b"), start=1):
            db.execute(
                """
                INSERT INTO lines
                    (line_id, url, headers_json, first_seen_at, last_seen_at)
                VALUES (?, ?, '{}', 'now', 'now')
                """,
                (
                    lid,
                    f"https://stream.example/{lid}.m3u8",
                ),
            )

            db.execute(
                """
                INSERT INTO channels (channel_id, category, name)
                VALUES (?, '体育频道', 'CCTV-5')
                """,
                (f"ch-{idx}",),
            )

            db.execute(
                """
                INSERT INTO run_candidate_pool
                    (
                        run_id, line_id, channel_id, url_snapshot,
                        headers_json_snapshot, channel_name_snapshot,
                        category_snapshot, ipv4_admission_status, created_at
                    )
                VALUES (
                    1, ?, ?, ?, '{}', 'CCTV-5',
                    '体育频道', 'passed', 'now'
                )
                """,
                (
                    lid,
                    f"ch-{idx}",
                    f"https://stream.example/{lid}.m3u8",
                ),
            )

        db.execute(
            """
            INSERT INTO run_candidate_pool_sources
            VALUES (1, 'line-a', 'ch-1', 's1', 'now')
            """
        )
        db.execute(
            """
            INSERT INTO run_candidate_pool_sources
            VALUES (1, 'line-a', 'ch-1', 's2', 'now')
            """
        )
        db.execute(
            """
            INSERT INTO run_candidate_pool_sources
            VALUES (1, 'line-b', 'ch-2', 's3', 'now')
            """
        )

        db.execute(
            """
            INSERT INTO source_scores
                (run_id, source_id, scored_at, total_score, components_json)
            VALUES (1, 's1', 'now', 70, '{}')
            """
        )
        db.execute(
            """
            INSERT INTO source_scores
                (run_id, source_id, scored_at, total_score, components_json)
            VALUES (1, 's2', 'now', 70, '{}')
            """
        )
        db.execute(
            """
            INSERT INTO source_scores
                (run_id, source_id, scored_at, total_score, components_json)
            VALUES (1, 's3', 'now', 99, '{}')
            """
        )

    result = pipeline._freeze_run_candidates(
        db_path,
        1,
        limit=1,
    )

    assert result["pool_count"] == 2
    assert result["frozen_count"] == 1
    assert result["rejected_count"] == 1

    with database_session(db_path) as db:
        row = db.execute(
            "SELECT line_id FROM run_candidates WHERE run_id=1"
        ).fetchone()

    # 来源数量优先于来源评分。
    assert row["line_id"] == "line-a"


def test_freeze_is_idempotent_and_does_not_change_existing_order(
    tmp_path: Path,
):
    db_path = tmp_path / "test.sqlite3"
    initialize_database(db_path)

    with database_session(db_path) as db:
        db.execute(
            """
            INSERT INTO runs
                (started_at, status, runner_identity, environment_type)
            VALUES ('now', 'running', 'test', 'cloud')
            """
        )

        db.execute(
            """
            INSERT INTO sources
                (
                    source_id, name, url, source_type,
                    first_seen_at, last_seen_at, active
                )
            VALUES (
                's', 's', 'https://s.example/list',
                'manual', 'now', 'now', 1
            )
            """
        )

        db.execute(
            """
            INSERT INTO lines
                (line_id, url, headers_json, first_seen_at, last_seen_at)
            VALUES ('l', 'https://s.example/live', '{}', 'now', 'now')
            """
        )

        db.execute(
            """
            INSERT INTO channels (channel_id, category, name)
            VALUES ('c', '体育频道', 'CCTV-5')
            """
        )

        db.execute(
            """
            INSERT INTO run_candidate_pool
                (
                    run_id, line_id, channel_id, url_snapshot,
                    headers_json_snapshot, channel_name_snapshot,
                    category_snapshot, ipv4_admission_status, created_at
                )
            VALUES (
                1, 'l', 'c', 'https://s.example/live',
                '{}', 'CCTV-5', '体育频道', 'passed', 'now'
            )
            """
        )

        db.execute(
            """
            INSERT INTO run_candidate_pool_sources
            VALUES (1, 'l', 'c', 's', 'now')
            """
        )

    first = pipeline._freeze_run_candidates(
        db_path,
        1,
        limit=1,
    )

    second = pipeline._freeze_run_candidates(
        db_path,
        1,
        limit=1,
    )

    assert first["already_frozen"] == 0
    assert second["already_frozen"] == 1
