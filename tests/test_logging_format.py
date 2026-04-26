"""Tests for structured JSON logging."""

from __future__ import annotations

import json
import logging

from mcp_hub.logging_config import JSONFormatter, configure_logging, request_id_var


def _make_record(msg: str = "test message", level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="test.logger",
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_json_formatter_produces_valid_json() -> None:
    formatter = JSONFormatter()
    output = formatter.format(_make_record("hello world"))
    parsed = json.loads(output)
    assert parsed["msg"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.logger"
    assert "ts" in parsed


def test_json_formatter_includes_all_required_fields() -> None:
    formatter = JSONFormatter()
    parsed = json.loads(formatter.format(_make_record()))
    for field in ("ts", "level", "logger", "msg"):
        assert field in parsed, f"expected field '{field}' in JSON output"


def test_json_formatter_includes_request_id_from_contextvar() -> None:
    formatter = JSONFormatter()
    token = request_id_var.set("req-abc-123")
    try:
        parsed = json.loads(formatter.format(_make_record("with request_id")))
        assert parsed["request_id"] == "req-abc-123"
    finally:
        request_id_var.reset(token)


def test_json_formatter_omits_request_id_when_not_set() -> None:
    formatter = JSONFormatter()
    token = request_id_var.set(None)
    try:
        parsed = json.loads(formatter.format(_make_record("no request_id")))
        assert "request_id" not in parsed
    finally:
        request_id_var.reset(token)


def test_json_formatter_includes_extra_fields() -> None:
    formatter = JSONFormatter()
    record = _make_record("mcp_tool call")
    record.__dict__["event"] = "mcp_tool"
    record.__dict__["tool_name"] = "ticket_create"
    record.__dict__["duration_ms"] = 42.1
    record.__dict__["success"] = True
    parsed = json.loads(formatter.format(record))
    assert parsed["event"] == "mcp_tool"
    assert parsed["tool_name"] == "ticket_create"
    assert parsed["duration_ms"] == 42.1
    assert parsed["success"] is True


def test_json_formatter_extra_does_not_duplicate_standard_fields() -> None:
    formatter = JSONFormatter()
    record = _make_record("dedup test")
    # These are standard LogRecord fields — should not appear twice or as raw values
    parsed = json.loads(formatter.format(record))
    assert "levelno" not in parsed
    assert "pathname" not in parsed
    assert "lineno" not in parsed


def test_configure_logging_installs_json_handler() -> None:
    configure_logging(debug=False)
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JSONFormatter)
    assert root.level == logging.INFO


def test_configure_logging_debug_sets_debug_level() -> None:
    configure_logging(debug=True)
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    # Restore to avoid polluting other tests
    configure_logging(debug=False)
