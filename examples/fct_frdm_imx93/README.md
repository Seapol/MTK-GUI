# FCT example — FRDM-IMX93, i.MX93 EVT (Proto-1), rev 1.3.2

The FCT plan for the FRDM-IMX93 board in the M160 step-type taxonomy
(`category` + `type`, 8 categories). ICT is disabled and the DUT ships with
FAT firmware already flashed, so this plan carries **no firmware-flash
stage**: every FCT row is a serial / transfer / RF exchange whose verdict
comes from the DUT's own reply.

## What is in the file

| Item | Value |
|---|---|
| FCT rows | 41 |
| Step taxonomy | M160 `category` + `type` |
| Firmware flash rows | 0 (board ships pre-flashed) |
| ICT stage | disabled |
| FCT stage | enabled |
| Yaml Build locks | 01 / 03 / 04 / 06 / 07 completed, 02 / 05 unused |

FCT row breakdown:

| Category | Count |
|---|---|
| Console.serial | 33 |
| Operation (power on / off) | 2 |
| Transfer (serial put / pull) | 2 |
| Wifi (scan / ping / iperf) | 3 |
| Bluetooth.rssi | 1 |

## How to load it

1. Log in as **Supervisor** on the real bench.
2. `File → Load Project` and pick
   `FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev_1.3.2.yaml`.
3. Open **Yaml Build** and check the 7 nodes: 02 Parse nets and 05 Build ICT
   are `Unused` (ICT disabled), the rest are `Completed`.
4. Open **Test Work Flow**, confirm ICT is disabled and FCT is enabled, then
   press **Run**.

Slot numbers, IP addresses and serial ports in this file are the ones of the
bench it was authored on; change them on the **Equipment** page for your own
station before running.
