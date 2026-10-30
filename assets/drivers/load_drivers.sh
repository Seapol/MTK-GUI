#!/bin/sh
# TEMPLATE - load Wi-Fi / BT drivers on demand.
# Copy to your project assets/drivers/ and adapt module list.
# Probe first: if the interface already exists the BSP autoloaded it.
#
# Reference example: projects/FRDM-IMX93/scripts/load_rf_drivers.sh

WIFI_IF="${WIFI_IF:-mlan0}"
BT_IF="${BT_IF:-hci0}"

load_wifi() {
    [ -d "/sys/class/net/$WIFI_IF" ] && return 0
    modprobe brcmfmac 2>/dev/null || modprobe mwifiex 2>/dev/null
    sleep 2
}

load_bt() {
    command -v hcitool >/dev/null 2>&1 || modprobe bluetooth
    modprobe btusb 2>/dev/null
    modprobe hci_uart 2>/dev/null
    sleep 2
    hciconfig "$BT_IF" up 2>/dev/null
}

load_wifi
load_bt

if [ -d "/sys/class/net/$WIFI_IF" ]; then
    echo "DRIVERS_OK wifi_if=$WIFI_IF"
else
    echo "DRIVERS_FAIL wifi_if=$WIFI_IF not available"
fi
if command -v hcitool >/dev/null 2>&1 && hcitool dev | grep -q "$BT_IF"; then
    echo "DRIVERS_OK bt_if=$BT_IF"
else
    echo "DRIVERS_FAIL bt_if=$BT_IF not available"
fi
