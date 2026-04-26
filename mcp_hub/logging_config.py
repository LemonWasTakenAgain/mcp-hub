"""Structured JSON logging for MCP Hub.

Provides:
- JSONFormatter: emits each log record as a single JSON line
- request_id_var: contextvar automatically included in every log record
- configure_logging(): replaces all handlers with JSON output
- instrument_tools(): wraps registered FastMCP tool fns to log invocations
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_tool_logger = logging.getLogger("mcp_hub.tools")

# Standard LogRecord attributes — excluded from the JSON extra fields to avoid noise
_SKIP_FIELDS = frozenset(
    {
        "name",
        "msg",
        "args",
        "created",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "exc_info",
        "exc_text",
        "taskName",
    }
)


class JSONFormatter(logging.Formatter):
    """Format each log record as a single JSON line for Loki ingestion.

    Automatically injects ``request_id`` from the contextvar when set.
    Extra fields passed via ``logging.info(..., extra={...})`` appear as
    top-level JSON keys alongside ``ts``, ``level``, ``logger``, ``msg``.
    """

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid is not None:
            out["request_id"] = rid
        # Merge in extra= fields, skipping standard LogRecord internals
        for key, val in record.__dict__.items():
            if key not in _SKIP_FIELDS and not key.startswith("_"):
                out[key] = val
        if record.exc_info:
            out["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(debug: bool = False) -> None:
    """Replace root logger handlers with a single JSON stream handler.

    Call once at application startup (in FastAPI lifespan) before any request
    processing begins. Suppresses high-volume libraries to WARNING.
    """
    level = logging.DEBUG if debug else logging.INFO
    formatter = JSONFormatter()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Propagate uvicorn loggers through root so they also emit JSON
    for uv_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(uv_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

    # Suppress high-volume / low-signal loggers
    for noisy in ("uvicorn.access", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def instrument_tools(mcp_server: Any) -> None:
    """Wrap every registered FastMCP tool fn to emit a structured log line.

    Replaces ``tool.fn`` on each registered tool with an async wrapper that
    logs ``{event: mcp_tool, tool_name, duration_ms, success}`` after every
    invocation. Must be called after all tools (including proxied) are registered.
    """
    tool_manager = getattr(mcp_server, "_tool_manager", None)
    if tool_manager is None:
        _tool_logger.warning("instrument_tools: no _tool_manager found on mcp_server")
        return

    tools: dict[str, Any] = getattr(tool_manager, "_tools", {})
    count = 0
    for tool_name, tool_obj in tools.items():
        original_fn: Any = getattr(tool_obj, "fn", None)
        if original_fn is None or not asyncio.iscoroutinefunction(original_fn):
            continue

        @functools.wraps(original_fn)
        async def _timed(
            *args: Any,
            _fn: Any = original_fn,
            _name: str = tool_name,
            **kwargs: Any,
        ) -> Any:
            start = time.monotonic()
            exc: BaseException | None = None
            try:
                return await _fn(*args, **kwargs)
            except BaseException as e:
                exc = e
                raise
            finally:
                duration_ms = round((time.monotonic() - start) * 1000, 1)
                _tool_logger.info(
                    "mcp_tool",
                    extra={
                        "event": "mcp_tool",
                        "tool_name": _name,
                        "duration_ms": duration_ms,
                        "success": exc is None,
                    },
                )

        tool_obj.fn = _timed
        count += 1

    _tool_logger.info(
        "tools instrumented",
        extra={"event": "tools_instrumented", "count": count},
    )
