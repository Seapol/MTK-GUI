#!/bin/sh
# FRDM-IMX93 (Linux) FCT preflight - merges the 4 console preflight
# rows into ONE DUT-side script (/root/preflight.sh).
#
# Checks (each with its own judgment and PASS/FAIL output):
#   1. kernel       - `uname -a` reports Linux imx93frdm
#   2. fat.py asset - /root/frdm_imx93_board_test/fat.py is a rw file
#   3. ALSA card    - `aplay -l` exposes card 0
#   4. HDMI monitor - /sys/class/drm/card0-HDMI-A-1/status = connected
#
# Paths can be overridden via environment variables for other boards:
#   FAT_PY=/path/fat.py HDMI_STATUS=/sys/.../status sh preflight.sh
#
# Final verdict markers (echo-safe: neither appears in the echoed
# command line "/root/preflight.sh"):
#   PREFLIGHT_PASS  (exit 0) - all 4 checks OK
#   PREFLIGHT_FAIL  (exit 1) - at least one check failed

FAT_PY="${FAT_PY:-/root/frdm_imx93_board_test/fat.py}"
HDMI_STATUS="${HDMI_STATUS:-/sys/class/drm/card0-HDMI-A-1/status}"

fails=0

# 1) kernel: uname -a must contain "Linux imx93frdm"
k=$(uname -a 2>/dev/null)
if echo "$k" | grep -q "Linux imx93frdm"; then
    echo "[1/4] kernel: PASS ($k)"
else
    echo "[1/4] kernel: FAIL (uname -a: ${k:-no output})"
    fails=$((fails + 1))
fi

# 2) fat.py assets: ls -l must show a rw regular file (-rw.*fat\.py)
l=$(ls -l "$FAT_PY" 2>/dev/null | grep -E -- '-rw.*fat\.py' | head -1)
if [ -n "$l" ]; then
    echo "[2/4] fat.py assets: PASS ($l)"
else
    echo "[2/4] fat.py assets: FAIL ($FAT_PY missing or not rw)"
    fails=$((fails + 1))
fi

# 3) ALSA card: aplay -l must list "card 0"
a=$(aplay -l 2>/dev/null | grep "card 0" | head -1)
if [ -n "$a" ]; then
    echo "[3/4] ALSA card: PASS ($a)"
else
    echo "[3/4] ALSA card: FAIL (no 'card 0' in aplay -l)"
    fails=$((fails + 1))
fi

# 4) HDMI monitor: status node must read exactly "connected"
s=$(cat "$HDMI_STATUS" 2>/dev/null)
if [ "$s" = "connected" ]; then
    echo "[4/4] HDMI monitor: PASS (HDMI_MONITOR_OK)"
else
    echo "[4/4] HDMI monitor: FAIL ($HDMI_STATUS: ${s:-node missing})"
    fails=$((fails + 1))
fi

# final verdict
if [ "$fails" -eq 0 ]; then
    echo "PREFLIGHT_PASS"
    exit 0
fi
echo "PREFLIGHT_FAIL"
exit 1
