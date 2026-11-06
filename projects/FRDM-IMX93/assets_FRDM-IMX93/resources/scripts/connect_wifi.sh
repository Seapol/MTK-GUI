#!/bin/sh
# FRDM-IMX93 (Linux) FCT - bring up Wi-Fi as a STATION and join the station's
# access point. Idempotent.
#
# TWO deployment profiles, selected by ONE positional argument:
#
#   bash <path>/connect_wifi.sh router    external Wi-Fi router; the Windows
#                                         host PC joins the SAME AP
#   bash <path>/connect_wifi.sh hotspot   no router: the Windows host PC itself
#                                         is the AP (Host PC hotspot)
#
# Both profiles are configured in advance on the Equipment page
# (Wired & Wireless Network); the four values below are the DUT-side copy.
# Keep them in sync with the Equipment page: the "Config assets for projects"
# window can write them into this file from there (M83 C15).
#
# SECURITY: credentials are hard-coded per profile and are NEVER passed on the
# command line. The console echoes the command, so a credential on the row would
# end up in the Console Log and in the DUT PDF report. There is no
# WIFI_SSID / WIFI_PASSWORD intake and no silent fallback: a missing or
# unknown profile fails loudly before anything is touched.
#
# Success/fail markers (the FCT console step matches these):
#   WIFI_CONNECTED_OK <ip/prefix> profile=<profile> ssid=<ssid>
#   WIFI_CONNECT_FAIL ...

PROFILE="${1:-}"

# Machine-readable profile declaration. The GUI reads ONLY these four lines to
# cross-check the Equipment page (Wired & Wireless Network) against this
# script, and warns when the two disagree. Keep the assignment form exactly as
# "<NAME>='<value>'" on one line: one name, one equals sign, one quoted value.
# The values themselves are assigned from here, so they exist exactly once.
AP_PROFILE_ROUTER_SSID='ChinaNet-4zEc-5G'
AP_PROFILE_ROUTER_PASSWORD='dgu3vcgs'
AP_PROFILE_HOTSPOT_SSID='MTK-FCT-AP'
AP_PROFILE_HOTSPOT_PASSWORD='mtkfct2026'

case "$PROFILE" in
    router)
        SSID="$AP_PROFILE_ROUTER_SSID"
        PASS="$AP_PROFILE_ROUTER_PASSWORD"
        ;;
    hotspot)
        # the Windows host PC runs this AP itself (Equipment page:
        # Wireless mode = "Host PC hotspot (no router)",
        # Host PC AP SSID / Host PC AP password must match these two values)
        SSID="$AP_PROFILE_HOTSPOT_SSID"
        PASS="$AP_PROFILE_HOTSPOT_PASSWORD"
        ;;
    *)
        echo "WIFI_CONNECT_FAIL (unknown profile '$PROFILE'; expected router or hotspot)"
        exit 1
        ;;
esac

if [ -z "$SSID" ] || [ -z "$PASS" ]; then
    echo "WIFI_CONNECT_FAIL (profile '$PROFILE' is not configured yet)"
    exit 1
fi

WIFI_IF="${WIFI_IF:-mlan0}"

# make sure the RF driver is loaded: the loader is a sibling of this script
# inside the project assets (drivers/load_drivers.sh). Probe-only - when the
# BSP already autoloaded the interface this is never reached.
if [ ! -d "/sys/class/net/$WIFI_IF" ]; then
    sh "$(dirname "$0")/load_drivers.sh" 2>/dev/null || true
    sleep 3
fi

# never run a local AP during the station test
killall -q hostapd 2>/dev/null
ip link set uap0 down 2>/dev/null
ip addr flush dev uap0 2>/dev/null

ip link set "$WIFI_IF" up
# disable Wi-Fi power-save (the IW612 dozes and drops the association after
# ~1 min idle; the SFTP / iPerf / RSSI steps run long after the connect step
# and must keep the link alive)
iw dev "$WIFI_IF" set power_save off 2>/dev/null || true
wpa_passphrase "$SSID" "$PASS" > /tmp/wpa.conf
chmod 600 /tmp/wpa.conf
killall -q wpa_supplicant 2>/dev/null
sleep 1
setsid sh -c "wpa_supplicant -i$WIFI_IF -c/tmp/wpa.conf -f/tmp/wpa.log" \
    </dev/null >/dev/null 2>&1 &
sleep 12
udhcpc -i "$WIFI_IF" -n -t 8 >/tmp/udhcpc.log 2>&1
sleep 1
ip route | grep -q default || \
    udhcpc -i "$WIFI_IF" -n -t 8 >>/tmp/udhcpc.log 2>&1

# re-apply power-save OFF AFTER the association: wpa_supplicant / the IW612
# driver can re-enable power management once associated, and the link dozes +
# drops ~1 min later (this silently broke the SFTP / iPerf steps, which run
# long after the connect step)
iw dev "$WIFI_IF" set power_save off 2>/dev/null || true
sleep 1

if ip -4 addr show "$WIFI_IF" | grep -q 'inet 192'; then
    echo "WIFI_CONNECTED_OK $(ip -4 addr show "$WIFI_IF" | awk '/inet/{print $2}') profile=$PROFILE ssid=$SSID"
else
    echo "WIFI_CONNECT_FAIL (profile=$PROFILE ssid=$SSID: no 192.x address from DHCP)"
    exit 1
fi
