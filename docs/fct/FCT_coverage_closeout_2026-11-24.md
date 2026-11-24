# FCT Coverage Closeout — FRDM-IMX93 (2026-11-24 night session)

Scope: the FCT stage on the FRDM-IMX93 rack, run #24–#27. The full per-run
transcript (bench table, console evidence, earlier run #19–#23 rows) lives on
the rack PC at `docs/fct/FCT_real_machine_verification_2026-11-24.md`;
this file is the record that belongs with the code.

## 1. Result

| Run | Start | Wall | Outcome |
|---|---|---|---|
| #24 | 23:08 | 182.75 s | rows 1–36 green, `Wi-Fi iPerf` ERROR (bench: AP client isolation) |
| #25 | 23:31 | 2:51 | `Bluetooth RSSI` ERROR `budget exceeded 15.3s > 15s (no verdict)` |
| #26 | 23:39 | 3:33 | RSSI PASS −55 dBm; `BT L2CAP ping` ERROR `46.6s > 45s (no verdict)` |
| #27 | 23:45 | **4:52** | **34 PASS / 11 Ignore / 0 FAIL / 0 ERROR — Overall PASS** |

Run #27 output: `DUT_PASS_i.MX93_FRDM-IMX93_EVT-(Proto-1)_2026-11-24_23-50-53.pdf`
with the CSV and console transcript beside it. Wall time includes two operator
gates (`Power On DUT`, `Power Off DUT`); the automated part is ≈2:50 against
≈25–30 min for the same 45 rows by hand on this bench.

## 2. Row ledger (run #27)

| # | Test | Result |
|---|---|---|
| 1 | Power On DUT | PASS 4.32 s |
| 2–3 | Enter USB download mode (FAT) · Burn FAT firmware | Ignore |
| 4 | Boot wait for prompt | PASS 0.55 s |
| 5 | Acquire root shell | Ignore (setup row, no judge) |
| 6 | Kernel check | PASS 0.52 s |
| 7 | Prepare asset dir | Ignore (setup row, no judge) |
| 8 | Deploy test assets to DUT | Ignore |
| 9 | Load RF drivers | PASS 5.02 s |
| 10–33 | FAT × 24 | PASS, 2.08 – 18.09 s |
| 34 | Wi-Fi connect | PASS 16.09 s |
| 35 | Wi-Fi Scan / RSSI (DUT console) | PASS 0.12 s (−17 dBm) |
| 36 | Wi-Fi Ping (DUT -> AP gateway) | PASS 4.13 s (5/5, 0 %) |
| 37 | Wi-Fi iPerf Throughput (iperf3) | **Ignore (disabled — bench)** |
| 38 | BT discoverable | PASS 16.03 s |
| 39 | Bluetooth RSSI | PASS 10.16 s (−56 dBm vs −70) |
| 40 | BT L2CAP ping | **Ignore (disabled — bench)** |
| 41 | Pull FAT log | **Ignore (disabled — software)** |
| 42 | Cleanup assets | Ignore |
| 43–44 | Enter USB download mode (OOBE) · Burn OOBE firmware | Ignore |
| 45 | Power Off DUT | PASS 124.61 s (incl. operator wait) |

## 3. The three rows the rack cannot judge, and how to re-enable them

Each row stays in the plan, `EN` unchecked, with the reason written as a YAML
comment beside it. The gap is visible in the table and the report instead of
disappearing from the count.

1. **`Wi-Fi iPerf Throughput (iperf3)`** — the lab AP isolates clients: the DUT
   (`192.168.71.12`) and the host (`192.168.71.8`) resolve each other's ARP but
   exchange 0 ICMP and 0 TCP bytes (ping 5/5 lost each way; the host's own
   loopback iperf3 is fine; the firewall rules are present and Enabled; the
   WLAN profile is Public and cannot be switched to Private without admin).
   Re-enable when host and DUT sit on a non-isolating segment, or when the
   host is wired into the AP LAN. DUT throughput was measured before the AP
   was found guilty: 255/256 Mbits/sec (ser), 169–226 Mbps manual runs.
2. **`BT L2CAP ping`** — no paired peer exists on the rack, so the DUT truthfully
   answers `BT_L2CAP_UNCONFIGURED` (verified on COM4). The row only becomes
   judgeable once `host_bt_addr` names a real peer and `BT_L2CAP_OK` is one of
   its pass markers; today it could only burn its budget to an ERROR.
3. **`Pull FAT log`** — the serial pull protocol is structurally broken: the
   DUT-side `read -r ack` consumes the chunk stream and every host `ACK <seq>`
   lands as a shell command (`-sh: ACK: command not found` interleaved into the
   base64). The report falls back to the console transcript, so no evidence is
   lost while the row is off. Fix owner: `serial_transfer.py`.

## 4. Two defects fixed during the closeout (m120)

- **A row budget equal to its own sub-timeout can only end in ERROR.** The RSSI
  row declared `rf_timeout_s: 15.0` inside a 15 s budget and logged
  `budget exceeded 15.3s > 15s (no verdict)`. The plan now declares a 10 s scan
  with `scan_attempts: 2` inside a 35 s row, and `run_step` logs a pre-flight
  `WARNING budget ... <= declared sub-timeout ...` so the next engineer sees
  the mistake before the work starts.
- **A missed BLE advertisement is a timing event, not a DUT fault.** the host
  scan retries once (2 s gap) before deciding; backend exceptions remain ERROR,
  a genuinely invisible DUT remains FAIL.

Earlier in the same session: console verdict truth (bare `\r` line separators
must not let a regex read two lines as one, shell echo of the command must not
count as a marker) and the iperf truth fixes (`-O 1 -J` hangs on the DUT's
iperf 3.16; an interrupted client wedges the host server, so the server is
restarted and health-probed before every measurement).

## 5. KPI status against the four design goals

| Goal | Status |
|---|---|
| Generality — new board, no code change | the plan is YAML-driven; tonight needed only YAML edits and comments |
| Lower effort than manual serial testing | 4:52 with two operator gates vs ≈25–30 min by hand |
| No fake testing | 0 FAIL / 0 ERROR; every PASS carries a real number or captured text |
| Clearly faster, reasonable duration | automated part ≈2:50; slowest rows: ETH throughput 18 s, BT discoverable 16 s, Wi-Fi connect 16 s |
| Coverage | 34/45 executed green, 3 rows bench/software-gated and documented, 8 setup/teardown rows by design |

Still missing, and **not** bench-gated: OOBE flashing (rows 43–44) needs a
download-mode procedure for this board; it is planned work.

## 6. Reproduce run #27

1. Close the GUI so COM4 is free; pre-stage the assets (≈225 s at 115200 baud)
   if `/root/fct_assets` was wiped.
2. Start the GUI → Supervisor + Real → load the project YAML (answer **No** to
   "Fill Product Information") → Run.
3. Answer the two operator gates (`Power On DUT` / `Power Off DUT`); the plan
   leaves `Stop if failure` on for production, off when you want the full ledger
   in one pass.
4. Leave with `File → Exit` (never kill the process: an upload may be in flight).
5. Outputs: `dist/work/FRDM-IMX93/DUT Report/<stamp>/` (PDF + CSV + console
   log) and `dist/logs/event/event_No_Project_<stamp>.log`.
