
import socket
import unittest
from unittest.mock import patch

from iptv_auto.ipv4 import (
    check_ipv4_url,
    clear_ipv4_dns_cache,
)


def dns_record(address, port=80):
    return (
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        (address, port),
    )


class IPv4AdmissionTests(unittest.TestCase):
    def setUp(self):
        clear_ipv4_dns_cache()

    def tearDown(self):
        clear_ipv4_dns_cache()

    def test_accepts_public_ipv4_literal(self):
        result = check_ipv4_url("http://8.8.8.8/live.m3u8")

        self.assertTrue(result.allowed)
        self.assertEqual(result.status, "ipv4_literal")

    def test_rejects_ipv6_literal(self):
        result = check_ipv4_url(
            "https://[2001:4860:4860::8888]/live.m3u8"
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.status, "ipv6_literal")

    def test_rejects_private_ipv4_literal(self):
        result = check_ipv4_url("http://192.168.1.10/live")

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.status, "non_public_ipv4_address"
        )

    @patch("iptv_auto.ipv4.socket.getaddrinfo")
    def test_accepts_domain_with_public_ipv4(self, mock_dns):
        mock_dns.return_value = [
            dns_record("8.8.8.8")
        ]

        result = check_ipv4_url(
            "https://stream.example.com/live.m3u8"
        )

        self.assertTrue(result.allowed)
        self.assertEqual(result.status, "ipv4_dns")
        self.assertEqual(result.addresses, ("8.8.8.8",))
        mock_dns.assert_called_once()

    @patch("iptv_auto.ipv4.socket.getaddrinfo")
    def test_rejects_domain_with_only_private_ipv4(self, mock_dns):
        mock_dns.return_value = [
            dns_record("192.168.1.20")
        ]

        result = check_ipv4_url(
            "https://private.example.com/live"
        )

        self.assertFalse(result.allowed)
        self.assertEqual(
            result.status, "non_public_ipv4_address"
        )

    @patch("iptv_auto.ipv4.socket.getaddrinfo")
    def test_rejects_domain_without_ipv4_record(self, mock_dns):
        mock_dns.return_value = []

        result = check_ipv4_url(
            "https://ipv6-only.example.com/live"
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.status, "no_ipv4_address")

    @patch("iptv_auto.ipv4.socket.getaddrinfo")
    def test_temporary_dns_failure_is_not_cached(self, mock_dns):
        mock_dns.side_effect = socket.gaierror(
            socket.EAI_AGAIN, "Temporary failure"
        )

        first = check_ipv4_url(
            "https://temporary.example.com/live"
        )
        second = check_ipv4_url(
            "https://temporary.example.com/live"
        )

        self.assertFalse(first.allowed)
        self.assertEqual(
            first.status, "dns_temporary_failure"
        )
        self.assertEqual(
            second.status, "dns_temporary_failure"
        )
        self.assertEqual(mock_dns.call_count, 2)

    @patch("iptv_auto.ipv4.socket.getaddrinfo")
    def test_successful_dns_result_is_cached(self, mock_dns):
        mock_dns.return_value = [
            dns_record("1.1.1.1")
        ]

        first = check_ipv4_url(
            "https://cache.example.com/live"
        )
        second = check_ipv4_url(
            "https://cache.example.com/live"
        )

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertEqual(mock_dns.call_count, 1)


if __name__ == "__main__":
    unittest.main()
