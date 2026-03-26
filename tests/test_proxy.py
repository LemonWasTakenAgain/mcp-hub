"""Test proxy registry and environment resolution."""

import os

from mcp_hub.proxy.env_resolver import resolve_env_vars, resolve_server_env
from mcp_hub.proxy.registry import TransportType, UpstreamRegistry, UpstreamServer


def test_upstream_server_default_prefix():
    server = UpstreamServer(name="brave-search", transport=TransportType.STDIO)
    assert server.prefix == "brave_search"
    assert server.tool_prefix == "brave_search__"


def test_upstream_server_custom_prefix():
    server = UpstreamServer(name="brave-search", transport=TransportType.STDIO, prefix="brave")
    assert server.prefix == "brave"
    assert server.tool_prefix == "brave__"


def test_registry_add_and_get():
    registry = UpstreamRegistry()
    server = UpstreamServer(name="test", transport=TransportType.STDIO, enabled=True)
    registry.add(server)
    assert len(registry.get_enabled()) == 1

    registry.disable("test")
    assert len(registry.get_enabled()) == 0

    registry.enable("test")
    assert len(registry.get_enabled()) == 1


def test_resolve_env_vars():
    os.environ["TEST_MCP_KEY"] = "secret123"
    result = resolve_env_vars("Bearer ${TEST_MCP_KEY}")
    assert result == "Bearer secret123"
    del os.environ["TEST_MCP_KEY"]


def test_resolve_env_vars_missing():
    result = resolve_env_vars("${NONEXISTENT_VAR_12345}")
    assert result == ""


def test_resolve_server_env():
    os.environ["TEST_API_KEY"] = "mykey"
    server = UpstreamServer(
        name="test",
        transport=TransportType.STDIO,
        command="npx",
        args=["-y", "test-server", "${TEST_API_KEY}"],
        env={"API_KEY": "${TEST_API_KEY}"},
    )
    resolved = resolve_server_env(server)
    assert resolved.env["API_KEY"] == "mykey"
    assert resolved.args[2] == "mykey"
    del os.environ["TEST_API_KEY"]


def test_registry_yaml_roundtrip(tmp_path):
    registry = UpstreamRegistry()
    registry.add(
        UpstreamServer(
            name="test-server",
            transport=TransportType.STDIO,
            enabled=True,
            description="A test server",
            command="npx",
            args=["-y", "test-pkg"],
            env={"KEY": "value"},
            prefix="test",
        )
    )
    registry.add(
        UpstreamServer(
            name="remote",
            transport=TransportType.SSE,
            enabled=False,
            url="http://localhost:9000/sse",
            prefix="remote",
        )
    )

    path = tmp_path / "test_upstreams.yaml"
    registry.to_yaml(path)

    loaded = UpstreamRegistry.from_yaml(path)
    assert len(loaded.servers) == 2
    assert loaded.servers["test-server"].command == "npx"
    assert loaded.servers["remote"].transport == TransportType.SSE
    assert loaded.servers["remote"].url == "http://localhost:9000/sse"
