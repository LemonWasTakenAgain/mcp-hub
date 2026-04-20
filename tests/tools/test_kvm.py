"""Tests for KVM tools — all HTTP calls are mocked, no real network access."""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest

from mcp_hub.tools import kvm as kvm_tools

MOCK_CONFIG = {
    "pikvm": {"url": "https://192.168.1.24", "verify_tls": False},
    "multi_kvm": {
        "tap_interval_ms": 150,
        "settle_ms": 100,
        "ports": {
            1: {"name": "pve1", "mgmt_ip": "192.168.1.10", "notes": ""},
            2: {"name": "pve2", "mgmt_ip": "192.168.1.11", "notes": ""},
            3: {"name": "pve3", "mgmt_ip": "192.168.1.12", "notes": ""},
            4: {"name": "unused", "mgmt_ip": None, "notes": ""},
        },
    },
}

# HID responses for keyboard online/offline scenarios
_HID_ONLINE = json.dumps(
    {"result": {"keyboard": {"online": True, "leds": {}}, "mouse": {"online": True}}}
).encode()
_HID_OFFLINE = json.dumps(
    {"result": {"keyboard": {"online": False, "leds": {}}, "mouse": {"online": False}}}
).encode()
_ATX_RESPONSE = json.dumps({"result": {"leds": {"power": True, "hdd": False}}}).encode()
_STREAMER_RESPONSE = json.dumps(
    {"result": {"source": {"online": True, "resolution": "1920x1080", "captured_fps": 30}}}
).encode()


@pytest.fixture(autouse=True)
def reset_config_cache():
    """Reset the module-level config cache between tests."""
    original = kvm_tools._config
    yield
    kvm_tools._config = original


# ── 1. No config file ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_ports_no_config():
    with patch.object(kvm_tools, "_load_config", return_value=None):
        result = await kvm_tools.list_ports()
    assert "Error" in result
    assert "config" in result.lower()


# ── 2. Config present → list ports ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_ports_returns_list():
    with patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG):
        result = await kvm_tools.list_ports()
    data = json.loads(result)
    assert isinstance(data, list)
    assert len(data) == 4
    names = [p["name"] for p in data]
    assert "pve1" in names
    assert "pve2" in names
    ports = [p["port"] for p in data]
    assert sorted(ports) == [1, 2, 3, 4]


# ── 3. kvm_status calls ATX/streamer/HID ──────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_status_calls_endpoints():
    mock_client = AsyncMock()
    mock_client.status = AsyncMock(
        return_value={
            "atx": {"leds": {"power": True, "hdd": False}},
            "streamer": {"source": {"online": True, "resolution": "1920x1080"}},
            "hid": {"keyboard": {"online": True, "leds": {}}, "mouse": {"online": True}},
        }
    )

    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
        patch.object(kvm_tools, "_make_client", return_value=mock_client),
    ):
        result = await kvm_tools.status()

    data = json.loads(result)
    assert "atx" in data
    assert "streamer" in data
    assert "hid" in data
    assert data["atx"]["leds"]["power"] is True


# ── 4. kvm_snap returns base64 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_snap_returns_base64():
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal fake JPEG header
    mock_client = AsyncMock()
    mock_client.snap = AsyncMock(return_value=fake_jpeg)

    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
        patch.object(kvm_tools, "_make_client", return_value=mock_client),
    ):
        result = await kvm_tools.snap()

    data = json.loads(result)
    assert data["ok"] is True
    assert data["format"] == "jpeg"
    assert data["size_bytes"] == len(fake_jpeg)
    decoded = base64.b64decode(data["data"])
    assert decoded == fake_jpeg


# ── 5. kvm_ocr — no tesseract ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_ocr_no_tesseract():
    with patch("shutil.which", return_value=None):
        result = await kvm_tools.ocr()
    assert "Error" in result
    assert "tesseract" in result.lower()


# ── 6. kvm_switch rejects bad port ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_switch_rejects_bad_port():
    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
    ):
        result = await kvm_tools.switch(5)
    assert "Error" in result
    assert "5" in result


# ── 7. kvm_switch refuses when HID offline ────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_switch_refuses_when_hid_offline():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=(200, _HID_OFFLINE))

    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
        patch.object(kvm_tools, "_make_client", return_value=mock_client),
    ):
        result = await kvm_tools.switch(2)

    assert "Error" in result
    assert "offline" in result.lower()


# ── 8. kvm_switch succeeds when HID online ────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_switch_succeeds_when_hid_online():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=(200, _HID_ONLINE))
    mock_client.send_key = AsyncMock()

    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
        patch.object(kvm_tools, "_make_client", return_value=mock_client),
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        result = await kvm_tools.switch(2)

    data = json.loads(result)
    assert data["ok"] is True
    assert data["active_port"] == 2


# ── 9. kvm_power hard-off requires confirm ────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_power_hard_off_requires_confirm():
    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
    ):
        result = await kvm_tools.power(action="hard-off", confirm=False)
    assert "Error" in result
    assert "confirm" in result.lower()


# ── 10. kvm_power hard-off with confirm calls atx_press_long ─────────────────


@pytest.mark.asyncio
async def test_kvm_power_hard_off_with_confirm():
    mock_client = AsyncMock()
    mock_client.atx_press_long = AsyncMock(return_value={"ok": True})

    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
        patch.object(kvm_tools, "_make_client", return_value=mock_client),
    ):
        result = await kvm_tools.power(action="hard-off", confirm=True)

    data = json.loads(result)
    assert data["ok"] is True
    mock_client.atx_press_long.assert_called_once_with("power")


# ── 11. kvm_power rejects bad action ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_power_rejects_bad_action():
    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
    ):
        result = await kvm_tools.power(action="explode")
    assert "Error" in result
    assert "explode" in result


# ── 12. kvm_send_keys rejects long text ───────────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_send_keys_rejects_long_text():
    long_text = "a" * 4097
    result = await kvm_tools.send_keys(text=long_text)
    assert "Error" in result
    assert "4096" in result


# ── 13. kvm_send_keys refuses when HID offline ────────────────────────────────


@pytest.mark.asyncio
async def test_kvm_send_keys_refuses_when_hid_offline():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=(200, _HID_OFFLINE))

    with (
        patch.object(kvm_tools, "_load_config", return_value=MOCK_CONFIG),
        patch.object(kvm_tools, "_get_credentials", return_value=("admin", "secret")),
        patch.object(kvm_tools, "_make_client", return_value=mock_client),
    ):
        result = await kvm_tools.send_keys(text="hello")

    assert "Error" in result
    assert "offline" in result.lower()
