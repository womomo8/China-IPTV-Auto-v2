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
    def test_parser_keeps_valid_entries_and_drops_placeholder(self):
        entries = parse_m3u(SAMPLE)
        self.assertEqual([e.name for e in entries], ["CCTV-5", "湖南卫视"])

    def test_deduplication(self):
        entries = parse_m3u(SAMPLE)
        self.assertEqual(len(deduplicate_entries(entries + entries)), 2)


if __name__ == "__main__":
    unittest.main()
