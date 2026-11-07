
"""Central, dependency-free configuration for China-IPTV-Auto V3.

All limits here are initial engineering defaults, not measured nationwide
performance guarantees. Keep operational thresholds centralized in this file.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import math
from typing import Final


SCHEMA_VERSION: Final[str] = "1.0"
FORMAL_MODE: Final[str] = "formal"
TEST_MODE: Final[str] = "test"
ALLOWED_RUN_MODES: Final[tuple[str, str]] = (FORMAL_MODE, TEST_MODE)

# The publication path is fixed by CORE_FLOW.md and models.py.
PUBLISH_OUTPUT_PATH: Final[str] = "output/iptv.m3u"


class ConfigError(ValueError):
    """Raised when configuration values are invalid or contradictory."""


@dataclass(frozen=True)
class Config:
    # Run mode. TEST is the safe default; FORMAL must be explicitly selected.
    run_mode: str = TEST_MODE

    # Discovery and source collection.
    max_sources: int = 20
    source_timeout_seconds: int = 12
    discovery_budget_seconds: int = 120
    source_max_requests: int = 4
    source_concurrency: int = 4
    max_candidates: int = 300

    # Quick filtering.
    quick_filter_max_candidates: int = 200
    quick_filter_concurrency: int = 8
    quick_filter_budget_seconds: int = 120

    # Deep validation and overall request budget.
    deep_validation_max_candidates: int = 40
    deep_validation_concurrency: int = 4
    deep_validation_budget_seconds: int = 540
    line_deadline_seconds: int = 30
    run_deadline_seconds: int = 840
    # Counts every outbound HTTP attempt, including retries and redirect hops.
    total_http_request_budget: int = 1600

    # Network request controls. DNS/connect/read are separate phase limits.
    dns_timeout_seconds: int = 3
    connect_timeout_seconds: int = 5
    read_timeout_seconds: int = 8
    request_timeout_seconds: int = 12
    max_redirects: int = 3
    max_dns_cname_depth: int = 8
    max_dns_a_records: int = 16
    require_ipv4_only: bool = True
    pin_checked_ipv4: bool = True
    verify_tls_certificates: bool = True
    ignore_environment_proxies: bool = True
    reject_mixed_public_private_dns: bool = True
    max_retries: int = 1
    retry_backoff_seconds: float = 0.5

    # Media and HLS resource budgets.
    max_media_resource_bytes: int = 8 * 1024 * 1024
    max_playlist_bytes: int = 1024 * 1024
    max_resources_per_candidate: int = 24
    max_download_bytes_per_candidate: int = 32 * 1024 * 1024
    max_download_bytes_per_run: int = 512 * 1024 * 1024
    hls_max_playlist_refreshes: int = 3
    hls_validation_seconds: int = 12
    hls_segment_request_timeout_seconds: int = 8

    # Isolated validator container limits. These do not grant network access.
    validator_cpu_limit: float = 1.0
    validator_memory_bytes: int = 384 * 1024 * 1024
    validator_pids_limit: int = 32
    validator_nofile_limit: int = 128
    validator_tmpfs_bytes: int = 64 * 1024 * 1024
    ffprobe_timeout_seconds: int = 8
    ffmpeg_timeout_seconds: int = 12
    validator_container_timeout_seconds: int = 30

    # Task lifetime and cleanup.
    task_ttl_seconds: int = 300
    cleanup_grace_seconds: int = 30
    cleanup_retry_count: int = 2

    # M3U output validation.
    m3u_output_path: str = PUBLISH_OUTPUT_PATH
    m3u_encoding: str = "utf-8"
    m3u_max_entries: int = 40
    m3u_max_name_chars: int = 256
    m3u_max_group_chars: int = 128
    m3u_max_line_chars: int = 8192
    m3u_require_extm3u_header: bool = True
    m3u_require_extinf_for_each_url: bool = True
    m3u_allow_only_http_https: bool = True
    m3u_reject_embedded_credentials: bool = True


DEFAULT_CONFIG: Final[Config] = Config()


def validate_config(config: Config = DEFAULT_CONFIG) -> Config:
    """Validate types, ranges, cross-field relationships and fixed contracts."""
    if not isinstance(config, Config):
        raise ConfigError("config must be a Config instance")

    positive_int_fields = (
        "max_sources",
        "source_timeout_seconds",
        "discovery_budget_seconds",
        "source_max_requests",
        "source_concurrency",
        "max_candidates",
        "quick_filter_max_candidates",
        "quick_filter_concurrency",
        "quick_filter_budget_seconds",
        "deep_validation_max_candidates",
        "deep_validation_concurrency",
        "deep_validation_budget_seconds",
        "line_deadline_seconds",
        "run_deadline_seconds",
        "total_http_request_budget",
        "dns_timeout_seconds",
        "connect_timeout_seconds",
        "read_timeout_seconds",
        "request_timeout_seconds",
        "max_media_resource_bytes",
        "max_playlist_bytes",
        "max_resources_per_candidate",
        "max_download_bytes_per_candidate",
        "max_download_bytes_per_run",
        "hls_validation_seconds",
        "hls_segment_request_timeout_seconds",
        "validator_memory_bytes",
        "validator_pids_limit",
        "validator_nofile_limit",
        "validator_tmpfs_bytes",
        "ffprobe_timeout_seconds",
        "ffmpeg_timeout_seconds",
        "validator_container_timeout_seconds",
        "task_ttl_seconds",
        "cleanup_grace_seconds",
        "m3u_max_entries",
        "m3u_max_name_chars",
        "m3u_max_group_chars",
        "m3u_max_line_chars",
    )
    non_negative_int_fields = (
        "max_redirects",
        "max_dns_cname_depth",
        "max_dns_a_records",
        "max_retries",
        "hls_max_playlist_refreshes",
        "cleanup_retry_count",
    )

    for name in positive_int_fields:
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigError(f"{name} must be a positive integer")

    for name in non_negative_int_fields:
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(f"{name} must be a non-negative integer")

    for name in ("validator_cpu_limit", "retry_backoff_seconds"):
        value = getattr(config, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{name} must be numeric")
        if not math.isfinite(value) or value <= 0:
            raise ConfigError(f"{name} must be finite and greater than zero")

    if not isinstance(config.run_mode, str) or config.run_mode not in ALLOWED_RUN_MODES:
        raise ConfigError("run_mode must be 'formal' or 'test'")

    if config.m3u_output_path != PUBLISH_OUTPUT_PATH:
        raise ConfigError(
            f"m3u_output_path is fixed at {PUBLISH_OUTPUT_PATH!r}"
        )

    if not isinstance(config.m3u_encoding, str) or config.m3u_encoding.lower().replace("_", "-") != "utf-8":
        raise ConfigError("m3u_encoding must be UTF-8")

    for name in (
        "m3u_require_extm3u_header",
        "m3u_require_extinf_for_each_url",
        "m3u_allow_only_http_https",
        "m3u_reject_embedded_credentials",
        "require_ipv4_only",
        "pin_checked_ipv4",
        "verify_tls_certificates",
        "ignore_environment_proxies",
        "reject_mixed_public_private_dns",
    ):
        if not isinstance(getattr(config, name), bool):
            raise ConfigError(f"{name} must be bool")

    # Network security switches are mandatory V3 boundaries, not optional tuning.
    for name in (
        "require_ipv4_only",
        "pin_checked_ipv4",
        "verify_tls_certificates",
        "ignore_environment_proxies",
        "reject_mixed_public_private_dns",
    ):
        if getattr(config, name) is not True:
            raise ConfigError(f"{name} must remain enabled by CORE_FLOW.md")

    # Collection and filtering caps must be ordered and finite.
    if config.max_candidates < config.quick_filter_max_candidates:
        raise ConfigError(
            "max_candidates must be >= quick_filter_max_candidates"
        )
    if config.quick_filter_max_candidates < config.deep_validation_max_candidates:
        raise ConfigError(
            "quick_filter_max_candidates must be >= deep_validation_max_candidates"
        )
    if config.deep_validation_max_candidates > config.m3u_max_entries:
        raise ConfigError(
            "deep_validation_max_candidates must be <= m3u_max_entries"
        )

    # Parallelism cannot exceed the number of work items.
    if config.source_concurrency > config.max_sources:
        raise ConfigError("source_concurrency cannot exceed max_sources")
    if config.quick_filter_concurrency > config.quick_filter_max_candidates:
        raise ConfigError(
            "quick_filter_concurrency cannot exceed quick_filter_max_candidates"
        )
    if config.deep_validation_concurrency > config.deep_validation_max_candidates:
        raise ConfigError(
            "deep_validation_concurrency cannot exceed deep_validation_max_candidates"
        )

    # A single request's phase timeouts must fit inside its total timeout.
    if config.request_timeout_seconds < max(
        config.dns_timeout_seconds,
        config.connect_timeout_seconds,
        config.read_timeout_seconds,
    ):
        raise ConfigError(
            "request_timeout_seconds must be >= each phase timeout"
        )
    if config.source_timeout_seconds < config.request_timeout_seconds:
        raise ConfigError(
            "source_timeout_seconds must be >= request_timeout_seconds"
        )
    if config.hls_segment_request_timeout_seconds > config.request_timeout_seconds:
        raise ConfigError(
            "HLS segment timeout cannot exceed request_timeout_seconds"
        )

    if config.max_playlist_bytes > config.max_media_resource_bytes:
        raise ConfigError("playlist byte limit cannot exceed the media resource limit")

    # Media limits must be coherent at per-resource, per-candidate and run levels.
    if config.max_download_bytes_per_candidate < config.max_media_resource_bytes:
        raise ConfigError(
            "per-candidate download budge
