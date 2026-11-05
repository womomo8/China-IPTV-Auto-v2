"""Tests for basic HTTP media-response validation."""

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from iptv_auto.measurement import (
    _is_valid_basic_http_body,
    _probe_http,
)


class MeasurementHTTPContentTests(unittest.TestCase):

    def test_reject_html_content_type(self):
        body = b"<html><body>Page not found</body></html>"

        self.assertFalse(
            _is_valid_basic_http_body("text/html", body)
        )

    def test_reject_html_with_false_media_content_type(self):
        body = b"<!DOCTYPE html><html><body>Error</body></html>"

        self.assertFalse(
            _is_valid_basic_http_body(
                "application/octet-stream",
                body,
            )
        )

    def test_reject_json_error_response(self):
        body = b'{"error":"stream unavailable"}'

        self.assertFalse(
            _is_valid_basic_http_body(
                "application/json",
                body,
            )
        )

    def test_reject_empty_response(self):
        self.assertFalse(
            _is_valid_basic_http_body("video/mp2t", b"")
        )

    def test_accept_hls_playlist(self):
        body = (
            b"#EXTM3U\n"
            b"#EXT-X-VERSION:3\n"
            b"#EXT-X-TARGETDURATION:10\n"
        )

        self.assertTrue(
            _is_valid_basic_http_body(
                "application/vnd.apple.mpegurl",
                body,
            )
        )

    def test_accept_hls_playlist_with_utf8_bom(self):
        body = (
            b"\xef\xbb\xbf"
            b"#EXTM3U\n"
            b"#EXT-X-VERSION:3\n"
        )

        self.assertTrue(
            _is_valid_basic_http_body(
                "text/plain",
                body,
            )
        )

    def test_accept_dash_manifest(self):
        body = (
            b'<?xml version="1.0"?>'
            b'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">'
            b"</MPD>"
        )

        self.assertTrue(
            _is_valid_basic_http_body(
                "application/dash+xml",
                body,
            )
        )

    def test_keep_existing_video_mime_compatibility(self):
        self.assertTrue(
            _is_valid_basic_http_body(
                "video/mp2t",
                b"x" * 12000,
            )
        )

    def test_http_html_response_is_failed(self):
        body = b"<html><body>Not a media stream</body></html>"
        content_type = "text/html"

        class Handler(BaseHTTPRequestHandler):

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            Handler,
        )

        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        thread.start()

        try:
            url = (
                f"http://127.0.0.1:{server.server_port}/live"
            )

            result = _probe_http(url, {}, 2)

            self.assertEqual(result.status, "failed")
            self.assertEqual(
                result.error_class,
                "non_media_response",
            )
            self.assertFalse(
                result.evidence["media_response_confirmed"]
            )
            self.assertFalse(
                result.evidence["media_playback_confirmed"]
            )

        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
