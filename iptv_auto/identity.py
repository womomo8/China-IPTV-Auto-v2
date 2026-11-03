"""Stable identifiers independent of source-list ordering."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit


def _digest(value: str, length: int = 24) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_url(url: str) -> str:
    """Normalize URL identity without changing path/query semantics.

    Invalid URLs are returned trimmed rather than raising during identity creation.
    IPv6 literals retain the brackets required in an authority component.
    """
    value = (url or "").strip()
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        host = parts.hostname
        if not scheme or not host:
            return value

        # Accessing .port can raise ValueError for malformed/out-of-range ports.
        port = parts.port
        try:
            ip = ipaddress.ip_address(host.split("%", 1)[0])
            host_text = f"[{host.lower()}]" if ip.version == 6 else host.lower()
        except ValueError:
            host_text = host.encode("idna").decode("ascii").lower()

        userinfo = ""
        if parts.username is not None:
            userinfo = parts.username
            if parts.password is not None:
                userinfo += ":" + parts.password
            userinfo += "@"

        default_port = (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        )
        port_text = f":{port}" if port is not None and not default_port else ""
        netloc = userinfo + host_text + port_text
        path = parts.path or "/"
        return urlunsplit((scheme, netloc, path, parts.query, ""))
    except (TypeError, ValueError, UnicodeError):
        return value


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
