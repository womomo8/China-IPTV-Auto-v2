"""Stable identifiers independent of source-list ordering."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit


def _digest(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_url(url: str) -> str:
    """Normalize only identity-relevant URL syntax; do not rewrite query semantics."""
    value = (url or "").strip()
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not scheme or not host:
        return value
    userinfo = ""
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += ":" + parts.password
        userinfo += "@"
    port = parts.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = userinfo + host + (f":{port}" if port and not default_port else "")
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def stable_result_id(url: str, headers: dict[str, str] | None = None) -> str:
    normalized_headers = {
        str(k).strip().lower(): str(v).strip()
        for k, v in sorted((headers or {}).items(), key=lambda item: str(item[0]).lower())
    }
    payload = json.dumps(
        {"url": normalize_url(url), "headers": normalized_headers},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "line_" + _digest(payload)


def stable_channel_id(category: str, name: str) -> str:
    def clean(value: str) -> str:
        return re.sub(r"\s+", "", (value or "").strip().casefold())
    return "channel_" + _digest(clean(category) + "|" + clean(name))


def stable_source_id(source_url: str) -> str:
    return "source_" + _digest(normalize_url(source_url))
