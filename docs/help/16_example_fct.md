# Example Build of an FCT Test Case — FRDM-IMX93 (rev 1.3.2)

This chapter walks you end-to-end through the shipped **FCT** example
product: **FRDM-IMX93** (NXP i.MX93 evaluation board). FCT is a *message
test* — the GUI drives the DUT through its serial console, Wi-Fi /
Bluetooth interfaces and operator dialogs, and every step passes when the
expected message appears (for example `RF drivers loaded OK`,
`WIFI_CONNECTED_OK`, `Overall result: PASS`) or fails when an error
message shows up.

This project is **FCT-only**: the ICT stage is disabled and the board
ships with the FAT firmware already flashed, so the plan carries **no
firmware-flash rows**. Every FCT row is a serial / transfer / RF exchange
whose verdict comes from the DUT's own reply.

**Goal of this tutorial**

- Load the shipped FRDM-IMX93 FCT plan (rev 1.3.2).
- Walk through the 7 nodes of the **Yaml Build** wizard.
- Understand the 41-row FCT sequence and the DUT-side scripts it calls.
- Run it on the bench and export the plan / report for review.

## Prerequisites

- The FRDM-IMX93 board is powered on and connected:
  - USB serial (CDC) to the host PC — the console appears as a COM port
    on Windows (for example `COM4`) or `/dev/cu.usbmodem...` on macOS.
  - Optional: Ethernet / Wi-Fi link between the DUT and the host for the
    file copy and the throughput tests.
- Supervisor login (the Operator role cannot edit the Yaml Build wizard).
- A station whose instruments and peripherals are configured on the
  **Equipment** page before the first run.

## Step 1 — Load the project YAML

Open **File → Load Yaml…** and pick the shipped reference plan:

```text
examples\fct_frdm_imx93\FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev_1.3.2.yaml
```

The loader fills the model, the product metadata and the Overall Flow band
in one pass. Forty-one rows appear in **Test Work Flow**; the ICT stage
stays empty because this plan is FCT-only, and every row sits at
**Pending** until you run.

| Fact | Value |
|---|---|
| FCT rows | 41 (all enabled) |
| Step taxonomy | M160 `category` + `type` |
| Firmware flash rows | 0 (board ships pre-flashed) |
| ICT stage | disabled |
| FCT stage | enabled |

## Step 2 — Open the 7-node Yaml Build wizard

Go to **Yaml Build**. The flow shows seven nodes; for this plan five are
**Completed** and two are **Unused**:

| Node | State | Why |
|---|---|---|
| 01 Design Input | Completed | product info + FCT test types |
| 02 Parse nets for ICT | Unused | ICT is disabled |
| 03 Firmware Config | Completed | FAT / OOBE both disabled (no flash) |
| 04 Equipment Config | Completed | instruments + peripherals |
| 05 Build ICT Test Sequence | Unused | ICT is disabled |
| 06 Build FCT Test Sequence | Completed | the 41-row sequence |
| 07 Apply & Save Yaml | Completed | validation OK, draft/final files |

Clicking an **Unused** node does not open a dialog — the step is out of
scope for an FCT-only plan, and that is the expected behaviour.

## Step 3 — Review the FCT sequence (node 06)

Open **06 Build FCT Test Sequence**. The left table shows the 41 rows as
`# / Name / Type / Channel / Timeout / Retries`; the right editor edits the
selected row. The `Type` column uses the M160 two-level vocabulary
(`category.type`), so a serial exchange is `Console.serial`, a file copy is
`Transfer.serial_put`, and a radio check is `Wifi.scan`.

The 41 rows in order:

| # | category.type | Name |
|---|---|---|
| 1 | Operation.power_on | Power On DUT |
| 2 | Console.serial | Boot wait for prompt |
| 3 | Console.serial | Acquire root shell |
| 4 | Console.serial | Kernel check |
| 5 | Console.serial | Prepare asset dir |
| 6 | Transfer.serial_put | Deploy test assets to DUT |
| 7 | Console.serial | Load RF drivers |
| 8 | Console.serial | Wi-Fi connect |
| 9 | Wifi.scan | Wi-Fi Scan / RSSI (DUT console) |
| 10 | Wifi.ping | Wi-Fi Ping (Host->AP / DUT->AP / DUT->Host) |
| 11 | Wifi.iperf | Wi-Fi iPerf Throughput (iperf3) |
| 12 | Console.serial | BT discoverable |
| 13 | Bluetooth.rssi | Bluetooth RSSI |
| 14 | Console.serial | BT L2CAP ping |
| 15–38 | Console.serial | FAT functional block (24 rows, `Overall result: PASS`) |
| 39 | Transfer.serial_pull | Pull FAT log |
| 40 | Console.serial | Cleanup assets |
| 41 | Operation.power_off | Power Off DUT |

The **Add Step** menu lists the seven FCT categories — Operation, Console,
Message, Transfer, ExternalGui, Wifi, Bluetooth — each with its FCT
sub-types. Measurement (R-GND / voltage / clock) and the ICT-only
operations are not offered here because they belong to the ICT builder.

## Step 4 — The DUT-side assets

The FCT chain calls a small set of files that must exist on the DUT
rootfs. They are **project assets**: they live in the project's
`assets_FRDM-IMX93/` folder and the `Transfer.serial_put` row (row 6)
copies them onto the DUT before the row that runs them. Nothing is
pre-installed on a production DUT.

The shipped deploy list:

| Host asset | DUT path |
|---|---|
| `assets_FRDM-IMX93/drivers/load_rf_drivers.sh` | `/root/fct_assets/drivers/load_rf_drivers.sh` |
| `assets_FRDM-IMX93/scripts/connect_wifi.sh` | `/root/fct_assets/scripts/connect_wifi.sh` |
| `assets_FRDM-IMX93/frdm_imx93_board_test.zip` | unzip `/root/fct_assets` |

Success markers the rows look for:

| Script / command | Pass marker |
|---|---|
| `load_rf_drivers.sh` | `RF drivers loaded OK` (with `BT_AUDIO_READY`) |
| `connect_wifi.sh router` | `WIFI_CONNECTED_OK` / `WIFI_CONNECT_FAIL` |
| FAT block (`fat.py`) | `Overall result: PASS` / `Overall result: FAIL` |

The `send` strings above come from the project YAML — keep each script's
final marker in sync with that row's capture pattern. Every script prints
exactly one OK line on success and one FAIL line on failure, so the capture
pattern is unambiguous.

The rows call the interpreter explicitly (`sh …` / `bash …`), which only
needs **read** permission on the file: no execute bit is required, so a
serial push never has to preserve file modes. Do **not** add `chmod +x`
rows — they cost a serial round-trip and hide the real question (whether
the file arrived intact).

## Step 5 — Save and export for review

1. **File → Save Yaml As…** — save the project under your own name.
2. **Yaml Build node 07 → Export MTK ICT Excel Sheet…** is for ICT
   plans; for this FCT-only plan, export the full sequence from
   **File → Export Config Workbook…** and hand it to the design engineer
   with the DUT script list for review.
3. Iterate on the captured patterns / limits and re-export until the plan
   is approved, then publish `Draft` → `Final`.

## Windows real-hardware runbook

### 1. DUT power-cycle timing (row 1)

Row 1 is `Operation.power_on` with a Go/Stop gate. Press **Run**; the
GO / STOP dialog appears, then:

1. **Power the DUT on.**
2. **Wait for the `login:` prompt (~25 s on the FRDM-IMX93 BSP).**
3. **Press GO.**

Pressing GO before the prompt is up leaves the carriage return in the
U-Boot window and can abort autoboot. Row 2 (`Boot wait for prompt`)
guards the exact moment the console is ready.

### 2. Host iperf3 server (row 11)

The throughput test needs an iperf3 server on the Host PC. The plan uses
the host address from the station configuration (`192.168.71.8` in the
shipped file); start the server before the run:

```text
iperf3.exe -s -D
```

- The server port (5201) must be allowed inbound by Windows Defender
  Firewall (see `14_faq.md`, Q17).
- The host runner kills the process after its timeout, so a long-running
  server must be detached (`-D`) — never foreground.

### 3. Serial pull of the FAT log (row 39)

`Transfer.serial_pull` pulls `/root/fat.log` into the DUT report over the
serial channel, then deletes the remote copy. Without the DUT serial
console bound, the row is an ERROR — it never falls back to Wi-Fi.

## Summary — the FCT build loop

- Load the YAML → review the 7 wizard nodes → check the 41-row FCT
  sequence → copy the DUT assets → run → export the report.
- FCT passes on **message evidence**: every row needs its capture pattern
  (`RF drivers loaded OK`, `WIFI_CONNECTED_OK`, `Overall result: PASS`).
  Keep the DUT scripts and their output markers in sync with the YAML
  captures.
- This FRDM-IMX93 plan has **no firmware-flash stage** — the board ships
  pre-flashed, so node 03 keeps FAT / OOBE disabled and the sequence has
  no ExternalGui.flash row.

## The plan that runs on the bench

```text
examples\fct_frdm_imx93\FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev_1.3.2.yaml
```

Forty-one rows, all enabled. Bench results are recorded after the
three-run verification pass and appended here with the date, the PASS /
FAIL / ERROR split and the per-unit cycle time.
