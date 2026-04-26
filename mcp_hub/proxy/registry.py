"""Upstream MCP server registry — defines all available upstream servers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml


class TransportType(StrEnum):
    STDIO = "stdio"
    SSE = "sse"


@dataclass
class UpstreamServer:
    """Configuration for a single upstream MCP server."""

    name: str
    transport: TransportType
    enabled: bool = True
    description: str = ""

    # stdio transport fields
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # sse transport fields
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    # proxy settings
    prefix: str = ""  # tool name prefix, defaults to name
    timeout: float = 30.0
    retries: int = 2
    auto_restart: bool = True
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown: float = 60.0

    def __post_init__(self) -> None:
        if not self.prefix:
            self.prefix = self.name.replace("-", "_")

    @property
    def tool_prefix(self) -> str:
        return f"{self.prefix}__"


@dataclass
class UpstreamRegistry:
    """Registry of all configured upstream MCP servers."""

    servers: dict[str, UpstreamServer] = field(default_factory=dict)

    def add(self, server: UpstreamServer) -> None:
        self.servers[server.name] = server

    def get_enabled(self) -> list[UpstreamServer]:
        return [s for s in self.servers.values() if s.enabled]

    def enable(self, name: str) -> None:
        if name in self.servers:
            self.servers[name].enabled = True

    def disable(self, name: str) -> None:
        if name in self.servers:
            self.servers[name].enabled = False

    @classmethod
    def from_yaml(cls, path: str | Path) -> UpstreamRegistry:
        """Load registry from a YAML config file."""
        registry = cls()
        path = Path(path)
        if not path.exists():
            return registry

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        for name, cfg in data.get("upstreams", {}).items():
            server = UpstreamServer(
                name=name,
                transport=TransportType(cfg.get("transport", "stdio")),
                enabled=cfg.get("enabled", True),
                description=cfg.get("description", ""),
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
                url=cfg.get("url", ""),
                headers=cfg.get("headers", {}),
                prefix=cfg.get("prefix", ""),
                timeout=cfg.get("timeout", 30.0),
                retries=cfg.get("retries", 2),
                auto_restart=cfg.get("auto_restart", True),
                circuit_breaker_threshold=cfg.get("circuit_breaker_threshold", 3),
                circuit_breaker_cooldown=cfg.get("circuit_breaker_cooldown", 60.0),
            )
            registry.add(server)

        return registry

    def to_yaml(self, path: str | Path) -> None:
        """Save registry to a YAML config file."""
        data: dict[str, Any] = {"upstreams": {}}
        for name, server in self.servers.items():
            entry: dict[str, Any] = {
                "transport": server.transport.value,
                "enabled": server.enabled,
                "description": server.description,
            }
            if server.transport == TransportType.STDIO:
                entry["command"] = server.command
                if server.args:
                    entry["args"] = server.args
                if server.env:
                    entry["env"] = server.env
            elif server.transport == TransportType.SSE:
                entry["url"] = server.url
                if server.headers:
                    entry["headers"] = server.headers
            if server.prefix != server.name.replace("-", "_"):
                entry["prefix"] = server.prefix
            if server.timeout != 30.0:
                entry["timeout"] = server.timeout
            data["upstreams"][name] = entry

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
