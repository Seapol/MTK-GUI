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
  screenshots (`images/18_01..18_10`, `19_01..19_05`); the chapter
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



