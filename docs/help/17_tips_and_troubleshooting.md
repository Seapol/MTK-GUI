# Tips & Troubleshooting

Sixteen things that are worth knowing before they cost a shift. Each tip is
one paragraph plus a pointer to the chapter that explains it in full.

### 1. Where your data lives

Everything that must survive a software upgrade is under
`C:\MTK_Station\work\`: `projects\`, `reports\<PROJECT>\`,
`sharepoint\<PROJECT>\`, `statistics\<PROJECT>\` and `accounts\`. Replacing
the `app\` folder never touches it. Deleting `work\` deletes the station's
history.

**More:** chapter 2 (Getting Started), under "Suggested First-Run Sequence".

### 2. One editor for YAML

Use the **Yaml Build** page. The Excel export exists for reviewing a plan
offline (and for limits / nominal edits); the YAML is the source of truth.
A plan is only really changed when the YAML says so.

**More:** chapter 9 (Yaml Build Page), under "Excel Import / Export".

### 3. Excel round-trip rules

The export marks columns read-only; changing a read-only column and
re-importing loses that edit. Import is field-by-field, so an empty cell
clears the field it belongs to. Fill a cell only when you mean to change it.

**More:** chapter 9 (Yaml Build Page), under "Excel Import / Export".

### 4. Console output keeps its colours - also on paper

The DUT console is rendered with its ANSI colours, dim text is lifted so it
stays readable, and the PDF appendix is capped at 10 pages (800 wrapped
lines). The full transcript is always written next to the PDF as
`<pdf name>_console_log.txt`.

**More:** chapter 10 (Console), under "Console Log Area".

### 5. `fat.log` wins

When a run pulls `fat.log` from the DUT, the report appendix renders that
file, not the console capture. The report states which source it used, so
the appendix never silently mixes the two.

**More:** chapter 11 (Reports & Logs), under "Session batch & export (Supervisor)".

### 6. The Shopfloor light

One lamp in the status bar reports the SharePoint upload of the last run:
grey = not configured, green = uploaded, amber = no upload yet, red =
failed. Hover it for the reason.

**More:** chapter 11 (Reports & Logs), under "SharePoint Upload (Report menu)".

### 7. Uploads happen three times by themselves

At the end of a run, when the Upload dialog is opened, and once at startup
for whatever the previous session left pending. You can upload the pending
files without running again.

**More:** chapter 11 (Reports & Logs), under "SharePoint Upload (Report menu)".

### 8. Exit waits for the upload

Leave the GUI with `File → Exit`. An upload in flight is waited for (up to a
few seconds per file); killing the process instead can cut the upload and
leave a partial file on the share.

**More:** chapter 3 (Menus Reference), under "File Menu".

### 9. Statistics are per project and per month

The history is one `work\statistics\<PROJECT>\YYYY-MM.jsonl` per month. A
failed write is a warning in the Event Log and never stops the run.

**More:** chapter 11 (Reports & Logs), under "ReportPage (route `reports`)".

### 10. A run with no measurement is not counted

The run-end hook only records a unit when `cycle_times` is non-empty, so
browsing without a real run does not pollute the yield. Load a plan, run it,
and the unit is counted once.

**More:** chapter 4 (Test Work Flow Page), under "How a Run Executes".

### 11. Host Wi-Fi and Bluetooth tests are adapter-bound

They read through `netsh wlan` and the WinRT BLE API: Airplane mode yields
zero results, a classic-only dongle cannot see BLE advertisements, and
`WLAN AutoConfig` must be running. Never run them on the NIC that carries
instrument traffic.

**More:** chapter 7 (Station Equipment), under "Test Peripherals".

### 12. Virtual mode is for training

`Virtual` runs the same plan against a simulated DUT and the fault injector;
use it to practise before the fixture and the real DUT are on the line.

**More:** chapter 1 (Overview), under "Modes: Real and Virtual".

### 13. `FAIL` is the board, `Error` is your station

A row that never produced output - a console still busy with the previous
command, an instrument backend throwing, a budget elapsing with nothing
captured - is reported as `Error`, not `FAIL`. Admitting a board is honest
only when the DUT actually answered something wrong. Read the Event Log line
next to the verdict before you blame either side.

**More:** chapter 4 (Test Work Flow Page), under "PASS, FAIL and Error - who owns the row".

### 14. A disabled row is a coverage decision, not a deletion

When the rack cannot perform a test (an AP that isolates clients, no paired
Bluetooth peer, no loopback jumper), uncheck `EN`, keep the row, and write the
reason as a YAML comment beside it. The run then logs
`FCT <row> -> Ignore (disabled)` and the gap stays visible in the table and
report. Coverage you cannot see is coverage you do not have.

**More:** chapter 4 (Test Work Flow Page), under "A row the bench cannot support".

### 15. The row budget must outlast the work inside it

A 10 s BLE scan inside a 15 s row can only end in `budget exceeded ... (no
verdict) -> ERROR`. Size the budget at least a couple of seconds above the
sub-timeout it wraps, and watch the Event Log for the advisory
`WARNING budget ... <= declared sub-timeout ...`.

**More:** chapter 4 (Test Work Flow Page), under "PASS, FAIL and Error - who owns the row".

### 16. Every powered row reading ~0 V means the supply, not the board

`Power On DUT` sets no voltage - it is a passive state row. The N5747A
output and current limit live in **04 · Equipment Config**. Left empty, the
supply stays off and the whole powered column fails together
(`DCV = 0.001 V but PSU output is OFF`), clocks included (`0 Hz (DUT
unpowered)`). Fill the Equipment Config card before blaming the DUT.

**More:** chapter 15 (Example Build of ICT Test Case), under "Before you run".
