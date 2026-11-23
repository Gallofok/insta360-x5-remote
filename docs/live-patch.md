# Live in-memory patching (ptrace) — the right way to test a gate patch

**This supersedes the earlier "you need a UART" conclusion.** The clean way to
try a gate patch is to NOP the branches **in the running `instaAIP` process**
with `ptrace`, not to deploy a replacement binary.

## Why in-memory beats replacing the daemon

Replacing `instaAIP` (via the SD boot hook, or kill-and-rerun) fights the whole
system: `instaAIP` is supervised, re-claims the USB gadget, rewrites
`hostapd.conf`, owns the Bluetooth stack, and its exFAT logs don't flush — so a
bad deploy bricks your access until you pull the card.

Patching the **live** process sidesteps all of it:

- the process keeps running — BLE / USB / `hostapd` stay exactly as they were,
  so your control and network paths never drop;
- nothing is written to flash;
- **revert = restart the process** (or power-cycle the camera) — the edit is
  RAM-only;
- you can iterate in seconds from the root shell you already have.

Tools: a tiny static aarch64 `ptrace` poker ([`tools/poker.c`](../tools/poker.c)
to NOP, [`tools/pokew.c`](../tools/pokew.c) to write/restore an arbitrary word).
Cross-compile with `aarch64-linux-gnu-gcc -static`, push to the camera, run from
the root shell.

## The version-match lesson (this bit us hard)

The firmware `.bin` on the vendor's download page can be a **newer build than
what's installed on the camera**. We reverse-engineered the *downloaded*
`instaAIP` (one size) but the camera was running a *different* one (another
size) — so every offset was wrong and every patch silently missed.

**Always patch against the binary the camera is actually running.** Pull it off
the device:

```sh
# on the camera (root shell): copy the live binary to the SD card
cp /usr/bin/instaAIP /tmp/SD0/iap_live.bin
# or transfer it over TFTP (busybox tftp is a client: -p = put)
tftp -p -l /usr/bin/instaAIP -r iap_live.bin <gateway-ip> <port>
```

(Note: large transfers over the camera's Wi-Fi are flaky; the SD-card copy is the
most reliable. A straight TCP hex dump — `xxd -p` piped over the telnet backdoor
— also works and, unlike UDP TFTP, won't drop packets.)

Then re-locate the gate in *that* binary (see [gate-re.md](gate-re.md)) and feed
those offsets to the poker.

## Finding the runtime address (PIE/ASLR)

`instaAIP` is a PIE, so file offsets ≠ runtime addresses. For each `.text` file
offset `F`, read `/proc/<pid>/maps`, find the **executable** mapping of the
binary (`start`, file `offset`), and compute `runtime = start + (F - offset)`.
`tools/poker.c` does exactly this, then `PTRACE_POKETEXT`s the AArch64 NOP
(`0xD503201F`) — which bypasses the read-only `r-x` page permission.

```sh
# NOP three gate branches in the live process (offsets are build-specific!)
./poker $(pidof instaAIP) instaAIP <off_outer> <off_inner> <off_mac>
# restore one of them to its original 4 bytes:
./pokew $(pidof instaAIP) instaAIP <off> <orig_hexword>
```

## What we observed (status) — the gate is TWO subsystems, not one

Port 6666 is served by **two cooperating threads**, each with its **own**
`ap_monitor_running` check. Bypassing one does nothing until you also handle the
other. This was the key realization after tracing the full path.

| Thread (by its log name) | Role | Its `ap_monitor_running` gate |
|---|---|---|
| `conn_monitor` | `select`s the **listen** socket, `accept()`s, looks up the peer MAC, then **promotes** the fd into a shared slot and (if idle too long) reaps it. It never reads client data. | outer + inner guards, plus the client-MAC `strncmp` |
| `wifi_recv`    | polls the promoted-fd slot and does the actual `recv()` / frame parsing / dispatch | a guard that **`usleep`s forever unless a station is associated** |

### Step 1 — the accept side (bypassed)

NOPing `conn_monitor`'s three branches (`ap_monitor_running` outer + inner, and
the client-MAC `strncmp`) plus one more fix (below) moved the LAN client from
`i/o timeout` → `EOF` → **fully accepted**:

- The routine right after `accept()` is a `getpeername()` + `ioctl(SIOCGARP)`
  that resolves the peer's MAC **on a fixed interface** (the AP interface, e.g.
  `wlanN`). A LAN peer isn't in that interface's ARP table → `ENXIO` → the
  connection is dropped. **Fix: repoint that interface string** (one byte in
  `.rodata`, via `pokew` to the whole word) to the interface your client is
  actually on (the STA/LAN side). `SIOCGARP` then returns 0.
- With that, `conn_monitor` **accepts, resolves the MAC, sets the socket
  non-blocking, applies send/recv timeouts, and promotes the fd** — verified by
  `strace` on the camera and by the kernel socket showing our bytes queued in
  `rx_queue`. The accept gate is beaten.

### Step 2 — the receive side (the real blocker)

Even fully accepted, **no thread ever reads the connection**: the bytes sit
unread in the socket's `rx_queue`. `wifi_recv` is the reader, and its loop is:

```
if (ap_monitor_running == 0)     // no associated station
        usleep(...);             // ...so just sleep, forever
else
        select(conn_fd); recv(conn_fd); ...   // service the client
```

So a LAN client is accepted and promoted, then starved: `wifi_recv` never leaves
its sleep because `ap_monitor_running` is 0 without a real 802.11 association.
**This, not the accept gate, is why bypassing the accept checks still yielded no
stream.**

### The correct fix (and a trap to avoid)

Do **not** NOP `wifi_recv`'s sleep branch. On the idle path (no connection,
`conn_fd == -1`) the fall-through builds an `fd_set` and glibc's `__fdelt_chk(-1)`
**aborts** — which crashes `instaAIP`, and it takes `instaAlg` + `amba_camctrl`
down with it (recoverable only by restarting the process / rebooting). We hit
exactly this.

The clean fix is to **set `ap_monitor_running` to 1** (emulate "a station is
associated"). That is the exact state the official app creates, so it drives both
threads down their *designed* paths: `conn_monitor` accepts, and `wifi_recv`
services the connection (and still `usleep`s safely when `conn_fd == -1`). It also
makes the two accept-side `ap_monitor_running` NOPs redundant — only the MAC
`strncmp` NOP and the ARP-interface fix remain strictly necessary. Write the flag
with `pokew` at its data address (resolve it from the thread-struct base the two
threads share; it is a single byte).

## Operational lessons

- **A bad live patch crashes the whole camera app stack**, not just `instaAIP`.
  `instaMonitor` did **not** auto-respawn it for us; recovery was a full reboot
  (the SD boot-hook brings telnet back; the gateway keep-awake re-wakes and
  re-joins Wi-Fi). Patch conservatively and keep a reboot path ready.
- **Detach every prior tracer before attaching a new one** — a process can have
  only one. A forgotten `strace` left attached makes the next attach fail and
  silently skews what you think you're measuring (it cost us real time here).
- **Identify threads by name, not by a guessed TID.** `cat
  /proc/<pid>/task/*/comm` maps TIDs to the real thread (`conn_monitor`,
  `wifi_recv`, `rpmsg_read`, …); several internal threads do unrelated pipe I/O
  that is easy to mistake for your socket.
- **`/proc/net/tcp` + `/proc/<pid>/fd` are enough to confirm an accept** without a
  tracer: your connection showing as `ESTABLISHED` with bytes in `rx_queue`, and
  a matching `socket:[inode]` in the daemon's fd table, proves the daemon accepted
  it even if nothing reads it yet.

## Verified end to end — the gate is beaten (live)

With the full set applied to the running daemon, a plain TCP client on the LAN
(no 802.11 association) was **serviced on 6666 and received live bidirectional
protocol frames** from the camera — proof the gate is fully defeated, not just
understood.

Two equivalent ways to satisfy `wifi_recv` were found; the branch-reroute is the
one actually run here because it needs no data-segment address:

- **Set `ap_monitor_running = 1`** (one byte, emulates association), or
- **Reroute `wifi_recv`'s "no-station → sleep" branch to its own
  connection-fd check** instead of the sleep. Concretely: the entry test is
  `cbnz ap,<service>` / `b <sleep>`; repoint that `b <sleep>` to the block that
  does `if (conn_fd >= 0) service(); else usleep()`. That block is the
  crash-safe one (it `usleep`s when idle, so it never reaches the `fd_set` build
  with `conn_fd == -1` — which is what aborted in `__fdelt_chk` when we NOP'd the
  sleep directly). Also NOP the **second** `ap_monitor_running` check on the
  post-recv path so servicing is continuous rather than gated behind a ~3 s idle
  sleep.

Minimal live set that worked (offsets build-specific): the two accept-side
`ap_monitor_running` NOPs, the client-MAC `strncmp` NOP, the ARP-interface byte
fix, the `wifi_recv` branch reroute, and the post-recv `ap_monitor_running` NOP.

What came back on the serviced socket was the camera's normal message stream —
length-prefixed frames `[u32 len][3-byte type][payload]`: keepalives (one type,
3-byte body), and status/notification frames (another type, protobuf bodies
carrying e.g. the joined-network name). So the serve path runs for us; the camera
treats the LAN client as a live peer.

## SOLVED — live H.264 to a non-associated LAN client

End to end, verified: a plain TCP client on the LAN (never associated to the
camera's hotspot) completes the handshake, drives the camera, and **receives the
live H.264 preview** — decoded to a real image. The full recipe:

### 1. The in-memory patch set (all `.text`, plus one data byte)

| What | Why |
|---|---|
| NOP the two `ap_monitor_running` accept guards | let `conn_monitor` accept a LAN client |
| NOP the client-MAC `strncmp` | a non-station MAC isn't the authorized one |
| Repoint the `getpeername`/`SIOCGARP` interface string to the client's interface | so the peer-MAC ARP lookup returns 0 instead of `ENXIO` |
| Reroute `wifi_recv`'s "no-station → sleep" branch to its connection-fd check | so it services the promoted fd with `ap_monitor_running == 0` |
| NOP the post-recv `ap_monitor_running` guard | continuous servicing, not gated behind a long idle sleep |
| Shrink `wifi_recv`'s idle `usleep` (NOP the `movk` that builds the ~3 s value, leaving ~50 ms) | so it polls the connection fd fast enough to catch it before the idle reaper closes it |
| **Set `ap_monitor_running = 1`** | **the key that lights up the SEND path** — without it the camera receives and dispatches commands but never writes anything back; with it, the sync echo, command responses, and the video substream all flow |

Note on writing the `ap_monitor_running` byte: it lives in the data segment, not
`.text`. If your poker computes the runtime address from the executable mapping
only, it can be off by the text/data segment gap — verify the write landed by
reading it back through `/proc/<pid>/mem`, and adjust the offset you feed it.

### 2. Drive the protocol like the app does

- **Handshake:** client sends `[u32 len][06 00 00]"syNceNdinS"`; the camera
  echoes `syNceNdinS` back. (This is the sync response community tools wait for;
  a mismatched handshake just times out.)
- **Commands:** `[u32 len][04 00 00][op][00][02][seq][00 00 80 00 00][protobuf]`,
  `seq` incrementing. The camera answers each with a `c8 …`-marked response under
  the same `seq`. Keepalives are `[07 00 00 00][05 00 00]`.
- **Start preview:** the `op = 0x01` command. **Send the setup commands
  one-at-a-time, paced (~80 ms apart), not in one burst** — dumping them all at
  once gets each one ACKed but never brings the encoder up, so `START_LIVE` is
  acknowledged yet no video follows. Paced, the camera transitions into preview
  and the video starts on the frame right after the `START_LIVE` response.
- **Video:** arrives as `type 01` frames on the same socket — a short per-frame
  header then Annex-B H.264 (SPS/PPS/IDR then P-frames), High profile.

Fastest way to get the exact command bytes for your firmware: capture the
official app's 6666 session once (it's a correct client) and replay its
client→camera stream.

### 3. Keep it running, stop it cleanly

- **Sustain:** a single `START_LIVE` yields only a few seconds of video — the
  camera stops sending unless the client keeps talking. The app streams
  indefinitely because it keeps sending its `type 04` status/poll commands the
  whole time. Replaying those commands **in a loop with the `seq` byte
  incrementing** (not a fixed captured `seq`) sustains the stream; a fixed `seq`
  stalls within ~30 s (the camera treats the repeats as stale).
- **Stop:** `op = 0x02` (empty body) is `STOP_LIVE_STREAM` — it triggers
  `InsApp_NetFifo_Stop_LiveStream` on the camera (confirmed by trace). Always send
  it **on the streaming connection, then close gracefully** (`shutdown(WR)`);
  dropping the TCP with a `RST` leaves the camera's preview pipeline running.
- **Reconnect fast:** only the frames up to and including `START_LIVE` are needed
  to bring video back (~the first ~60 frames), so a reconnect warms up in ~3 s
  rather than replaying the whole capture.

### 4. Delivering to a browser / phone (latency)

The raw 6666 stream is low-latency H.264 — the same bytes the app decodes
frame-by-frame (~sub-second). Re-packaging as **HLS** adds 2–5 s (segment +
player buffering); feeding the H.264 to a **WebRTC** server (e.g. go2rtc/MediaMTX)
keeps it near the app's latency and plays in any browser. `-c:v copy` into the
muxer needs timestamps — `ffmpeg -use_wallclock_as_timestamps 1` works and avoids
re-encoding on a weak gateway.

### The "camera shows occupied / preview" caveat (cosmetic)

Forcing `ap_monitor_running = 1` is a *flag*, not a real 802.11 association. The
camera's on-screen "app is previewing" / busy state is normally cleared by the
**hostapd station-disassociation event** when a real phone leaves the hotspot —
an event that never fires here (there is no real station). So after you stop and
disconnect, the camera's own screen can stay in the preview/occupied state until
it sleeps or is touched/power-cycled, even though every session (6666, BLE, the
flag) is actually released. It's cosmetic — the device is free — but there's no
clean network-side way to force the display back without a genuine association.

### Releasing the BLE keep-awake cleanly

If a gateway holds a BLE keep-awake session, note that **killing the BLE client
process does not drop the link** — the host's `bluetoothd` keeps the ACL
connection open, so the camera still sees a central connected. Issue an explicit
`bluetoothctl disconnect <addr>` (or equivalent) on teardown, or the camera never
transitions to "nobody connected."

### Gotchas that cost time here

- `wifi_recv` sleeps in multi-second steps when idle; its ~3 s sleep is longer
  than the connection's idle-reaper window, so without the sleep-shrink patch the
  promoted connection gets reaped before the thread ever services it (flaky
  "sometimes it works").
- The server handles **one** connection at a time (`off44`/current-conn slot); a
  stale, un-reaped connection blocks new accepts. Connect once, cleanly, hold.
- **Thread TIDs are not stable across reboots.** Identify `conn_monitor` /
  `wifi_recv` by `/proc/<pid>/task/*/comm`, never by a remembered TID — reading
  the wrong thread's state sends you chasing ghosts.
- A bad patch crashes the whole app stack (reboot to recover); `/tmp` is tmpfs,
  so re-stage tools after any reboot and re-apply (ASLR base changes).
