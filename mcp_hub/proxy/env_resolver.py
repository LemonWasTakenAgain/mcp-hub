"""Resolve environment variable placeholders in upstream server configs."""

from __future__ import annotations

import logging
import os
import re

from mcp_hub.proxy.registry import UpstreamRegistry, UpstreamServer

logger = logging.getLogger("mcp_hub.proxy")

ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def resolve_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} placeholders with actual environment variable values."""

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        resolved = os.environ.get(var_name, "")
        if not resolved:
            logger.warning("Environment variable %s is not set", var_name)
        return resolved

    return ENV_PATTERN.sub(_replace, value)


def has_unresolved_vars(value: str) -> bool:
    """Check if a string still has ${VAR} placeholders."""
    return bool(ENV_PATTERN.search(value))


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
    """Check if a server has all required configuration to connect."""
    if not server.command and not server.url:
        return False, "No command (stdio) or URL (sse) specified"

    # Check for empty args that were supposed to be env vars
    for arg in server.args:
        if not arg.strip():
            return False, "Empty argument (likely missing env var)"

    return True, "Ready"
