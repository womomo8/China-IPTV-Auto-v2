"""Shared, dependency-free data contracts for China-IPTV-Auto V3.

This module defines and validates data shapes. It does not perform network,
filesystem, Docker, media-probing, cryptographic-file, or publication actions.
Those operations belong to security.py, the host controller, and pipeline.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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


STAGE_ORDER = (
    StageName.DISCOVERY,
    StageName.NORMALIZATION,
    StageName.QUICK_FILTER,
    StageName.DEEP_VALIDATION,
    StageName.PUBLISH,
)


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
            _string(
                getattr(self, key),
                f"candidate.{key}",
                2048,
                allow_empty=True,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in (
                "candidate_id",
                "name",
                "url",
                "source_id",
                "group",
                "tvg_id",
                "tvg_name",
                "logo",
            )
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Candidate":
        _keys(
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
        _id(self.source_id, "source_id")
        _tuple_type(self.candidates, Candidate, "source.candidates")

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
        _keys(
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
        _id(self.run_id, "run_id")
        _int(self.run_attempt, "run_attempt", 1)
        _id(self.task_id, "task_id")
        _id(self.candidate_id, "candidate_id")
        _id(self.resource_id, "resource_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in (
                "run_id",
                "run_attempt",
                "task_id",
                "candidate_id",
                "resource_id",
            )
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskIdentity":
        _keys(
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

        if not isinstance(self.identity, TaskIdentity):
            raise ContractError("task.identity must be TaskIdentity")

        if not isinstance(self.task_type, TaskType):
            raise ContractError("task.task_type must be TaskType")

        _timestamp(self.created_at, "task.created_at")
        _timestamp(self.deadline, "task.deadline")

        if _dt(self.deadline) <= _dt(self.created_at):
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
        _keys(value, expected, "task_request")

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
        except (ValueError, TypeError) as exc:
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

        _id(self.file_id, "media.file_id")
        _relative_path(self.relative_path)
        _nonempty(self.content_type, "media.content_type", 128)
        _int(self.actual_size, "media.actual_size", 1)

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
            "file_id": self.file_id,
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "actual_size": self.actual_size,
            "sha256": self.sha256,
            "complete": self.complete,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MediaFileEntry":
        expected = {
            "schema_version",
            "run_id",
            "run_attempt",
            "task_id",
            "candidate_id",
            "resource_id",
            "file_id",
            "relative_path",
            "content_type",
            "actual_size",
            "sha256",
            "complete",
            "created_at",
        }
        _keys(value, expected, "media_file_entry")

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

        return cls(
            value["schema_version"],
            identity,
            value["file_id"],
            value["relative_path"],
            value["content_type"],
            value["actual_size"],
            value["sha256"],
            value["complete"],
            value["created_at"],
        )


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

        ids: set[str] = set()
        paths: set[str] = set()

        for entry in self.entries:
            if not self.identity.matches(entry.identity):
                raise ContractError(
                    "manifest entry task identity mismatch"
                )

            if entry.file_id in ids or entry.relative_path in paths:
                raise ContractError(
                    "manifest contains duplicate file_id or path"
                )

            ids.add(entry.file_id)
            paths.add(entry.relative_path)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self.identity.to_dict(),
            "entries": [item.to_dict() for item in self.entries],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MediaManifest":
        expected = {
            "schema_version",
            "run_id",
            "run_attempt",
            "task_id",
            "candidate_id",
            "resource_id",
            "entries",
            "created_at",
        }
        _keys(value, expected, "media_manifest")

        if not isinstance(value["entries"], list):
            raise ContractError("manifest.entries must be a list")

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

        return cls(
            value["schema_version"],
            identity,
            tuple(
                MediaFileEntry.from_dict(item)
                for item in value["entries"]
            ),
            value["created_at"],
        )


@dataclass(frozen=True)
class ProbeEvidence:
    """Probe evidence; host authenticity is checked separately."""

    ffprobe_exit_code: int
    ffmpeg_exit_code: int
    media_bytes_read: int
    packets_read: int
    streams: tuple[str, ...]
    probe_completed: bool
    playback_seconds: float

    def __post_init__(self) -> None:
        _int(self.ffprobe_exit_code, "evidence.ffprobe_exit_code", 0)
        _int(self.ffmpeg_exit_code, "evidence.ffmpeg_exit_code", 0)
        _int(self.media_bytes_read, "evidence.media_bytes_read", 0)
        _int(self.packets_read, "evidence.packets_read", 0)
        _tuple_str(self.streams, "evidence.streams", 64)
        _bool(self.probe_completed, "evidence.probe_completed")

        if (
            isinstance(self.playback_seconds, bool)
            or not isinstance(self.playback_seconds, (int, float))
            or not (0 <= self.playback_seconds < float("inf"))
        ):
            raise ContractError(
                "evidence.playback_seconds must be a finite non-negative number"
            )

    @property
    def sufficient_for_pass(self) -> bool:
        return (
            self.probe_completed
            and self.ffprobe_exit_code == 0
            and self.ffmpeg_exit_code == 0
            and self.media_bytes_read > 0
            and self.packets_read > 0
            and bool(self.streams)
            and self.playback_seconds > 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ffprobe_exit_code": self.ffprobe_exit_code,
            "ffmpeg_exit_code": self.ffmpeg_exit_code,
            "media_bytes_read": self.media_bytes_read,
            "packets_read": self.packets_read,
            "streams": list(self.streams),
            "probe_completed": self.probe_completed,
            "playback_seconds": self.playback_seconds,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProbeEvidence":
        _keys(
            value,
            {
                "ffprobe_exit_code",
                "ffmpeg_exit_code",
                "media_bytes_read",
                "packets_read",
                "streams",
                "probe_completed",
                "playback_seconds",
            },
            "probe_evidence",
        )

        if not isinstance(value["streams"], list):
            raise ContractError("evidence.streams must be a list")

        return cls(
            value["ffprobe_exit_code"],
            value["ffmpeg_exit_code"],
            value["media_bytes_read"],
            value["packets_read"],
            tuple(value["streams"]),
            value["probe_completed"],
            value["playback_seconds"],
        )


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
            raise ContractError(
                "container_result.identity must be TaskIdentity"
            )

        _nonempty(
            self.validator_image_digest,
            "validator_image_digest",
            256,
        )
        _int(self.exit_code, "container_result.exit_code", 0)
        _timestamp(self.started_at, "container_result.started_at")
        _timestamp(self.finished_at, "container_result.finished_at")

        if _dt(self.finished_at) < _dt(self.started_at):
            raise ContractError(
                "container result finished_at precedes started_at"
            )

        if (
            self.evidence is not None
            and not isinstance(self.evidence, ProbeEvidence)
        ):
            raise ContractError(
                "container_result.evidence must be ProbeEvidence or None"
            )

        if self.error is not None and not isinstance(self.error, ErrorInfo):
            raise ContractError(
                "container_result.error must be ErrorInfo or None"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self.identity.to_dict(),
            "validator_image_digest": self.validator_image_digest,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "evidence": (
                self.evidence.to_dict() if self.evidence else None
            ),
            "error": self.error.to_dict() if self.error else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ContainerResult":
        expected = {
            "schema_version",
            "run_id",
            "run_attempt",
            "task_id",
            "candidate_id",
            "resource_id",
            "validator_image_digest",
            "exit_code",
            "started_at",
            "finished_at",
            "evidence",
            "error",
        }
        _keys(value, expected, "container_result")

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

        evidence = (
            ProbeEvidence.from_dict(value["evidence"])
            if value["evidence"] is not None
            else None
        )

        error = (
            ErrorInfo.from_dict(value["error"])
            if value["error"] is not None
            else None
        )

        return cls(
            value["schema_version"],
            identity,
            value["validator_image_digest"],
            value["exit_code"],
            value["started_at"],
            value["finished_at"],
            evidence,
            error,
        )


@dataclass(frozen=True)
class HostVerification:
    """Host-controller verification record.

    Never construct this from container JSON alone.
    """

    identity: TaskIdentity
    result_sha256: str
    image_digest_verified: bool
    exit_code_verified: bool
    output_bounded: bool
    identity_verified: bool
    schema_verified: bool

    def __post_init__(self) -> None:
        if not isinstance(self.identity, TaskIdentity):
            raise ContractError(
                "host_verification.identity must be TaskIdentity"
            )

        if (
            not isinstance(self.result_sha256, str)
            or not _SHA256_RE.fullmatch(self.result_sha256)
        ):
            raise ContractError(
                "host_verification.result_sha256 must be lowercase SHA-256"
            )

        for name in (
            "image_digest_verified",
            "exit_code_verified",
            "output_bounded",
            "identity_verified",
            "schema_verified",
        ):
            _bool(
                getattr(self, name),
                f"host_verification.{name}",
            )

    @property
    def trusted(self) -> bool:
        return all(
            (
                self.image_digest_verified,
                self.exit_code_verified,
                self.output_bounded,
                self.identity_verified,
                self.schema_verified,
            )
        )


@dataclass(frozen=True)
class LineResult:
    candidate: Candidate
    status: LineStatus
    reason: str
    evidence: ProbeEvidence | None = None
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, Candidate):
            raise ContractError(
                "line_result.candidate must be Candidate"
            )

        if not isinstance(self.status, LineStatus):
            raise ContractError(
                "line_result.status must be LineStatus"
            )

        _nonempty(self.reason, "line_result.reason", 1000)

        if (
            self.evidence is not None
            and not isinstance(self.evidence, ProbeEvidence)
        ):
            raise ContractError(
                "line_result.evidence must be ProbeEvidence or None"
            )

        if self.error is not None and not isinstance(self.error, ErrorInfo):
            raise ContractError(
                "line_result.error must be ErrorInfo or None"
            )

        if self.status is LineStatus.PASS and (
            self.evidence is None
            or not self.evidence.sufficient_for_pass
        ):
            raise ContractError(
                "PASS requires sufficient successful media probe evidence"
            )

        if self.status is LineStatus.NODE_ERROR and self.error is None:
            raise ContractError(
                "NODE_ERROR requires error details"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "status": self.status.value,
            "reason": self.reason,
            "evidence": (
                self.evidence.to_dict() if self.evidence else None
            ),
            "error": self.error.to_dict() if self.error else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineResult":
        _keys(
            value,
            {"candidate", "status", "reason", "evidence", "error"},
            "line_result",
        )

        try:
            status = LineStatus(value["status"])
        except (ValueError, TypeError) as exc:
            raise ContractError(
                "line_result.status is unsupported"
            ) from exc

        evidence = (
            ProbeEvidence.from_dict(value["evidence"])
            if value["evidence"] is not None
            else None
        )

        error = (
            ErrorInfo.from_dict(value["error"])
            if value["error"] is not None
            else None
        )

        return cls(
            Candidate.from_dict(value["candidate"]),
            status,
            value["reason"],
            evidence,
            error,
        )


@dataclass(frozen=True)
class StageResult:
    stage: StageName
    status: StageStatus
    started_at: str | None = None
    finished_at: str | None = None
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.stage, StageName)
            or not isinstance(self.status, StageStatus)
        ):
            raise ContractError(
                "stage result has invalid stage or status"
            )

        if self.started_at is not None:
            _timestamp(self.started_at, "stage.started_at")

        if self.finished_at is not None:
            _timestamp(self.finished_at, "stage.finished_at")

        if (
            self.started_at
            and self.finished_at
            and _dt(self.finished_at) < _dt(self.started_at)
        ):
            raise ContractError(
                "stage finished_at precedes started_at"
            )

        if self.error is not None and not isinstance(self.error, ErrorInfo):
            raise ContractError(
                "stage.error must be ErrorInfo or None"
            )

        if self.status is StageStatus.FAILED and self.error is None:
            raise ContractError(
                "failed stage requires error details"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error.to_dict() if self.error else None,
        }


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    run_attempt: int
    mode: RunMode
    stages: tuple[StageResult, ...]
    line_results: tuple[LineResult, ...]
    critical_error: bool = False

    def __post_init__(self) -> None:
        _id(self.run_id, "run_id")
        _int(self.run_attempt, "run_attempt", 1)

        if not isinstance(self.mode, RunMode):
            raise ContractError("run.mode must be RunMode")

        _tuple_type(self.stages, StageResult, "run.stages")
        _tuple_type(self.line_results, LineResult, "run.line_results")
        _bool(self.critical_error, "run.critical_error")

        stage_names = [stage.stage for stage in self.stages]

        if len(stage_names) != len(set(stage_names)):
            raise ContractError("run contains duplicate stages")

        if stage_names != sorted(
            stage_names,
            key=STAGE_ORDER.index,
        ):
            raise ContractError(
                "run stages are not in the fixed five-step order"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the run data without making business decisions."""
        return {
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "mode": self.mode.value,
            "stages": [
                result.to_dict()
                for result in self.stages
            ],
            "line_results": [
                result.to_dict()
                for result in self.line_results
            ],
            "critical_error": self.critical_error,
        }


@dataclass(frozen=True)
class PublishDecision:
    eligible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _bool(self.eligible, "publish.eligible")
        _tuple_str(self.reasons, "publish.reasons", 1000)

        if self.eligible and self.reasons:
            raise ContractError(
                "eligible publish decision cannot contain rejection reasons"
            )

        if not self.eligible and not self.reasons:
            raise ContractError(
                "rejected publish decision must explain why"
            )


def validate_container_result(
    result: ContainerResult,
    expected: TaskIdentity,
    host: HostVerification,
) -> None:
    """Raise unless the host-verified result matches the expected task."""

    if (
        not isinstance(result, ContainerResult)
        or not isinstance(expected, TaskIdentity)
    ):
        raise ContractError(
            "invalid result or expected identity"
        )

    if not isinstance(host, HostVerification) or not host.trusted:
        raise ContractError(
            "container result has not passed host verification"
        )

    if (
        not result.identity.matches(expected)
        or not host.identity.matches(expected)
    ):
        raise ContractError("task identity mismatch")

    if result.exit_code != 0:
        raise ContractError(
            "container exit code is not zero"
        )

    if result.error is not None:
        raise ContractError(
            "container reported an error"
        )

    if result.evidence is None:
        raise ContractError(
            "container result has no media evidence"
        )


def _mapping(value: Any, name: str) -> None:
    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")


def _keys(
    value: Mapping[str, Any],
    expected: set[str],
    name: str,
) -> None:
    _mapping(value, name)

    missing = expected - set(value)
    extra = set(value) - expected

    if missing or extra:
        raise ContractError(
            f"{name} keys mismatch; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )


def _string(
    value: Any,
    name: str,
    maximum: int,
    allow_empty: bool = False,
) -> None:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not allow_empty and not value.strip())
    ):
        raise ContractError(
            f"{name} must be a "
            f"{'possibly empty ' if allow_empty else 'non-empty '}"
            f"string up to {maximum} characters"
        )


def _nonempty(value: Any, name: str, maximum: int) -> None:
    _string(value, name, maximum, False)


def _bool(value: Any, name: str) -> None:
    if not isinstance(value, bool):
        raise ContractError(f"{name} must be bool")


def _int(value: Any, name: str, minimum: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
    ):
        raise ContractError(
            f"{name} must be an integer >= {minimum}"
        )


def _id(value: Any, name: str) -> None:
    if (
        not isinstance(value, str)
        or not _ID_RE.fullmatch(value)
    ):
        raise ContractError(
            f"{name} is not a valid identifier"
        )


def _schema(value: Any) -> None:
    if value != SCHEMA_VERSION:
        raise ContractError(
            f"unsupported schema_version: {value!r}"
        )


def _relative_path(value: Any) -> None:
    if (
        not isinstance(value, str)
        or not _RELATIVE_PATH_RE.fullmatch(value)
    ):
        raise ContractError(
            "media.relative_path must be a safe relative path"
        )

    if (
        value.startswith("/")
        or "\\" in value
        or any(
            part in ("", ".", "..")
            for part in value.split("/")
        )
    ):
        raise ContractError(
            "media.relative_path contains traversal or invalid segments"
        )

    if re.match(r"^[A-Za-z]:", value):
        raise ContractError(
            "media.relative_path must not be a drive path"
        )


def _timestamp(value: Any, name: str) -> None:
    _dt(value, name)


def _dt(value: Any, name: str = "timestamp") -> datetime:
    if not isinstance(value, str):
        raise ContractError(
            f"{name} must be an ISO-8601 string"
        )

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ContractError(
            f"{name} must be a valid ISO-8601 timestamp"
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(
            f"{name} must include a timezone"
        )

    return parsed


def _tuple_type(
    value: Any,
    expected: type,
    name: str,
) -> None:
    if (
        not isinstance(value, tuple)
        or any(not isinstance(item, expected) for item in value)
    ):
        raise ContractError(
            f"{name} must be a tuple of {expected.__name__}"
        )


def _tuple_str(
    value: Any,
    name: str,
    maximum: int,
) -> None:
    if (
        not isinstance(value, tuple)
        or any(
            not isinstance(item, str)
            or not item
            or len(item) > maximum
            for item in value
        )
    ):
        raise ContractError(
            f"{name} must be a tuple of non-empty strings "
            f"up to {maximum} characters"
        )
