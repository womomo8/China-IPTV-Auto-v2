
"""Lightweight IPv4 admission gate for IPTV stream URLs."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
import threading
import time
from urllib.parse import urlsplit


CACHE_TTL_SECONDS = 300

_CACHE = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class IPv4Admission:
    allowed: bool
    status: str
    addresses: tuple[str, ...] = ()


def _default_port(scheme: str, port: int | None) -> int:
    if port is not None:
        return port

    return {
        "http": 80,
        "https": 443,
        "rtsp": 554,
        "rtmp": 1935,
        "rtp": 5004,
        "udp": 5004,
    }.get(scheme, 0)


def _check_literal(host: str, scheme: str):
    candidate = host.split("%", 1)[0]

    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None

    if isinstance(address, ipaddress.IPv6Address):
        return IPv4Admission(
            False, "ipv6_literal", (str(address),)
        )

    if address.is_multicast:
        if scheme in {"udp", "rtp"}:
            return IPv4Admission(
                True, "ipv4_multicast", (str(address),)
            )

        return IPv4Admission(
            False, "non_public_ipv4_address", (str(address),)
        )

    if not address.is_global:
        return IPv4Admission(
            False, "non_public_ipv4_address", (str(address),)
        )

    return IPv4Admission(
        True, "ipv4_literal", (str(address),)
    )


def _resolve_ipv4(host: str, port: int) -> IPv4Admission:
    key = (host.casefold(), port)
    now = time.monotonic()

    with _CACHE_LOCK:
        cached = _CACHE.get(key)

        if cached and cached[0] > now:
            return cached[1]

    try:
        records = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )

        addresses = sorted({
            str(ipaddress.IPv4Address(record[4][0]))
            for record in records
        })

        public_addresses = tuple(
            address
            for address in addresses
            if ipaddress.IPv4Address(address).is_global
        )

        if public_addresses:
            result = IPv4Admission(
                True, "ipv4_dns", public_addresses
            )
        elif addresses:
            result = IPv4Admission(
                False,
                "non_public_ipv4_address",
                tuple(addresses),
            )
        else:
            result = IPv4Admission(
                False, "no_ipv4_address"
            )

    except socket.gaierror as exc:
        no_data = {
            getattr(socket, "EAI_NONAME", None),
            getattr(socket, "EAI_NODATA", None),
        }

        if exc.errno in no_data:
            result = IPv4Admission(
                False, "no_ipv4_address"
            )
        else:
            result = IPv4Admission(
                False, "dns_temporary_failure"
            )

    except (OSError, ValueError):
        result = IPv4Admission(
            False, "dns_temporary_failure"
        )

    # Do not cache temporary failures.
    if result.status != "dns_temporary_failure":
        with _CACHE_LOCK:
            _CACHE[key] = (
                time.monotonic() + CACHE_TTL_SECONDS,
                result,
            )

    return result


def check_ipv4_url(url: str) -> IPv4Admission:
    """Check whether a stream URL has an eligible IPv4 endpoint."""

    try:
        parts = urlsplit(str(url).strip())
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port

    except (TypeError, ValueError):
        return IPv4Admission(False, "malformed_url")

    if not host:
        return IPv4Admission(False, "missing_host")

    literal = _check_literal(host, scheme)

    if literal is not None:
        return literal

    port = _default_port(scheme, port)

    if not port:
        return IPv4Admission(
            False, "missing_port_for_dns"
        )

    return _resolve_ipv4(host, port)


def clear_ipv4_dns_cache() -> None:
    """Clear cache for tests."""

    with _CACHE_LOCK:
        _CACHE.clear()
