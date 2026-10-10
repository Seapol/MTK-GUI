#!/bin/sh
# FRDM-IMX93 (Linux) FCT - prepare the A2DP SINK (pipewire/wireplumber +
# NoInputNoOutput agent) so the Host PC can pair/connect and stream a test
# tone that comes out of the DUT 3.5 mm headphone jack. Idempotent.
#
# Generic: the Host PC Bluetooth address is NOT hard-coded. It is supplied
# per Host via an environment variable or positional arg:
#
#   HOST_BT_MAC=AA:BB:CC:DD:EE:FF sh start_bt_audio.sh
#   sh start_bt_audio.sh AA:BB:CC:DD:EE:FF
#
# The Host must be trusted so NoInputNoOutput does not cancel per-service
# authorization. With no Host address the sink still starts (discoverable).
#
# Ready marker:
#   BT_AUDIO_READY

HOST="${HOST_BT_MAC:-${1:-14:7D:DA:D2:BA:B4}}"
BT_IF="${BT_IF:-hci0}"

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
