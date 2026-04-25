# MCP Hub: PiKVM / Multi-KVM Integration Design

**Author:** Infra Planner
**Date:** 2026-04-19
**Status:** Implemented in MR !59 (kvm_* MCP tool family, merged 2026-04-20)
**Reference implementation:** `~/bin/pikvm` (Python CLI, works against PiKVM at 192.168.1.24)

## Problem

Monitoring Proxmox hypervisors (pve1/pve2/pve3) during BIOS, boot, or memtest requires the PiKVM at `https://192.168.1.24`. Today every agent session:

1. Hard-codes the PiKVM URL + HTTP Basic credentials in ad-hoc `curl` calls
2. Re-implements snapshot, OCR, ATX polling, and error-parsing logic from scratch
3. Cannot switch ports on the attached multi-KVM (a physical TESmart-class switch) without knowing the `Ctrl-Ctrl-<digit>` hotkey sequence

This is error-prone (leaked credentials in session logs), redundant (already-rewritten twice), and blocks any cross-session automation like cron-driven health checks.

## Goal

Expose PiKVM + multi-KVM capabilities as **first-class MCP tools** on the existing `mcp-hub` service. Agents call `kvm_snap(port=1)` instead of curling an authenticated URL.

## Non-Goals

- WebRTC / live H.264 streaming — snapshot is enough for agentic monitoring
- Mass-storage device (MSD) ISO mounting — separate follow-up if useful
- Serial-over-LAN — this ASUS X99-A II doesn't wire a serial port anyway

## Architecture

```
┌──────────────┐     MCP/SSE      ┌───────────────┐    HTTPS+Basic   ┌────────────┐
│  Agent       │ ───────────────> │  mcp-hub pod  │ ───────────────> │  PiKVM     │
│  (Claude)    │ <─────────────── │  (Python)     │ <─────────────── │  192.168.  │
└──────────────┘                  └───────────────┘                  │  1.24      │
                                         │                           └──────┬─────┘
                                         │ K8s Secret                       │ USB-HID
                                         │ pikvm-credentials                │ HDMI-in
                                         ▼                                  ▼
                                     /etc/mcp-hub/pikvm.yaml          ┌────────────┐
                                                                      │ Multi-KVM  │
                                                                      │ 1:pve1     │
                                                                      │ 2:pve2     │
                                                                      │ 3:pve3     │
                                                                      │ 4:(unused) │
                                                                      └────────────┘
```

Key points:
- **Credentials live in a K8s Secret** (`pikvm-credentials` in the `mcp-hub` namespace), mounted as env vars into the pod. Agents never see the password.
- **Ports routable?** Yes — mcp-hub pod is on VLAN 40 pod network, PiKVM is on VLAN 1. Inter-VLAN routing between VLAN 1 and VLAN 40 works via the 192.168.1.1 gateway. No new firewall rules required.
- **Statelessness:** port-switching is implicit: every tool that touches a specific host calls `switch_port(port)` first. Agents pass `port` as an argument; the hub tracks "current port" as a hint only, not a source of truth.

## Proposed MCP Tools

| Tool | Args | Returns | Notes |
|------|------|---------|-------|
| `kvm_ports` | — | list of `{port, name, mgmt_ip, notes}` | Static from config |
| `kvm_status` | `port?` | `{atx, streamer, hid}` dict | Switches first if `port` given |
| `kvm_snap` | `port?` | base64 JPEG or image-content part | Returns the current HDMI frame |
| `kvm_ocr` | `port?`, `psm?` | OCR text | Tesseract on the snapshot |
| `kvm_switch` | `port` | `{ok, active_port}` | Ctrl-Ctrl-digit hotkey. **Refuses if `keyboard_hid.online=false`** |
| `kvm_power` | `port?`, `action: on/off/hard-off/reset` | `{ok}` | ATX button emulation |
| `kvm_send_keys` | `port?`, `text` | `{ok}` | Literal typing; follow-up could accept key-combo strings like `ctrl+alt+del` |
| `kvm_watch_start` | `port`, `name`, `subject` | `{watcher_id}` | Background coroutine polling every 30s |
| `kvm_watch_events` | `watcher_id`, `since?` | list of events | Returns accumulated events since cursor |
| `kvm_watch_stop` | `watcher_id` | `{ok}` | Terminates the watcher |

The `watch_*` family is the critical addition for agentic long-duration tasks (memtest runs, BIOS observation, cluster-node reboots). The watcher runs **server-side** in the hub so it survives individual agent sessions ending.

## Safety

- **`kvm_switch` and `kvm_send_keys`** are HID operations — they can interrupt anything running on the target. Tool descriptions must make this clear. Recommended guardrail: hub refuses these tools for any port whose config has `locked: true`. Default `locked: false`.
- **`kvm_power` with `action=hard-off`** should require an explicit confirmation arg (`confirm: true`) to avoid accidental force-off.
- **Credential scope:** the K8s Secret is readable only by the mcp-hub ServiceAccount. Not mirrored into logs or traces.

## Known Blockers (must resolve before MVP)

1. **PiKVM keyboard HID is currently offline** (`keyboard.online: false`). The mouse HID works (`mouse.online: true`) — probably a USB-HID cable issue on the console side of the multi-KVM. **Until this is fixed, `kvm_switch` and `kvm_send_keys` will always fail the preflight check.** Reference implementation already enforces this. Fix: try USB-C-to-USB-C cable (from prior session), or plug PiKVM's HID out directly into the multi-KVM's dedicated keyboard input if available.
2. **Multi-KVM hotkey assumption:** Config assumes `Ctrl-Ctrl-<digit>` with ~150ms inter-tap delay. If the physical switch uses a different hotkey (Scroll-Scroll, NumLock-NumLock, etc.), update `multi_kvm.hotkey` / `tap_interval_ms` in config.

## Implementation Plan

1. Dev Manager files an implementation ticket using this doc as spec
2. Dev Manager implements `src/mcp_hub/tools/kvm.py` with the tool functions above, plus a thin `PikvmClient` class (mirrors the `~/bin/pikvm` Python CLI)
3. K8s secret created: `kubectl -n mcp-hub create secret generic pikvm-credentials --from-literal=user=admin --from-literal=password=<redacted>`. SOPS-encrypted YAML in `~/projects/homelab/kubernetes/` committed via Infra Planner
4. mcp-hub Helm values updated to mount the secret + config (Infra Planner half)
5. Integration test: agent calls `kvm_ocr(port=1)` and confirms it gets pve1's current screen
6. Follow-up: add `kvm_watch_*` with Redis-backed event queue for long-running observation

## Reference Implementation

`~/bin/pikvm` is a ~300-line Python CLI that already exposes all non-watch endpoints. It shares the same conceptual model: config in `~/.config/pikvm/config.yaml`, one subcommand per MCP tool, same port-switch preflight, same error handling. Dev Manager should port its `PikvmClient`-equivalent logic directly into the hub — the endpoint paths, auth, and PiKVM quirks (e.g. `allow_offline=1` for snapshots, stuck ATX LED on ASUS boards) are all already validated.

## Open Questions

- Do we also want to expose the PiKVM **websocket** HID stream for low-latency typing? Not needed for monitoring; defer.
- Should `kvm_watch_*` events publish to the MCP Hub ticket queue, or stay private to the watcher? Proposed: private; expose with a separate `kvm_watch_subscribe` tool later.
