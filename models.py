"""Shared, dependency-free data contracts for China-IPTV-Auto V3.

This module validates data only. Network, filesystem, Docker, media probing,
cryptographic file verification and publication belong to their designated
components and the GitHub Actions host controller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
import re
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RELATIVE_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,512}$")


class ContractError(ValueError):
    """Raised when a value violates a V3 data contract."""


class RunMode(str, Enum):
    FORMAL = "formal"
    TEST = "test"


class LineStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NODE_ERROR = "NODE_ERROR"


class StageName(str, Enum):
    DISCOVERY = "discovery"
    NORMALIZATION = "normalization"
    QUICK_FILTER = "quick_filter"
    DEEP_VALIDATION = "deep_validation"
    PUBLISH = "publish"


STAGE_ORDER = (StageName.DISCOVERY, StageName.NORMALIZATION,
               StageName.QUICK_FILTER, StageName.DEEP_VALIDATION,
               StageName.PUBLISH)


class StageStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TaskType(str, Enum):
    MEDIA_PROBE = "media_probe"


class MetadataStatus(str, Enum):
    RELIABLE = "RELIABLE"
    MISSING = "MISSING"
    UNPARSEABLE = "UNPARSEABLE"


class ChannelIdentityStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    UNKNOWN = "UNKNOWN"


class ChannelMatchStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"


class ChannelMode(str, Enum):
    USER_CONFIGURED = "USER_CONFIGURED"
    AUTO_DISCOVERY = "AUTO_DISCOVERY"


class SourceStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BUDGET_LIMIT = "BUDGET_LIMIT"
    TIMED_OUT = "TIMED_OUT"
    PARTIAL = "PARTIAL"


class DiscoveryStopStatus(str, Enum):
    COMPLETED = "COMPLETED"
    BUDGET_LIMIT = "BUDGET_LIMIT"
    INTERRUPTED = "INTERRUPTED"


class DiscoveryStopReason(str, Enum):
    ALL_SOURCES_PROCESSED = "ALL_SOURCES_PROCESSED"
    MAX_ENABLED_SOURCES = "MAX_ENABLED_SOURCES"
    MAX_DISCOVERY_DURATION = "MAX_DISCOVERY_DURATION"
    MAX_CANDIDATES = "MAX_CANDIDATES"
    MAX_TOTAL_REQUESTS = "MAX_TOTAL_REQUESTS"
    MAX_TOTAL_REDIRECTS = "MAX_TOTAL_REDIRECTS"
    MAX_TOTAL_RETRIES = "MAX_TOTAL_RETRIES"
    MAX_RESOURCE_BYTES = "MAX_RESOURCE_BYTES"
    MAX_TOTAL_DOWNLOAD_BYTES = "MAX_TOTAL_DOWNLOAD_BYTES"
    MAX_CHANNEL_RESULTS = "MAX_CHANNEL_RESULTS"
    MAX_REPORT_BYTES = "MAX_REPORT_BYTES"
    UNEXPECTED_INTERRUPTION = "UNEXPECTED_INTERRUPTION"


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str
    retryable: bool = False
    component: str = ""

    def __post_init__(self) -> None:
        _nonempty(self.code, "error.code", 64)
        _nonempty(self.message, "error.message", 1000)
        _bool(self.retryable, "error.retryable")
        _string(self.component, "error.component", 64, True)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "retryable": self.retryable, "component": self.component}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ErrorInfo":
        _keys(value, {"code", "message", "retryable", "component"}, "error")
        return cls(**dict(value))


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    name: str
    url: str
    source_id: str
    group: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    logo: str = ""

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        _nonempty(self.name, "candidate.name", 256)
        _nonempty(self.url, "candidate.url", 4096)
        _id(self.source_id, "candidate.source_id")
        for key in ("group", "tvg_id", "tvg_name", "logo"):
            _string(getattr(self, key), f"candidate.{key}", 2048, True)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in
                ("candidate_id", "name", "url", "source_id", "group",
                 "tvg_id", "tvg_name", "logo")}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Candidate":
        keys = {"candidate_id", "name", "url", "source_id", "group",
                "tvg_id", "tvg_name", "logo"}
        _keys(value, keys, "candidate")
        return cls(**dict(value))


@dataclass(frozen=True)
class SourceChannelMetadata:
    """Original channel metadata supplied by one source for one candidate."""
    source_id: str
    source_channel_name: str
    source_channel_group: str
    source_entry_id: str | None
    candidate_id: str
    metadata_status: MetadataStatus

    def __post_init__(self) -> None:
        _id(self.source_id, "channel_metadata.source_id")
        _string(self.source_channel_name, "channel_metadata.source_channel_name", 256, True)
        _string(self.source_channel_group, "channel_metadata.source_channel_group", 128, True)
        if self.source_entry_id is not None:
            _nonempty(self.source_entry_id, "channel_metadata.source_entry_id", 256)
        _id(self.candidate_id, "channel_metadata.candidate_id")
        if not isinstance(self.metadata_status, MetadataStatus):
            raise ContractError("channel_metadata.metadata_status is invalid")
        if self.metadata_status is MetadataStatus.RELIABLE and not self.source_channel_name.strip():
            raise ContractError("reliable channel metadata requires a source channel name")
        if (self.metadata_status is MetadataStatus.MISSING
                and self.source_channel_name):
            raise ContractError("missing channel metadata must not contain a channel name")

    @property
    def identity_status(self) -> ChannelIdentityStatus:
        return (ChannelIdentityStatus.IDENTIFIED
                if self.metadata_status is MetadataStatus.RELIABLE
                else ChannelIdentityStatus.UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {"source_id": self.source_id,
                "source_channel_name": self.source_channel_name,
                "source_channel_group": self.source_channel_group,
                "source_entry_id": self.source_entry_id,
                "candidate_id": self.candidate_id,
                "metadata_status": self.metadata_status.value}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceChannelMetadata":
        _keys(value, {"source_id", "source_channel_name", "source_channel_group",
                      "source_entry_id", "candidate_id", "metadata_status"},
              "source_channel_metadata")
        try:
            status = MetadataStatus(value["metadata_status"])
        except (ValueError, TypeError) as exc:
            raise ContractError("channel metadata status is unsupported") from exc
        data = dict(value)
        data["metadata_status"] = status
        return cls(**data)


@dataclass(frozen=True)
class UserChannelConfig:
    """User-maintained display settings only; never contains URLs or IDs."""
    name: str
    group: str
    order: int

    def __post_init__(self) -> None:
        _nonempty(self.name, "user_channel.name", 256)
        if self.name != self.name.strip():
            raise ContractError("user_channel.name must not have outer whitespace")
        _string(self.group, "user_channel.group", 128, True)
        _int(self.order, "user_channel.order", 1)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "group": self.group, "order": self.order}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UserChannelConfig":
        _keys(value, {"name", "group", "order"}, "user_channel")
        return cls(**dict(value))


def validate_user_channel_config(
    channels: tuple[UserChannelConfig, ...],
) -> tuple[UserChannelConfig, ...]:
    """Validate the user list; an empty tuple deliberately means auto discovery."""
    _tuple_type(channels, UserChannelConfig, "user_channels")
    names: set[str] = set()
    orders: set[int] = set()
    for item in channels:
        normalized = item.name.strip().casefold()
        if normalized in names:
            raise ContractError("user channel names must be unique")
        if item.order in orders:
            raise ContractError("user channel order values must be unique")
        names.add(normalized)
        orders.add(item.order)
    return channels


def channel_mode_for(channels: tuple[UserChannelConfig, ...]) -> ChannelMode:
    validate_user_channel_config(channels)
    return (ChannelMode.USER_CONFIGURED if channels
            else ChannelMode.AUTO_DISCOVERY)


@dataclass(frozen=True)
class ChannelDiscoveryResult:
    """One current-run source-channel/candidate association and its validation."""
    source_metadata: SourceChannelMetadata
    identity_status: ChannelIdentityStatus
    line_status: LineStatus
    match_status: ChannelMatchStatus = ChannelMatchStatus.NOT_APPLICABLE
    matched_user_channel_name: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.source_metadata, SourceChannelMetadata):
            raise ContractError("discovery_result.source_metadata is invalid")
        if not isinstance(self.identity_status, ChannelIdentityStatus):
            raise ContractError("discovery_result.identity_status is invalid")
        if self.identity_status is not self.source_metadata.identity_status:
            raise ContractError("channel identity conflicts with source metadata reliability")
        if not isinstance(self.line_status, LineStatus):
            raise ContractError("discovery_result.line_status is invalid")
        if not isinstance(self.match_status, ChannelMatchStatus):
            raise ContractError("discovery_result.match_status is invalid")
        if self.matched_user_channel_name is not None:
            _nonempty(self.matched_user_channel_name,
                      "discovery_result.matched_user_channel_name", 256)
        _string(self.reason, "discovery_result.reason", 1000, True)
        if self.match_status is ChannelMatchStatus.MATCHED:
            if self.identity_status is not ChannelIdentityStatus.IDENTIFIED or not self.matched_user_channel_name:
                raise ContractError("MATCHED requires identified channel and matched user name")
        elif self.matched_user_channel_name is not None:
            raise ContractError("only MATCHED results may name a user channel")
        if self.match_status is ChannelMatchStatus.UNMATCHED and not self.reason:
            raise ContractError("UNMATCHED result requires a reason")
        if self.identity_status is ChannelIdentityStatus.UNKNOWN and not self.reason:
            raise ContractError("unknown channel identity requires an explanation")
        # Deliberately no rule promotes UNKNOWN to IDENTIFIED when line_status is PASS.

    @property
    def candidate_id(self) -> str:
        return self.source_metadata.candidate_id

    def to_dict(self) -> dict[str, Any]:
        return {"source_metadata": self.source_metadata.to_dict(),
                "identity_status": self.identity_status.value,
                "line_status": self.line_status.value,
                "match_status": self.match_status.value,
                "matched_user_channel_name": self.matched_user_channel_name,
                "reason": self.reason}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ChannelDiscoveryResult":
        _keys(value, {"source_metadata", "identity_status", "line_status",
                      "match_status", "matched_user_channel_name", "reason"},
              "channel_discovery_result")
        try:
            identity = ChannelIdentityStatus(value["identity_status"])
            line = LineStatus(value["line_status"])
            match = ChannelMatchStatus(value["match_status"])
        except (ValueError, TypeError) as exc:
            raise ContractError("channel discovery result contains unsupported status") from exc
        return cls(SourceChannelMetadata.from_dict(value["source_metadata"]),
                   identity, line, match, value["matched_user_channel_name"],
                   value["reason"])


@dataclass(frozen=True)
class SourceOutcome:
    source_id: str
    candidates: tuple[Candidate, ...] = ()
    error: ErrorInfo | None = None
    completed: bool = True
    channel_metadata: tuple[SourceChannelMetadata, ...] = ()
    status: SourceStatus | None = None
    requests_used: int = 0
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        _id(self.source_id, "source_id")
        _tuple_type(self.candidates, Candidate, "source.candidates")
        _tuple_type(self.channel_metadata, SourceChannelMetadata, "source.channel_metadata")
        if self.error is not None and not isinstance(self.error, ErrorInfo):
            raise ContractError("source.error must be ErrorInfo or None")
        _bool(self.completed, "source.completed")
        _int(self.requests_used, "source.requests_used", 0)
        if (isinstance(self.elapsed_seconds, bool) or
            not isinstance(self.elapsed_seconds, (int, float)) or
            not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0):
            raise ContractError("source.elapsed_seconds must be finite and non-negative")
        selected = self.status
        if selected is None:
            selected = (SourceStatus.FAILED if self.completed and self.error is not None else
                        SourceStatus.SUCCEEDED if self.completed else SourceStatus.PARTIAL)
            object.__setattr__(self, "status", selected)
        if not isinstance(selected, SourceStatus):
            raise ContractError("source.status is invalid")
        if selected in (SourceStatus.SUCCEEDED, SourceStatus.FAILED) and not self.completed:
            raise ContractError("completed source status requires completed=True")
        if selected in (SourceStatus.SKIPPED, SourceStatus.BUDGET_LIMIT,
                        SourceStatus.TIMED_OUT, SourceStatus.PARTIAL) and self.completed:
            raise ContractError("incomplete source status requires completed=False")
        if selected is SourceStatus.FAILED and self.error is None:
            raise ContractError("failed source requires error details")
        if selected is SourceStatus.SUCCEEDED and self.error is not None:
            raise ContractError("successful source cannot contain an error")
        if selected is SourceStatus.SKIPPED and (
            self.error is not None or self.requests_used or self.candidates or self.channel_metadata
        ):
            raise ContractError("skipped source must not contain processed data or an error")
        candidate_map = {c.candidate_id: c for c in self.candidates}
        if len(candidate_map) != len(self.candidates):
            raise ContractError("source contains duplicate candidate IDs")
        metadata_candidate_ids = [m.candidate_id for m in self.channel_metadata]
        if len(metadata_candidate_ids) != len(set(metadata_candidate_ids)):
            raise ContractError("source contains duplicate channel metadata for a candidate")
        for metadata in self.channel_metadata:
            if metadata.source_id != self.source_id:
                raise ContractError("channel metadata source_id mismatch")
            candidate = candidate_map.get(metadata.candidate_id)
            if candidate is None or candidate.source_id != self.source_id:
                raise ContractError("channel metadata candidate association mismatch")

    def identity_status_for(self, candidate_id: str) -> ChannelIdentityStatus:
        """Missing metadata is explicitly treated as UNKNOWN, never inferred from URL/name."""
        _id(candidate_id, "candidate_id")
        for metadata in self.channel_metadata:
            if metadata.candidate_id == candidate_id:
                return metadata.identity_status
        if any(candidate.candidate_id == candidate_id for candidate in self.candidates):
            return ChannelIdentityStatus.UNKNOWN
        raise ContractError("candidate_id does not belong to this source outcome")

    def to_dict(self) -> dict[str, Any]:
        return {"source_id": self.source_id,
                "candidates": [x.to_dict() for x in self.candidates],
                "error": self.error.to_dict() if self.error else None,
                "completed": self.completed,
                "channel_metadata": [x.to_dict() for x in self.channel_metadata],
                "status": self.status.value,
                "requests_used": self.requests_used,
                "elapsed_seconds": self.elapsed_seconds}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceOutcome":
        # Older serialized records are accepted; newly serialized records always
        # include the explicit source disposition and usage counters.
        base = {"source_id", "candidates", "error", "completed"}
        allowed = base | {"channel_metadata", "status", "requests_used", "elapsed_seconds"}
        _mapping(value, "source_outcome")
        if not base.issubset(value) or set(value) - allowed:
            _keys(value, allowed, "source_outcome")
        if not isinstance(value["candidates"], list):
            raise ContractError("source.candidates must be a list")
        metadata = value.get("channel_metadata", [])
        if not isinstance(metadata, list):
            raise ContractError("source.channel_metadata must be a list")
        error = ErrorInfo.from_dict(value["error"]) if value["error"] is not None else None
        status_value = value.get("status")
        if status_value is not None:
            try:
                status_value = SourceStatus(status_value)
            except (ValueError, TypeError) as exc:
                raise ContractError("source.status is unsupported") from exc
        return cls(value["source_id"],
                   tuple(Candidate.from_dict(x) for x in value["candidates"]),
                   error, value["completed"],
                   tuple(SourceChannelMetadata.from_dict(x) for x in metadata),
                   status_value, value.get("requests_used", 0),
                   value.get("elapsed_seconds", 0.0))


@dataclass(frozen=True)
class DiscoveryBudgetLimits:
    """Per-run discovery ceilings; concrete values are supplied by config.py."""
    max_sources: int
    source_timeout_seconds: int
    source_max_requests: int
    discovery_budget_seconds: int
    max_candidates: int
    total_http_request_budget: int
    max_total_redirects: int
    max_total_retries: int
    max_media_resource_bytes: int
    max_download_bytes_per_run: int
    max_channel_discovery_results: int
    max_discovery_report_bytes: int

    def __post_init__(self) -> None:
        zero_allowed = {"max_total_redirects", "max_total_retries"}
        for name in self.__dataclass_fields__:
            _int(getattr(self, name), f"discovery_limits.{name}",
                 0 if name in zero_allowed else 1)
        if self.max_media_resource_bytes > self.max_download_bytes_per_run:
            raise ContractError("single-resource limit cannot exceed run download limit")

    def to_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiscoveryBudgetLimits":
        _keys(value, set(cls.__dataclass_fields__), "discovery_budget_limits")
        return cls(**dict(value))


@dataclass(frozen=True)
class DiscoveryBudgetUsage:
    """Actual per-run usage and source outcome counts."""
    sources_processed: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    sources_skipped: int = 0
    candidates_collected: int = 0
    requests_used: int = 0
    redirects_used: int = 0
    retries_used: int = 0
    downloaded_bytes: int = 0
    largest_resource_bytes: int = 0
    channel_results_count: int = 0
    report_bytes: int = 0
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name == "elapsed_seconds":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ContractError("discovery elapsed_seconds must be finite and non-negative")
            else:
                _int(value, f"discovery_usage.{name}", 0)
        if self.sources_succeeded + self.sources_failed != self.sources_processed:
            raise ContractError("every processed source must be counted as succeeded or failed")
        if self.largest_resource_bytes > self.downloaded_bytes:
            raise ContractError("largest resource cannot exceed total downloaded bytes")

    def validate_against(self, limits: DiscoveryBudgetLimits) -> None:
        if not isinstance(limits, DiscoveryBudgetLimits):
            raise ContractError("discovery limits are required")
        pairs = {
            "sources_processed": "max_sources",
            "candidates_collected": "max_candidates",
            "requests_used": "total_http_request_budget",
            "redirects_used": "max_total_redirects",
            "retries_used": "max_total_retries",
            "largest_resource_bytes": "max_media_resource_bytes",
            "downloaded_bytes": "max_download_bytes_per_run",
            "channel_results_count": "max_channel_discovery_results",
            "report_bytes": "max_discovery_report_bytes",
        }
        for used, maximum in pairs.items():
            if getattr(self, used) > getattr(limits, maximum):
                raise ContractError(f"discovery usage exceeds {maximum}")
        if self.elapsed_seconds > limits.discovery_budget_seconds:
            raise ContractError("discovery usage exceeds discovery duration budget")

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiscoveryBudgetUsage":
        _keys(value, set(cls.__dataclass_fields__), "discovery_budget_usage")
        return cls(**dict(value))


@dataclass(frozen=True)
class DiscoveryBudgetResult:
    limits: DiscoveryBudgetLimits
    usage: DiscoveryBudgetUsage
    stop_status: DiscoveryStopStatus
    stop_reason: DiscoveryStopReason
    unprocessed_data: bool

    def __post_init__(self) -> None:
        if not isinstance(self.limits, DiscoveryBudgetLimits) or not isinstance(self.usage, DiscoveryBudgetUsage):
            raise ContractError("discovery budget result requires limits and usage records")
        if not isinstance(self.stop_status, DiscoveryStopStatus) or not isinstance(self.stop_reason, DiscoveryStopReason):
            raise ContractError("discovery budget stop status/reason is invalid")
        _bool(self.unprocessed_data, "discovery_budget.unprocessed_data")
        self.usage.validate_against(self.limits)
        if self.stop_status is DiscoveryStopStatus.COMPLETED:
            if self.stop_reason is not DiscoveryStopReason.ALL_SOURCES_PROCESSED:
                raise ContractError("completed discovery must use ALL_SOURCES_PROCESSED")
            if self.unprocessed_data:
                raise ContractError("completed discovery cannot report unprocessed data")
        elif self.stop_status is DiscoveryStopStatus.BUDGET_LIMIT:
            if self.stop_reason in (DiscoveryStopReason.ALL_SOURCES_PROCESSED,
                                    DiscoveryStopReason.UNEXPECTED_INTERRUPTION):
                raise ContractError("budget stop requires a budget-limit reason")
        elif self.stop_reason is not DiscoveryStopReason.UNEXPECTED_INTERRUPTION:
            raise ContractError("interrupted discovery requires UNEXPECTED_INTERRUPTION")
        elif not self.unprocessed_data:
            raise ContractError("interrupted discovery must report unprocessed data")
        reached = {
            DiscoveryStopReason.MAX_ENABLED_SOURCES: self.usage.sources_processed >= self.limits.max_sources,
            DiscoveryStopReason.MAX_DISCOVERY_DURATION: self.usage.elapsed_seconds >= self.limits.discovery_budget_seconds,
            DiscoveryStopReason.MAX_CANDIDATES: self.usage.candidates_collected >= self.limits.max_candidates,
            DiscoveryStopReason.MAX_TOTAL_REQUESTS: self.usage.requests_used >= self.limits.total_http_request_budget,
            DiscoveryStopReason.MAX_TOTAL_REDIRECTS: self.usage.redirects_used >= self.limits.max_total_redirects,
            DiscoveryStopReason.MAX_TOTAL_RETRIES: self.usage.retries_used >= self.limits.max_total_retries,
            DiscoveryStopReason.MAX_RESOURCE_BYTES: self.usage.largest_resource_bytes >= self.limits.max_media_resource_bytes,
            DiscoveryStopReason.MAX_TOTAL_DOWNLOAD_BYTES: self.usage.downloaded_bytes >= self.limits.max_download_bytes_per_run,
            DiscoveryStopReason.MAX_CHANNEL_RESULTS: self.usage.channel_results_count >= self.limits.max_channel_discovery_results,
            DiscoveryStopReason.MAX_REPORT_BYTES: self.usage.report_bytes >= self.limits.max_discovery_report_bytes,
        }
        if self.stop_reason in reached and not reached[self.stop_reason]:
            raise ContractError("discovery stop reason does not match reached budget")

    @property
    def normal_stop(self) -> bool:
        return self.stop_status in (DiscoveryStopStatus.COMPLETED, DiscoveryStopStatus.BUDGET_LIMIT)

    def to_dict(self) -> dict[str, Any]:
        return {"limits": self.limits.to_dict(), "usage": self.usage.to_dict(),
                "stop_status": self.stop_status.value, "stop_reason": self.stop_reason.value,
                "unprocessed_data": self.unprocessed_data}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DiscoveryBudgetResult":
        _keys(value, {"limits", "usage", "stop_status", "stop_reason", "unprocessed_data"},
              "discovery_budget_result")
        try:
            status = DiscoveryStopStatus(value["stop_status"])
            reason = DiscoveryStopReason(value["stop_reason"])
        except (ValueError, TypeError) as exc:
            raise ContractError("discovery stop status/reason is unsupported") from exc
        return cls(DiscoveryBudgetLimits.from_dict(value["limits"]),
                   DiscoveryBudgetUsage.from_dict(value["usage"]), status, reason,
                   value["unprocessed_data"])


@dataclass(frozen=True)
class TaskIdentity:
    run_id: str
    run_attempt: int
    task_id: str
    candidate_id: str
    resource_id: str

    def __post_init__(self) -> None:
        _id(self.run_id, "run_id")
        _int(self.run_attempt, "run_attempt", 1)
        _id(self.task_id, "task_id")
        _id(self.candidate_id, "candidate_id")
        _id(self.resource_id, "resource_id")

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in
                ("run_id", "run_attempt", "task_id", "candidate_id", "resource_id")}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskIdentity":
        _keys(value, {"run_id", "run_attempt", "task_id", "candidate_id", "resource_id"}, "task_identity")
        return cls(**dict(value))

    def matches(self, other: "TaskIdentity") -> bool:
        return isinstance(other, TaskIdentity) and self == other


@dataclass(frozen=True)
class TaskRequest:
    schema_version: str
    identity: TaskIdentity
    task_type: TaskType
    created_at: str
    deadline: str

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        if not isinstance(self.identity, TaskIdentity) or not isinstance(self.task_type, TaskType):
            raise ContractError("task identity or type is invalid")
        _timestamp(self.created_at, "task.created_at")
        _timestamp(self.deadline, "task.deadline")
        if _dt(self.deadline) <= _dt(self.created_at):
            raise ContractError("task.deadline must be later than task.created_at")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, **self.identity.to_dict(),
                "task_type": self.task_type.value, "created_at": self.created_at,
                "deadline": self.deadline}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskRequest":
        keys = {"schema_version", "run_id", "run_attempt", "task_id", "candidate_id",
                "resource_id", "task_type", "created_at", "deadline"}
        _keys(value, keys, "task_request")
        identity = TaskIdentity.from_dict({k: value[k] for k in
            ("run_id", "run_attempt", "task_id", "candidate_id", "resource_id")})
        try:
            kind = TaskType(value["task_type"])
        except (ValueError, TypeError) as exc:
            raise ContractError("task.task_type is unsupported") from exc
        return cls(value["schema_version"], identity, kind, value["created_at"], value["deadline"])


@dataclass(frozen=True)
class MediaFileEntry:
    schema_version: str
    identity: TaskIdentity
    file_id: str
    relative_path: str
    content_type: str
    actual_size: int
    sha256: str
    complete: bool
    created_at: str

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        if not isinstance(self.identity, TaskIdentity):
            raise ContractError("media.identity must be TaskIdentity")
        _id(self.file_id, "media.file_id")
        _relative_path(self.relative_path)
        _nonempty(self.content_type, "media.content_type", 128)
        _int(self.actual_size, "media.actual_size", 1)
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256):
            raise ContractError("media.sha256 must be 64 lowercase hexadecimal characters")
        _bool(self.complete, "media.complete")
        if not self.complete:
            raise ContractError("incomplete media cannot enter a validation manifest")
        _timestamp(self.created_at, "media.created_at")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, **self.identity.to_dict(),
                "file_id": self.file_id, "relative_path": self.relative_path,
                "content_type": self.content_type, "actual_size": self.actual_size,
                "sha256": self.sha256, "complete": self.complete, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MediaFileEntry":
        keys = {"schema_version", "run_id", "run_attempt", "task_id", "candidate_id",
                "resource_id", "file_id", "relative_path", "content_type", "actual_size",
                "sha256", "complete", "created_at"}
        _keys(value, keys, "media_file_entry")
        identity = TaskIdentity.from_dict({k: value[k] for k in
            ("run_id", "run_attempt", "task_id", "candidate_id", "resource_id")})
        return cls(value["schema_version"], identity, value["file_id"], value["relative_path"],
                   value["content_type"], value["actual_size"], value["sha256"],
                   value["complete"], value["created_at"])


@dataclass(frozen=True)
class MediaManifest:
    schema_version: str
    identity: TaskIdentity
    entries: tuple[MediaFileEntry, ...]
    created_at: str

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        if not isinstance(self.identity, TaskIdentity):
            raise ContractError("manifest.identity must be TaskIdentity")
        _tuple_type(self.entries, MediaFileEntry, "manifest.entries")
        if not self.entries:
            raise ContractError("manifest.entries must not be empty")
        _timestamp(self.created_at, "manifest.created_at")
        ids: set[str] = set(); paths: set[str] = set()
        for entry in self.entries:
            if not self.identity.matches(entry.identity):
                raise ContractError("manifest entry task identity mismatch")
            if entry.file_id in ids or entry.relative_path in paths:
                raise ContractError("manifest contains duplicate file_id or path")
            ids.add(entry.file_id); paths.add(entry.relative_path)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, **self.identity.to_dict(),
                "entries": [x.to_dict() for x in self.entries], "created_at": self.created_at}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MediaManifest":
        keys = {"schema_version", "run_id", "run_attempt", "task_id", "candidate_id",
                "resource_id", "entries", "created_at"}
        _keys(value, keys, "media_manifest")
        if not isinstance(value["entries"], list):
            raise ContractError("manifest.entries must be a list")
        identity = TaskIdentity.from_dict({k: value[k] for k in
            ("run_id", "run_attempt", "task_id", "candidate_id", "resource_id")})
        return cls(value["schema_version"], identity,
                   tuple(MediaFileEntry.from_dict(x) for x in value["entries"]), value["created_at"])


@dataclass(frozen=True)
class ProbeEvidence:
    ffprobe_exit_code: int
    ffmpeg_exit_code: int
    media_bytes_read: int
    packets_read: int
    streams: tuple[str, ...]
    probe_completed: bool
    playback_seconds: float

    def __post_init__(self) -> None:
        for key in ("ffprobe_exit_code", "ffmpeg_exit_code", "media_bytes_read", "packets_read"):
            _int(getattr(self, key), f"evidence.{key}", 0)
        _tuple_str(self.streams, "evidence.streams", 64)
        _bool(self.probe_completed, "evidence.probe_completed")
        if (isinstance(self.playback_seconds, bool) or
            not isinstance(self.playback_seconds, (int, float)) or
            not math.isfinite(self.playback_seconds) or self.playback_seconds < 0):
            raise ContractError("evidence.playback_seconds must be finite and non-negative")

    @property
    def sufficient_for_pass(self) -> bool:
        return (self.probe_completed and self.ffprobe_exit_code == 0 and
                self.ffmpeg_exit_code == 0 and self.media_bytes_read > 0 and
                self.packets_read > 0 and bool(self.streams) and self.playback_seconds > 0)

    def to_dict(self) -> dict[str, Any]:
        return {"ffprobe_exit_code": self.ffprobe_exit_code, "ffmpeg_exit_code": self.ffmpeg_exit_code,
                "media_bytes_read": self.media_bytes_read, "packets_read": self.packets_read,
                "streams": list(self.streams), "probe_completed": self.probe_completed,
                "playback_seconds": self.playback_seconds}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProbeEvidence":
        keys = {"ffprobe_exit_code", "ffmpeg_exit_code", "media_bytes_read", "packets_read",
                "streams", "probe_completed", "playback_seconds"}
        _keys(value, keys, "probe_evidence")
        if not isinstance(value["streams"], list):
            raise ContractError("evidence.streams must be a list")
        return cls(value["ffprobe_exit_code"], value["ffmpeg_exit_code"],
                   value["media_bytes_read"], value["packets_read"], tuple(value["streams"]),
                   value["probe_completed"], value["playback_seconds"])


@dataclass(frozen=True)
class ContainerResult:
    schema_version: str
    identity: TaskIdentity
    validator_image_digest: str
    exit_code: int
    started_at: str
    finished_at: str
    evidence: ProbeEvidence | None = None
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        _schema(self.schema_version)
        if not isinstance(self.identity, TaskIdentity):
            raise ContractError("container_result.identity must be TaskIdentity")
        _nonempty(self.validator_image_digest, "validator_image_digest", 256)
        _int(self.exit_code, "container_result.exit_code", 0)
        _timestamp(self.started_at, "container_result.started_at")
        _timestamp(self.finished_at, "container_result.finished_at")
        if _dt(self.finished_at) < _dt(self.started_at):
            raise ContractError("container result finished_at precedes started_at")
        if self.evidence is not None and not isinstance(self.evidence, ProbeEvidence):
            raise ContractError("container_result.evidence must be ProbeEvidence or None")
        if self.error is not None and not isinstance(self.error, ErrorInfo):
            raise ContractError("container_result.error must be ErrorInfo or None")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, **self.identity.to_dict(),
                "validator_image_digest": self.validator_image_digest, "exit_code": self.exit_code,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "evidence": self.evidence.to_dict() if self.evidence else None,
                "error": self.error.to_dict() if self.error else None}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContainerResult":
        keys = {"schema_version", "run_id", "run_attempt", "task_id", "candidate_id",
                "resource_id", "validator_image_digest", "exit_code", "started_at",
                "finished_at", "evidence", "error"}
        _keys(value, keys, "container_result")
        identity = TaskIdentity.from_dict({k: value[k] for k in
            ("run_id", "run_attempt", "task_id", "candidate_id", "resource_id")})
        evidence = ProbeEvidence.from_dict(value["evidence"]) if value["evidence"] is not None else None
        error = ErrorInfo.from_dict(value["error"]) if value["error"] is not None else None
        return cls(value["schema_version"], identity, value["validator_image_digest"],
                   value["exit_code"], value["started_at"], value["finished_at"], evidence, error)


@dataclass(frozen=True)
class HostVerification:
    identity: TaskIdentity
    result_sha256: str
    image_digest_verified: bool
    exit_code_verified: bool
    output_bounded: bool
    identity_verified: bool
    schema_verified: bool

    def __post_init__(self) -> None:
        if not isinstance(self.identity, TaskIdentity):
            raise ContractError("host_verification.identity must be TaskIdentity")
        if not isinstance(self.result_sha256, str) or not _SHA256_RE.fullmatch(self.result_sha256):
            raise ContractError("host_verification.result_sha256 must be lowercase SHA-256")
        for key in ("image_digest_verified", "exit_code_verified", "output_bounded",
                    "identity_verified", "schema_verified"):
            _bool(getattr(self, key), f"host_verification.{key}")

    @property
    def trusted(self) -> bool:
        return all((self.image_digest_verified, self.exit_code_verified,
                    self.output_bounded, self.identity_verified, self.schema_verified))


@dataclass(frozen=True)
class LineResult:
    candidate: Candidate
    status: LineStatus
    reason: str
    evidence: ProbeEvidence | None = None
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, Candidate) or not isinstance(self.status, LineStatus):
            raise ContractError("line result candidate or status is invalid")
        _nonempty(self.reason, "line_result.reason", 1000)
        if self.evidence is not None and not isinstance(self.evidence, ProbeEvidence):
            raise ContractError("line_result.evidence must be ProbeEvidence or None")
        if self.error is not None and not isinstance(self.error, ErrorInfo):
            raise ContractError("line_result.error must be ErrorInfo or None")
        if self.status is LineStatus.PASS and (self.evidence is None or not self.evidence.sufficient_for_pass):
            raise ContractError("PASS requires sufficient successful media probe evidence")
        if self.status is LineStatus.NODE_ERROR and self.error is None:
            raise ContractError("NODE_ERROR requires error details")

    def to_dict(self) -> dict[str, Any]:
        return {"candidate": self.candidate.to_dict(), "status": self.status.value,
                "reason": self.reason, "evidence": self.evidence.to_dict() if self.evidence else None,
                "error": self.error.to_dict() if self.error else None}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineResult":
        _keys(value, {"candidate", "status", "reason", "evidence", "error"}, "line_result")
        try:
            status = LineStatus(value["status"])
        except (ValueError, TypeError) as exc:
            raise ContractError("line_result.status is unsupported") from exc
        evidence = ProbeEvidence.from_dict(value["evidence"]) if value["evidence"] is not None else None
        error = ErrorInfo.from_dict(value["error"]) if value["error"] is not None else None
        return cls(Candidate.from_dict(value["candidate"]), status, value["reason"], evidence, error)


@dataclass(frozen=True)
class StageResult:
    stage: StageName
    status: StageStatus
    started_at: str | None = None
    finished_at: str | None = None
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, StageName) or not isinstance(self.status, StageStatus):
            raise ContractError("stage result has invalid stage or status")
        if self.started_at is not None: _timestamp(self.started_at, "stage.started_at")
        if self.finished_at is not None: _timestamp(self.finished_at, "stage.finished_at")
        if self.started_at and self.finished_at and _dt(self.finished_at) < _dt(self.started_at):
            raise ContractError("stage finished_at precedes started_at")
        if self.error is not None and not isinstance(self.error, ErrorInfo):
            raise ContractError("stage.error must be ErrorInfo or None")
        if self.status is StageStatus.FAILED and self.error is None:
            raise ContractError("failed stage requires error details")

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage.value, "status": self.status.value,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "error": self.error.to_dict() if self.error else None}


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    run_attempt: int
    mode: RunMode
    stages: tuple[StageResult, ...]
    line_results: tuple[LineResult, ...]
    critical_error: bool = False
    # None preserves the original serialization contract for older callers.
    source_outcomes: tuple[SourceOutcome, ...] | None = None
    channel_discovery_results: tuple[ChannelDiscoveryResult, ...] | None = None
    discovery_budget: DiscoveryBudgetResult | None = None

    def __post_init__(self) -> None:
        _id(self.run_id, "run_id")
        _int(self.run_attempt, "run_attempt", 1)
        if not isinstance(self.mode, RunMode): raise ContractError("run.mode must be RunMode")
        _tuple_type(self.stages, StageResult, "run.stages")
        _tuple_type(self.line_results, LineResult, "run.line_results")
        _bool(self.critical_error, "run.critical_error")
        if self.source_outcomes is not None:
            _tuple_type(self.source_outcomes, SourceOutcome, "run.source_outcomes")
            source_ids = [x.source_id for x in self.source_outcomes]
            if len(source_ids) != len(set(source_ids)):
                raise ContractError("run contains duplicate source outcomes")
        if self.channel_discovery_results is not None:
            _tuple_type(self.channel_discovery_results, ChannelDiscoveryResult,
                        "run.channel_discovery_results")
            discovery_ids = [x.candidate_id for x in self.channel_discovery_results]
            if len(discovery_ids) != len(set(discovery_ids)):
                raise ContractError("run contains duplicate channel discovery candidate results")
        if self.discovery_budget is not None and not isinstance(self.discovery_budget, DiscoveryBudgetResult):
            raise ContractError("run.discovery_budget must be DiscoveryBudgetResult or None")
        if self.channel_discovery_results is not None and self.source_outcomes is None:
            raise ContractError("channel discovery results require source outcomes")
        if self.channel_discovery_results is not None and self.discovery_budget is None:
            raise ContractError("channel discovery results require discovery budget summary")
        if self.source_outcomes is not None and self.discovery_budget is None:
            raise ContractError("source outcomes require discovery budget summary")
        if self.source_outcomes is not None and self.channel_discovery_results is not None:
            metadata_pairs = {(m.source_id, m.candidate_id, m)
                              for outcome in self.source_outcomes for m in outcome.channel_metadata}
            for result in self.channel_discovery_results:
                marker = (result.source_metadata.source_id, result.candidate_id,
                          result.source_metadata)
                if marker not in metadata_pairs:
                    raise ContractError("channel discovery result is not backed by a source outcome")
        if self.source_outcomes is not None and self.discovery_budget is not None:
            outcomes = self.source_outcomes
            limits = self.discovery_budget.limits
            usage = self.discovery_budget.usage
            for outcome in outcomes:
                if outcome.requests_used > limits.source_max_requests:
                    raise ContractError("source outcome exceeds per-source request budget")
                if outcome.status is SourceStatus.BUDGET_LIMIT and outcome.requests_used < limits.source_max_requests:
                    raise ContractError("source budget-limit status does not match request count")
            processed = sum(x.status is not SourceStatus.SKIPPED for x in outcomes)
            succeeded = sum(x.status is SourceStatus.SUCCEEDED for x in outcomes)
            failed = sum(x.status in (SourceStatus.FAILED, SourceStatus.BUDGET_LIMIT,
                                      SourceStatus.TIMED_OUT, SourceStatus.PARTIAL)
                         for x in outcomes)
            skipped = sum(x.status is SourceStatus.SKIPPED for x in outcomes)
            if (processed, succeeded, failed, skipped) != (
                usage.sources_processed, usage.sources_succeeded,
                usage.sources_failed, usage.sources_skipped
            ):
                raise ContractError("source outcomes do not match discovery budget source counts")
        if self.channel_discovery_results is not None and self.discovery_budget is not None:
            if len(self.channel_discovery_results) != self.discovery_budget.usage.channel_results_count:
                raise ContractError("channel discovery results do not match budget result count")
        if self.channel_discovery_results is not None:
            line_map = {x.candidate.candidate_id: x for x in self.line_results}
            if len(line_map) != len(self.line_results):
                raise ContractError("run contains duplicate line results for a candidate")
            for item in self.channel_discovery_results:
                line = line_map.get(item.candidate_id)
                if item.line_status is LineStatus.PASS and (line is None or line.status is not LineStatus.PASS):
                    raise ContractError("channel PASS result lacks matching PASS line result")
                if line is not None and item.line_status is not line.status:
                    raise ContractError("channel discovery line status mismatch")
        if (self.discovery_budget is not None and
            self.discovery_budget.stop_status is DiscoveryStopStatus.INTERRUPTED and
            not self.critical_error):
            raise ContractError("unexpected discovery interruption must be a critical run error")
        names = [x.stage for x in self.stages]
        if len(names) != len(set(names)) or names != sorted(names, key=STAGE_ORDER.index):
            raise ContractError("run stages are duplicated or not in fixed five-step order")

    def to_dict(self) -> dict[str, Any]:
        data = {"run_id": self.run_id, "run_attempt": self.run_attempt,
                "mode": self.mode.value, "stages": [x.to_dict() for x in self.stages],
                "line_results": [x.to_dict() for x in self.line_results],
                "critical_error": self.critical_error}
        if self.source_outcomes is not None:
            data["source_outcomes"] = [x.to_dict() for x in self.source_outcomes]
        if self.channel_discovery_results is not None:
            data["channel_discovery_results"] = [x.to_dict() for x in self.channel_discovery_results]
        if self.discovery_budget is not None:
            data["discovery_budget"] = self.discovery_budget.to_dict()
        return data


@dataclass(frozen=True)
class PublishDecision:
    eligible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _bool(self.eligible, "publish.eligible")
        _tuple_str(self.reasons, "publish.reasons", 1000)
        if self.eligible and self.reasons:
            raise ContractError("eligible publish decision cannot contain rejection reasons")
        if not self.eligible and not self.reasons:
            raise ContractError("rejected publish decision must explain why")


def validate_container_result(result: ContainerResult, expected: TaskIdentity,
                              host: HostVerification) -> None:
    """Raise unless the host-verified result matches the expected task."""
    if not isinstance(result, ContainerResult) or not isinstance(expected, TaskIdentity):
        raise ContractError("invalid result or expected identity")
    if not isinstance(host, HostVerification) or not host.trusted:
        raise ContractError("container result has not passed host verification")
    if not result.identity.matches(expected) or not host.identity.matches(expected):
        raise ContractError("task identity mismatch")
    if result.exit_code != 0: raise ContractError("container exit code is not zero")
    if result.error is not None: raise ContractError("container reported an error")
    if result.evidence is None: raise ContractError("container result has no media evidence")


def _mapping(value: Any, name: str) -> None:
    if not isinstance(value, Mapping): raise ContractError(f"{name} must be a mapping")


def _keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    _mapping(value, name)
    missing, extra = expected - set(value), set(value) - expected
    if missing or extra:
        raise ContractError(f"{name} keys mismatch; missing={sorted(missing)}, extra={sorted(extra)}")


def _string(value: Any, name: str, maximum: int, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()):
        raise ContractError(f"{name} must be a {'possibly empty ' if allow_empty else 'non-empty '}string up to {maximum} characters")


def _nonempty(value: Any, name: str, maximum: int) -> None:
    _string(value, name, maximum, False)


def _bool(value: Any, name: str) -> None:
    if not isinstance(value, bool): raise ContractError(f"{name} must be bool")


def _int(value: Any, name: str, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{name} must be an integer >= {minimum}")


def _id(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ContractError(f"{name} is not a valid identifier")


def _schema(value: Any) -> None:
    if value != SCHEMA_VERSION: raise ContractError(f"unsupported schema_version: {value!r}")


def _relative_path(value: Any) -> None:
    if not isinstance(value, str) or not _RELATIVE_PATH_RE.fullmatch(value):
        raise ContractError("media.relative_path must be a safe relative path")
    if value.startswith("/") or "\\" in value or any(p in ("", ".", "..") for p in value.split("/")):
        raise ContractError("media.relative_path contains traversal or invalid segments")
    if re.match(r"^[A-Za-z]:", value): raise ContractError("media.relative_path must not be a drive path")


def _timestamp(value: Any, name: str) -> None:
    _dt(value, name)


def _dt(value: Any, name: str = "timestamp") -> datetime:
    if not isinstance(value, str): raise ContractError(f"{name} must be an ISO-8601 string")
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc: raise ContractError(f"{name} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{name} must include a timezone")
    return parsed


def _tuple_type(value: Any, expected: type, name: str) -> None:
    if not isinstance(value, tuple) or any(not isinstance(x, expected) for x in value):
        raise ContractError(f"{name} must be a tuple of {expected.__name__}")


def _tuple_str(value: Any, name: str, maximum: int) -> None:
    if not isinstance(value, tuple) or any(not isinstance(x, str) or not x or len(x) > maximum for x in value):
        raise ContractError(f"{name} must be a tuple of non-empty strings up to {maximum} characters")
