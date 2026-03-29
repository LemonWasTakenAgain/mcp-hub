"""MCP client connector — manages a connection to a single upstream MCP server."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import Tool

from mcp_hub.proxy.registry import TransportType, UpstreamServer

logger = logging.getLogger("mcp_hub.proxy")


@dataclass
class UpstreamConnection:
    """A live connection to an upstream MCP server."""

    server: UpstreamServer
    session: ClientSession | None = None
    tools: list[Tool] = field(default_factory=list)
    connected: bool = False
    error: str | None = None
    _stack: AsyncExitStack | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _consecutive_failures: int = 0
    _circuit_open_until: float = 0.0

    async def connect(self) -> None:
        """Establish connection to the upstream server and discover tools."""
        async with self._lock:
            if self.connected:
                return
            # Clean up any leftover stack from a broken connection
            if self._stack is not None:
                try:
                    await self._stack.aclose()
                except Exception:
                    pass
                self._stack = None
                self.session = None
            try:
                self._stack = AsyncExitStack()
                await self._stack.__aenter__()

                if self.server.transport == TransportType.STDIO:
                    await self._connect_stdio()
                elif self.server.transport == TransportType.SSE:
                    await self._connect_sse()

                # Initialize the session
                await self.session.initialize()

                # Discover tools
                result = await self.session.list_tools()
                self.tools = result.tools
                self.connected = True
                self.error = None

                logger.info(
                    "Connected to %s: %d tools discovered",
                    self.server.name,
                    len(self.tools),
                )

            except Exception as e:
                self.error = str(e)
                self.connected = False
                logger.error("Failed to connect to %s: %s", self.server.name, e)
                if self._stack:
                    await self._stack.aclose()
                    self._stack = None
                raise

    async def _connect_stdio(self) -> None:
        """Connect via stdio transport (spawns a subprocess)."""
        params = StdioServerParameters(
            command=self.server.command,
            args=self.server.args,
            env=self.server.env if self.server.env else None,
        )
        stdio_transport = await self._stack.enter_async_context(stdio_client(params))
        read_stream, write_stream = stdio_transport
        self.session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

    async def _connect_sse(self) -> None:
        """Connect via SSE transport (HTTP connection)."""
        sse_transport = await self._stack.enter_async_context(
            sse_client(
                url=self.server.url,
                headers=self.server.headers if self.server.headers else None,
            )
        )
        read_stream, write_stream = sse_transport
        self.session = await self._stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> str:
        """Call a tool on the upstream server."""
        if not self.connected or not self.session:
            raise ConnectionError(f"Not connected to {self.server.name}")

        if time.monotonic() < self._circuit_open_until:
            raise ConnectionError(f"Circuit open for {self.server.name}, retry after cooldown")

        try:
            result = await asyncio.wait_for(
                self.session.call_tool(tool_name, arguments or {}),
                timeout=self.server.timeout,
            )
            # Combine all content blocks into a string
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                elif hasattr(content, "data"):
                    parts.append(f"[binary data: {content.mimeType}]")
                else:
                    parts.append(str(content))
            self._consecutive_failures = 0
            return "\n".join(parts)

        except TimeoutError:
            raise TimeoutError(
                f"Tool {tool_name} on {self.server.name} timed out after {self.server.timeout}s"
            )
        except Exception as e:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._circuit_open_until = time.monotonic() + 60.0
                logger.warning(
                    "Circuit opened for %s after %d consecutive failures — skipping for 60s",
                    self.server.name,
                    self._consecutive_failures,
                )
            if self.server.auto_restart:
                logger.warning(
                    "Tool call failed on %s, will reconnect: %s",
                    self.server.name,
                    e,
                )
                self.connected = False
            raise

    async def refresh_tools(self) -> list[Tool]:
        """Re-discover tools from the upstream server."""
        if not self.connected or not self.session:
            await self.connect()
        result = await self.session.list_tools()
        self.tools = result.tools
        return self.tools

    async def disconnect(self) -> None:
        """Disconnect from the upstream server."""
        async with self._lock:
            if self._stack:
                try:
                    await self._stack.aclose()
                except Exception as e:
                    logger.warning("Error disconnecting from %s: %s", self.server.name, e)
                self._stack = None
            self.session = None
            self.connected = False
            self.tools = []
            logger.info("Disconnected from %s", self.server.name)

    @property
    def status(self) -> dict:
        return {
            "name": self.server.name,
            "transport": self.server.transport.value,
            "connected": self.connected,
            "tools": len(self.tools),
            "error": self.error,
        }
