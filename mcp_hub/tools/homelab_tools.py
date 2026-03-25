"""Homelab utility tools for MCP."""

from __future__ import annotations

import asyncio
import platform
import shutil
from datetime import datetime, timezone

from mcp_hub.tools._validation import validate_hostname, validate_port, validate_url


async def system_info() -> str:
    """Get system information for the host running MCP Hub."""
    uname = platform.uname()
    disk = shutil.disk_usage("/")

    lines = [
        "## System Information\n",
        f"- **Hostname**: {uname.node}",
        f"- **OS**: {uname.system} {uname.release}",
        f"- **Architecture**: {uname.machine}",
        f"- **Python**: {platform.python_version()}",
        f"- **Disk**: {disk.used // (1024**3)} GB used / {disk.total // (1024**3)} GB total "
        f"({disk.free // (1024**3)} GB free)",
        f"- **Time**: {datetime.now(timezone.utc).isoformat()}",
    ]

    try:
        with open("/proc/meminfo") as f:
            mem_lines = f.readlines()
        mem_total = mem_avail = ""
        for line in mem_lines:
            if line.startswith("MemTotal:"):
                mem_total = line.split(":")[1].strip()
            elif line.startswith("MemAvailable:"):
                mem_avail = line.split(":")[1].strip()
        lines.append(f"- **Memory**: {mem_avail} available / {mem_total} total")
    except FileNotFoundError:
        pass

    try:
        with open("/proc/loadavg") as f:
            load = f.read().split()[:3]
        lines.append(f"- **Load**: {' '.join(load)}")
    except FileNotFoundError:
        pass

    return "\n".join(lines)


async def ping_host(host: str) -> str:
    """Ping a host and return the result.

    Args:
        host: Hostname or IP address to ping
    """
    try:
        host = validate_hostname(host)
    except ValueError as e:
        return f"Invalid host: {e}"

    proc = await asyncio.create_subprocess_exec(
        "ping", "-c", "3", "-W", "2", host,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        return f"Ping {host} succeeded:\n```\n{stdout.decode()}\n```"
    return f"Ping {host} failed (exit code {proc.returncode}):\n```\n{stderr.decode()}\n```"


async def check_service(host: str, port: int) -> str:
    """Check if a TCP service is reachable.

    Args:
        host: Hostname or IP address
        port: TCP port number
    """
    try:
        host = validate_hostname(host)
        port = validate_port(port)
    except ValueError as e:
        return f"Invalid input: {e}"

    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
        return f"Service at {host}:{port} is **reachable**."
    except (ConnectionRefusedError, OSError) as e:
        return f"Service at {host}:{port} is **unreachable**: {e}"
    except asyncio.TimeoutError:
        return f"Service at {host}:{port} **timed out** after 5 seconds."


async def dns_lookup(hostname: str) -> str:
    """Perform a DNS lookup using dig.

    Args:
        hostname: Domain name to resolve
    """
    try:
        hostname = validate_hostname(hostname)
    except ValueError as e:
        return f"Invalid hostname: {e}"

    proc = await asyncio.create_subprocess_exec(
        "dig", "+short", hostname,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    result = stdout.decode().strip()
    if result:
        return f"DNS lookup for {hostname}:\n{result}"
    return f"No DNS records found for {hostname}."


async def http_check(url: str) -> str:
    """Check HTTP endpoint status and response time.

    Args:
        url: Full URL to check (e.g., http://gitlab.homelab.local)
    """
    try:
        url = validate_url(url)
    except ValueError as e:
        return f"Invalid URL: {e}"

    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            return (
                f"**{url}**\n"
                f"- Status: {resp.status_code} {resp.reason_phrase}\n"
                f"- Content-Type: {resp.headers.get('content-type', 'unknown')}\n"
                f"- Size: {len(resp.content)} bytes"
            )
    except httpx.HTTPError as e:
        return f"HTTP check failed for {url}: {e}"
