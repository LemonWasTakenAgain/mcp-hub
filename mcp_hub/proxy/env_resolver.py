"""Resolve environment variable placeholders in upstream server configs."""

from __future__ import annotations

import os
import re

from mcp_hub.proxy.registry import UpstreamRegistry, UpstreamServer

ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def resolve_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} placeholders with actual environment variable values."""
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return ENV_PATTERN.sub(_replace, value)


def resolve_server_env(server: UpstreamServer) -> UpstreamServer:
    """Resolve all environment variable placeholders in a server config."""
    # Resolve env dict values
    resolved_env = {k: resolve_env_vars(v) for k, v in server.env.items()}
    server.env = {k: v for k, v in resolved_env.items() if v}  # drop empty

    # Resolve args
    server.args = [resolve_env_vars(a) for a in server.args]

    # Resolve URL and headers for SSE
    server.url = resolve_env_vars(server.url)
    server.headers = {k: resolve_env_vars(v) for k, v in server.headers.items()}

    return server


def resolve_registry(registry: UpstreamRegistry) -> UpstreamRegistry:
    """Resolve all environment variable placeholders across the registry."""
    for server in registry.servers.values():
        resolve_server_env(server)
    return registry


def check_server_ready(server: UpstreamServer) -> tuple[bool, str]:
    """Check if a server has all required env vars resolved (no empty required values)."""
    # Check if env vars that were referenced are now resolved
    for key, value in server.env.items():
        if not value and ENV_PATTERN.search(server.env.get(key, "")):
            return False, f"Missing environment variable for {key}"

    # Check command exists
    if not server.command:
        return False, "No command specified"

    return True, "Ready"
