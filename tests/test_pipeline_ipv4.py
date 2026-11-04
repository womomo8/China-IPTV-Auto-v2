
import json
from pathlib import Path
from unittest.mock import patch

from iptv_auto import pipeline
from iptv_auto.database import database_session, initialize_database
from iptv_auto.ipv4 import IPv4Admission
from iptv_auto.sources import SourceFetchResult


def test_ipv4_admission_statistics_reach_same_run_summary(
    tmp_path: Path,
):
    database_path = tmp_path / "pipeline-ipv4.sqlite3"
    initialize_database(database_path)

    run_id = 1
    source_id = "source-test"

    with database_session(database_path) as db:
        db.execute(
            """
            INSERT INTO runs
                (
                    run_id,
                    started_at,
                    status,
                    runner_identity,
                    environment_type,
                    summary_json
                )
            VALUES (
                ?, '2026-11-05T00:00:00Z',
                'running', 'test-runner', 'cloud', '{}'
            )
            """,
            (run_id,),
        )

        db.execute(
            """
            INSERT INTO sources
                (
                    source_id,
                    name,
                    url,
                    source_type,
                    first_seen_at,
                    last_seen_at,
                    active
                )
            VALUES (
                ?, '测试来源',
                'https://example.com/list.m3u',
                'manual',
                '2026-11-05T00:00:00Z',
                '2026-11-05T00:00:00Z',
                1
            )
            """,
            (source_id,),
        )

    playlist = """#EXTM3U
#EXTINF:-1 group-title="体育",CCTV-5
https://1.1.1.1/live1.m3u8
#EXTINF:-1 group-title="体育",CCTV-5
https://[2001:4860:4860::8888]/live2.m3u8
#EXTINF:-1 group-title="体育",CCTV-5
https://dns-temp.example/live3.m3u8
"""

    admissions = [
        IPv4Admission(True, "ipv4_literal"),
        IPv4Admission(False, "ipv6_literal"),
        IPv4Admission(False, "dns_temporary_failure"),
    ]

    config = {
        "sources": {
            "pool_capacity": 30,
            "new_sources_per_run": 8,
        },
        "discovery": {
            "request_timeout_seconds": 8,
        },
    }

    with (
        patch.object(
            pipeline,
            "collect_source_candidates",
            return_value=[],
        ),
        patch.object(
            pipeline,
            "fetch_playlist",
            return_value=SourceFetchResult(
                ok=True,
                text=playlist,
                status_code=200,
                duration_ms=12.0,
            ),
        ),
        patch(
            "iptv_auto.line_registry.check_ipv4_url",
            side_effect=admissions,
        ),
    ):
        source_summary = pipeline._discover_and_ingest(
            config,
            database_path,
            run_id,
        )

    expected_admission = {
        "passed": 1,
        "excluded": 1,
        "temporary_failure": 1,
    }

    assert source_summary["ipv4_admission"] == expected_admission
    assert source_summary["parsed_entries"] == 3
    assert source_summary["accepted_entries"] == 1
    assert source_summary["rejected_entries"] == 2

    with database_session(database_path) as db:
        registered = db.execute(
            "SELECT url FROM lines"
        ).fetchall()

        source_check = db.execute(
            """
            SELECT run_id, discovered_lines, accepted_lines,
                   evidence_json
              FROM source_checks
             WHERE run_id = ? AND source_id = ?
            """,
            (run_id, source_id),
        ).fetchone()

    assert len(registered) == 1
    assert registered[0]["url"] == "https://1.1.1.1/live1.m3u8"

    assert source_check is not None
    assert source_check["run_id"] == run_id
    assert source_check["discovered_lines"] == 3
    assert source_check["accepted_lines"] == 1

    source_evidence = json.loads(source_check["evidence_json"])
    assert source_evidence["ipv4_admission"] == expected_admission

    pipeline._save_summary(
        database_path,
        run_id,
        {"source_stage": source_summary},
    )

    with database_session(database_path) as db:
        run = db.execute(
            """
            SELECT summary_json
              FROM runs
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

    saved_summary = json.loads(run["summary_json"])

    assert (
        saved_summary["source_stage"]["ipv4_admission"]
        == expected_admission
    )
