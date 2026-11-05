import tempfile
import unittest
from pathlib import Path

from iptv_auto.channel_catalog import (
    ChannelCatalogError,
    load_channel_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "channels.yaml"


class ChannelCatalogTests(unittest.TestCase):

    def setUp(self):
        self.catalog = load_channel_catalog(CATALOG_PATH)

    def test_official_channel_total_is_38(self):
        self.assertEqual(self.catalog.total_channels, 38)

    def test_official_category_counts(self):
        counts = {}

        for channel in self.catalog.channels:
            counts[channel.category] = (
                counts.get(channel.category, 0) + 1
            )

        self.assertEqual(
            counts,
            {
                "央视频道": 10,
                "卫视频道": 12,
                "港澳台频道": 5,
                "体育频道": 11,
            },
        )

    def test_cctv5_and_cctv5_plus_are_separate(self):
        cctv5 = self.catalog.resolve("CCTV-5")
        cctv5_plus = self.catalog.resolve("CCTV-5+")

        self.assertIsNotNone(cctv5)
        self.assertIsNotNone(cctv5_plus)

        self.assertNotEqual(cctv5.channel_id, cctv5_plus.channel_id)
        self.assertNotEqual(cctv5.name, cctv5_plus.name)

    def test_cctv5_plus_spacing_variation(self):
        official = self.catalog.resolve("CCTV-5+")

        self.assertIsNotNone(official)
        self.assertEqual(
            self.catalog.resolve("CCTV 5+").channel_id,
            official.channel_id,
        )

    def test_cctv4_alias(self):
        official = self.catalog.resolve("CCTV-4 中文国际")

        self.assertIsNotNone(official)
        self.assertEqual(
            self.catalog.resolve("CCTV4").channel_id,
            official.channel_id,
        )

    def test_unknown_channel_is_not_accepted(self):
        self.assertIsNone(
            self.catalog.resolve("未知测试频道")
        )

    def test_invalid_total_is_rejected(self):
        original = CATALOG_PATH.read_text(encoding="utf-8")
        invalid = original.replace(
            "total_channels: 38",
            "total_channels: 37",
            1,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "channels.yaml"
            path.write_text(invalid, encoding="utf-8")

            with self.assertRaises(ChannelCatalogError):
                load_channel_catalog(path)


if __name__ == "__main__":
    unittest.main()
