import json
import unittest
from unittest.mock import patch

from iptv_auto.identity import stable_source_id
from iptv_auto.sources import (
    SourceCandidate,
    collect_source_candidates,
    discover_github_playlists,
    fetch_playlist,
)


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit=-1):
        return self.body[:limit]


class SourceTests(unittest.TestCase):
    def test_manual_sources_are_kept_first_and_deduplicated(self):
        manual = {
            "source_id": "source_a", "name": "手动", "url": "https://x.test/a.m3u",
            "source_type": "manual",
        }
        discovered = [
            SourceCandidate(stable_source_id("https://x.test/a.m3u"), "duplicate",
                            "https://x.test/a.m3u", "discovered"),
            SourceCandidate("source_b", "new", "https://x.test/b.m3u", "discovered"),
        ]
        config = {
            "sources": {"manual": [{"name": "手动", "url": "https://x.test/a.m3u"}],
                        "discovery_enabled": True, "pool_capacity": 30, "new_sources_per_run": 8},
            "discovery": {"request_timeout_seconds": 8, "max_candidate_lines": 36,
                          "max_seconds": 480},
        }
        with patch("iptv_auto.sources.discover_github_playlists", return_value=discovered):
            result = collect_source_candidates(config)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].source_type, "manual")
        self.assertEqual(result[1].source_id, "source_b")

    def test_discovery_disabled_skips_network(self):
        config = {
            "sources": {"manual": [], "discovery_enabled": False, "pool_capacity": 30,
                        "new_sources_per_run": 8},
            "discovery": {"request_timeout_seconds": 8, "max_candidate_lines": 36,
                          "max_seconds": 480},
        }
        with patch("iptv_auto.sources.discover_github_playlists") as discover:
            self.assertEqual(collect_source_candidates(config), [])
            discover.assert_not_called()

    def test_github_discovery_finds_only_playlist_blobs(self):
        search = {"items": [{"full_name": "demo/iptv", "default_branch": "main"}]}
        tree = {"truncated": False, "tree": [
            {"type": "blob", "path": "live.m3u", "size": 100},
            {"type": "blob", "path": "README.md", "size": 100},
            {"type": "tree", "path": "nested", "size": 0},
            {"type": "blob", "path": "huge.m3u", "size": 99999999},
        ]}
        responses = [json.dumps(search).encode(), json.dumps(tree).encode()]
        with patch("iptv_auto.sources._http_get",
                   side_effect=[(200, responses[0]), (200, responses[1])]):
            result = discover_github_playlists()
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].url.endswith("/live.m3u"))

    def test_fetch_playlist_decodes_utf8_bom(self):
        with patch("iptv_auto.sources._http_get",
                   return_value=(200, bytes([239, 187, 191]) + b"#EXTM3U\\n")):
            result = fetch_playlist("https://example.test/list.m3u")
        self.assertTrue(result.ok)
        self.assertTrue(result.text.startswith("#EXTM3U"))

    def test_fetch_rejects_empty_body(self):
        with patch("iptv_auto.sources._http_get", return_value=(200, b"")):
            result = fetch_playlist("https://example.test/list.m3u")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_class, "empty_response")

    def test_fetch_rejects_invalid_url(self):
        result = fetch_playlist("file:///etc/passwd")
        self.assertFalse(result.ok)
        self.assertEqual(result.error_class, "invalid_url")


if __name__ == "__main__":
    unittest.main()
