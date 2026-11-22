# insta360-x5-remote

**English** · [中文](README.zh-CN.md)

Reverse-engineering notes and tooling for operating an **Insta360 X5** as a
remotely-controllable network node — wake it, keep it awake, put it on a
network, and pull its live preview — from a small always-on gateway (e.g. a
Raspberry Pi) instead of the phone app.

> Independent research for interoperability with hardware you own. Not
> affiliated with or endorsed by Arashi Vision / Insta360. Use at your own risk.
> Modifying a camera can brick it or void its warranty.

---

## TL;DR — what works today

| Capability | Status | How |
|---|---|---|
| Unpack the firmware | ✅ | UBI/UBIFS, **not encrypted** → extract rootfs |
| Identify the platform | ✅ | Ambarella CV5, Linux 5.10 aarch64, Broadcom BCM43456 (dual-band) Wi-Fi |
| Root shell on the camera | ✅ | SD-card boot hook (reversible — remove card = stock) |
| BLE control (wake / status / capture / power / Wi-Fi config) | ✅ | [`insta360ctl`](https://github.com/xaionaro-go/insta360ctl) + [X5 BLE patches](https://github.com/soul667/insta360-x5-toolkit) |
| **Remote wake from standby** | ✅ | Camera keeps advertising BLE while "asleep"; a BLE command brings it back in seconds |
| **Keep-awake** | ✅ | Hold a BLE session + heartbeat (emulates the app) → camera stays up & on the network |
| Join an existing Wi-Fi network (STA) | ✅ | BLE `SET_WIFI_CONNECTION_INFO` (needs the **plaintext** PSK, not the 64-hex key) |
| Local control API (OSC) | ✅ | HTTP OSC on `:80` (`/osc/info`, `/osc/state`, `camera.getOptions`, `camera.startCapture`, …) |
| Decode the live-preview protocol (port 6666) | ✅ | `syNceNdinS` framing, H.264 High dual-fisheye, `START_LIVE_STREAM` |
| Forward a stream to a VPS and watch remotely | ✅ | VPN overlay + MediaMTX/go2rtc (standard, off-the-shelf) |
| **On-device / LAN live preview without a hotspot client** | ❌ | Blocked by an access gate (see below) |

The **one missing link** for fully-remote live view is a **real Wi-Fi client
associated to the camera's own hotspot** (the camera's AP is 5 GHz, so a
2.4 GHz-only gateway cannot associate to it as-is).

---

## Platform

- **SoC:** Ambarella CV5 (ARM64 Cortex-A53 + CVflow NPU/DSP + RTOS co-core)
- **OS (Linux side):** Linux 5.10.x aarch64 (BusyBox userland, hostname `buildroot`)
- **Wi-Fi/BT:** Broadcom BCM43456 — dual-band, the stock image loads the
  **concurrent AP+STA ("apsta") firmware** by default
- **Key daemons:** `instaAIP` (network / OSC / port-6666 message server),
  `instaAlg` (stitching), `amba_camctrl` (IPC bridge to the RTOS),
  `instaMonitor` (process supervisor)

Firmware container is plain (not encrypted): the `linux` volume is a standard
UBI image. Carve from the first `UBI#` marker and extract UBIFS with
`ubireader`.

---

## How the camera decides "a client is connected"

Understanding this is the key to everything else. The camera correlates
**three independent signals**, not one:

1. **BLE link + session** — a GATT server (service `0xBE80`, chars
   `0xBE81/0xBE82`). Link-up is a controller event; a *session* also needs the
   `syNceNdinS` handshake and a periodic heartbeat (`InsApp_HeartBeat_Thread`).
2. **802.11 association** — when a station associates to the hotspot, `hostapd`
   fires an event (`hostapd_event.sh`) that sets an internal
   `ap_monitor_running` flag and records the client. This is a hardware-level
   event; it cannot be forged in software from a non-associated host.
3. **Port-6666 session** — a TCP control/preview channel with its own handshake,
   a recorded client MAC, and keepalives (there's a "first packet timeout" /
   idle-timeout reaper).

Consequences we observed:

- **It auto-leaves a joined Wi-Fi network ~120 s after the BLE session ends** —
  the STA link is tied to the app session, so a keep-awake must hold BLE.
- **The preview (6666) only serves a genuinely associated hotspot client** — see
  the gate.

---

## The port-6666 access gate (decompiled)

The preview/control server lives in the thread
`InsMDev_Wifi_Connect_Monitor` inside `instaAIP`. Three checks keep
non-hotspot clients out (addresses are from one specific build; treat as a map,
not gospel):

- an outer `ap_monitor_running == 0` guard that skips the whole `select/accept`
  block when no hotspot client is associated,
- an inner `ap_monitor_running == 0` guard right before `accept()`
  (logs `"Wifi ap_monitor_running is false, skip accept."`),
- a **client-MAC check**: `strncmp(client_mac, authorized_mac)` — a mismatch is
  rejected with `"diff mac not allow connect"`.

This is why connecting to `:6666` from the LAN, from loopback, or source-bound
to a fake `192.168.42.x` address all **accept the TCP connection but never
answer the handshake** — the server is gated on a *real association*, not on the
peer IP.

Patching these branches to NOP is mechanically trivial and the boot hook can run
a modified `instaAIP` (reversibly). **But** deploying/validating a modified
main daemon on this closed box is impractical **without a hardware serial
console**: `instaAIP` actively re-grabs the USB gadget, reverts `hostapd`, and
owns the BT stack, and exFAT log writes don't flush — so blind deploys leave the
camera unrecoverable remotely. A UART is the honest prerequisite for that path.

---

## Reverse-engineering method (reproducible)

1. **Firmware:** carve the UBI volume, extract UBIFS with `ubireader`.
2. **Triage:** `strings` + a custom **AArch64 xref tool** that resolves
   `ADRP+ADD` / `ADRP+LDR` literal-pool references (plain `objdump | grep`
   misses the literal-pool form). Map log strings → the functions that use them.
3. **Follow the syscalls:** locate the single `accept()` / `getpeername()` call
   sites to find the server loop.
4. **Decompile:** Ghidra (headless). On an **aarch64 host** the public release
   ships no native decompiler — build it from source:
   `make -C Ghidra/Features/Decompiler/src/decompile/cpp ghidra_opt ARCH_TYPE=`
   (needs `bison`/`flex`; the Makefile's default `-m32` is wrong for arm64, so
   override `ARCH_TYPE=`), then drop `ghidra_opt` in as
   `…/Decompiler/os/linux_arm_64/decompile`. Ghidra 12.x needs JDK 25.
5. **Protocol:** capture the official app over the hotspot (`tcpdump` on a rooted
   phone), reassemble the port-6666 TCP stream, and decode the length-prefixed
   `syNceNdinS` frames + the multiplexed H.264 substream.

---

## Architecture (reference)

```
                 BLE: wake / keep-awake / Wi-Fi config / control
   ┌─────────────────────────────────────────────────────────┐
   │                                                          ▼
[gateway]  ── Wi-Fi client ──▶  [X5 hotspot]  ── 6666 ──▶  H.264 dual-fisheye
   │  (needs 5 GHz to                                         │
   │   associate to the AP)                                   ▼
   └── wired/uplink ──▶ [VPS: stitch + MediaMTX] ──VPN──▶ phone (remote view)
```

The gateway can be any always-on box with BLE + a 5 GHz Wi-Fi client
(e.g. a Raspberry Pi with a cheap Linux-friendly 5 GHz USB adapter). Because the
6666 gate requires a *real* associated client, the gateway's Wi-Fi radio must be
able to join the camera's 5 GHz AP.

---

## Status / limitations

- **Live, fully-standalone (no extra client) streaming is not solved** — it
  needs either a real 5 GHz hotspot client, or a gate-patched `instaAIP` (which
  in turn needs a UART to deploy/debug safely).
- Everything here is **version-specific**. Firmware addresses, the gate layout,
  and even protocol details change between builds — re-derive, don't trust
  offsets blindly.
- No firmware images, extracted binaries, or patched blobs are distributed here
  — only methods and findings.

## Documentation

- [Capability matrix](docs/capabilities.md) — verified / partial / unsolved, item by item
- [The port-6666 access gate (deep dive)](docs/gate-re.md) — decompiled logic + patch map
- [Reproduction guide](docs/reproduce.md) — from firmware unpack to protocol capture to Ghidra

## Credits

- [`xaionaro-go/insta360ctl`](https://github.com/xaionaro-go/insta360ctl) — BLE/Wi-Fi control tool
- [`soul667/insta360-x5-toolkit`](https://github.com/soul667/insta360-x5-toolkit) — X5 BLE protocol patches
- [`shack-32/Insta360-X5-FW-Mod`](https://github.com/shack-32/Insta360-X5-FW-Mod) — X5 firmware boot-hook / carving
- [`schlarpc/insta360-link-firmware-re`](https://github.com/schlarpc/insta360-link-firmware-re) — related Insta360 firmware RE

## License

Documentation: CC BY 4.0. Any original scripts: MIT. Trademarks belong to their
respective owners.
