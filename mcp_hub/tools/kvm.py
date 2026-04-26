"""KVM tools — PiKVM HTTP client + multi-KVM port switch logic.

Config loaded from /etc/mcp-hub/pikvm.yaml on first call (lazy, cached).
Credentials from env vars MH_PIKVM_USER / MH_PIKVM_PASSWORD.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, cast

import httpx
import yaml

from mcp_hub.tools._validation import validate_kvm_port, validate_power_action

_CONFIG_PATH = Path("/etc/mcp-hub/pikvm.yaml")
_config: dict[str, Any] | None = None


def _load_config() -> dict[str, Any] | None:
    """Load config from /etc/mcp-hub/pikvm.yaml. Returns None if missing."""
    global _config
    if _config is not None:
        return _config
    if not _CONFIG_PATH.exists():
        return None
    with _CONFIG_PATH.open() as f:
        _config = yaml.safe_load(f)
    return _config


def _get_credentials() -> tuple[str, str] | None:
    """Return (user, password) from env vars, or None if either is missing."""
    user = os.environ.get("MH_PIKVM_USER", "")
    password = os.environ.get("MH_PIKVM_PASSWORD", "")
    if not user or not password:
        return None
    return user, password


class PikvmClient:
    """Async HTTP client for PiKVM API."""

    def __init__(self, base_url: str, user: str, password: str, verify_tls: bool = False) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = (user, password)
        self._verify_tls = verify_tls

    async def get(
        self, path: str, query: dict[str, str] | None = None, accept: str = "application/json"
    ) -> tuple[int, bytes]:
        """GET a path. Returns (status_code, body_bytes)."""
        url = self._base_url + path
        async with httpx.AsyncClient(verify=self._verify_tls) as client:
            resp = await client.get(
                url,
                params=query,
                auth=self._auth,
                headers={"Accept": accept},
                timeout=10.0,
            )
            return resp.status_code, resp.content

    async def post(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        """POST a path with optional query params. Returns parsed JSON."""
        url = self._base_url + path
        async with httpx.AsyncClient(verify=self._verify_tls) as client:
            resp = await client.post(
                url,
                params=query,
                auth=self._auth,
                timeout=10.0,
            )
            if resp.content:
                return cast(dict[str, Any], resp.json())
            return {"ok": True}

    async def snap(self) -> bytes:
        """GET /api/streamer/snapshot with allow_offline=1. Returns JPEG bytes."""
        status, body = await self.get(
            "/api/streamer/snapshot",
            query={"allow_offline": "1"},
            accept="image/jpeg",
        )
        if status != 200:
            raise RuntimeError(f"snapshot failed: HTTP {status}")
        return body

    async def status(self) -> dict[str, Any]:
        """Fetch /api/atx, /api/streamer, /api/hid and combine into one dict."""
        atx_status, atx_body = await self.get("/api/atx")
        stm_status, stm_body = await self.get("/api/streamer")
        hid_status, hid_body = await self.get("/api/hid")
        return {
            "atx": (
                json.loads(atx_body).get("result")
                if atx_status == 200
                else {"error": f"HTTP {atx_status}"}
            ),
            "streamer": (
                json.loads(stm_body).get("result")
                if stm_status == 200
                else {"error": f"HTTP {stm_status}"}
            ),
            "hid": (
                json.loads(hid_body).get("result")
                if hid_status == 200
                else {"error": f"HTTP {hid_status}"}
            ),
        }

    async def send_key(self, key: str, state: int) -> None:
        """Send a key press/release. state: 1=press, 0=release."""
        await self.post("/api/hid/events/send_key", query={"key": key, "state": str(state)})

    async def atx_click(self, button: str) -> dict[str, Any]:
        """POST /api/atx/click?button=<button>."""
        return await self.post("/api/atx/click", query={"button": button})

    async def atx_press_long(self, button: str) -> dict[str, Any]:
        """POST /api/atx/press_long?button=<button>."""
        return await self.post("/api/atx/press_long", query={"button": button})


async def _switch_port(client: PikvmClient, cfg: dict[str, Any], port: int) -> None:
    """Send Ctrl-Ctrl-<digit> hotkey to switch multi-KVM port."""
    hid_status, hid_body = await client.get("/api/hid")
    hid = json.loads(hid_body)["result"]
    if not hid["keyboard"]["online"]:
        raise RuntimeError(
            "keyboard HID offline; cannot switch port until USB-HID cable is connected"
        )
    mk = cfg["multi_kvm"]
    await client.send_key("ControlLeft", 1)
    await asyncio.sleep(0.05)
    await client.send_key("ControlLeft", 0)
    await asyncio.sleep(mk.get("tap_interval_ms", 150) / 1000)
    await client.send_key("ControlLeft", 1)
    await asyncio.sleep(0.05)
    await client.send_key("ControlLeft", 0)
    await asyncio.sleep(0.05)
    await client.send_key(f"Digit{port}", 1)
    await asyncio.sleep(0.05)
    await client.send_key(f"Digit{port}", 0)
    await asyncio.sleep(mk.get("settle_ms", 800) / 1000)


def _make_client(cfg: dict[str, Any], creds: tuple[str, str]) -> PikvmClient:
    """Create a PikvmClient from config and credentials."""
    pikvm = cfg["pikvm"]
    return PikvmClient(
        base_url=pikvm["url"],
        user=creds[0],
        password=creds[1],
        verify_tls=pikvm.get("verify_tls", False),
    )


def _char_to_key(ch: str) -> str | None:
    """Convert a character to a PiKVM HID key name."""
    if ch == " ":
        return "Space"
    if ch == "\n":
        return "Enter"
    if ch.isalpha():
        return f"Key{ch.upper()}"
    if ch.isdigit():
        return f"Digit{ch}"
    syms = {
        "-": "Minus",
        "=": "Equal",
        "[": "BracketLeft",
        "]": "BracketRight",
        "\\": "Backslash",
        ";": "Semicolon",
        "'": "Quote",
        ",": "Comma",
        ".": "Period",
        "/": "Slash",
        "`": "Backquote",
    }
    return syms.get(ch)


# -- Tool functions --


async def list_ports() -> str:
    """List configured KVM ports from config. No HTTP call."""
    cfg = _load_config()
    if cfg is None:
        return f"Error: config file not found at {_CONFIG_PATH}"
    ports = cfg.get("multi_kvm", {}).get("ports", {})
    result = [
        {
            "port": num,
            "name": info.get("name", ""),
            "mgmt_ip": info.get("mgmt_ip"),
            "notes": info.get("notes", ""),
        }
        for num, info in sorted(ports.items())
    ]
    return json.dumps(result)


async def status(port: int = 0) -> str:
    """Get ATX, streamer, and HID status. Optionally switch port first."""
    cfg = _load_config()
    if cfg is None:
        return f"Error: config file not found at {_CONFIG_PATH}"
    creds = _get_credentials()
    if creds is None:
        return "Error: MH_PIKVM_USER or MH_PIKVM_PASSWORD env var not set"
    try:
        validate_kvm_port(port)
        client = _make_client(cfg, creds)
        if port != 0:
            await _switch_port(client, cfg, port)
        result = await client.status()
        return json.dumps(result)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


async def snap(port: int = 0) -> str:
    """Capture a JPEG snapshot. Optionally switch port first. Returns base64-encoded JPEG."""
    cfg = _load_config()
    if cfg is None:
        return f"Error: config file not found at {_CONFIG_PATH}"
    creds = _get_credentials()
    if creds is None:
        return "Error: MH_PIKVM_USER or MH_PIKVM_PASSWORD env var not set"
    try:
        validate_kvm_port(port)
        client = _make_client(cfg, creds)
        if port != 0:
            await _switch_port(client, cfg, port)
        jpeg_bytes = await client.snap()
        return json.dumps(
            {
                "ok": True,
                "format": "jpeg",
                "size_bytes": len(jpeg_bytes),
                "data": base64.b64encode(jpeg_bytes).decode(),
            }
        )
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


async def ocr(port: int = 0, psm: int = 6) -> str:
    """OCR the current HDMI frame using tesseract. Optionally switch port first."""
    if not shutil.which("tesseract"):
        return "Error: tesseract not installed — install it with: apt-get install tesseract-ocr"
    cfg = _load_config()
    if cfg is None:
        return f"Error: config file not found at {_CONFIG_PATH}"
    creds = _get_credentials()
    if creds is None:
        return "Error: MH_PIKVM_USER or MH_PIKVM_PASSWORD env var not set"
    try:
        validate_kvm_port(port)
        client = _make_client(cfg, creds)
        if port != 0:
            await _switch_port(client, cfg, port)
        jpeg_bytes = await client.snap()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            tf.write(jpeg_bytes)
            tmp_path = tf.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "tesseract",
                tmp_path,
                "-",
                "--psm",
                str(psm),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode(errors="replace")
        finally:
            os.unlink(tmp_path)
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


async def switch(port: int) -> str:
    """Switch multi-KVM to a specific port via Ctrl-Ctrl-<digit> hotkey."""
    cfg = _load_config()
    if cfg is None:
        return f"Error: config file not found at {_CONFIG_PATH}"
    creds = _get_credentials()
    if creds is None:
        return "Error: MH_PIKVM_USER or MH_PIKVM_PASSWORD env var not set"
    try:
        validate_kvm_port(port)
        if port == 0:
            return "Error: port must be 1, 2, 3, or 4 for kvm_switch"
        client = _make_client(cfg, creds)
        await _switch_port(client, cfg, port)
        return json.dumps({"ok": True, "active_port": port})
    except ValueError as e:
        return f"Error: {e}"
    except RuntimeError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


async def power(port: int = 0, action: str = "on", confirm: bool = False) -> str:
    """Emulate ATX power button. hard-off requires confirm=True."""
    cfg = _load_config()
    if cfg is None:
        return f"Error: config file not found at {_CONFIG_PATH}"
    creds = _get_credentials()
    if creds is None:
        return "Error: MH_PIKVM_USER or MH_PIKVM_PASSWORD env var not set"
    try:
        validate_kvm_port(port)
        validate_power_action(action)
        if action == "hard-off" and not confirm:
            return (
                "Error: hard-off forces an immediate power cut. "
                "Pass confirm=True to confirm this disruptive action."
            )
        client = _make_client(cfg, creds)
        if port != 0:
            await _switch_port(client, cfg, port)
        if action in ("on", "off"):
            await client.atx_click("power")
        elif action == "reset":
            await client.atx_click("reset")
        elif action == "hard-off":
            await client.atx_press_long("power")
        return json.dumps({"ok": True, "action": action})
    except ValueError as e:
        return f"Error: {e}"
    except RuntimeError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


async def send_keys(port: int = 0, text: str = "") -> str:
    """Type literal text on target via USB HID keyboard emulation."""
    if len(text) > 4096:
        return "Error: text too long (max 4096 characters)"
    cfg = _load_config()
    if cfg is None:
        return f"Error: config file not found at {_CONFIG_PATH}"
    creds = _get_credentials()
    if creds is None:
        return "Error: MH_PIKVM_USER or MH_PIKVM_PASSWORD env var not set"
    try:
        validate_kvm_port(port)
        client = _make_client(cfg, creds)
        if port != 0:
            await _switch_port(client, cfg, port)
        # Check HID online before sending
        hid_status, hid_body = await client.get("/api/hid")
        hid = json.loads(hid_body)["result"]
        if not hid["keyboard"]["online"]:
            return "Error: keyboard HID offline — target won't see keystrokes"
        sent = 0
        for ch in text:
            key = _char_to_key(ch)
            if key is None:
                continue
            shifted = ch.isupper() or ch in '!@#$%^&*()_+{}|:"<>?~'
            if shifted:
                await client.send_key("ShiftLeft", 1)
            await client.send_key(key, 1)
            await asyncio.sleep(0.05)
            await client.send_key(key, 0)
            if shifted:
                await client.send_key("ShiftLeft", 0)
            sent += 1
        return json.dumps({"ok": True, "characters_sent": sent})
    except ValueError as e:
        return f"Error: {e}"
    except RuntimeError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"
