"""Proxy Manager — orchestrates all upstream connections and registers proxied tools."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_hub.mcp_server import register_tool, unregister_tool
from mcp_hub.proxy.connector import UpstreamConnection
from mcp_hub.proxy.registry import UpstreamRegistry, UpstreamServer

logger = logging.getLogger("mcp_hub.proxy")


class ProxyManager:
    """Manages connections to all upstream MCP servers and proxies their tools."""

    def __init__(self, registry: UpstreamRegistry, mcp_server: FastMCP):
        self.registry = registry
        self.mcp_server = mcp_server
        self.connections: dict[str, UpstreamConnection] = {}
        self._tool_map: dict[str, tuple[UpstreamConnection, str]] = {}
        self._health_task: asyncio.Task | None = None
        self._reconnect_locks: dict[str, asyncio.Lock] = {}

    async def start(self) -> None:
        """Connect to all enabled upstream servers and register their tools."""
        enabled = self.registry.get_enabled()
        if not enabled:
            logger.info("No upstream servers enabled")
            return

        logger.info("Connecting to %d upstream MCP servers...", len(enabled))

        # Connect to all servers concurrently
        tasks = [self._connect_server(server) for server in enabled]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        connected = sum(1 for r in results if r is True)
        failed = len(results) - connected
        total_tools = sum(len(c.tools) for c in self.connections.values() if c.connected)

        logger.info(
            "Proxy started: %d/%d servers connected, %d tools proxied (%d failed)",
            connected,
            len(enabled),
            total_tools,
            failed,
        )

        # Start health monitor
        self._health_task = asyncio.create_task(self._health_loop())

    async def _connect_server(self, server: UpstreamServer) -> bool:
        """Connect to a single upstream server and register its tools."""
        conn = UpstreamConnection(server=server)
        self.connections[server.name] = conn

        try:
            await conn.connect()
            self._register_proxied_tools(conn)
            return True
        except Exception as e:
            logger.error("Failed to connect to %s: %s", server.name, e)
            return False

    def _register_proxied_tools(self, conn: UpstreamConnection) -> None:
        """Register all tools from an upstream server on the local MCP server."""
        for tool in conn.tools:
            proxied_name = f"{conn.server.tool_prefix}{tool.name}"
            original_name = tool.name

            # Build description with upstream attribution
            desc = tool.description or f"Tool from {conn.server.name}"
            desc = f"[{conn.server.name}] {desc}"

            # Store the mapping
            self._tool_map[proxied_name] = (conn, original_name)

            # Extract input schema
            input_schema = {}
            if tool.inputSchema:
                input_schema = dict(tool.inputSchema)

            # Register a proxy function on the FastMCP server
            self._register_proxy_tool(proxied_name, desc, input_schema, conn, original_name)

            logger.debug(
                "Registered proxied tool: %s -> %s/%s",
                proxied_name,
                conn.server.name,
                original_name,
            )

        logger.info(
            "Registered %d tools from %s (prefix: %s)",
            len(conn.tools),
            conn.server.name,
            conn.server.tool_prefix,
        )

    @staticmethod
    def _build_arg_model(input_schema: dict) -> type:
        """Build a dynamic Pydantic model from a JSON Schema for argument validation.

        This creates an ArgModelBase subclass whose fields match the upstream tool's
        input schema, so that call_fn_with_arg_validation correctly validates and
        unpacks arguments instead of requiring a single 'kwargs' field.
        """
        from typing import Any as TypingAny

        from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
        from pydantic import ConfigDict, Field

        properties = input_schema.get("properties", {})
        required = set(input_schema.get("required", []))

        field_definitions: dict[str, tuple] = {}
        for name, prop in properties.items():
            annotation = TypingAny
            desc = prop.get("description", "")
            if name in required:
                field_definitions[name] = (
                    annotation,
                    Field(description=desc),
                )
            else:
                field_definitions[name] = (
                    annotation,
                    Field(default=prop.get("default"), description=desc),
                )

        # If no properties, create a model that accepts anything
        cfg = ConfigDict(arbitrary_types_allowed=True, extra="allow")
        if not field_definitions:
            model = type(
                "DynamicArgs",
                (ArgModelBase,),
                {"model_config": cfg},
            )
        else:
            namespace: dict[str, TypingAny] = {
                "__annotations__": {},
                "model_config": cfg,
            }
            for name, (annotation, field) in field_definitions.items():
                namespace["__annotations__"][name] = annotation
                namespace[name] = field
            model = type("DynamicArgs", (ArgModelBase,), namespace)
            model.model_rebuild()

        return model

    def _register_proxy_tool(
        self,
        proxied_name: str,
        description: str,
        input_schema: dict,
        conn: UpstreamConnection,
        original_name: str,
    ) -> None:
        """Register a single proxied tool on the FastMCP server."""
        # We need to capture these in the closure
        _conn = conn
        _original = original_name
        _name = proxied_name

        async def proxy_handler(**kwargs) -> str:
            start = time.monotonic()
            try:
                filtered = {k: v for k, v in kwargs.items() if v is not None} if kwargs else None
                result = await _conn.call_tool(_original, filtered if filtered else None)
                duration = (time.monotonic() - start) * 1000
                logger.info(
                    "Proxied call %s -> %s/%s (%.0fms)",
                    _name,
                    _conn.server.name,
                    _original,
                    duration,
                )
                return result
            except Exception as e:
                logger.error("Proxied call failed %s: %s", _name, e)
                return f"Error calling {_original} on {_conn.server.name}: {e}"

        # Dynamically register on the FastMCP server
        # Build the tool with the upstream's input schema
        proxy_handler.__name__ = proxied_name
        proxy_handler.__doc__ = description

        # Use the low-level tool manager to register with the proper schema
        from mcp.server.fastmcp.tools import Tool as FastMCPTool
        from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata

        # Build an arg model from the upstream's input schema so that
        # call_fn_with_arg_validation validates against the real parameters
        # instead of the proxy_handler(**kwargs) signature
        arg_model = self._build_arg_model(input_schema)
        metadata = FuncMetadata(arg_model=arg_model)

        tool = FastMCPTool(
            fn=proxy_handler,
            name=proxied_name,
            description=description,
            parameters=input_schema if input_schema else {"type": "object", "properties": {}},
            fn_metadata=metadata,
            is_async=True,
        )
        register_tool(proxied_name, tool)

    async def _health_loop(self) -> None:
        """Periodically check upstream connections and reconnect if needed."""
        while True:
            await asyncio.sleep(60)
            for name, conn in list(self.connections.items()):
                if not conn.connected and conn.server.auto_restart and conn.server.enabled:
                    lock = self._reconnect_locks.setdefault(name, asyncio.Lock())
                    if lock.locked():
                        continue  # Already reconnecting via manual reconnect()
                    async with lock:
                        logger.info("Attempting reconnect to %s...", name)
                        try:
                            await conn.connect()
                            self._register_proxied_tools(conn)
                            logger.info("Reconnected to %s", name)
                        except Exception as e:
                            logger.warning("Reconnect to %s failed: %s", name, e)

    async def stop(self) -> None:
        """Disconnect from all upstream servers."""
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        tasks = [conn.disconnect() for conn in self.connections.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self.connections.clear()
        self._tool_map.clear()
        logger.info("Proxy manager stopped")

    async def reconnect(self, name: str) -> bool:
        """Manually reconnect to a specific upstream server."""
        if name not in self.connections:
            return False

        lock = self._reconnect_locks.setdefault(name, asyncio.Lock())
        async with lock:
            conn = self.connections[name]
            await conn.disconnect()

            # Remove old proxied tools
            prefix = conn.server.tool_prefix
            to_remove = [k for k in self._tool_map if k.startswith(prefix)]
            for k in to_remove:
                del self._tool_map[k]
                unregister_tool(k)

            try:
                await conn.connect()
                self._register_proxied_tools(conn)
                return True
            except Exception:
                return False

    async def add_server(self, server: UpstreamServer) -> bool:
        """Add and connect to a new upstream server at runtime."""
        self.registry.add(server)
        return await self._connect_server(server)

    def get_status(self) -> dict:
        """Get status of all upstream connections."""
        return {
            "total_servers": len(self.connections),
            "connected": sum(1 for c in self.connections.values() if c.connected),
            "total_proxied_tools": len(self._tool_map),
            "servers": [conn.status for conn in self.connections.values()],
        }

    def get_tool_map(self) -> dict[str, str]:
        """Get mapping of proxied tool names to their upstream source."""
        return {
            name: f"{conn.server.name}/{original}"
            for name, (conn, original) in self._tool_map.items()
        }

    @classmethod
    def from_config(cls, config_path: str | Path, mcp_server: FastMCP) -> ProxyManager:
        """Create a ProxyManager from a YAML config file."""
        registry = UpstreamRegistry.from_yaml(config_path)
        return cls(registry=registry, mcp_server=mcp_server)
