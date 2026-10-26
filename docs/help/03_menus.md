# Menus Reference

The main menu bar has seven menus in a fixed order:
**File / View / Settings / Tools / Run / Report / Help** (Help is
the rightmost). The bar lives inside the window on every platform
(the native macOS top-of-screen bar is disabled on purpose), and it
is built once - no page, project or window state ever reorders it.
This chapter walks through every entry: what it does and which
dialog it opens. Menu entries that require a permission are noted;
the permission keys themselves are described in chapter
`04_test_workflow.md` (How Permissions Affect the Page).

## File Menu

Project file and account handling.

- **Load Yaml…** - opens the platform file-open dialog and loads a
  project YAML into the whole application (test tables, rails,
  consoles, instrument parameters, channel allocation). The run
  gate blocks any run until a project is loaded. Large plans load
  through a staged chain tracked by a **modal progress dialog**
  (`Loading project…`, stages at 5 % / 25 % / 45 % / 95 % / 100 %);
  the same stages also mirror on the global status bar. Run Control
  and the double-click table editing are disabled until the load
  completes, and a project already loaded is closed automatically
  FIRST (switching projects never blends two test projects). A run
  still active blocks the load with a hint - stop it first. *Dialog:
  file open dialog + progress dialog.*
- **Apply and Save Yaml** - commits the current page state into the
  project YAML model and saves it to the loaded file. Saving a
  project without usable test items asks for confirmation first.
  *Dialog: confirmation box (only when the plan has no test
  items).* Operator accounts without the save permission see the
  entry disabled.
- **Save as Yaml…** - same commit, but writes to a chosen file.
  *Dialog: file save dialog.* Permission-gated like the save above.
- **Close Yaml** - unloads the current project: the ICT / FCT test
  tables clear COMPLETELY (zero rows - no placeholder rows since
  2026-10-15), rails and the Overall Flow clear, the Overall Result
  resets (the Event Log history is kept). *Dialog: confirmation
  box.*
- **Switch Account…** - opens the login dialog again for an account
  change; switching to Supervisor requires the password
  re-authentication. *Dialog: login window.*
- **Exit** - closes the application (ordered resource cleanup).

## View Menu

Look-and-feel of the station.

- **Console Background Color…** - opens a colour picker and applies
  the chosen background to every console pane. *Dialog: colour
  picker (QColorDialog).*
- **Reset Background (Black)** - restores the factory black console
  background. No dialog.
- **GUI Theme** - submenu with five exclusive colour schemes:
  `Light`, `Dark`, `Ocean`, `Forest`, `High Contrast`. Selecting one
  restyles the whole application immediately and the choice is
  persisted (restored on the next start). No dialog.

## Settings Menu

Configuration functions - mostly supervisor territory.

- **Operator Permissions…** - supervisor-only. Opens the permission
  matrix where every Operator right is granted or revoked (Save
  YAML, edit ICT / FCT, Product Information, Long Run, serial
  parameters, channels, Equipment configuration, ...). The matrix
  is saved to `config/permissions.json`. *Dialog: Operator
  Permissions window.*
- **Auto-SN (virtual serial, +1 per run)** - checkable toggle. When
  active, the four Product Information fields are disabled and
  filled virtually on every Run (defaults + an auto-incrementing
  serial). No dialog.
- **Serial Number Format Check...** - opens the serial rule editor
  (`prefix` + digit count, either part may stay empty = not
  checked). The rule is applied by the pre-test check before every
  run. *Dialog: Serial Number Format Check window.*
- **Virtual Fault Injection...** - only enabled in Virtual mode
  with a Supervisor account. Opens the fault-injection configuration
  (Virtual Test Fail Ratio 0-100 %, Virtual Equipment Error 0-100
  %). *Dialog: Virtual Fault Injection window.*

## Tools Menu

One submenu: **Set All instruments** with four batch operations
over every instrument configured in the project YAML. The batch
runs on a worker thread (the UI never freezes), every result line
lands in the Event Log and the status-bar LEDs follow the result.
Failures pop up an error dialog naming the instrument (see chapter
`06_instruments.md`). Every batch action except `Disconnect all`
also hands the live instrument session to the Test Work Flow page
for Real-mode runs.

- **Connect all** - batch connect of every configured instrument
  plus identification read.
- **Disconnect all** - batch close of all connections; the run
  gateway is detached again.
- **Reset all** - batch reset of every configured instrument.
- **Test all connections** - reconnect + `*IDN?` identify every
  instrument to verify the wiring.

## Run Menu

The Visual-Studio-style debug entries - the same actions as the
Run Control panel buttons, with the standard shortcuts bound
application-wide. The full behaviour (gates, breakpoints, stepping)
is described in chapter `04_test_workflow.md` (Run Control, Debug
Controls).

- **Run** (`F5`) - start a run, or continue from a paused
  breakpoint. No dialog (the run gates may pop their warnings).
- **Run Without Debug** (`Ctrl+F5`) - run once ignoring every
  breakpoint.
- **Stop** (`Shift+F5`) - abort the current run (teardown rows
  still execute).
- **Restart Run** (`Ctrl+Shift+F5`) - abort, then start fresh.
- **Step** (`F10`) - execute exactly one more workflow node, then
  pause.
- **Step Into** (`F11`) - same granularity, keeps single-step mode
  engaged.
- **Continue** (`Shift+F11`) - leave single-step mode and resume
  full speed.
- **Toggle Breakpoint** (`F9`) - toggle the breakpoint of the
  current row of the focused ICT / FCT table.
- **Clear All Breakpoints** (`Ctrl+Shift+F9`) - remove every
  breakpoint.
- **Run to Cursor** (`Ctrl+F10`) - temporary breakpoint on the
  current row, start / continue, auto-remove when hit.

## Report Menu

Quality and traceability outputs (chapter `11_reports_logs.md`
covers the file formats).

- **Generate Report…** - opens the DUT Report view and exports the
  PDF report: product / batch information, test time, the summary
  of every test result and the complete console log dump. Fixed
  file naming `DUT_[PASS/FAIL]_[Serial#]_[Core ID]_[Project
  Part#]_[Batch#]_[Date]_[Time].pdf`. *Dialog: DUT Report window.*
- **Event Log** - opens the Event Log viewer (the full session log
  with filtering, Error / Warning highlighting and export for
  traceability). *Dialog: Event Log window.*
- **Statistics** - opens the quality statistics view: choose the
  range (day / week / month / year / batch) and read Yield, average
  cycle time, UPH/UPD, CpK and the error ranking. *Dialog:
  Statistics window.*
- **SharePoint Upload...** - opens the SharePoint upload dialog: site
  share link, local folder, real-time sync vs timestamped packaged
  upload, and **Connect & Sign in...** for the real tenant session
  (embedded login window, MFA included; no password is stored). Test
  Connection probes reachability and write permission with that
  session. Virtual mode uses the fake transport. *Dialog: SharePoint
  Upload window.*

## Help Menu

- **User Guide** - renders the all-in-one guide (this document,
  every chapter on one page with a sidebar TOC) into a temporary
  HTML file and opens it in the system web browser.
- **About** - opens the About dialog with the version, branch and
  build information (silently degraded when the build metadata is
  unavailable). *Dialog: About window.*

## Permission Quick Map

| Menu entry | Operator default | Permission key |
|---|---|---|
| File > Load Yaml… | available (always allowed by design) | - |
| File > Apply and Save Yaml | disabled | `save_yaml` |
| File > Save as Yaml… | disabled | `save_yaml` |
| Settings > Operator Permissions… | supervisor only | - |
| Settings > Auto-SN | gated | `run_policy_auto_sn` |
| Settings > Serial Number Format Check... | gated | `sn_format_check` |
| Settings > Virtual Fault Injection... | Virtual mode + supervisor only | - |
| Run menu | available (Run / Stop stay available for every role) | run-policy entries follow `run_policy_stop_failure` / `run_policy_stop_short` |
| Tools > Set All instruments | available | equipment windows follow `equipment_config` |
| Report menu | available | - |
| Help menu | available | - |
