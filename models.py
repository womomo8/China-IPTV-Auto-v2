"""Shared, dependency-free data contracts for China-IPTV-Auto V3.

This module validates data shape and identity only. It does not perform network
access, filesystem access, Docker operations, media probing, or PASS decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
import math
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ContractError(ValueError):
    """Raised when data does not satisfy a shared V3 contract."""


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


class StageStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TaskType(str, Enum):
    MEDIA_PROBE = "media_probe"


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
        _string(self.component, "error.component", 64, allow_empty=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "component": self.component,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ErrorInfo":
        _mapping(value, "error")
        _only_keys(
            value,
            {"code", "message", "retryable", "component"},
            "error",
        )
        return cls(**dict(value))


@dataclass(frozen=True)
class Candidate:
    """A discovered IPTV candidate. URL is business data, never a container task field."""

    candidate_id: str
    name: str
    url: str
    source_id: str
    group: str = ""
    tvg_id: str = ""
    tvg_name: str = ""
    logo: str = ""

    def __post_init__(self) -> None:
        _identifier(self.candidate_id, "candidate_id")
        _nonempty(self.name, "candidate.name", 256)
        _nonempty(self.url, "candidate.url", 4096)
        _identifier(self.source_id, "candidate.source_id")

        for key in ("group", "tvg_id", "tvg_name", "logo"):
            _string(
                getattr(self, key),
                f"candidate.{key}",
                2048,
                allow_empty=True,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "url": self.url,
            "source_id": self.source_id,
            "group": self.group,
            "tvg_id": self.tvg_id,
            "tvg_name": self.tvg_name,
            "logo": self.logo,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Candidate":
        _mapping(value, "candidate")
        _only_keys(
            value,
            {
                "candidate_id",
                "name",
                "url",
                "source_id",
                "group",
                "tvg_id",
                "tvg_name",
                "logo",
            },
            "candidate",
        )
        return cls(**dict(value))


@dataclass(frozen=True)
class SourceOutcome:
    source_id: str
    candidates: tuple[Candidate, ...] = ()
    error: ErrorInfo | None = None
    completed: bool = True

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _tuple_of(self.candidates, Candidate, "source.candidates")

        if self.error is not None and not isinstance(self.error, ErrorInfo):
            raise ContractError("source.error must be ErrorInfo or None")

        _bool(self.completed, "source.completed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "candidates": [item.to_dict() for item in self.candidates],
            "error": self.error.to_dict() if self.error else None,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceOutcome":
        _mapping(value, "source_outcome")
        _only_keys(
            value,
            {"source_id", "candidates", "error", "completed"},
            "source_outcome",
        )

        if not isinstance(value["candidates"], list):
            raise ContractError("source.candidates must be a list")

        error = (
            ErrorInfo.from_dict(value["error"])
            if value["error"] is not None
            else None
        )

        return cls(
            value["source_id"],
            tuple(
                Candidate.from_dict(item)
                for item in value["candidates"]
            ),
            error,
            value["completed"],
        )


@dataclass(frozen=True)
class TaskIdentity:
    run_id: str
    run_attempt: int
    task_id: str
    candidate_id: str
    resource_id: str

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _int(self.run_attempt, "run_attempt", minimum=1)
        _identifier(self.task_id, "task_id")
        _identifier(self.candidate_id, "candidate_id")
        _identifier(self.resource_id, "resource_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "task_id": self.task_id,
            "candidate_id": self.candidate_id,
            "resource_id": self.resource_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskIdentity":
        _mapping(value, "task_identity")
        _only_keys(
            value,
            {
                "run_id",
                "run_attempt",
                "task_id",
                "candidate_id",
                "resource_id",
            },
            "task_identity",
        )
        return cls(**dict(value))


@dataclass(frozen=True)
class TaskRequest:
    schema_version: str
    identity: TaskIdentity
    task_type: TaskType
    created_at: str
    deadline: str

    def __post_init__(self) -> None:
        _schema(self.schema_version)

        if not isinstance(self.identity, TaskIdentity):
            raise ContractError("task.identity must be TaskIdentity")

        if not isinstance(self.task_type, TaskType):
            raise ContractError("task.task_type must be TaskType")

        _timestamp(self.created_at, "task.created_at")
        _timestamp(self.deadline, "task.deadline")

        if _parse_time(self.deadline) <= _parse_time(self.created_at):
            raise ContractError(
                "task.deadline must be later than task.created_at"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self.identity.to_dict(),
            "task_type": self.task_type.value,
            "created_at": self.created_at,
            "deadline": self.deadline,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskRequest":
        _mapping(value, "task_request")

        expected = {
            "schema_version",
            "run_id",
            "run_attempt",
            "task_id",
            "candidate_id",
            "resource_id",
            "task_type",
            "created_at",
            "deadline",
        }
        _only_keys(value, expected, "task_request")

        identity = TaskIdentity.from_dict(
            {
                key: value[key]
                for key in (
                    "run_id",
                    "run_attempt",
                    "task_id",
                    "candidate_id",
                    "resource_id",
                )
            }
        )

        try:
            task_type = TaskType(value["task_type"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ContractError(
                "task.task_type is unsupported"
            ) from exc

        return cls(
            value["schema_version"],
            identity,
            task_type,
            value["created_at"],
            value["deadline"],
        )


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

        _identifier(self.file_id, "media.file_id")
        _relative_path(self.relative_path)
        _nonempty(self.content_type, "media.content_type", 128)
        _int(self.actual_size, "media.actual_size", minimum=1)

        if (
            not isinstance(self.sha256, str)
            or not _SHA256_RE.fullmatch(self.sha256)
        ):
            raise ContractError(
                "media.sha256 must be 64 lowercase hexadecimal characters"
            )

        _bool(self.complete, "media.complete")

        if not self.complete:
            raise ContractError(
                "incomplete media cannot enter a validation manifest"
            )

        _timestamp(self.created_at, "media.created_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self.identity.to_dict(),
            "f
