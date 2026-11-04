
"""IPv4-only input options for supported FFmpeg TCP protocols."""
from __future__ import annotations

from urllib.parse import urlsplit


IPV4_LOCAL_ADDRESS = "0.0.0.0"

# These protocols use TCP and have been verified with FFmpeg's
# underlying TCP local_addr option.
SUPPORTED_IPV4_TCP_SCHEMES = {
    "http",
    "https",
    "rtmp",
}


def ffmpeg_ipv4_input_options(url: str) -> list[str] | None:
    """Return IPv4-only FFmpeg input options.

    None means this protocol cannot currently be guaranteed to use
    IPv4 by this implementation. Callers must not count it as passed.
    """
    try:
        scheme = urlsplit(str(url).strip()).scheme.lower()
    except (TypeError, ValueError):
        return None

    if scheme not in SUPPORTED_IPV4_TCP_SCHEMES:
        return None

    return [
        "-local_addr",
        IPV4_LOCAL_ADDRESS,
    ]
