# Project Audit — mtk-gui

- Date: 2026-09-30
- HEAD: `5d3c41f` on `develop` (main at `14ac1d4`, 1 commit ahead of origin/main)
- Code size: 25 Python files, ~11,217 lines (incl. smoke_test.py)
- Compliance refs: `.traerules`, `docs/parallel_dev_plan.md`, `docs/interface_spec.md`
- Rule honored: read-only audit, no source code modified.

## 1. Source File Inventory

### 1.1 Application code (mtkgui/ package)

| File | Lines | Role | Git status |
|---|---|---|---|
| `mtkgui/test_workflow_page.py` | 3365 | Test Work Flow page: tables, waveform, run engine, sequence editor | Modified (uncommitted) |
| `mtkgui/equipment_page.py` | 1283 | Equipment block diagram + instrument config dialogs | Tracked, clean |
| `mtkgui/widgets/multi_console.py` | 1151 | Serial/SSH/Virtual channel manager + console popups | Tracked, clean |
| `mtkgui/main_window.py` | 857 | MainWindow, menus, status bars, event log, dialog centering | Tracked, clean |
| `mtkgui/virtual_hardware.py` | 700 | VirtualRack, VirtualPSU/Fixture/DAQ973A/U2355A, FaultPolicy | **UNTRACKED** |
| `mtkgui/virtual_dut.py` | 463 | VirtualDutWorker (simulated DUT shell), profile editor | Modified (uncommitted) |
| `mtkgui/style.py` | 461 | Global QSS + token substitution | Tracked, clean |
| `mtkgui/project_config.py` | 326 | YAML build/save/load/apply | Modified (uncommitted) |
| `mtkgui/ansi.py` | 240 | ANSI escape handling for console | Tracked, clean |
| `mtkgui/widgets/console_widget.py` | 220 | Console view widget | Tracked, clean |
| `mtkgui/permissions.py` | 217 | Login dialog, roles, permissions store (config/permissions.json) | Tracked, clean |
| `mtkgui/widgets/send_panel.py` | 180 | Console send panel | Tracked, clean |
| `mtkgui/virtual_mode.py` | 123 | Virtual fault injection dialog + config | Tracked, clean |
| `mtkgui/widgets/connection_panel.py` | 122 | Channel connection parameters UI | Tracked, clean |
| `mtkgui/ssh_worker.py` | 114 | SSH transport thread (paramiko) | Tracked, clean |
| `mtkgui/quick_commands.py` | 103 | Quick commands store (commands.json) | Tracked, clean |
| `mtkgui/serial_worker.py` | 98 | Serial transport thread (pyserial) | Tracked, clean |
| `mtkgui/theme.py` | 96 | 5 GUI themes | Tracked, clean |
| `mtkgui/at_commands.py` | 30 | AT command helpers | Tracked, clean |
| `mtkgui/serial_params.py` | 25 | Serial parameter dataclass | Tracked, clean |
| `mtkgui/__init__.py` + `widgets/__init__.py` | 11 | Package markers | Tracked, clean |

### 1.2 Supporting files

| Path | Lines | Role | Git status |
|---|---|---|---|
| `smoke_test.py` | 903 | Offscreen feature-assert harness (only test suite) | Modified (uncommitted) |
| `main.py` | 38 | Entry point: login gate -> MainWindow | Tracked, clean |
| `scripts/capture_preview.py` | 91 | Preview screenshot tool | Modified (uncommitted) |
| `requirements.txt` | 5 | PySide6, pyserial, paramiko, PyYAML, pyinstaller | Tracked, clean |
| `docs/git_workflow.md` | — | Branch rules | Tracked (committed) |
| `docs/parallel_dev_plan.md` | — | Parallel dev plan | Untracked |
| `docs/solo_session_templates.md` | — | SOLO session templates | Untracked |
| `docs/interface_spec.md` | — | Module interface spec v0.1 DRAFT | Untracked |
| `config/*.yaml` | — | Product test configs (FRDM-IMX93, PROJECT_00000) | Tracked |
| `MTK_GUI.spec`, `MTK_GUI_windows.spec` | — | PyInstaller packaging | Tracked |
| `.github/` | — | Windows exe build workflow | Tracked |

### 1.3 Structure vs `.traerules` §2 target layout

| .traerules target | Actual | Gap |
|---|---|---|
| `./src` | `mtkgui/` package | Naming only (accepted mapping) |
| `./tests` | **absent** | No pytest suite at all |
| `./assets` | **absent** | No icons/diagram assets folder |
| `./config` | `config/` | Present; `config/schema/` absent |
| `./docs` | `docs/` | Present (4 docs) |
| `./logs` | `logs/`, `event/` | Present, gitignored |

## 2. Feature Status vs `.traerules`

| Area | Status | Evidence |
|---|---|---|
| Login / Supervisor-Operator roles / permissions | Done | `permissions.py`, `main_window.apply_permissions` |
| Real/Virtual mode gating (Virtual = Supervisor only) | Done | `main.py:27`, `main_window.py` |
| Equipment page: block diagram + config dialogs | Done (UI); connect is simulated | `equipment_page.py:963-977` |
| Console: serial + SSH + virtual DUT, quick commands | Done | `widgets/multi_console.py`, `serial_worker.py`, `ssh_worker.py` |
| ICT/FCT tables, sequence editor, op steps | Done | `test_workflow_page.py` |
| Virtual-mode full run (fault injection, "Virtual" results) | Done | `virtual_hardware.py`, `_virtual_fault_roll` |
| Real-mode ICT/rail/voltage/clock measurement | **Placeholder** | `test_workflow_page.py:1841` "Real mode keeps the legacy placeholder verdict until the SCPI ...", `:1890` "instrument drivers pending" |
| Real instrument connection (VISA/GPIB/USB) | **Missing** | `equipment_page.py:976` "demo build has no VISA layer"; no `pyvisa` in requirements |
| Power rail waveform + capture + CSV export + AI review | Done (virtual data) | `_capture_rails`, `_write_csv`, `_ai_wave_review` |
| FCT 12 methods incl. console/CLI messaging | Done (virtual/real via console) | `FCT_METHODS`, `_exec_fct_console` |
| RF test (WiFi/BLE) via external host CLI tools | **Simulated only** | `test_workflow_page.py:2082-2090` — WIFI/Bluetooth alias to simulated `SendtoCLI` defaults |
| FAT / OOBE firmware flash (JLink) | **Manual operator step** | Template rows "Flash FAT Firmware (3rd-party GUI)" gated by MessageGoStop; no JLink code |
| Config page (YAML editor) | **Missing** | `.traerules` §7 fixed page; no editor module |
| Log viewer as module | Embedded | Event log inside `main_window.py` (T6 to extract) |
| GUI themes (5) + WCAG contrast | Done | `theme.py`, `style.py` |
| Long Run / Interval run control | Done | `_build_run_control`, `_start_next_cycle` |
| Windows exe CI build | Done | `.github/` workflow |

## 3. Unfinished Functions (prioritized)

1. **Real-mode instrument driver layer (T1)** — no `mtkgui/drivers/`, no VISA
   layer; all Real-mode ICT/rail/voltage/clock rows keep placeholder verdicts
   (`test_workflow_page.py:1841,1890`). Blocks production use of Real mode.
2. **Test flow engine as a module (T2)** — run logic
   (`start_run/_run_step/_exec_ict_row/_exec_fct_console/_finish_run`, ~1000+
   lines) embedded in the `TestWorkFlowPage` QWidget; `TestRunner`/`StepResult`
   from interface_spec.md do not exist yet.
3. **Automated firmware flashing (FAT/OOBE via JLink)** — currently an operator
   manual action ("3rd-party GUI") wrapped in MessageGoStop dialogs; JLink is in
   the `.traerules` instrument list but has no code.
4. **Real RF test execution** — WIFI/Bluetooth fall back to simulated CLI
   commands; host-side external CLI tool invocation (.traerules §3.8) absent.
5. **YAML config editor page (T5)** — `.traerules` §7 Config page missing.
6. **Log viewer module (T6)** — extract from `main_window.py`.
7. **pytest suite + `tests/` folder** — absent; `smoke_test.py` is the only
   harness (assert-based, offscreen, not pytest-collected).
8. **`config/schema/`** — YAML schema not materialized (T5 scope).
9. **Type-hint debt** — `.traerules` §4 mandates type hints everywhere; most
   existing functions lack them (e.g. `main.py:17`, `project_config.py:39`).
   Not a standalone refactor — enforce per-file in each task's scope.

## 4. Code Risk Checklist

| # | Severity | Risk | Evidence | Mitigation -> task |
|---|---|---|---|---|
| R1 | HIGH | `virtual_hardware.py` (700 lines) is **untracked**; 9 more files modified-uncommitted — work-loss risk, blocks clean feature-branch baselines | `git status` | Commit WIP in logical groups -> T0a |
| R2 | HIGH | Monolith `test_workflow_page.py` (3365 lines: UI + engine + 540-line editor dialog); any flow-behavior branch touches it -> merge conflicts | file size, class layout | T2 extraction; T3 waits for T2 merge (plan §9.2) |
| R3 | HIGH | No pytest infra, yet parallel-dev plan requires green tests per commit | no `tests/`, pytest not in requirements | T0c scaffold `tests/` + pytest config; adding deps needs user approval (.traerules forbidden_action) |
| R4 | MEDIUM | Virtual fault logic duplicated: page `_virtual_fault_roll` vs `FaultPolicy.roll` — behavior drift risk between UI and virtual layer | `test_workflow_page.py:797`, `virtual_hardware.py:65` | T4 must unify behind FaultPolicy; T2 keeps engine-side call |
| R5 | MEDIUM | Equipment page uses `_mock_configs()` inventory instead of YAML-driven instrument list | `equipment_page.py:227,1014` | Fold into T1 (drivers) or T5 (config schema) decision |
| R6 | MEDIUM | Supervisor password stored as plain constant in `permissions.py` (source-visible) | memory + module review | Note for user decision; out of current task scopes |
| R7 | MEDIUM | Waveform repaint without segment caching caused UI lag on repeated runs (known lesson); `WaveformWidget.paintEvent` repaints full series | memory lessons | T3 waveform widget must add dirty-rect/caching |
| R8 | LOW | Transport worker edge cases (USB unplug mid-read, SSH drop) — workers are small but untested | `serial_worker.py` 98 lines | cover in T1 mocked-transport tests |
| R9 | LOW | `main` ahead of `origin/main` by 1; docs untracked — machines may diverge | `git branch -vv` | push after T0 commits |
| R10 | LOW | Default FCT template + SN format defaults hardcoded in page (acceptable as templates, but product params must stay in YAML) | `test_workflow_page.py:1400-1406` | T5 review when schema lands |

## 5. Alignment Notes -> `docs/tasks.md`

- T0 (baseline) is confirmed as hard blocker and is split into concrete
  sub-tasks T0a–T0d (see tasks.md) driven by R1/R3.
- T1 scope gains `mtkgui/drivers/errors.py` (shared exceptions, interface_spec
  §1.3) and the mock-config migration decision (R5).
- T2 gains an explicit non-regression requirement: unify duplicated virtual
  fault roll logic (R4) and keep `smoke_test.py` green.
- T3 gains waveform caching requirement (R7).
- T5 gains `config/schema/` materialization.
- New pending-decision item D1 (user input): real RF test CLI tools and
  firmware-flash automation scope (JLink) — affects T1/T2 backlog, blocked on
  user decision because it may add dependencies.
