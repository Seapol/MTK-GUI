# Tips & Troubleshooting

Twelve things that are worth knowing before they cost a shift. Each tip is
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
