#!/bin/sh
# TEMPLATE - L2CAP ping helper for the BT Pair_Connect FCT step.
# Host PC BT name + BD address are passed as args (see the step
# editor).  Copy to your project assets/resources/scripts/ and adapt.
#
# Usage: sh bt_conn.sh <host_bt_name> <host_bd_addr> [count]

HOST_NAME="${1:-HostPC}"
HOST_ADDR="${2:-AA:BB:CC:DD:EE:FF}"
COUNT="${3:-4}"

# Wait for hci0 (probe first; the BT prepare step may have loaded it)
for i in 1 2 3 4 5; do
    hcitool dev | grep -q hci0 && break
    sleep 1
done
hcitool dev | grep -q hci0 || { echo "BT_CONN_FAIL hci0 missing"; exit 1; }

# L2CAP ping (classic BT) to the Host PC
l2ping -c "$COUNT" "$HOST_ADDR" > /tmp/l2ping.out 2>&1
rc=$?
if [ $rc -eq 0 ]; then
    echo "BT_CONN_OK host=$HOST_NAME addr=$HOST_ADDR count=$COUNT"
else
    echo "BT_CONN_FAIL host=$HOST_NAME addr=$HOST_ADDR (rc=$rc)"
fi
exit $rc
