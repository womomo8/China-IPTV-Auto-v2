from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from iptv_auto import pipeline
from iptv_auto.playlist import PlaylistEntry


def _entry(index: int) -> PlaylistEntry:
    return PlaylistEntry(
        name="CCTV-5",
        url=f"https://stream.example/{index}.m3u8",
        category="体育频道",
        headers={},
        line_id=f"line-{index}",
        channel_id="official-cctv5",
    )


def test_candidate_selection_enforces_run_wide_limit_and_deduplicates():
    entries = [_entry(index) for index in range(40)]
    entries.insert(5, entries[4])
    seen = set()

    selected, overflow = pipeline._take_candidate_entries(
        entries, seen, 36
    )

    assert len(selected) == 36
    assert len(seen) == 36
    assert overflow == 4
    assert selected[0].line_id == "line-0"
    assert selected[-1].line_id == "line-35"


def test_candidate_selection_keeps_same_url_for_different_channel_identity():
    first = PlaylistEntry(
        name="CCTV-5", url="https://stream.example/shared.m3u8",
        category="体育频道", headers={}, line_id="same-line",
        channel_id="cctv5",
    )
    second = PlaylistEntry(
        name="CCTV-5+", url="https://stream.example/shared.m3u8",
        category="体育频道", headers={}, line_id="same-line",
        channel_id="cctv5plus",
    )

    selected, overflow = pipeline._take_candidate_entries(
        [first, second], set(), 36
    )

    assert len(selected) == 2
    assert overflow == 0


def test_pipeline_stops_cleanly_when_first_stage_has_no_eligible_lines(
    tmp_path: Path,
):
    config = {"paths": {"database": str(tmp_path / "data" / "test.sqlite3")}}
    source_summary = {
        "stage_status": "completed_no_candidates",
        "accepted_entries": 0,
        "stop_reason": "all_sources_processed",
    }

    with (
        patch.object(pipeline, "load_config", return_value=config),
        patch.object(
            pipeline, "load_channel_catalog",
            return_value=SimpleNamespace(total_channels=38),
        ),
        patch.object(pipeline, "initialize_database"),
        patch.object(pipeline, "_runner_identity", return_value="test-runner"),
        patch.object(pipeline, "_create_or_resume_run", return_value=7),
        patch.object(pipeline, "_save_summary") as save_summary,
        patch.object(
            pipeline, "_discover_and_ingest", return_value=source_summary
        ),
        patch.object(pipeline, "run_basic_measurements") as basic_measurements,
    ):
        result = pipeline.run_pipeline(
            config_path=tmp_path / "config.yaml"
        )

    assert result["status"] == "completed_no_candidates"
    assert result["run_id"] == 7
    assert result["summary"]["completion_reason"] == "no_eligible_candidates"
    basic_measurements.assert_not_called()
    assert save_summary.call_args.kwargs["status"] == "completed_no_candidates"
