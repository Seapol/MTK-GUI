#!/bin/bash
# FRDM-IMX93 (Linux) - load the NXP/u-blox Wi-Fi + Bluetooth drivers.
#
# Generic: no per-board MAC/BD/IP is hard-coded. Interface names can be
# overridden via environment variables for other boards.
#
#   WIFI_IF=mlan0  BT_IF=hci0  sh load_rf_drivers.sh
#
# Success marker (the FCT console step waits for this exact line):
#   RF drivers loaded OK

WIFI_IF="${WIFI_IF:-mlan0}"
BT_IF="${BT_IF:-hci0}"

echo "Loading Wi-Fi..."
modprobe moal mod_para=nxp/wifi_mod_para.conf
ip link set "$WIFI_IF" up
echo "Wi-Fi $WIFI_IF ready"

echo "Loading Bluetooth..."
modprobe btnxpuart
hciconfig "$BT_IF" up
echo "Bluetooth $BT_IF ready"

echo "RF drivers loaded OK"
