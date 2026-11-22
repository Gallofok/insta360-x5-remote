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

## What we observed (status)

Against the **correct** (camera-resident) binary, NOPing the three gate branches
(`ap_monitor_running` outer + inner, and the client-MAC `strncmp`) changed the
LAN client's result on port 6666 from:

- **`i/o timeout`** (connection accepted at TCP level, handshake silently
  ignored — the gate fully blocks you), to
- **`EOF`** (the server now *engages* with the connection and then closes it).

So the three branches are the right targets and we are **inside the serve path**.
There is at least one more peer-dependent check: right after `accept()` the code
calls a `getpeername`-based routine and branches to a close if it "fails" — and
for a LAN client (not an associated hotspot station) it does fail. Forcing that
branch with a blind NOP leaves an uninitialised peer-MAC buffer and makes things
worse (back to a hang), so it needs a cleaner fix: understand what the serve
path reads about the peer and whether a non-station peer can satisfy it.

**Open question:** whether the stream *delivery* path is intrinsically tied to an
associated station, or whether the remaining checks can be satisfied/bypassed for
an arbitrary TCP client. That's the next piece of RE.

## Next steps

1. Re-trace the serve path from `accept()` to the first handshake reply in the
   **camera-resident** binary; enumerate every branch that can `close()` the fd.
2. Prefer satisfying a check over NOPing it when NOPing leaves invalid state.
3. `strace -f -p <pid> -e trace=network,close` on the camera during a connection
   pinpoints the exact closing syscall (attach can be finicky on a busy
   multithreaded daemon — detach any prior tracer first).
