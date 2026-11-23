# The port-6666 access gate — deep dive

How the Insta360 X5 decides whether to answer a client on its control/preview
port (`6666`), reverse-engineered from `instaAIP`.

> Addresses/offsets below come from **one** firmware build. They **will** differ
> on yours. The method reproduces; the numbers don't.

## Where it lives

The server is a thread named (in its own log strings)
`InsMDev_Wifi_Connect_Monitor`. It is the only place in `instaAIP` that calls
`accept()`, with a `getpeername()` right after — that pairing is how you find it
without symbols (the binary is stripped).

## What the decompiler shows

Trimmed, renamed pseudo-C of the accept loop:

```c
for (;;) {
    if (!thread_should_run) pthread_exit(0);

    // (A) OUTER GATE — whole select/accept block is skipped with no client
    if (ap_monitor_running) {
        // idle/first-packet timeouts that reap a stale connection ...
        select(server_fd + 1, &rfds, ...);
        if (FD_ISSET(server_fd, &rfds) && current_conn < 0) {

            // (B) INNER GATE — right before accept()
            if (!ap_monitor_running) {
                log("[MsgDevice] Wifi ap_monitor_running is false, skip accept.");
            } else {
                int fd = accept(server_fd, &peer, &len);
                // ... per-IP rate-limit ("reject high-frequency connect") ...
                // ... station-table bookkeeping ...

                // (C) MAC GATE
                get_current_client_mac(cur_mac);
                if (strncmp(cur_mac, authorized_mac, n) != 0) {
                    wifi_state_busy_callback();
                    log("diff mac not allow connect. current[%s] new[%s]", ...);
                    close(fd);
                    continue;                 // rejected
                }
                log("mac is the same.");
                // accepted → promote fd to the active connection, keepalive, serve
            }
        }
    }
}
```

## The three checks

| # | Check | Effect if it fails |
|---|---|---|
| A | `ap_monitor_running != 0` (outer) | entire select/accept block skipped |
| B | `ap_monitor_running != 0` (inner) | logs *"skip accept"*, no `accept()` |
| C | `strncmp(client_mac, authorized_mac) == 0` | logs *"diff mac not allow connect"*, closes the socket |

- **`ap_monitor_running`** is a global flag set/cleared by the hotspot
  association events (`hostapd` → `hostapd_event.sh`). It is non-zero only while
  a station is associated to the camera's AP.
- **`authorized_mac`** is the MAC of the client the camera has bound to; a second
  different-MAC client is refused.

This matches every black-box observation:

- LAN / loopback / a source-bound fake `192.168.42.x` all **accept the TCP
  connection but never answer the handshake** — because A/B skip `accept()`
  processing entirely when no real station is associated, and C would reject a
  wrong MAC anyway.
- The official app works because it **is** a genuinely associated station, and
  its MAC becomes `authorized_mac`.

## Patch map (and why it's not plug-and-play)

Each gate is a single conditional branch; turning it into a `NOP`
(`d5 20 03 1f` little-endian `0xD503201F`) makes the server serve any client:

| Gate | Instruction (this build) | Patch |
|---|---|---|
| A (outer) | `cbz w, <skip>` | NOP |
| B (inner) | `cbz w, <skip-accept>` | NOP |
| C (MAC) | `cbnz w, <reject>` | NOP |

`.text` here is loaded 1:1 (virtual address == file offset), so patching is a
byte edit; `objdump` confirms the NOPs.

**Don't deploy a replacement binary — patch the running process in memory.**
Replacing `instaAIP` (SD boot hook, or kill-and-rerun) fights the whole system
(it re-claims USB, rewrites `hostapd.conf`, owns BT; exFAT logs don't flush; a
broken daemon = no remote recovery). The clean way is `ptrace`: NOP these
branches **in the live process** — it keeps running, nothing touches flash, and
revert = restart. See [**live-patch.md**](live-patch.md). (An earlier version of
these notes concluded you need a UART; in-memory patching makes that unnecessary
for user-space daemon work.)

**Two caveats that cost us a lot of time:**

1. **Patch the binary the camera is actually running**, not the one from the
   vendor download — the download can be a *newer build* with different offsets.
   Pull `/usr/bin/instaAIP` off the device and re-locate the gate in it.
2. The three branches above are necessary but **not sufficient**: NOPing them
   moves a LAN client from `timeout` to `EOF` (engaged, then closed) — there's a
   further `getpeername`-based, peer-dependent check in the serve path. See
   [live-patch.md](live-patch.md) for the current status and the open question.

## Takeaway

The gate is understood **and defeated**: patched in memory (`ptrace`) it serves a
non-associated LAN client the live H.264 — no hotspot association, no 5 GHz radio
(the camera joins your Wi-Fi instead). See [live-patch.md](live-patch.md) for the
full working recipe. The *stock* way to satisfy the gate — present a **real
associated hotspot client** (and the camera's AP is 5 GHz, so that client needs a
5 GHz radio) — still works but is no longer the only route.
