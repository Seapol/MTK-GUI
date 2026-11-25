# FCT example — FRDM-IMX93, i.MX93 EVT (Proto-1), rev 1.3.1

The FCT plan that reached `Overall Flow: ICT -> FCT all PASS` on the real
bench on 2026-11-24 (Run #27). It is the reference for a message-based FCT
stage: every row is a serial / CLI / dialog exchange whose verdict comes from
the DUT's own reply, not from a numeric measurement.

## What is in the file

| Item | Count |
|---|---|
| FCT rows | 45 |
| Enabled at the last real run | 42 |
| Verdicts in Run #27 | 34 PASS / 11 Ignore / 0 FAIL / 0 ERROR |
| Cycle time | 4:52 total, ~2:50 automated, the rest the two human gates |

## Why three rows are disabled

They stay in the file, disabled, with the date and the reason written above
each one. That is deliberate: a closed item must remain readable so the next
engineer can re-open it after one look.

- `Wi-Fi iPerf Throughput (iperf3)` — the lab AP isolates clients, so the DUT
  (`192.168.71.12`) never reaches the host iperf3 server (`192.168.71.8:5201`)
  although ARP resolves both ways.
- `BT L2CAP ping` — no paired peer exists; the DUT answers
  `BT_L2CAP_UNCONFIGURED`.
- `Pull FAT log` — the serial pull protocol is structurally broken on this
  firmware, so the run falls back to the console transcript.

Re-enable each row only after its precondition is met; the full condition list
is in `docs/fct/FCT_coverage_closeout_2026-11-24.md`.

## Two defects this bench run found, and both are fixed

- `Bluetooth RSSI` budget: a 15 s budget was declared while the row also
  declared three 35 s sub-timeouts. The row now retries the scan twice and
  declares 35 s in all three places.
- `run_step` warns `WARNING budget ... <= declared sub-timeout ...` before a
  row starts, instead of failing 15 s into it.

## How to load it

1. Log in as **Supervisor** on the real bench.
2. `File → Load Project` and pick
   `FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev_1.3.1.yaml`.
3. Open **Test Work Flow**, check that the ICT stage is disabled and FCT is
   enabled, then press **Run**. The two `MessageGoStop` rows stop for a human
   PASS/FAIL.

Slot numbers, IP addresses and serial ports in this file are the ones of the
2026-11-24 bench; change them on the **Equipment** page for your own station
before running.
