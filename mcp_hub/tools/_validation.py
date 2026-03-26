"""Input validation for MCP tools — prevents command injection and bad inputs."""

import re
from urllib.parse import urlparse

# Hostname: letters, digits, dots, hyphens only. No shell metacharacters.
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]{0,253}[a-zA-Z0-9])?$")

# IP address (v4 only for simplicity)
_IPV4_RE = re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$")


def validate_hostname(host: str) -> str:
    """Validate a hostname or IP address. Raises ValueError on invalid input."""
    host = host.strip()
    if not host:
        raise ValueError("Hostname cannot be empty")
    if len(host) > 255:
        raise ValueError("Hostname too long (max 255 characters)")
    # If it looks like an IP (all digits and dots), validate strictly as IPv4
    if re.match(r"^[\d.]+$", host):
        if _IPV4_RE.match(host):
            return host
        raise ValueError(
            f"Invalid hostname: {host!r}. Only letters, digits, dots, and hyphens allowed."
        )
    if _HOSTNAME_RE.match(host):
        return host
    raise ValueError(
        f"Invalid hostname: {host!r}. Only letters, digits, dots, and hyphens allowed."
    )


def validate_port(port: int) -> int:
    """Validate a TCP port number."""
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"Invalid port: {port}. Must be 1-65535.")
    return port


def validate_url(url: str) -> str:
    """Validate an HTTP(S) URL."""
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme!r}. Must be http or https.")
    if not parsed.hostname:
        raise ValueError("URL must have a hostname")
    return url
