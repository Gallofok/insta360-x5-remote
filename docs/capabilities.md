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
| Pull 6666 live H.264 from a **non-associated LAN client** | ✅ | Via the in-memory gate patch set **+ `ap_monitor_running=1`**, with the app's sync + commands + `START_LIVE` replayed **paced**. Verified: full control session + 3.8 MB live H.264 (High profile), decoded to a real frame. See [live-patch.md](live-patch.md) |
| Pull 6666 from LAN with no patch (stock) | ❌ | TCP connects, handshake never answered — stock gate requires a genuine 802.11 association, not a peer IP |
| Fully standalone on-device serving (camera as its own client) | ❌ | Camera can't be its own hotspot client; loopback is additionally gated (the LAN-client patch path above is the working route) |

## Attempted workarounds

| Approach | Status | Why |
|---|---|---|
| Force the AP to 2.4 GHz (so a 2.4-only gateway can associate) | ❌ | `instaAIP` regenerates `hostapd.conf` and keeps the AP on the STA's band; manual edits are reverted |
| Software-fake an associated client (IP alias `192.168.42.x`, source-bind) | ❌ | Gate checks a real association, not the peer IP |
| **Live in-memory gate patch via `ptrace`** | ✅ | **Solved end to end.** Patch the running `instaAIP` (no flash, revert = restart): NOP the `ap_monitor_running` accept guards + MAC `strncmp`, repoint the `SIOCGARP` interface, reroute+de-sleep `wifi_recv`, and **set `ap_monitor_running=1`** (the key that lights up the SEND path). Then replay the app's sync + commands + `START_LIVE` **paced**. Result: full control session + live H.264 to a non-associated LAN client, decoded to a real frame. See [live-patch.md](live-patch.md) |
| Replace `instaAIP` via SD boot hook | ❌ | Fights the supervised daemon (re-grabs USB/Wi-Fi/BT); exFAT logs don't flush; a bad binary = no remote recovery. Also failed because the **downloaded firmware ≠ the installed version** (wrong offsets) |
| USB-serial (g_serial) console for debugging | ❌ | `/dev/ttyGS0` comes up, but `instaAIP` re-claims the USB gadget for mass-storage; superseded by in-memory patching anyway |

## The full chain (solved)

No 5 GHz radio needed. The camera joins **your** Wi-Fi (STA, over BLE); the
gateway, on the same LAN, applies the in-memory gate patch (incl.
`ap_monitor_running=1`) and speaks the 6666 protocol (`syNceNdinS` + paced
commands + `START_LIVE`) → pulls the live H.264 → forwards to a VPS. Verified end
to end. See [live-patch.md](live-patch.md).

The stock, no-patch alternative (a real 5 GHz hotspot client associated to the
camera's AP) also works but is not required. The one thing still **open** is
fully-standalone serving — the camera pulling its own 6666 over loopback and
forwarding itself (gated in stock firmware; untested under the full patch set).
