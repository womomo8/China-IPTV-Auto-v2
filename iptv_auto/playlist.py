"""Conservative M3U parser. It parses records; it does not claim they play."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from typing import Iterable

from .identity import stable_result_id, stable_channel_id


SUPPORTED_SCHEMES = ("http://", "https://", "rtsp://", "rtmp://", "rtp://", "udp://")
PLACEHOLDER_WORDS = (
    "广告", "测试频道", "无信号", "暂无信号", "信号中断", "占位",
    "advertisement", "no signal", "test channel",
)


@dataclass(frozen=True)
class PlaylistEntry:
    name: str
    url: str
    category: str = ""
    headers: dict[str, str] | None = None
    line_id: str = ""
    channel_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_extinf(line: str) -> tuple[str, str]:
    category_match = re.search(r'group-title="([^"]*)"', line, re.IGNORECASE)
    category = category_match.group(1).strip() if category_match else ""
    # The display name is the text after the last comma; commas in attributes are
    # not expected in well-formed EXTINF metadata, but rsplit is safer here.
    name = line.rsplit(",", 1)[-1].strip() if "," in line else ""
    return category, name


def _looks_like_placeholder(name: str, category: str) -> bool:
    text = f"{name} {category}".casefold()
    return any(word.casefold() in text for word in PLACEHOLDER_WORDS)


def parse_m3u(text: str) -> list[PlaylistEntry]:
    """Parse common EXTINF + URL playlists and discard malformed/obvious placeholders."""
    entries: list[PlaylistEntry] = []
    pending: tuple[str, str] | None = None

    for raw in text.replace("\ufeff", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF"):
            pending = _parse_extinf(line)
            continue
        if line.startswith("#"):
            # Header metadata such as #EXTVLCOPT may be supported in a later parser
            # extension. Do not silently attach unknown directives as HTTP headers.
            continue
        if not line.lower().startswith(SUPPORTED_SCHEMES):
            pending = None
            continue
        if pending is None:
            # URL without EXTINF cannot be safely mapped to a channel.
            continue

        category, name = pending
        pending = None
        if not name or _looks_like_placeholder(name, category):
            continue

        line_id = stable_result_id(line, {})
        channel_id = stable_channel_id(category, name)
        entries.append(PlaylistEntry(
            name=name,
            url=line,
            category=category,
            headers={},
            line_id=line_id,
            channel_id=channel_id,
        ))
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
