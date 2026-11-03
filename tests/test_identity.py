import unittest

from iptv_auto.identity import normalize_url, stable_result_id, stable_channel_id


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

    def test_ipv6_authority_keeps_brackets(self):
        self.assertEqual(
            normalize_url("http://[2001:DB8::1]:80/live"),
            "http://[2001:db8::1]/live",
        )

    def test_non_default_and_zero_ports_are_preserved(self):
        self.assertEqual(normalize_url("http://example.com:8080/a"), "http://example.com:8080/a")
        self.assertEqual(normalize_url("http://example.com:0/a"), "http://example.com:0/a")

    def test_invalid_port_does_not_crash_identity(self):
        value = "http://example.com:99999/live"
        self.assertEqual(normalize_url(value), value)


if __name__ == "__main__":
    unittest.main()
