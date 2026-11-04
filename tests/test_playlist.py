import unittest

from iptv_auto.playlist import parse_m3u, deduplicate_entries


SAMPLE = """#EXTM3U
#EXTINF:-1 group-title="央视",CCTV-5
https://example.com/cctv5.m3u8
#EXTINF:-1 group-title="央视",无信号测试频道
https://example.com/placeholder.m3u8
#EXTINF:-1 group-title="卫视",湖南卫视
https://example.com/hunan.m3u8
"""


class PlaylistTests(unittest.TestCase):
    def test_channel_name_with_comma_is_preserved(self):
        playlist = """#EXTM3U
#EXTINF:-1 group-title="央视",CCTV-5,高清
https://example.com/live.m3u8
"""
        entries = parse_m3u(playlist)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "CCTV-5,高清")
        self.assertEqual(entries[0].category, "央视")
    def test_parser_keeps_valid_entries_and_drops_placeholder(self):
        entries = parse_m3u(SAMPLE)
        self.assertEqual([e.name for e in entries], ["CCTV-5", "湖南卫视"])

    def test_deduplication(self):
        entries = parse_m3u(SAMPLE)
        self.assertEqual(len(deduplicate_entries(entries + entries)), 2)

    def test_extvlcopt_user_agent_and_referrer_are_parsed(self):
        playlist = """#EXTM3U
#EXTINF:-1 group-title="央视",CCTV-5
#EXTVLCOPT:http-user-agent=MyPlayer/1.0
#EXTVLCOPT:http-referrer=https://example.org/page
https://example.com/live.m3u8
"""
        entry = parse_m3u(playlist)[0]
        self.assertEqual(entry.headers["User-Agent"], "MyPlayer/1.0")
        self.assertEqual(entry.headers["Referer"], "https://example.org/page")

    def test_exthttp_json_headers_are_parsed(self):
        playlist = """#EXTM3U
#EXTINF:-1,CCTV-5
#EXTHTTP:{"User-Agent":"AgentX","Referer":"https://example.org"}
https://example.com/live
"""
        entry = parse_m3u(playlist)[0]
        self.assertEqual(entry.headers, {"User-Agent": "AgentX", "Referer": "https://example.org"})

    def test_header_difference_changes_line_identity(self):
        playlist = """#EXTM3U
#EXTINF:-1,频道一
#EXTVLCOPT:http-user-agent=AgentA
https://example.com/live
#EXTINF:-1,频道二
#EXTVLCOPT:http-user-agent=AgentB
https://example.com/live
"""
        entries = parse_m3u(playlist)
        self.assertEqual(len(entries), 2)
        self.assertNotEqual(entries[0].line_id, entries[1].line_id)

    def test_malformed_exthttp_entry_is_rejected_not_silently_accepted(self):
        playlist = """#EXTM3U
#EXTINF:-1,频道
#EXTHTTP:{not-json}
https://example.com/live
#EXTINF:-1,正常频道
https://example.com/ok
"""
        entries = parse_m3u(playlist)
        self.assertEqual([entry.name for entry in entries], ["正常频道"])

    def test_non_header_vlc_options_do_not_become_headers(self):
        playlist = """#EXTM3U
#EXTINF:-1,频道
#EXTVLCOPT:network-caching=1000
https://example.com/live
"""
        entry = parse_m3u(playlist)[0]
        self.assertEqual(entry.headers, {})


if __name__ == "__main__":
    unittest.main()
