import unittest

from iptv_auto.identity import stable_result_id, stable_channel_id


class IdentityTests(unittest.TestCase):
    def test_default_https_port_is_normalized(self):
        self.assertEqual(
            stable_result_id("https://EXAMPLE.com:443/live.m3u8"),
            stable_result_id("https://example.com/live.m3u8"),
        )

    def test_header_changes_identity(self):
        self.assertNotEqual(
            stable_result_id("https://example.com/live", {"User-Agent": "A"}),
            stable_result_id("https://example.com/live", {"User-Agent": "B"}),
        )

    def test_channel_whitespace_is_normalized(self):
        self.assertEqual(
            stable_channel_id(" CCTV ", "CCTV 5"),
            stable_channel_id("cctv", "CCTV5"),
        )


if __name__ == "__main__":
    unittest.main()
