"""Central configuration for China-IPTV-Auto V3.

All limits are initial engineering defaults, not measured nationwide
performance guarantees. Keep operational thresholds centralized here.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import math
import re
from typing import Final
from urllib.parse import urlsplit

from models import (
    ChannelMode,
    ContractError,
    UserChannelConfig,
    channel_mode_for,
    validate_user_channel_config,
)


FORMAL_MODE: Final[str] = "formal"
TEST_MODE: Final[str] = "test"
ALLOWED_RUN_MODES: Final[tuple[str, str]] = (
    FORMAL_MODE,
    TEST_MODE,
)

PUBLISH_OUTPUT_PATH: Final[str] = "output/iptv.m3u"

_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ConfigError(ValueError):
    """Raised when configuration values are invalid or contradictory."""


@dataclass(frozen=True)
class SourceDefinition:
    """A configured source entry.

    URL syntax is checked here. Public-IP, DNS, redirect, TLS and network
    safety checks must be performed by security.py at runtime.
    """

    source_id: str
    url: str
    enabled: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_id, str)
            or not _SOURCE_ID_RE.fullmatch(self.source_id)
        ):
            raise ConfigError(
                "source_id must be a valid non-empty identifier"
            )

        if (
            not isinstance(self.url, str)
            or not self.url
            or len(self.url) > 4096
            or self.url != self.url.strip()
            or any(ord(char) < 32 for char in self.url)
        ):
            raise ConfigError("source URL must be a valid non-empty string")

        try:
            parsed = urlsplit(self.url)
            # Accessing .port also validates the port syntax and range.
            _ = parsed.port
        except ValueError as exc:
            raise ConfigError("source URL has an invalid port or format") from exc

        if parsed.scheme.lower() not in ("http", "https"):
            raise ConfigError("source URL must use HTTP or HTTPS")

        if not parsed.hostname:
            raise ConfigError("source URL must contain a hostname")

        if parsed.username is not None or parsed.password is not None:
            raise ConfigError("source URL must not contain embedded credentials")

        if parsed.fragment:
            raise ConfigError("source URL must not contain a fragment")

        if not isinstance(self.enabled, bool):
            raise ConfigError("source enabled must be bool")


# Source registry:
# - Add a SourceDefinition to register another source.
# - Change its URL to replace a source address.
# - Set enabled=False to temporarily disable a source.
# - Remove the entry to delete it from the registry.
#
# This is a configuration registry, not a trust list. Every network request
# must still pass the complete security checks in security.py.
SOURCE_REGISTRY: Final[tuple[SourceDefinition, ...]] = (
    SourceDefinition(
        source_id="source-001",
        url="http://1.94.31.214/live/live9/dgtv.txt",
    ),
)


# User-maintained channel display configuration.
# Leave this tuple empty to enable automatic channel discovery.
# Entries may contain only name, group and order; never put URLs or candidate IDs here.
USER_CHANNELS: Final[tuple[UserChannelConfig, ...]] = ()


def validate_user_channels(
    channels: tuple[UserChannelConfig, ...] = USER_CHANNELS,
) -> tuple[UserChannelConfig, ...]:
    """Validate user channel settings against the models.py data contract."""
    try:
        return validate_user_channel_config(channels)
    except ContractError as exc:
        raise ConfigError(str(exc)) from exc


def user_channel_mode(
    channels: tuple[UserChannelConfig, ...] = USER_CHANNELS,
) -> ChannelMode:
    """Return the single channel mode selected by whether config is empty."""
    try:
        return channel_mode_for(channels)
    except ContractError as exc:
        raise ConfigError(str(exc)) from exc


@dataclass(frozen=True)
class Config:
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

    # Deep validation and whole-run budgets.
    deep_validation_max_candidates: int = 40
    deep_validation_concurrency: int = 4
    deep_validation_budget_seconds: int = 540
    line_deadline_seconds: int = 30
    run_deadline_seconds: int = 840
    total_http_request_budget: int = 1600

    # Discovery-wide budgets. These are separate from per-request limits.
    max_total_redirects: int = 400
    max_total_retries: int = 200
    max_channel_discovery_results: int = 300
    max_discovery_report_bytes: int = 2 * 1024 * 1024

    # Network request controls.
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

    # Isolated validator container limits.
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


def validate_source_registry(
    sources: tuple[SourceDefinition, ...] = SOURCE_REGISTRY,
    config: Config = DEFAULT_CONFIG,
) -> tuple[SourceDefinition, ...]:
    """Validate the configured source registry without network access."""

    if not isinstance(sources, tuple):
        raise ConfigError("source registry must be a tuple")

    if not isinstance(config, Config):
        raise ConfigError("config must be a Config instance")

    source_ids: set[str] = set()
    source_urls: set[str] = set()
    enabled_count = 0

    for source in sources:
        if not isinstance(source, SourceDefinition):
            raise ConfigError(
                "every source registry entry must be SourceDefinition"
            )

        if source.source_id in source_ids:
            raise ConfigError(
                f"duplicate source_id: {source.source_id}"
            )

        normalized_url = source.url.rstrip("/")

        if normalized_url in source_urls:
            raise ConfigError(
                f"duplicate source URL: {source.source_id}"
            )

        source_ids.add(source.source_id)
        source_urls.add(normalized_url)

        if source.enabled:
            enabled_count += 1

    if enabled_count > config.max_sources:
        raise ConfigError(
            "enabled source count cannot exceed max_sources"
        )

    return sources


def enabled_sources(
    sources: tuple[SourceDefinition, ...] = SOURCE_REGISTRY,
    config: Config = DEFAULT_CONFIG,
) -> tuple[SourceDefinition, ...]:
    """Return enabled source entries in their configured order."""

    validate_source_registry(sources, config)

    return tuple(source for source in sources if source.enabled)


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
        "max_channel_discovery_results",
        "max_discovery_report_bytes",
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
        "max_total_redirects",
        "max_total_retries",
        "max_dns_cname_depth",
        "max_dns_a_records",
        "max_retries",
        "hls_max_playlist_refreshes",
        "cleanup_retry_count",
    )

    for name in positive_int_fields:
        value = getattr(config, name)

        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{name} must be a positive integer")

        if value <= 0:
            raise ConfigError(f"{name} must be a positive integer")

    for name in non_negative_int_fields:
        value = getattr(config, name)

        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{name} must be a non-negative integer")

        if value < 0:
            raise ConfigError(f"{name} must be a non-negative integer")

    for name in ("validator_cpu_limit", "retry_backoff_seconds"):
        value = getattr(config, name)

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{name} must be numeric")

        if not math.isfinite(value) or value <= 0:
            raise ConfigError(
                f"{name} must be finite and greater than zero"
            )

    if (
        not isinstance(config.run_mode, str)
        or config.run_mode not in ALLOWED_RUN_MODES
    ):
        raise ConfigError("run_mode must be 'formal' or 'test'")

    if (
        not isinstance(config.m3u_encoding, str)
        or config.m3u_encoding.lower().replace("_", "-") != "utf-8"
    ):
        raise ConfigError("m3u_encoding must be UTF-8")

    boolean_fields = (
        "m3u_require_extm3u_header",
        "m3u_require_extinf_for_each_url",
        "m3u_allow_only_http_https",
        "m3u_reject_embedded_credentials",
        "require_ipv4_only",
        "pin_checked_ipv4",
        "verify_tls_certificates",
        "ignore_environment_proxies",
        "reject_mixed_public_private_dns",
    )

    for name in boolean_fields:
        if not isinstance(getattr(config, name), bool):
            raise ConfigError(f"{name} must be bool")

    # Mandatory V3 security boundaries.
    for name in (
        "require_ipv4_only",
        "pin_checked_ipv4",
        "verify_tls_certificates",
        "ignore_environment_proxies",
        "reject_mixed_public_private_dns",
    ):
        if getattr(config, name) is not True:
            raise ConfigError(
                f"{name} must remain enabled by CORE_FLOW.md"
            )

    # Candidate limits describe different pipeline stages.
    # M3U output capacity is independent of validation capacity.
    if config.max_candidates < config.quick_filter_max_candidates:
        raise ConfigError(
            "max_candidates must be >= quick_filter_max_candidates"
        )

    if (
        config.quick_filter_max_candidates
        < config.deep_validation_max_candidates
    ):
        raise ConfigError(
            "quick_filter_max_candidates must be >= "
            "deep_validation_max_candidates"
        )

    if config.source_concurrency > config.max_sources:
        raise ConfigError(
            "source_concurrency cannot exceed max_sources"
        )

    if (
        config.quick_filter_concurrency
        > config.quick_filter_max_candidates
    ):
        raise ConfigError(
            "quick_filter_concurrency cannot exceed "
            "quick_filter_max_candidates"
        )

    if (
        config.deep_validation_concurrency
        > config.deep_validation_max_candidates
    ):
        raise ConfigError(
            "deep_validation_concurrency cannot exceed "
            "deep_validation_max_candidates"
        )

    # Request timeout relationships.
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

    if (
        config.hls_segment_request_timeout_seconds
        > config.request_timeout_seconds
    ):
        raise ConfigError(
            "HLS segment timeout cannot exceed request_timeout_seconds"
        )

    # Discovery budget relationships. Redirects and retries are separately
    # bounded globally and remain subordinate to the total HTTP request cap.
    if (
        config.max_total_redirects + config.max_total_retries
        > config.total_http_request_budget
    ):
        raise ConfigError(
            "global redirect and retry budgets cannot exceed total HTTP request budget"
        )

    if config.max_channel_discovery_results > config.max_candidates:
        raise ConfigError(
            "channel discovery result limit cannot exceed candidate limit"
        )

    if config.max_sources * config.source_max_requests > config.total_http_request_budget:
        raise ConfigError(
            "source request capacity cannot exceed total HTTP request budget"
        )

    # Media resource budgets.
    if config.max_playlist_bytes > config.max_media_resource_bytes:
        raise ConfigError(
            "playlist byte limit cannot exceed media resource limit"
        )

    if (
        config.max_download_bytes_per_candidate
        < config.max_media_resource_bytes
    ):
        raise ConfigError(
            "per-candidate download budget must be >= one resource limit"
        )

    if (
        config.max_download_bytes_per_candidate
        > config.max_download_bytes_per_run
    ):
        raise ConfigError(
            "per-candidate budget cannot exceed per-run budget"
        )

    if (
        config.max_resources_per_candidate
        * config.max_media_resource_bytes
        < config.max_download_bytes_per_candidate
    ):
        raise ConfigError(
            "resource count and per-resource size cannot support "
            "per-candidate budget"
        )

    # HLS and validator deadlines.
    if config.hls_validation_seconds > config.line_deadline_seconds:
        raise ConfigError(
            "HLS validation time cannot exceed per-line deadline"
        )

    if (
        config.ffprobe_timeout_seconds
        + config.ffmpeg_timeout_seconds
        > config.validator_container_timeout_seconds
    ):
        raise ConfigError(
            "FFprobe and FFmpeg timeouts exceed container deadline"
        )

    if (
        config.validator_container_timeout_seconds
        > config.line_deadline_seconds
    ):
        raise ConfigError(
            "validator container timeout cannot exceed per-line deadline"
        )

    # Whole-run deadline must cover all stage budgets and cleanup.
    minimum_run_budget = (
        config.discovery_budget_seconds
        + config.quick_filter_budget_seconds
        + config.deep_validation_budget_seconds
        + config.cleanup_grace_seconds
    )

    if config.run_deadline_seconds < minimum_run_budget:
        raise ConfigError(
            "run_deadline_seconds is shorter than stage budgets plus cleanup"
        )

    if (
        config.deep_validation_budget_seconds
        < config.line_deadline_seconds
    ):
        raise ConfigError(
            "deep validation budget must allow at least one complete "
            "line deadline"
        )

    # Keep container limits within the verified precheck envelope.
    if config.validator_memory_bytes < 256 * 1024 * 1024:
        raise ConfigError(
            "validator_memory_bytes must be at least 256 MiB"
        )

    if config.validator_pids_limit < 8:
        raise ConfigError(
            "validator_pids_limit must be at least 8"
        )

    if config.validator_nofile_limit < 32:
        raise ConfigError(
            "validator_nofile_limit must be at least 32"
        )

    if config.validator_tmpfs_bytes < 16 * 1024 * 1024:
        raise ConfigError(
            "validator_tmpfs_bytes must be at least 16 MiB"
        )

    if config.validator_cpu_limit > 1.0:
        raise ConfigError(
            "validator_cpu_limit cannot exceed 1 CPU"
        )

    if config.validator_memory_bytes > 512 * 1024 * 1024:
        raise ConfigError(
            "validator_memory_bytes cannot exceed 512 MiB"
        )

    if config.validator_pids_limit > 64:
        raise ConfigError(
            "validator_pids_limit cannot exceed 64 PID"
        )

    if config.validator_tmpfs_bytes > 64 * 1024 * 1024:
        raise ConfigError(
            "validator_tmpfs_bytes cannot exceed 64 MiB"
        )

    if (
        config.task_ttl_seconds
        < config.validator_container_timeout_seconds
    ):
        raise ConfigError(
            "task_ttl_seconds must be >= validator_container_timeout_seconds"
        )

    if config.cleanup_grace_seconds < 5:
        raise ConfigError(
            "cleanup_grace_seconds must be at least 5 seconds"
        )

    if config.m3u_max_line_chars < 4096:
        raise ConfigError(
            "M3U line limit must accommodate models.py URL limit"
        )

    return config


def load_config(run_mode: str | None = None) -> Config:
    """Return validated configuration; FORMAL must be explicitly selected."""
    selected_mode = TEST_MODE if run_mode is None else run_mode
    return validate_config(Config(run_mode=selected_mode))


def config_as_dict(
    config: Config = DEFAULT_CONFIG,
) -> dict[str, object]:
    """Return a plain dictionary for diagnostics without mutating the config."""
    validate_config(config)

    return {
        item.name: getattr(config, item.name)
        for item in fields(config)
    }


# Fail fast if source-controlled defaults are internally consistent.
validate_config(DEFAULT_CONFIG)
validate_source_registry()
validate_user_channels()
