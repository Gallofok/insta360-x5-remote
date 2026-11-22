# Agent handoff

State of the project so anyone (human or agent) can pick it up immediately.
Sanitized: fill the placeholders from your own setup; keep real
MACs/SSIDs/PSKs/IPs out of the repo.

## Goal

Operate an Insta360 X5 as a remote camera node: a home gateway wakes/keeps it
awake, puts it on the network, pulls its live preview over port `6666`, and
relays it to a VPS for remote viewing — no phone app in the loop.

## One-line status

Everything works **except** pulling the 6666 stream, which is gated to a **real
Wi-Fi client associated to the camera's own (5 GHz) hotspot**. The single
missing piece is a **5 GHz Wi-Fi client on the gateway**.

## What's done (see `docs/capabilities.md` for the full matrix)

- Firmware unpacked (UBI/UBIFS, unencrypted); platform mapped (Ambarella CV5,
  Linux 5.10 aarch64, BCM43456).
- Root on the camera via the SD-card boot hook (`gateway/bootup.sh`), reversible.
- BLE control, remote wake, keep-awake, Wi-Fi join — all working
  (`gateway/x5keeper.sh` is the keep-awake daemon).
- OSC (`:80`) control working.
- 6666 preview protocol decoded; a real stream captured/decoded/stitched.
- The 6666 access gate reverse-engineered end to end (`docs/gate-re.md`).

## Immediate next step (to get live streaming)

1. Put a **Linux-friendly 5 GHz USB Wi-Fi adapter** on the gateway (MT7612U /
   MT7921AU class, plug-and-play).
2. Associate it to the camera hotspot (SSID like `X5 <serial>.OSC`, its
   password is readable from the camera's `/tmp/hostapd.conf` once you have root,
   or via the app flow). The gateway now gets a `192.168.42.x` lease → it is a
   *real associated client* → it passes the gate.
3. From the gateway, pull the stream (reuse `insta360ctl stream --addr
   192.168.42.1`, or re-implement the `syNceNdinS` + `START_LIVE_STREAM`
   sequence — see the captured params in the RE notes).
4. Forward to the VPS (MediaMTX/go2rtc) over the wired uplink; stitch
   dual-fisheye → equirectangular with ffmpeg `v360=dfisheye` on the VPS.
5. Keep-awake is then doubly covered (the held 6666 session itself keeps the
   camera up, same as the app).

## The firmware-patch path (optional, harder)

The gate (`InsMDev_Wifi_Connect_Monitor`) can be NOP-patched to serve any client
(`docs/gate-re.md` has the patch map). The patched `instaAIP` can be run via the
boot hook (reversible). **Blocker:** deploying/debugging a modified main daemon
needs a **hardware UART** — the software USB-serial gadget is re-claimed by
`instaAIP`, exFAT logs don't flush, and a broken daemon kills Wi-Fi/BT (no remote
recovery). Get a serial console on the mainboard before attempting this.

## Gotchas learned the hard way

- **Plaintext PSK only** — `wifi-join` needs your Wi-Fi's plaintext password; a
  64-hex derived key is rejected.
- **~120 s STA teardown** — the camera leaves your Wi-Fi ~120 s after the BLE
  session ends. It is *not* a power-off; BLE stays alive. The keeper holds a BLE
  session to prevent it.
- **One BT adapter** — `wifi-join` and the BLE keep-alive hold contend for the
  same adapter; do them sequentially (the keeper does).
- **Pi Bluetooth can wedge** after many rapid `hciconfig`/`btmgmt` resets
  (`Set Powered failed`). A Pi reboot fixes it. Don't mistake a wedged *host* BT
  for a camera fault — this cost us a lot of time.
- **instaAIP fights you** — it regenerates `hostapd.conf` (reverts AP band
  changes), re-claims the USB gadget, and owns the BT stack. User-space
  overrides don't stick.
- **exFAT on the camera doesn't flush** — on-SD debug logs can read empty even
  though the process ran. Prefer a serial console for live output.
- **The gate is association-based, not IP-based** — adding a `192.168.42.x`
  alias and source-binding does **not** pass it.

## Local artifacts (NOT in this repo — keep them off GitHub)

Kept on the operator's own machines/notes, never committed:
- the firmware `.bin` and the extracted `rootfs/` (copyright);
- the built patched `instaAIP` and the Ghidra project;
- the real MAC/SSID/PSK/LAN-IP/overlay-IP values (put them in
  `/etc/x5keeper.conf` locally, which is git-ignored).

## Repo layout

```
README.md / README.zh-CN.md   overview (EN/中文)
docs/capabilities.md          verified / partial / unsolved
docs/gate-re.md               the 6666 gate, decompiled + patch map
docs/reproduce.md             firmware → root → protocol → Ghidra
tools/                        analysis tools (xref, pcap/stream decoders, Ghidra script, probe)
gateway/                      runtime: SD boot hook, keep-awake daemon + systemd unit
```
