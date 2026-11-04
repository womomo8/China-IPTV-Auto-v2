
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iptv_auto.database import database_session, initialize_database
from iptv_auto.identity import stable_channel_id, stable_result_id
from iptv_auto.ipv4 import IPv4Admission
from iptv_auto.line_registry import LineRegistry, validate_entry
from iptv_auto.playlist import PlaylistEntry


def make_entry(
    name="CCTV-5",
    url="https://stream.example.com/live.m3u8",
    category="体育",
    headers=None,
):
    headers = headers or {}
    return PlaylistEntry(
        name=name,
        url=url,
        category=category,
        headers=headers,
        line_id=stable_result_id(url, headers),
        channel_id=stable_channel_id(category, name),
    )


class LineRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.sqlite3"
        initialize_database(self.db_path)

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO runs
                    (started_at, status, runner_identity, environment_type)
                VALUES ('2026-11-04T00:00:00Z', 'running', 'test', 'cloud')
                """
            )
            db.execute(
                """
                INSERT INTO sources
                    (source_id, name, url, source_type,
                     first_seen_at, last_seen_at, active)
                VALUES ('source-test', '测试来源',
                        'https://example.com/list.m3u',
                        'manual', '2026-11-04T00:00:00Z',
                        '2026-11-04T00:00:00Z', 1)
                """
            )

        self.registry = LineRegistry(self.db_path)

        # Keep existing registry tests independent of external DNS.
        self.dns_patcher = patch(
            "iptv_auto.ipv4.socket.getaddrinfo",
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("8.8.8.8", 443),
                )
            ],
        )
        self.dns_patcher.start()

    def tearDown(self):
        self.dns_patcher.stop()
        self.temp.cleanup()

    def test_valid_entry(self):
        self.assertIsNone(validate_entry(make_entry()))

    def test_rejects_empty_channel_name(self):
        self.assertEqual(
            validate_entry(make_entry(name="")),
            "empty_channel_name",
        )

    def test_rejects_placeholder_channel(self):
        self.assertEqual(
            validate_entry(make_entry(name="广告")),
            "placeholder_channel",
        )

    def test_rejects_unsupported_protocol(self):
        self.assertEqual(
            validate_entry(make_entry(url="ftp://example.com/live")),
            "unsupported_protocol",
        )

    def test_rejects_malformed_url(self):
        self.assertEqual(
            validate_entry(make_entry(url="http://")),
            "missing_host",
        )

    def test_rejects_private_ip(self):
        self.assertEqual(
            validate_entry(make_entry(url="http://192.168.1.10/live")),
            "non_public_ip_address",
        )

    def test_inactive_source_cannot_register_lines(self):
        with database_session(self.db_path) as db:
            db.execute(
                "UPDATE sources SET active = 0 WHERE source_id = ?",
                ("source-test",),
            )

        with self.assertRaisesRegex(ValueError, "来源已停用"):
            self.registry.ingest(
                run_id=1,
                source_id="source-test",
                entries=[make_entry()],
            )

    def test_registers_entry_and_relationships(self):
        entry = make_entry()
        result = self.registry.ingest(
            run_id=1,
            source_id="source-test",
            entries=[entry],
        )

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.accepted_line_ids, (entry.line_id,))
        self.assertEqual(result.ipv4_passed_count, 1)

        with database_session(self.db_path) as db:
            line_count = db.execute(
                "SELECT COUNT(*) FROM lines WHERE line_id = ?",
                (entry.line_id,),
            ).fetchone()[0]
            source_link_count = db.execute(
                "SELECT COUNT(*) FROM source_lines WHERE source_id = ?",
                ("source-test",),
            ).fetchone()[0]
            channel_link_count = db.execute(
                "SELECT COUNT(*) FROM line_channels WHERE line_id = ?",
                (entry.line_id,),
            ).fetchone()[0]

        self.assertEqual(line_count, 1)
        self.assertEqual(source_link_count, 1)
        self.assertEqual(channel_link_count, 1)

    def test_duplicate_entry_is_not_registered_twice(self):
        entry = make_entry()
        result = self.registry.ingest(
            run_id=1,
            source_id="source-test",
            entries=[entry, entry],
        )

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.duplicate_count, 1)

    def test_blacklisted_line_is_rejected(self):
        entry = make_entry()

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO blacklists
                    (target_type, target_id, reason, created_at)
                VALUES ('line', ?, 'confirmed invalid content',
                        '2026-11-04T00:00:00Z')
                """,
                (entry.line_id,),
            )

        result = self.registry.ingest(
            run_id=1,
            source_id="source-test",
            entries=[entry],
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected[0].reason, "blacklisted")

    def test_blacklisted_normalized_url_is_rejected(self):
        entry = make_entry(
            url="https://EXAMPLE.com:443/live.m3u8"
        )

        with database_session(self.db_path) as db:
            db.execute(
                """
                INSERT INTO blacklists
                    (target_type, target_id, reason, created_at)
                VALUES (
                    'url',
                    'https://example.com/live.m3u8',
                    'confirmed invalid content',
                    '2026-11-04T00:00:00Z'
                )
                """
            )

        result = self.registry.ingest(
            run_id=1,
            source_id="source-test",
            entries=[entry],
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected[0].reason, "blacklisted")

    def test_transient_failures_are_not_added_to_blacklist(self):
        entry = make_entry()
        result = self.registry.ingest(
            run_id=1,
            source_id="source-test",
            entries=[entry],
        )

        self.assertEqual(result.accepted_count, 1)

        with database_session(self.db_path) as db:
            blacklist_count = db.execute(
                "SELECT COUNT(*) FROM blacklists WHERE target_id = ?",
                (entry.line_id,),
            ).fetchone()[0]

        self.assertEqual(blacklist_count, 0)

    def test_ipv4_rejected_entry_is_not_registered(self):
        entry = make_entry()

        with patch(
            "iptv_auto.line_registry.check_ipv4_url",
            return_value=IPv4Admission(
                False, "no_ipv4_address"
            ),
        ):
            result = self.registry.ingest(
                run_id=1,
                source_id="source-test",
                entries=[entry],
            )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.ipv4_passed_count, 0)
        self.assertEqual(result.ipv4_excluded_count, 1)
        self.assertEqual(
            result.rejected[0].reason,
            "ipv4_no_ipv4_address",
        )

        with database_session(self.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM lines WHERE line_id = ?",
                (entry.line_id,),
            ).fetchone()[0]

        self.assertEqual(count, 0)

    def test_temporary_dns_failure_is_not_blacklisted(self):
        entry = make_entry()

        with patch(
            "iptv_auto.line_registry.check_ipv4_url",
            return_value=IPv4Admission(
                False, "dns_temporary_failure"
            ),
        ):
            result = self.registry.ingest(
                run_id=1,
                source_id="source-test",
                entries=[entry],
            )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(
            result.ipv4_temporary_failure_count, 1
        )

        with database_session(self.db_path) as db:
            blacklist_count = db.execute(
                "SELECT COUNT(*) FROM blacklists WHERE target_id = ?",
                (entry.line_id,),
            ).fetchone()[0]

        self.assertEqual(blacklist_count, 0)


if __name__ == "__main__":
    unittest.main()
