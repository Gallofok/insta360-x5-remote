# gateway

Runtime pieces for the always-on gateway (e.g. a Raspberry Pi with BLE + a wired
uplink). Needs `insta360ctl` (with the X5 BLE patches) in `PATH`.

## Root backdoor (camera side)

`bootup.sh` goes on the **SD-card root**. The firmware's `S99bootdone` runs it as
root at boot; it opens a passwordless root shell on TCP `2323`. Remove the card
to revert to stock. Put the camera on your LAN (BLE `wifi-join`), then
`telnet <camera-ip> 2323`.

## Keep-awake daemon (gateway side)

Emulates the app's persistent BLE session so the camera never sleeps / never
leaves your Wi-Fi.

```sh
sudo cp x5keeper.sh /usr/local/bin/x5keeper.sh
sudo cp x5keeper.conf.example /etc/x5keeper.conf   # then edit it
sudo cp x5keeper.service /etc/systemd/system/
sudo systemctl enable --now x5keeper.service
```

`/etc/x5keeper.conf` holds your `BLE_MAC` / `SSID` / `PSK` (plaintext!) / `CAM_IP`
and is intentionally **not** in the repo. Validated: camera stays reachable
indefinitely (15 min, 0 drops in testing).
