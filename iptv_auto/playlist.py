"""M3U parser with explicit HTTP-header handling.

Malformed header directives invalidate only their associated entry. This avoids
silently treating a header-dependent stream as if it required no headers.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import re
from typing import Iterable

from .identity import stable_result_id, stable_channel_id


SUPPORTED_SCHEMES = ("http://", "https://", "rtsp://", "rtmp://", "rtp://", "udp://")
PLACEHOLDER_WORDS = (
    "广告", "测试频道", "无信号", "暂无信号", "信号中断", "占位",
    "advertisement", "no signal", "test channel",
)
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


@dataclass(frozen=True)
class PlaylistEntry:
    name: str
    url: str
    category: str = ""
    headers: dict[str, str] | None = None
    line_id: str = ""
    channel_id: str = ""
    parse_warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_extinf(line: str) -> tuple[str, str]:
    category_match = re.search(r'group-title="([^"]*)"', line, re.IGNORECASE)
    category = category_match.group(1).strip() if category_match else ""
    name = line.rsplit(",", 1)[-1].strip() if "," in line else ""
    return category, name


def _looks_like_placeholder(name: str, category: str) -> bool:
    text = f"{name} {category}".casefold()
    return any(word.casefold() in text for word in PLACEHOLDER_WORDS)


def _safe_header(name: object, value: object) -> tuple[str, str]:
    key = str(name).strip()
    val = str(value).strip()
    if not _HEADER_NAME.fullmatch(key):
        raise ValueError(f"非法 HTTP 请求头名称：{key!r}")
    if "\r" in val or "\n" in val:
        raise ValueError(f"HTTP 请求头 {key!r} 含有换行符")
    return key, val


def _merge_header(headers: dict[str, str], name: str, value: str) -> None:
    # Header names are case-insensitive; preserve the first spelling.
    existing = next((key for key in headers if key.lower() == name.lower()), None)
    headers[existing or name] = value


def _apply_directive(line: str, headers: dict[str, str]) -> str | None:
    """Apply a supported header directive; return a warning on malformed input."""
    upper = line.upper()
    if upper.startswith("#EXTVLCOPT:"):
        option = line.split(":", 1)[1].strip()
        if "=" not in option:
            return None
        key, value = option.split("=", 1)
        key = key.strip().lower()
        mapped = {
            "http-user-agent": "User-Agent",
            "http-referrer": "Referer",
            "http-referer": "Referer",
        }.get(key)
        if mapped is None:
            # Other VLC options (network-caching, program, etc.) are not HTTP headers.
            return None
        try:
            name, val = _safe_header(mapped, value)
            _merge_header(headers, name, val)
        except ValueError as exc:
            return str(exc)
        return None

    if upper.startswith("#EXTHTTP:"):
        raw_json = line.split(":", 1)[1].strip()
        try:
            data = json.loads(raw_json)
            if not isinstance(data, dict):
                raise ValueError("EXTHTTP 内容必须是 JSON 对象")
            for name, value in data.items():
                if isinstance(value, (dict, list)) or value is None:
                    raise ValueError(f"请求头 {name!r} 的值必须是字符串或数字")
                safe_name, safe_value = _safe_header(name, value)
                _merge_header(headers, safe_name, safe_value)
        except (json.JSONDecodeError, ValueError) as exc:
            return f"无法解析 EXTHTTP 请求头：{exc}"
        return None

    return None


def parse_m3u(text: str) -> list[PlaylistEntry]:
    """Parse EXTINF records, including supported HTTP headers and safe failures."""
    entries: list[PlaylistEntry] = []
    pending: tuple[str, str] | None = None
    headers: dict[str, str] = {}
    warnings: list[str] = []

    for raw in text.replace("\ufeff", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF"):
            # A new EXTINF starts a new record; discard stale metadata.
            pending = _parse_extinf(line)
            headers = {}
            warnings = []
            continue
        if line.startswith("#"):
            warning = _apply_directive(line, headers)
            if warning:
                warnings.append(warning)
            continue
        if not line.lower().startswith(SUPPORTED_SCHEMES):
            pending = None
            headers = {}
            warnings = []
            continue
        if pending is None:
            headers = {}
            warnings = []
            continue

        category, name = pending
        pending = None
        if not name or _looks_like_placeholder(name, category):
            headers = {}
            warnings = []
            continue

        # Never emit a URL whose required header metadata was malformed.
        if warnings:
            headers = {}
            warnings = []
            continue

        clean_headers = dict(headers)
        line_id = stable_result_id(line, clean_headers)
        channel_id = stable_channel_id(category, name)
        entries.append(PlaylistEntry(
            name=name,
            url=line,
            category=category,
            headers=clean_headers,
            line_id=line_id,
            channel_id=channel_id,
            parse_warnings=(),
        ))
        headers = {}
        warnings = []
    return entries


def deduplicate_entries(entries: Iterable[PlaylistEntry]) -> list[PlaylistEntry]:
    """Deduplicate by stable line + channel identity while preserving first-seen order."""
    seen: set[tuple[str, str]] = set()
    result: list[PlaylistEntry] = []
    for entry in entries:
        key = (entry.line_id, entry.channel_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result
