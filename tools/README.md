# tools

Analysis helpers used during the reverse engineering. All generic — no device
data baked in.

| File | What it does |
|---|---|
| `xref.py` | AArch64 string→code xref finder; resolves `ADRP+ADD` **and** `ADRP+LDR` (literal-pool) refs that `objdump \| grep` misses. `python3 xref.py <instaAIP> 0x<string_vaddr>` |
| `pcap_6666.py` | Extract the port-6666 TCP streams from a pcap and dump each direction to a file. `python3 pcap_6666.py capture.pcap` |
| `frames.py` | Decode the length-prefixed `syNceNdinS` frames from a 6666 stream dump. `python3 frames.py <stream.bin> [N]` |
| `extract_video.py` | Reassemble the contiguous TCP stream and write the H.264 substream. `python3 extract_video.py capture.pcap out.h264` |
| `srcprobe.go` | Source-bound 6666 handshake probe (used to prove the gate is association-based, not IP-based). `go build srcprobe.go && ./srcprobe <srcIP> <dstIP>:6666` |
| `ghidra/Decomp.java` | Headless Ghidra post-script: decompile the functions that call `accept`/`getpeername` (the 6666 server loop). |

Decode a captured stream end to end:

```sh
python3 pcap_6666.py capture.pcap          # -> per-direction .bin files
python3 extract_video.py capture.pcap preview.h264
ffprobe preview.h264
ffmpeg -i preview.h264 -vf "v360=dfisheye:e:ih_fov=193:iv_fov=193" equirect.mp4
```
