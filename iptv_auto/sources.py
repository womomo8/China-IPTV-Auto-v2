"""Public IPTV source discovery and bounded playlist retrieval.

Discovery uses GitHub's public repository search and repository tree API.
It only discovers candidate playlist URLs; it does not declare their streams
usable. Actual line screening and measurement belong to later pipeline stages.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .identity import normalize_url, stable_source_id


GITHUB_API = "https://api.github.com"
USER_AGENT = "China-IPTV-Auto-v2/0.1"
PLAYLIST_SUFFIXES = (".m3u", ".m3u8")
MAX_PLAYLIST_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class SourceCandidate:
    source_id: str
    name: str
    url: str
    source_type: str


@dataclass(frozen=True)
class SourceFetchResult:
    ok: bool
    text: str = ""
    status_code: int | None = None
    duration_ms: float = 0.0
    error_class: str = ""


def _http_get(url: str, timeout: float, *, accept: str = "*/*") -> tuple[int, bytes]:
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        body = response.read(MAX_PLAYLIST_BYTES + 1)
        return int(status), body


def _valid_playlist_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme.lower() in {"http", "https"} and bool(parts.netloc)
    except ValueError:
        return False


def _candidate(name: str, url: str, source_type: str) -> SourceCandidate | None:
    value = url.strip()
    if not _valid_playlist_url(value):
        return None
    normalized = normalize_url(value)
    return SourceCandidate(
        source_id=stable_source_id(normalized),
        name=(name or "").strip() or "未命名来源",
        url=value,
        source_type=source_type,
    )


def _github_json(url: str, timeout: float) -> dict[str, Any] | None:
    try:
        status, body = _http_get(
            url, timeout, accept="application/vnd.github+json"
        )
        if status != 200:
            return None
        data = json.loads(body.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, UnicodeError):
        return None


def discover_github_playlists(
    *,
    timeout: float = 8,
    max_repositories: int = 12,
    max_candidates: int = 36,
    max_seconds: float = 480,
) -> list[SourceCandidate]:
    """Find public M3U files in IPTV-related GitHub repositories.

    The discovery stage is deliberately bounded. GitHub search/API failures
    simply produce no new candidates; they do not affect existing source data.
    """
    deadline = time.monotonic() + max(1.0, max_seconds)
    search_url = (
        f"{GITHUB_API}/search/repositories"
        "?q=iptv+m3u+playlist+in:name,description&sort=updated&order=desc&per_page="
        f"{min(max(1, max_repositories), 30)}"
    )
    search_data = _github_json(search_url, timeout)
    if not search_data:
        return []

    candidates: list[SourceCandidate] = []
    seen: set[str] = set()
    repositories = search_data.get("items", [])
    if not isinstance(repositories, list):
        return []

    for repo in repositories[:max_repositories]:
        if time.monotonic() >= deadline or len(candidates) >= max_candidates:
            break
        if not isinstance(repo, dict):
            continue
        full_name = repo.get("full_name")
        branch = repo.get("default_branch")
        if not isinstance(full_name, str) or not isinstance(branch, str):
            continue
        if not full_name or not branch:
            continue

        tree_url = (
            f"{GITHUB_API}/repos/{quote(full_name, safe='/')}/git/trees/"
            f"{quote(branch, safe='')}?recursive=1"
        )
        tree_data = _github_json(tree_url, timeout)
        if not tree_data or tree_data.get("truncated") is True:
            continue
        tree = tree_data.get("tree", [])
        if not isinstance(tree, list):
            continue

        for item in tree:
            if len(candidates) >= max_candidates or time.monotonic() >= deadline:
                break
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            path = item.get("path")
            size = item.get("size")
            if not isinstance(path, str) or not path.lower().endswith(PLAYLIST_SUFFIXES):
                continue
            if isinstance(size, int) and (size <= 0 or size > MAX_PLAYLIST_BYTES):
                continue
            raw_url = (
                "https://raw.githubusercontent.com/"
                f"{full_name}/{quote(branch, safe='')}/{quote(path, safe='/')}"
            )
            candidate = _candidate(f"{full_name}/{path}", raw_url, "discovered")
            if candidate and candidate.source_id not in seen:
                seen.add(candidate.source_id)
                candidates.append(candidate)

    return candidates


def collect_source_candidates(
    config: dict[str, Any],
    *,
    discoverer=None,
) -> list[SourceCandidate]:
    """Merge manual and discovered sources, prioritizing manual entries in this batch."""
    if discoverer is None:
        discoverer = discover_github_playlists
    source_cfg = config["sources"]
    discovery_cfg = config["discovery"]
    manual: list[SourceCandidate] = []
    for item in source_cfg.get("manual", []):
        candidate = _candidate(item["name"], item["url"], "manual")
        if candidate:
            manual.append(candidate)

    discovered: list[SourceCandidate] = []
    if source_cfg.get("discovery_enabled", True):
        discovered = discoverer(
            timeout=float(discovery_cfg["request_timeout_seconds"]),
            max_candidates=int(discovery_cfg["max_candidate_lines"]),
            max_seconds=float(discovery_cfg["max_seconds"]),
        )

    merged: list[SourceCandidate] = []
    seen: set[str] = set()
    for candidate in manual + discovered:
        if candidate.source_id in seen:
            continue
        seen.add(candidate.source_id)
        merged.append(candidate)

    # Manual entries are retained first; newly discovered entries are capped
    # independently so one run cannot flood the source pool.
    pool_capacity = int(source_cfg["pool_capacity"])
    new_limit = int(source_cfg["new_sources_per_run"])
    if len(manual) > pool_capacity:
        raise ValueError("人工来源数量超过来源池容量，请先减少 config.yaml 中的 sources.manual")
    return (manual + [item for item in merged if item.source_type == "discovered"][:new_limit])[:pool_capacity]


def fetch_playlist(url: str, *, timeout: float = 8) -> SourceFetchResult:
    """Fetch one playlist with a strict byte cap and normalized failure classes."""
    if not _valid_playlist_url(url):
        return SourceFetchResult(False, error_class="invalid_url")
    started = time.monotonic()
    try:
        status, body = _http_get(url, timeout)
        duration = (time.monotonic() - started) * 1000
        if status < 200 or status >= 300:
            return SourceFetchResult(
                False, status_code=status, duration_ms=duration,
                error_class="http_status",
            )
        if len(body) > MAX_PLAYLIST_BYTES:
            return SourceFetchResult(
                False, status_code=status, duration_ms=duration,
                error_class="response_too_large",
            )
        try:
            content = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = body.decode("gb18030", errors="replace")
        if not content.strip():
            return SourceFetchResult(
                False, status_code=status, duration_ms=duration,
                error_class="empty_response",
            )
        return SourceFetchResult(
            True, text=content, status_code=status, duration_ms=duration
        )
    except HTTPError as exc:
        return SourceFetchResult(
            False, status_code=exc.code,
            duration_ms=(time.monotonic() - started) * 1000,
            error_class="http_status",
        )
    except (TimeoutError,):
        error = "timeout"
    except (URLError,):
        error = "network_error"
    except (OSError,):
        error = "network_error"
    except Exception:
        error = "fetch_error"
    return SourceFetchResult(
        False, duration_ms=(time.monotonic() - started) * 1000,
        error_class=error,
    )
