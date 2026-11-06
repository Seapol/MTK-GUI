#!/bin/sh
# TEMPLATE - system pre-flight check for a production DUT.
# Copy to your project assets/precheck/ and adapt.
# Runs on the DUT over the console serial port; idempotent.
#
# Reference example: projects/FRDM-IMX93/scripts/preflight.sh

echo "== precheck =="
uname -a
cat /proc/device-tree/model 2>/dev/null || echo "(no device-tree model)"
df -h | head -8
free -m

# RF interfaces expected on this project (edit for your DUT):
#   FRDM-IMX93: mlan0 (Wi-Fi), hci0 (BT)
WIFI_IF="${WIFI_IF:-mlan0}"
BT_IF="${BT_IF:-hci0}"

if [ -d "/sys/class/net/$WIFI_IF" ]; then
    echo "PRECHECK_OK wifi_if=$WIFI_IF present"
else
    echo "PRECHECK_FAIL wifi_if=$WIFI_IF missing (load drivers step required)"
fi

if command -v hcitool >/dev/null 2>&1 && hcitool dev | grep -q "$BT_IF"; then
    echo "PRECHECK_OK bt_if=$BT_IF present"
else
    echo "PRECHECK_FAIL bt_if=$BT_IF missing (load drivers step required)"
fi
