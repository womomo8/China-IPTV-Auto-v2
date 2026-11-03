import tempfile
import unittest
from pathlib import Path

import yaml

from iptv_auto.config import ConfigError, load_config


VALID = {
    "project": {"name": "China-IPTV-Auto-v2", "timezone": "Asia/Shanghai"},
    "paths": {
        "database": "data/db.sqlite3", "output_dir": "output",
        "playlist": "output/result.m3u", "backup_dir": "output/backups",
        "logs_dir": "logs",
    },
    "sources": {
        "pool_capacity": 30, "new_sources_per_run": 8,
        "discovery_enabled": True, "manual": [],
    },
    "discovery": {
        "max_seconds": 480, "request_timeout_seconds": 8,
        "max_candidate_lines": 36,
    },
    "precheck": {
        "require_http_or_https_or_supported_stream_scheme": True,
        "reject_empty_url": True, "reject_obvious_placeholders": True,
    },
    "measurement": {
        "basic_rounds_required_for_release": 3, "basic_timeout_seconds": 8,
        "max_concurrency": 12, "deep_candidates_per_channel": 5,
        "deep_timeout_seconds": 25, "stability_retests": 2,
    },
    "scoring": {
        "weights": {
            "success_rate": 30, "stability": 25, "throughput": 15,
            "freshness": 15, "ad_placeholder_risk": 10, "source_reliability": 5,
        },
        "grades": {"A": 85, "B": 70, "C": 50},
    },
    "release": {
        "minimum_success_rate": 0.90, "minimum_score": 70,
        "require_latest_measurement_success": True,
        "require_three_basic_rounds": True, "require_ffprobe_pass": True,
        "max_lines_per_channel": 3, "preserve_previous_on_failure": True,
        "atomic_replace": True,
    },
    "network_identity": {
        "cloud_measurements_must_be_labeled": True,
        "never_claim_cloud_test_is_fujian_mobile_home_test": True,
    },
    "blacklist": {
        "confirmed_ad_or_invalid_content_only": True,
        "transient_network_errors_are_not_permanent_blacklist": True,
        "congestion_or_stutter_only_reduces_score": True,
    },
}


class ConfigValidationTests(unittest.TestCase):
    def _load_data(self, data):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.yaml"
            path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
            return load_config(path)

    def test_valid_configuration_passes(self):
        self.assertEqual(self._load_data(VALID)["release"]["minimum_score"], 70)

    def test_null_section_returns_config_error(self):
        data = dict(VALID)
        data["scoring"] = None
        with self.assertRaises(ConfigError):
            self._load_data(data)

    def test_wrong_weights_type_returns_config_error(self):
        data = yaml.safe_load(yaml.safe_dump(VALID))
        data["scoring"]["weights"] = []
        with self.assertRaises(ConfigError):
            self._load_data(data)

    def test_boolean_cannot_replace_integer(self):
        data = yaml.safe_load(yaml.safe_dump(VALID))
        data["sources"]["pool_capacity"] = True
        with self.assertRaises(ConfigError):
            self._load_data(data)

    def test_release_gate_cannot_be_weakened(self):
        data = yaml.safe_load(yaml.safe_dump(VALID))
        data["release"]["require_ffprobe_pass"] = False
        with self.assertRaises(ConfigError):
            self._load_data(data)

    def test_cloud_environment_protection_cannot_be_disabled(self):
        data = yaml.safe_load(yaml.safe_dump(VALID))
        data["network_identity"]["never_claim_cloud_test_is_fujian_mobile_home_test"] = False
        with self.assertRaises(ConfigError):
            self._load_data(data)

    def test_manual_source_must_be_valid_http_url(self):
        data = yaml.safe_load(yaml.safe_dump(VALID))
        data["sources"]["manual"] = [{"name": "bad", "url": "not-a-url"}]
        with self.assertRaises(ConfigError):
            self._load_data(data)

    def test_manual_source_must_be_a_list(self):
        data = yaml.safe_load(yaml.safe_dump(VALID))
        data["sources"]["manual"] = None
        with self.assertRaises(ConfigError):
            self._load_data(data)

    def test_concurrency_must_be_bounded_positive_integer(self):
        data = yaml.safe_load(yaml.safe_dump(VALID))
        data["measurement"]["max_concurrency"] = 1000
        with self.assertRaises(ConfigError):
            self._load_data(data)


if __name__ == "__main__":
    unittest.main()
