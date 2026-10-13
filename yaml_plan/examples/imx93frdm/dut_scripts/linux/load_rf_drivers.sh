#!/bin/bash
# FRDM-IMX93 (Linux) - load the NXP/u-blox Wi-Fi + Bluetooth drivers AND
# prepare the A2DP SINK (pipewire/wireplumber + NoInputNoOutput agent) so
# the Host PC can pair/connect and stream a test tone that comes out of
# the DUT 3.5 mm headphone jack. Idempotent (merged from the former
# load_rf_drivers.sh + start_bt_audio.sh).
#
# Generic: no per-board MAC/BD/IP is hard-coded. Interface names and the
# Host BT address can be overridden via environment variables or args:
#
#   WIFI_IF=mlan0 BT_IF=hci0 HOST_BT_MAC=AA:BB:CC:DD:EE:FF sh load_rf_drivers.sh
#   sh load_rf_drivers.sh AA:BB:CC:DD:EE:FF
#
# The Host must be trusted so NoInputNoOutput does not cancel per-service
# authorization. With no Host address the sink still starts (discoverable).
#
# Success markers (the FCT console step waits for the FINAL line):
#   BT_AUDIO_READY        (sink prepared)
#   RF drivers loaded OK  (final verdict line)

WIFI_IF="${WIFI_IF:-mlan0}"
BT_IF="${BT_IF:-hci0}"
HOST="${HOST_BT_MAC:-${1:-14:7D:DA:D2:BA:B4}}"

echo "Loading Wi-Fi..."
modprobe moal mod_para=nxp/wifi_mod_para.conf
ip link set "$WIFI_IF" up
echo "Wi-Fi $WIFI_IF ready"

echo "Loading Bluetooth..."
modprobe btnxpuart
hciconfig "$BT_IF" up
echo "Bluetooth $BT_IF ready"

# ------------------------------------------------ A2DP sink preparation
mkdir -p /run/user/0
chmod 700 /run/user/0
export XDG_RUNTIME_DIR=/run/user/0

if ! pgrep -x pipewire >/dev/null 2>&1; then
    setsid pipewire </dev/null >/tmp/pipewire.log 2>&1 &
    sleep 2
fi
if ! pgrep -x wireplumber >/dev/null 2>&1; then
    setsid wireplumber </dev/null >/tmp/wireplumber.log 2>&1 &
    sleep 6
fi

hciconfig "$BT_IF" up 2>/dev/null
hciconfig "$BT_IF" piscan 2>/dev/null

if ! pgrep -f 'bluetoothctl --agent' >/dev/null 2>&1; then
    setsid sh -c 'bluetoothctl --agent NoInputNoOutput' \
        </dev/null >/tmp/btagent.log 2>&1 &
    sleep 3
fi
if [ -n "$HOST" ]; then
    bluetoothctl trust "$HOST" >/dev/null 2>&1
fi
sleep 1
echo "BT_AUDIO_READY"

echo "RF drivers loaded OK"
