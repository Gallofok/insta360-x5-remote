# Capability matrix

What has actually been done, how sure we are, and what is still open.
Everything is **firmware-version-specific** — treat addresses and exact
protocol bytes as a map, not a guarantee.

Legend: ✅ verified on real hardware · ⚠️ partial / needs specific hardware ·
❌ unsolved / blocked.

## Firmware & platform

| Item | Status | Notes |
|---|---|---|
| Unpack firmware container | ✅ | `linux` UBI volume, **not encrypted**; carve from first `UBI#`, extract UBIFS with `ubireader` |
| Identify SoC / OS / radio | ✅ | Ambarella CV5 · Linux 5.10 aarch64 · Broadcom BCM43456 (dual-band; apsta firmware default) |
| Enumerate daemons | ✅ | `instaAIP`, `instaAlg`, `amba_camctrl`, `instaMonitor` |
| Build an aarch64 Ghidra decompiler | ✅ | Public release ships none for arm64; build `ghidra_opt` with `ARCH_TYPE=` |

## Root & control

| Item | Status | Notes |
|---|---|---|
| Root shell on the camera | ✅ | SD-card boot hook runs a script as root; reversible (remove card = stock) |
| Scan / connect over BLE | ✅ | GATT service `0xBE80` |
| Read status / state | ✅ | BLE + OSC `/osc/state` |
| Start / stop capture, photo, marker | ✅ | BLE and/or OSC `camera.startCapture` / `stopCapture` |
| Power off | ✅ | BLE command |
| Set Wi-Fi mode (AP / STA) | ✅ | BLE; but see "join" caveat below |
| Join an existing Wi-Fi (STA) | ✅ | BLE `SET_WIFI_CONNECTION_INFO`; requires the **plaintext** PSK (a 64-hex derived key is rejected) |
| Query/set OSC options | ✅ | `camera.getOptions` / `setOptions`; e.g. `offDelay`/`sleepDelay` (range `[300,65535]`/`[20,65535]`, `65535` ≈ never) |

## Power / session behaviour

| Item | Status | Notes |
|---|---|---|
| Remote wake from standby | ✅ | Camera keeps advertising BLE while "asleep"; a BLE command restores it in ~4–8 s |
| Keep-awake | ✅ | Hold a BLE session feeding a periodic query (app-style heartbeat) → camera stays up & on Wi-Fi indefinitely (validated 15 min, 0 drops) |
| Understand the ~120 s drop | ✅ | **Not** a power-off: the STA (home-Wi-Fi) link is tied to the app/BLE session and is torn down ~120 s after it ends |
| Keep-awake via `SendToRTOS` | ❌ | The `SendToRTOS` binary referenced by scripts is **absent** on the running image |

## Live preview (port 6666)

| Item | Status | Notes |
|---|---|---|
| Decode the 6666 protocol | ✅ | Length-prefixed frames + `syNceNdinS` handshake; stream subtype carries H.264 **High, dual-fisheye** |
| Capture & decode a real stream | ✅ | Pulled via the official app over the hotspot, reassembled, decoded, stitched (ffmpeg `v360`) |
| Reverse the access gate | ✅ | `InsMDev_Wifi_Connect_Monitor`: `ap_monitor_running` guards + client-MAC check — see [gate-re.md](gate-re.md) |
| Pull 6666 from a **real associated** hotspot client | ⚠️ | Proven with the official app (which *is* such a client); a non-app raw client should pass the same gate but was not independently confirmed (adb/association friction) |
| Pull 6666 from LAN / loopback / spoofed source | ❌ | TCP connects, handshake never answered — the gate requires a genuine 802.11 association, not a peer IP |
| Fully standalone on-device serving | ❌ | Camera can't be its own hotspot client; loopback is additionally gated |

## Attempted workarounds

| Approach | Status | Why |
|---|---|---|
| Force the AP to 2.4 GHz (so a 2.4-only gateway can associate) | ❌ | `instaAIP` regenerates `hostapd.conf` and keeps the AP on the STA's band; manual edits are reverted |
| Software-fake an associated client (IP alias `192.168.42.x`, source-bind) | ❌ | Gate checks a real association, not the peer IP |
| **Live in-memory gate patch via `ptrace`** | ⚠️ | **The right method** — patch the running `instaAIP`; process stays up, no flash, revert = restart. Gate fully reversed: it's **two threads**, `conn_monitor` (accept) + `wifi_recv` (recv), each with its own `ap_monitor_running` check. Accept side bypassed & verified (LAN client accepted + promoted, bytes queued in `rx_queue`); the real blocker is `wifi_recv`, which `usleep`s unless a station is associated. Correct fix = set `ap_monitor_running=1` (NOT a NOP — the idle fall-through aborts and crashes the app stack). See [live-patch.md](live-patch.md) |
| Replace `instaAIP` via SD boot hook | ❌ | Fights the supervised daemon (re-grabs USB/Wi-Fi/BT); exFAT logs don't flush; a bad binary = no remote recovery. Also failed because the **downloaded firmware ≠ the installed version** (wrong offsets) |
| USB-serial (g_serial) console for debugging | ❌ | `/dev/ttyGS0` comes up, but `instaAIP` re-claims the USB gadget for mass-storage; superseded by in-memory patching anyway |

## The one missing link

A **5 GHz Wi-Fi client** for the gateway (e.g. a Linux-friendly USB adapter on
the Pi). With it, the gateway becomes a *real* associated client → passes the
gate legitimately → pulls 6666 → forwards to a VPS. Everything else in the chain
is already done.
