#!/bin/sh
# Keep an Insta360 X5 awake and on your Wi-Fi by emulating the official app's
# persistent BLE session. Needs insta360ctl (with the X5 BLE patches) in PATH,
# run as root (BLE needs CAP_NET_ADMIN). See x5keeper.service.
#
# Config: /etc/x5keeper.conf  (copy x5keeper.conf.example, edit)
. /etc/x5keeper.conf 2>/dev/null || { echo "missing /etc/x5keeper.conf"; exit 1; }

while true; do
  # 1) make sure the camera is on your Wi-Fi; if not, (re)join over BLE
  if ! ping -c1 -W2 "$CAM_IP" >/dev/null 2>&1; then
    for t in 1 2 3; do
      insta360ctl direct --addr "$BLE_MAC" wifi-join --ssid "$SSID" --password "$PSK" >/dev/null 2>&1 && break
      sleep 2
    done
    sleep 6
  fi
  # 2) hold a BLE session feeding a heartbeat -> camera stays awake & on Wi-Fi.
  #    Blocks until the link drops; the loop then re-checks/re-joins/re-holds.
  #    (wifi-join and the hold share one BT adapter, so they run sequentially.)
  (while true; do echo state; sleep 15; done) \
    | insta360ctl multi shell --addr "$BLE_MAC" --connect-timeout 30s --command-timeout 6s >/dev/null 2>&1
  sleep 2
done
