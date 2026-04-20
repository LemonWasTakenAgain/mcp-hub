"""Input validation for MCP tools — prevents command injection and bad inputs."""

import ipaddress
import re
import socket
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


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/reserved IP address."""
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        pass
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for _, _, _, _, sockaddr in resolved:
            addr = ipaddress.ip_address(sockaddr[0])
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                return True
    except socket.gaierror:
        pass
    return False


_VALID_KVM_PORTS = frozenset({1, 2, 3, 4})


def validate_kvm_port(port: int) -> int:
    """Validate KVM port number (1-4). Port 0 means 'current port, no switch'."""
    if port == 0:
        return 0
    if port not in _VALID_KVM_PORTS:
        raise ValueError(f"Invalid KVM port: {port}. Must be 1, 2, 3, or 4.")
    return port


_VALID_POWER_ACTIONS = frozenset({"on", "off", "reset", "hard-off"})


def validate_power_action(action: str) -> str:
    """Validate ATX power action."""
    if action not in _VALID_POWER_ACTIONS:
        raise ValueError(f"Invalid action: {action!r}. Must be one of: on, off, reset, hard-off.")
    return action


def validate_url(url: str, *, allow_private: bool = False) -> str:
    """Validate an HTTP(S) URL. Blocks RFC1918/private IPs unless allow_private=True."""
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme!r}. Must be http or https.")
    if not parsed.hostname:
        raise ValueError("URL must have a hostname")
    if not allow_private and _is_private_ip(parsed.hostname):
        raise ValueError(
            f"URL targets a private/internal IP address: {parsed.hostname!r}. "
            "Use allow_private=True to bypass this check for trusted callers."
        )
    return url
