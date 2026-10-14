#!/bin/sh
# FRDM-IMX93 (Linux) FCT - bring up Wi-Fi as a STATION and connect to the
# factory router AP; the Host PC is on the same AP (it keeps its internet
# link). Idempotent.
#
# Generic: the SSID/password are NOT hard-coded per board. They come from
# environment variables or positional args, so the SAME asset folder works
# on every DUT and every line/station:
#
#   WIFI_SSID=MyAP WIFI_PASSWORD=secret sh connect_wifi.sh
#   sh connect_wifi.sh MyAP secret
#
# The Wi-Fi password stays on the DUT side (wpa config); it is never put
# in the mtk-gui YAML.
#
# Success/fail markers (the FCT console step matches these):
#   WIFI_CONNECTED_OK <ip/prefix>
#   WIFI_CONNECT_FAIL

SSID="${WIFI_SSID:-${1:-}}"
PASS="${WIFI_PASSWORD:-${2:-}}"

# the SSID / password are per-site deployment values and come from the
# yaml ({{ssid}} / {{password}}) - never hard-coded here
if [ -z "$SSID" ] || [ -z "$PASS" ]; then
    echo "WIFI_CONNECT_FAIL (SSID/password not provided)"
    exit 1
fi
WIFI_IF="${WIFI_IF:-mlan0}"

# make sure the RF driver is loaded
if [ ! -d "/sys/class/net/$WIFI_IF" ]; then
    sh "$(dirname "$0")/load_rf_drivers.sh"
    sleep 3
fi
# never run a local AP during the station test
killall -q hostapd 2>/dev/null
ip link set uap0 down 2>/dev/null
ip addr flush dev uap0 2>/dev/null

ip link set "$WIFI_IF" up
# disable Wi-Fi power-save (the IW612 dozes and drops the association
# after ~1 min idle; the SFTP / iPerf / RSSI steps run long after the
# connect step and must keep the link alive)
iw dev "$WIFI_IF" set power_save off 2>/dev/null || true
wpa_passphrase "$SSID" "$PASS" > /tmp/wpa.conf
killall -q wpa_supplicant 2>/dev/null
sleep 1
setsid sh -c "wpa_supplicant -i$WIFI_IF -c/tmp/wpa.conf -f/tmp/wpa.log" \
    </dev/null >/dev/null 2>&1 &
sleep 12
udhcpc -i "$WIFI_IF" -n -t 8 >/tmp/udhcpc.log 2>&1
sleep 1
ip route | grep -q default || \
    udhcpc -i "$WIFI_IF" -n -t 8 >>/tmp/udhcpc.log 2>&1

if ip -4 addr show "$WIFI_IF" | grep -q 'inet 192'; then
    echo "WIFI_CONNECTED_OK $(ip -4 addr show "$WIFI_IF" | awk '/inet/{print $2}')"
else
    echo "WIFI_CONNECT_FAIL"
fi
