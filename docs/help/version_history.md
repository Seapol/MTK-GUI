# Version History

Release log of the MTK GUI. The GUI version starts at
**v1.0.0.0**; at any time the application carries exactly ONE
version - the current release version.

**Versioning rule** (user directive 2026-10-14):

- `develop` commits are NOT recorded in this log and do NOT bump
  the version - between releases the GUI keeps showing the current
  release version.
- A **Release** bumps the four-segment version number, gets its own
  git commit (Release commit), and records its changes as one entry
  in this file. The release entry is reviewed by the owner BEFORE
  the release is committed and published.

Entry format:

```text
## v<MAJOR>.<MINOR>.<PATCH>.<BUILD> - <YYYY-MM-DD>
- <change>
```

## v1.0.0.0 - 2026-10-14

- Initial release baseline of the MTK GUI versioning scheme.
- Feature set at baseline: ICT / FCT test execution engine with
  stop policies, breakpoints and Long Run; Yaml Build plan
  authoring (five-card block flow with embedded channel
  allocation, Excel import / export, Draft / Final publishing with
  archive); Equipment rack block diagram with
  DAQ973A / DAQM908A / DAQM907A / U2355A / N5747A; multi-channel
  serial / SSH console; Real-mode honesty (no simulation without a
  connected rack); DUT report / Event Log / Statistics; role and
  permission management; five GUI themes; Windows packaging via
  PyInstaller + GitHub Actions.

## Latest activity (2026-11)

GUI head: **`d1c0248` (M132) - 2026-11-26**. Everything up to it is on
`origin/develop`; a bundle built from this commit runs the same test
logic as the head.

- `d1c0248` (M132) - Console drops the `Quick:` row: the dropdown plus
  `Save Cmd` / `Clear Cmd` and the `quick_commands.py` store are gone;
  `Font...` moves to the right end of the Send row, Tab completion keeps
  the sent history plus the AT catalog
- `c416481` -> `4b696fb` (M131) - node 04 Equipment Config becomes a
  seven-card launcher with one dialog per module; `Instruments` gates
  the other six (`LOCKED`); node dialogs size themselves from the
  panel's minimum height plus a 120px chrome reserve, so the four card
  rows fit without a scrollbar
- `1efcda8` (M130c) - read-only node and unchecked firmware slot force
  grey text on every child widget, not just the controls
- `2719f07` / `6a6ecf4` (M130) - node 03 keeps a single Pass keyword,
  the duplicate working-directory row is gone, disabled inputs are grey
  through the theme
- `1d89a66` / `e681264` (M129) - node 02 lays `Parsed Nets` and `Other
  Nets` side by side, 560px each
- `d02ee3a` (M128) - node dialogs are sized after layout activation, so
  node 01 is never clipped
- `b8c9c45` (M127/M128) - node dialogs own `Save Draft` / `Next`,
  padlocks, colour-coded cards and `Empty` / `Edited` / `Completed` badges
- `087d590` - design input two-column meta, revision dropdowns,
  side-by-side blocks
- `f58dd8b` - `File -> Restart GUI` restarts through the normal exit path
- `e01b6d5` - performance timing log on by default, runtime switch,
  stall watchdog and the live viewer
- `e165fd2` / `caaea2c` (M124) - node dialogs resizable and scrollable,
  capped inputs, `Next` inside the dialogs
- `d5f5fd0` (M123) - SharePoint REST calls follow the web that owns the
  folder
- `3ef9e3b` -> `d2395fe` (docs) - packaged builds name their commit and
  the User Guide is rebuilt against the live page

The complete commit-by-commit list follows below; release entries stay
above it, because `develop` commits do not bump the version.

## Development milestones (not releases)

Engineering traceability only: these are `develop` commits. They do
NOT bump the version and do NOT change what the application reports
as its current release.

- **M6** (2026-10-23, `7a179b6`) - BOM import in Design Input
  (`design_input.bom_file`; the shared `ict/netparse/bom.py` library
  serves both the GUI and the headless CLI); the Control IO DIO pool
  moved to the U2355A `DIO01` - `DIO24` (24-channel capacity,
  over-capacity reported as `gpio=24 (+4 over capacity)`, DAQM907A
  DIO stays fixture-reserved); the unused `mtkgui/gui/designinput/`
  package removed.
- **M7** (2026-10-23, `e7930ef`) - `U2355A DIO Read` (reference level
  log, always `Done`) and `U2355A DIO Write` (drive with
  `Channels` + `Pattern`) standard operations; DIO Write isolation
  preflight with three notice levels (not isolated / cannot confirm /
  passive-only), `Cancel` + `Force-Continue` modal and headless
  refusal; netparse `isolated` / `active_drivers` evidence in CSV,
  JSON and the Test Plan evidence markdown; the old 24-channel
  walking GPIO template row removed from the Test Work Flow page.
- **M8** (2026-10-26, `develop`) - Yaml Build page hang fix: the
  Channel Allocation tables refresh through a content fingerprint
  (`sha1` of the testable nets + allocation state), so re-entering
  the page no longer rebuilds all three tables unconditionally (800
  nets: 0.43 s full rebuild -> ~0.005 s on an unchanged model, with
  3 regression tests); `save_to_model` skips the write when the data
  is unchanged and re-renders only the visible rows on a hit.
- **M9** (2026-10-26, `develop`) - `File > Load Yaml…` now shows a
  **modal progress dialog** (`Loading project…`, staged 5 / 25 / 45 /
  95 / 100 %), mirroring the same stages on the global status bar, so
  large project loads (e.g. the 537 KB / 800-net 96624 plan) no
  longer look frozen.
- **M10** (2026-10-26, `develop`) - SharePoint sign-in bypass for
  tenants that reject the embedded login (e.g. AD account validation
  failures): `Open in System Browser` signs in outside the app and
  `Import Browser Session...` imports the `FedAuth` / `rtFa` cookies
  copied from the browser (F12 > Application > Cookies) with a site
  host check, followed by an automatic Test Connection. New dialog
  strings (`not signed in - use Connect & Sign in, or sign in in your
  own browser then Import Browser Session`) and 6 new unit tests.
- **M11** (2026-10-26, `develop`) - modal progress dialog for
  `Parse Nets for ICT` (progress bridge) and for the Auto-Channel
  Allocation card (four phases: power 33 % -> clock 33 % -> control
  IO 33 % -> validating 100 %); failures are caught and surfaced as
  an error dialog instead of a frozen GUI.
- **M12** (2026-10-26, `develop`) - every dialog of the application
  (21 QDialogs) re-checked for sizing and window controls: oversized
  dialogs are clamped to the work area (DialogCenterer cap 92% ->
  85%) and all dialogs gain **minimize / maximize** buttons plus a
  size grip (`mtkgui/gui/dialog_sizing.py`: `fit_dialog` /
  `enable_dialog_controls`), so bottom button rows stay reachable on
  high-DPI displays.
- **M13** (2026-10-26, `develop`) - startup splash
  (`mtkgui/splash.py`, tkinter launch window before the heavy
  PySide6 / QtWebEngine imports) was added, then **removed on request
  (2026-10-27)** - it flashed by too quickly on cold starts and the
  login window follows almost immediately; the timing marks
  (`splash shown` / `splash closed`) were removed with it.
- **M14** (2026-10-26, `develop`) - SharePoint browser-session
  workflow completed: `Open in System Browser…` now opens the site AND
  the `Import Browser Session…` dialog in one click (paste `FedAuth` /
  `rtFa` from F12 > Application > Cookies). An automatic Edge
  debug-port handover was implemented and then **verified blocked** on
  this company Edge (v156): `--remote-debugging-port` is ignored on
  the real profile (anti-debug protection), cookies are app-bound
  encrypted so a copied profile cannot decrypt them, and the
  `RemoteDebuggingAllowed` policies are locked - documented in the
  Help, the paste path stays as the working one on managed hosts.
- **M15** (2026-10-27, `develop`) - SharePoint Upload **temporarily
  disabled** (user direction): the `Report > SharePoint Upload…` menu
  item is greyed out with a tooltip, and the handler shows a notice
  instead of opening the dialog (double guard). The dialog, engine,
  state and Help guide stay intact; re-enable with
  `sp_upload_action.setEnabled(True)` in `main_window.py`.
- **M16** (2026-10-27, `develop`) - timing log upgraded from
  startup-only to **full-lifecycle performance logging**: session
  header per process run (time / pid / frozen / python version);
  **wall-clock timestamp column** per event (correlate slow deltas
  with the clock); category column derived from the label prefix
  (`ui:`, `twf:`, `testflow:`, `yamlbuild:`, `io:`, `page:` …) with
  explicit override; `[WAIT]` markers + waited-time on spans that wait
  for the OPERATOR; per-thread begin/end pairing (worker threads no
  longer cross-pair into false mismatches). Instrumentation now covers
  the runtime, not just startup: page switches, staged YAML load,
  YAML save (file pick + write), Auto-Channel Allocation, DIO-write
  isolation confirm, Parse-Nets Excel export / import (file pick), the
  Export page file pick, and the SPF / NET / BOM import file picks -
  every wait-on-user action is marked `[WAIT]`. `MTK_TIMING=0` still
  disables the file. 9 unit tests.
- **M17** (2026-10-27, `develop`) - Help **User Guide** chapters 15
  and 16 added: `15 · Example Build of ICT Test Case` (96317 /
  FRDM-IMXRT700: SPF / NET / BOM import -> Parse Nets -> limits
  review -> channel allocation -> build sequence -> save YAML ->
  export test-plan Excel for design review) and `16 · Example Build
  of FCT Test Case` (FRDM-IMX93: load the demo YAML -> Console /
  Wi-Fi / Bluetooth / Sequence editor -> DUT-side Linux script list
  (`/root/preflight.sh`, `/root/load_rf_drivers.sh`, `/root/fat.py`,
  `fat_result.json`, `fat.log`, `iperf3`) and the scp / sftp copy
  steps). Both chapters are driven by live GUI walks with 15 new
  screenshots (`18_01`…`18_10`, `19_01`…`19_05` - retired on
  2026-11-25 and replaced by the walkthrough shots of M122); the chapter
  mount list (`help_content.py` `CHAPTERS`) grows from fourteen to
  sixteen chapters.
- **M18** (2026-10-27, `develop`) - FCT SFTP result round-trip: the
  GUI FCT executor (`fct_exec.py`) now handles `sftp_get` / `sftp_put`
  rows (previously only the CLI demo runner did), supports the
  `{{dut_report}}` token in the SFTP local path (resolved to the
  `DUT Report` folder at run start), creates the local parent
  directory on demand, and **removes the DUT-side file after a
  successful fetch** - so `fat_result.json` / `fat.log` land in DUT
  Report every run and stale results can never leak into the next
  test. The FRDM-IMX93 demo YAML's "Retrieve fat_result.json (SFTP)"
  and "Retrieve fat.log (SFTP)" rows now point at
  `{{dut_report}}/...` instead of the macOS absolute path. 4 new unit
  tests (`test_fct_exec.py`).
- **M19** (2026-10-27, `develop`) - Packaging: **projects travel with
  the exe**. The Windows bundle now ships the whole `projects/` tree
  into `_internal\projects` (runtime products are stripped: `*.pyc`,
  `__pycache__`, `_run_work`, `reports`, `fat_result.json`,
  `fat.log`), and `resolve_tenant_base()` picks the projects workspace
  as `MTKGUI_TENANT_BASE` env -> `projects/` next to the exe ->
  built-in `_internal\projects` -> CWD `projects`; the post-Load
  auto-save follows the same workspace. **Output directory is now
  configurable**: `build_windows.ps1 -OutDir <path>` packages
  anywhere (`-SkipProjects` excludes the projects data, `-KeepRunning`
  skips the GUI auto-stop).
- **M77** (2026-11-06, `develop`) - Windows real-hardware runbook
  cross-reference: see `16 · Example Build of FCT Test Case`
  ("Windows real-hardware runbook") and `14 · FAQ` **Q17** for the
  Windows firewall setup; the same milestone makes the host ping
  cross-platform, makes the Wi-Fi connect step really consume its
  `timeout_s`, judges Bluetooth pair / A2DP on the DUT when the host
  CLI is unavailable, and auto-binds the SFTP `ssh` channel over the
  Wi-Fi DUT IP.
- **M78** (2026-11-06, `develop`) - timeout truth and run purity:
  one resolved wall-clock budget per step (the old 99999 ms clamp is
  gone, the Wi-Fi op budget covers association, the hidden 60 s iperf
  budget is gone, over-budget steps are aborted with
  `budget exceeded: Xs > Ys -> FAIL`), an application-level stall
  watchdog (`Tools > FCT Watchdog`, default 8.0 s, 0 = off, persisted
  across sessions), and **Console buffer semantics** - pressing Run
  clears the Console display and the channel read buffers before step
  1, one run reads only bytes produced during that run, the finished
  log stays on screen, and each report embeds exactly one run's log
  (see `docs/fct/B4-FCT-Execution-Design.md` §7.1).



- **M79** (2026-11-06, `develop`) - the sequence builder rejects a
  sequence that contains no real test (an operations-only plan is
  configuration, not a test plan).
- **M80-A** (2026-11-07, `develop`) - Equipment page layout pass:
  deletions, dialog merges, and the left column restructured.
- **M80-B** (2026-11-07, `develop`) - network mode selection with
  schema additions and auto-detect for the host/router links.
- **M80-C** (2026-11-08, `develop`) - mirror guard, mode-key
  preservation and the address-combo test fix.
- **M83** (2026-11-07, `develop`) - shared editor layout kit: every
  editor page is built from one set of spacing / button / dialog
  helpers instead of per-page magic numbers.
- **M84** (2026-11-08, `develop`) - `Tools > Config assets` removed;
  assets are project-owned.
- **M85** (2026-11-08, `develop`) - the Config assets panel and the
  `Sync from Equipment` helper removed.
- **M87** (2026-11-09, `develop`) - statistics history moved to
  `work\statistics\<PROJECT>\` as monthly JSONL.
- **M87-F** (2026-11-09, `develop`) - `append_run` shards by the
  record month, not the wall clock.
- **M90** (2026-11-08, `develop`) - the two Event Log entries folded
  into one Settings submenu.
- **M92** (2026-11-08, `develop`) - `Stop if any short` renamed to
  `Stop if any R-GND short`, so the policy names what it measures.
- **M93** (2026-11-08, `develop`) - the checked checkbox draws a real
  check mark in the indicator.
- **M95** (2026-11-08, `develop`) - the Console LEDs left the status
  bar; the channel state lives in the Console tabs.
- **M96** (2026-11-08, `develop`) - `DAQ CSV Data` entry removed and
  the report folders moved into Settings.
- **M97 / M98** (2026-11-08 / 2026-11-11, `develop`) - the
  supervisor password was briefly stored as a station hash (M97) and
  then restored as the single source constant in
  `mtkgui/permissions.py` (M98), so nobody has two places to change.
- **v2-0** (2026-11-18, `develop`) - housekeeping: the pending M99
  follow-ups landed before the v2 rework.
- **v2-1** (2026-11-18, `develop`) - **retired flash-probe vendors**:
  the five third-party debug-probe toolchains were removed everywhere;
  the acceptance is a grep test over `mtkgui/`, `tests/` and `docs/`.
- **v2-2 / v2-2b** (2026-11-18, `develop`) - config, settings and the
  event log moved out of the package into the station workspace, and
  the timing suite re-greened.
- **v2-3a** (2026-11-18, `develop`) - the seven-step Yaml Build shell
  landed; the tab presents it as five visible nodes (04 Build ICT is one
  editor, not three separate step pages).
- **v2-3b** (2026-11-18, `develop`) - node 01 rebuilt as three
  blocks: route select, product information, design files.
- **v2-3c / v2-3d** (2026-11-18, `develop`) - the demo clock row got
  its test point so 4 MHz routes to the U2355A counter, and the four
  suites the rebuild left stale went green.
- **v2-3e** (2026-11-19, `develop`) - the seven-step wizard mounted in
  the Yaml Build tab and shares one model with the page.
- **v2-4** (2026-11-19, `develop`) - Route B (traditional ICT Excel)
  importer plus the rules.v2 schema.
- **v2-5** (2026-11-19, `develop`) - node 03 Firmware Config panel.
- **v2-9a** (2026-11-18, `develop`) - the five fixture operations
  collapsed into one `Fixture Ready` verdict.
- **v2-9b** (2026-11-18, `develop`) - power rails captured with a
  DAQ AI `Start/End` operation pair, so the waveform is one run's
  data.
- **v2-9c** (2026-11-18, `develop`) - run without limits: rows report
  **TBD** and the board ends **Pending** instead of a false PASS.
- **v2-10** (2026-11-19, `develop`) - node 04 Equipment Config
  (seven-tab model, panel, gate).
- **v2-11 / v2-11b** (2026-11-19, `develop`) - node 05 Build ICT
  sequence (flat model, six blocks) emitted as engine
  `ict_test_cases`.
- **v2-12a** (2026-11-19, `develop`) - Route A parse triggered from
  node 02's Parse button.
- **v2-13** (2026-11-19, `develop`) - `STEP_FLASH` became a one-class
  step type in the FCT model.
- **v2-14** (2026-11-20, `develop`) - `Message(Console)` OK also
  replies to the DUT console.
- **v2-15** (2026-11-20, `develop`) - the U2355A DIO Read/Write
  standard operations removed; GPIO drive/read/toggle is a test row.
- **v2-16** (2026-11-20, `develop`) - Command Snippet Helper with
  Linux / Windows CLI templates.
- **v2-17** (2026-11-20, `develop`) - node 07 Apply_Save Yaml panel
  (read-only preview plus publish).
- **v2-18** (2026-11-20, `develop`) - horizontal Yaml Build
  **flowchart** view with per-node dialog editing and jump-to-failed.
- **m100-A** (2026-11-21, `develop`) - Equipment left column:
  DUT group dropped, control board ungated, `mlan0` cleanup, optional
  placeholders.
- **m100-B** (2026-11-21, `develop`) - single-ended MUX default,
  one-wire SE resistance action, DIO split into `8R + 8W`.
- **m100-C** (2026-11-21, `develop`) - Peripherals split into
  **Host PC** and **Router** with an enable toggle and legacy
  migration.
- **m100-D** (2026-11-21, `develop`) - instrument LEDs moved to the
  left column, async `Refresh` and `Self-Test All`.
- **m101-A…E** (2026-11-21, `develop`) - Test Work Flow rework:
  `STEP_FLASH` names for the default flash rows, 2x2 body layout with
  chevron collapse, read-only float view on double-click, Console as
  a tab widget with the Command Helper, fixed 350 px status progress.
- **m102a / m102b** (2026-11-22, `develop`) - Route C: headless
  parser for the MTK ICT Excel Sheet, import on node 01, read-only
  skipped node 02.
- **m103a / m103b / m103c** (2026-11-22, `develop`) - four-sheet
  MTK ICT Excel writer with the node 07 export button, `File ▸ Excel`
  submenu and import flows, run-state lock and File-menu hygiene.
- **m104a / m104b** (2026-11-22, `develop`) - SharePoint Upload
  re-enabled for Supervisor, `Report > Event Log` renamed to
  `Event Log Folder…`, and the menu shortcuts
  (`Ctrl+O/S/Shift+S`, `Ctrl+Shift+D/E/T`).
- **m106** (2026-11-23, `develop`) - Yaml Build flowchart paint fixed,
  node dialogs scroll, caption band added.
- **m107a / m107b** (2026-11-23, `develop`) - `serial_pull` honours
  the `{{dut_report}}` local-path token; `fat.py` per-item Summary
  rows render in the FCT table.
- **m108** (2026-11-23, `develop`) - unified FCT capture early-exits
  on an expected or unexpected match instead of waiting out the
  window.
- **m109** (2026-11-23, `develop`) - `{{host_bt_addr}}` token
  available to FCT console commands.
- **m110** (2026-11-23, `develop`) - the DUT report lists every
  planned FCT/ICT item, so an omission is visible on the DUT.
- **m111 / m112 / m113** (2026-11-24, `develop`) - serial push
  confirms the heredoc close with `PUSH_DONE`, confirms command
  completion with a computed marker on the DUT, and the deploy step
  creates the remote parent directory and reports decode errors.
- **m115** (2026-11-24, `develop`) - the FCT stop policy honours the
  per-step `on_fail` and treats `Error` like `FAIL` when deciding to
  stop.
- **m116** (2026-11-24, `develop`) - stage rows roll up their child
  verdicts instead of always PASS; serial pull streams without a shell
  ACK round-trip; Wi-Fi console RSSI judges only the reply to its own
  command.
- **m117** (2026-11-24, `develop`) - Windows host Bluetooth BD
  address resolved without the WinRT `Await` (no WinRT dependency in
  the packaged build); BLE scan runs on a worker thread and tolerates
  a truncated advertising name; an unresolved token stays visible
  instead of turning into an empty address.
- **m118** (2026-11-24, `develop`) - console truth and budget truth:
  no PASS without a positive judge (a console row must name what it
  expects), the visible Timeout column is the single budget source,
  stale console bytes are drained before each send, and Yaml Build
  restores the stored 45-row FCT list instead of re-deriving 38.
- **m119 / m119b** (2026-11-24, `develop`) - CR-safe judge, echo
  strip, iperf JSON parsing, idle gate, plus the no-omit flag and an
  iperf server restart/health check.
- **m120** (2026-11-24, `develop`) - Bluetooth RSSI scan retry and the
  budget-vs-sub-timeout advisory (`budget <= sub-timeout + 1.0` logs a
  warning at run start instead of failing mid-run).
- **m121** (2026-11-25, `develop`) - the Virtual rack's `Power On/Off`
  honours the operation `state` and takes its setpoints from
  `equipment.psu.params`; a missing setpoint is an **Error**, never a
  silent 0 V. This is the defect that made an ICT plan fail every
  powered row in Virtual mode.
- **m122** (2026-11-25, `develop`) - **two reference plans shipped**:
  `examples\ict_96624\` (34 rows, 31 enabled, 12 rails, built by
  Route A from a 2 231-net netlist) and `examples\fct_frdm_imx93\`
  (45 rows, 3 disabled with a reason, the plan that passed on the
  bench). Plus: an empty stage clears the table on load instead of
  leaving the previous project's rows, the status colours come from
  the theme, a one-row stored FCT list no longer overrides the
  derived rows, and the FCT budget wall stops retries instead of
  re-judging a real FAIL as a platform ERROR. Suite:
  **3 370 passed, 12 skipped**.
