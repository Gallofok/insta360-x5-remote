# Reproduction guide

From a stock camera to: unpacked firmware, a root shell, a decoded protocol,
and a Ghidra decompilation. Commands are illustrative — adapt paths/addresses to
your build. **Do this only on hardware you own.**

Placeholders: `<AP_PASS>` camera hotspot password, `<SSID>`/`<PSK>` your Wi-Fi,
`<BLE_MAC>` the camera's BLE address, `<CAM_LAN_IP>` its DHCP address.

---

## 0. Tools

- A Linux box (x86_64 or arm64) for analysis
- `ubi_reader` (`pip install ubi_reader`), `binutils` (`objdump`), `python3`
- A Bluetooth adapter + [`insta360ctl`](https://github.com/xaionaro-go/insta360ctl)
  with the [X5 BLE patches](https://github.com/soul667/insta360-x5-toolkit)
- (optional) a rooted Android phone with `tcpdump` for protocol capture
- (optional) Ghidra + a JDK for decompilation

---

## 1. Get and unpack the firmware

Download the official `.bin` for your model/version. The container is not
encrypted; the Linux rootfs is a UBI volume.

```sh
# find the UBI image inside the .bin
grep -abo "UBI#" Insta360X5FW.bin | head         # note the first offset
# carve from that offset to EOF
python3 - <<'PY'
off = <FIRST_UBI_OFFSET>
open("sys_sw.ubi","wb").write(open("fw.bin","rb").read()[off:])
PY
ubireader_display_info sys_sw.ubi                # shows the 'linux' volume
ubireader_extract_files -o rootfs sys_sw.ubi     # -> rootfs/.../linux/
```

You now have a BusyBox rootfs: `usr/bin/instaAIP` (the daemon of interest),
`usr/local/share/script/*.sh` (Wi-Fi/AP/USB setup), `etc/init.d/S99bootdone`
(the boot hook).

---

## 2. Root via the SD-card boot hook (reversible)

`etc/init.d/S99bootdone` runs, as root, a `bootup.sh` from the SD card root if
present, and will run a `/tmp/SD0/instaAIP` *instead* of the stock one if you
drop one there. So a plain file on the card gets you code execution at boot —
**remove the card and the camera is 100 % stock again.**

A minimal `bootup.sh` that opens a passwordless root shell over the network:

```sh
#!/bin/sh
telnetd -l /bin/sh -p 2323 &
exit 0
```

Copy it to the (exFAT/FAT32) card root, boot, put the camera on your LAN (below),
then `telnet <CAM_LAN_IP> 2323`.

---

## 3. Drive it over BLE

```sh
sudo insta360ctl scan
sudo insta360ctl direct --addr <BLE_MAC> status
# put the camera on your Wi-Fi (plaintext PSK!):
sudo insta360ctl direct --addr <BLE_MAC> wifi-join --ssid "<SSID>" --password "<PSK>"
```

Notes:
- The camera keeps advertising BLE in standby, so the same commands **wake** it.
- It leaves your Wi-Fi ~120 s after the BLE session ends — hold a BLE session
  (feed a periodic `state`) to keep it up.

---

## 4. Capture & decode the preview protocol

With a rooted phone associated to the camera **hotspot** (`<AP_PASS>`), run the
official app and capture:

```sh
# on the phone (root):
tcpdump -i any -s0 -w /sdcard/x5.pcap 'port 6666 or net 192.168.42.0/24'
```

Reassemble the camera→phone TCP stream on `6666`. Frames are
`[u32 little-endian length][type byte(s)][payload]`; the session opens with a
`syNceNdinS` handshake. Stream frames carry a short header then Annex-B H.264
(**High profile, dual-fisheye**). Concatenate the video substream and play/probe
with `ffmpeg`/`ffprobe`; stitch with the `v360=dfisheye` filter.

---

## 5. Decompile `instaAIP` with Ghidra

On an **aarch64 analysis host**, the public Ghidra ships no native decompiler —
build it:

```sh
sudo apt-get install -y bison flex
cd Ghidra/Features/Decompiler/src/decompile/cpp
make ghidra_opt ARCH_TYPE=            # ARCH_TYPE= avoids the wrong default -m32
cp ghidra_opt ../../../os/linux_arm_64/decompile
# Ghidra 12.x needs JDK 25; point support/launch.properties JAVA_HOME_OVERRIDE at it
```

Headless import + a small post-script that decompiles the function calling
`accept`/`getpeername` gets you the gate pseudo-C (see
[gate-re.md](gate-re.md)).

### Finding functions without symbols

The binary is stripped, so cross-reference **log strings** to code. A plain
`objdump | grep` misses `ADRP+LDR` (literal-pool) references — resolve both
`ADRP+ADD` and `ADRP+LDR` yourself:

```python
# sketch: for each ADRP, track the page in its dest reg; when a following
# ADD/LDR uses that reg, page + imm == target string VA  => a reference site.
```

---

## Safety / etiquette

- Keep a way back: the SD-card method is reversible; don't flash modified images
  unless you have a hardware recovery path.
- A broken `instaAIP` kills Wi-Fi/BT — without a **UART** you can't recover
  remotely. Get a serial console before iterating on daemon patches.
- Don't redistribute firmware images or extracted/patched binaries.
