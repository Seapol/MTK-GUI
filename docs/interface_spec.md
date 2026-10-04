# MTK-GUI Module Interface Specification

- Version: 0.1 (DRAFT — pending user approval per change protocol below)
- Date: 2026-09-30
- Scope: all development tasks (TRAE SOLO) must comply with this document.

This document defines data structure, input/output, cross-module API contracts.
Any changes to this spec must be approved first, then updated in this file.
Changes to interface are high-risk and must be handled as standalone task on develop branch.

## General Rule

Module can only communicate via defined API / data structures. No direct access to
internal variables of another module.

## Module List & Interface

### 1. Common Module (src/common)

Folder mapping: "src/common" maps to the existing shared modules of the `mtkgui/`
package (see docs/parallel_dev_plan.md §5.2). This module provides:

#### 1.1 YAML config loader — existing: `mtkgui/project_config.py`

```python
build_config(workflow_page, equipment_page) -> dict   # GUI state -> config dict
save_config(config: dict, path: str) -> None          # config dict -> YAML file
load_config(path: str) -> dict                        # YAML file -> raw config dict
apply_config(config: dict, workflow_page, equipment_page) -> None  # dict -> GUI state
default_filename(config: dict) -> str
```

- Callers must treat the returned dict as read-only; mutation is internal to
  project_config.
- T5 (yaml-config-editor) owns this file; T2/T3/T4 must call these functions
  as-is and never re-parse YAML themselves.

#### 1.2 Global logger — existing behavior, formalized by T6

- Event log: one file per GUI session under `event/`; CSV test logs under `logs/`.
- Log entry = timestamped text line; `Clear` empties the view but keeps a marker
  in the session log file; `Save as` exports current view.
- T6 extracts this into `mtkgui/logs/` behind an interface announced in this
  spec before any other module consumes it.

#### 1.3 Shared exception types — NEW (created by T1)

Location v0.1: `mtkgui/drivers/errors.py` (importable cross-module; relocation
to a future `mtkgui/common/` requires a spec change).

```python
class InstrumentError(Exception): ...        # base for all instrument faults
class InstrumentTimeoutError(InstrumentError): ...
class InstrumentIOError(InstrumentError): ...     # serial/GPIB/USB IO failure
class InstrumentConfigError(InstrumentError): ... # bad/missing YAML parameters
class ConnectionLostError(InstrumentError): ...
```

### 2. Instrument Driver Module

Owner: T1 (`feature/instrument-driver`), new package `mtkgui/drivers/`.
Reference behavior model: `mtkgui/virtual_hardware.py`
(VirtualPSU / VirtualFixture / VirtualDAQ973A / VirtualU2355A) — real drivers
must reproduce these semantics against physical instruments.

- **Input**: instrument address + measurement parameters, all read from YAML via
  the Common loader (never hardcoded, .traerules §4).
- **Output**: `MeasurementResult` (typed, see below).

```python
class InstrumentDriver(ABC):
    def open(self, address: str, options: dict) -> None: ...
    def close(self) -> None: ...
    def write(self, command: str) -> None: ...
    def query(self, command: str) -> str: ...
    def identify(self) -> str: ...

@dataclass
class MeasurementResult:
    value: float | str        # measured value (numeric) or matched text
    unit: str                 # "Ohm", "V", "Hz", ""
    status: Status            # OK / FAIL / ERROR / TIMEOUT
    timestamp: datetime       # UTC timestamp of the reading
    source: str               # instrument model + channel, e.g. "DAQ973A/MB1M101"
```

Status codes: `OK` (measurement within contract), `FAIL` (out of limits —
decided by the ENGINE, not the driver), `ERROR` (instrument fault), `TIMEOUT`.
Drivers report `ERROR`/`TIMEOUT` by raising the shared exceptions above or
returning status; they never decide PASS/FAIL (that is engine logic).

Per-model modules: `daq973a.py` (DAQM908A resistance/DCV, DAQM907A totalizer/AO),
`n5747a.py` (power supply), `u2355a.py` (counter/GPIO/rail capture), `jlink.py`
(flash). Command sets must match Keysight programming manuals (.traerules §5).

### 3. Test Flow Engine

Owner: T2 (`feature/testflow-engine`), new package `mtkgui/engine/`.

- **Input**: config dict from Common loader; measurement data via Instrument
  Driver API; console transport handles (see §4.2); DUT abstraction
  (real transport or `VirtualDutWorker` / `VirtualRack`).
- **Output**: per-step results, waveform sample data, summary report.

```python
@dataclass
class StepResult:
    status: StepStatus        # RUNNING / PASS / FAIL / ERROR / IGNORED
    measured: float | str | None
    duration_s: float
    message: str              # sub-action log line, e.g. "Fixture Clamp Down: Done"

class StepStatus(str, Enum):
    RUNNING = "RUNNING"; PASS = "PASS"; FAIL = "FAIL"
    ERROR = "ERROR"; IGNORED = "IGNORED"   # rendered as "Ignore" (gray) in UI

class TestRunner(QObject):
    # signals
    step_started = Signal(int)                    # step index
    step_finished = Signal(int, StepResult)
    run_finished = Signal(dict)                   # summary report
    # control
    def start(self, lr_total: int = 1) -> None: ...   # Long Run cycle count
    def abort(self) -> None: ...
```

- Step model mirrors YAML: `kind` (op / ict / fct), `name`, `method`, `enable`,
  `params` / `op_params`, limits (`min` / `max` / `unit`), `wait`, `timeout`.
- Stop strategies: `stop_if_failure` (default **false**), `stop_if_any_short`
  (default **true** — abort before power-up on impedance shorts).
- Basic fault-policy retry: `retry_count` (default **0** = off) re-executes a
  FAIL/ERROR step up to N times BEFORE the stop strategies are evaluated.
  Constraints: `N` is a non-negative integer (0–9 recommended bound; the
  engine clamps negatives to 0); only FAIL/ERROR steps are retried — PASS /
  "Done" and IGNORED steps are never re-executed; an operator Stop during a
  step always wins over a retry. Configuration precedence:
  demo CLI `--retry N` > YAML `test_workflow.retry` > default `0`.
  Usage: transient instrument faults (bus glitches, one-shot timeouts);
  limit FAILs that reflect real DUT defects are NOT expected to recover and
  will still trigger the stop strategies after the retries are exhausted.
- Firmware flash steps are op steps with `op_params`:
  `{"type": "flash", "slot": "fat" | "oobe", "image": <path>}`. The image
  path is taken ONLY from the YAML `firmware.<slot>_image` key — the engine
  never guesses a path.
- Overall Result rollup: FAIL if any non-ignored step FAIL/ERROR; otherwise PASS.
- Waveform sample data: ordered samples `t -> {rail_name: voltage}` captured
  between `start_s` and `end_s` at `rate_hz` (negative `start_s` = pre-trigger).

### 4. UI Layer

Pages: `main_window.py`, `test_workflow_page.py`, `equipment_page.py`, console
widgets. UI must NOT implement instrument measurement logic. UI only reads
config; it does NOT modify the core YAML schema (editing happens through T5's
editor page via Common loader API only).

#### 4.1 Consumption contract

- UI subscribes ONLY to `TestRunner` signals and renders `StepResult.status`:
  PASS / FAIL / ERROR / RUNNING / IGNORED ("Ignore").
- UI obtains product data exclusively via `load_config` / `apply_config`.

#### 4.2 Console transport handle (existing: `mtkgui/widgets/multi_console.py`)

Consumed by FCT steps through the engine (documented, existing signatures):

```python
MultiConsoleWidget.write_to_channel(key: str, payload: bytes) -> None
MultiConsoleWidget.get_read_buffer(key: str) -> bytearray
MultiConsoleWidget.clear_read_buffer(key: str) -> None
MultiConsoleWidget.channel_connected(key: str) -> bool   # real connected state
MultiConsoleWidget.open_channel(key: str) / close_channel(key: str)
# signal: connection_changed(key: str, connected: bool)
```

#### 4.3 Virtual layer contract (existing: `virtual_hardware.py`, `virtual_dut.py`)

- `VirtualRack.execute_op(name: str, params: dict)`, `measure_row(kind, name,
  unit, lo_s, hi_s, force=None)`, `capture_rails(rails, start_s, end_s,
  rate_hz, force=None)` — engine calls these in Virtual mode; the engine must
  use the SAME call shape against real drivers (adapter pattern).
- `FaultPolicy.set_ratios(fail_pct, err_pct)` / `.roll(...)`; config persisted
  by `virtual_mode.load_fault_config()` / `save_fault_config(cfg)`.
- `VirtualDutWorker.write(data: bytes) -> int` / `inject_fault(kind)` / `stop()`.

## YAML Schema Contract

All product config yaml follow unified schema defined in `config/schema`.
No module can invent new yaml fields without updating this spec.

> Status: `config/schema/` does not exist yet. v0.1 authoritative schema = the
> structure produced by `project_config.build_config/_workflow_to_yaml/
> _equipment_to_yaml` and consumed by `apply_config`; live examples:
> `config/FRDM-IMX93_*.yaml`, `config/PROJECT_00000_*.yaml`.
> T5 materializes `config/schema/` (JSON Schema + documented reference) as part
> of its scope; until then the build/apply functions are the single source of
> truth. Top-level sections: equipment (instrument addresses/options),
> workflow (overall flow + stop strategies, ICT steps, FCT steps with
> kind/op_params), console channels.
>
> Engine-consumed keys added by the P0 TestFlow baseline (already written by
> `build_config` / read by `apply_config` / the engine):
>
> | Key | Meaning | Default |
> |---|---|---|
> | `test_workflow.retry` | basic fault-policy step retry: re-execute a FAIL/ERROR step up to N times before the stop strategies evaluate | `0` (off) |
> | `test_workflow.stop_if_failure` | abort the whole run on any FAIL step | `false` |
> | `test_workflow.stop_if_any_short` | abort before power-up on impedance shorts | `true` |
> | `firmware.<slot>_image` | flash image path for slot `fat` / `oobe`; the ONLY source the engine reads (never guessed) | — (required by flash steps) |
>
> Flash steps are op steps with `op_params: {"type": "flash", "slot": "fat" |
> "oobe", "image": <path from firmware.<slot>_image>}` (see §3).
>
> Case-generation keys added by P1-16 (owned by `mtkgui.engine.casegen`,
> consumed only by the generator/sync tools - the runner ignores them):
>
> | Key | Meaning |
> |---|---|
> | `ict_test_cases[].priority` / `power_domain` / `upstream` / `downstream` / `instrument` / `test_dim` / `notes` | optional review metadata exported to the human-review Excel and editable there; the engine treats them as pass-through |
> | `ict_test_cases[].ai_meta` | AI provenance `{gen_version, gen_time, sources, reviewed}` |
> | `ict_case_audit` | generation audit + per-sync history snapshots (`{time, source, actor, added, removed, changed, rows_before, rows_after}`), `review_version`, `final` |

### 6. GUI Shell Framework (NEW — owned by P2-1, `mtkgui/gui/`)

Pure-additive application skeleton. The shell imports NOTHING from
`mtkgui.engine`; later P2 stages mount business pages exclusively via
`register_page`. No P1 module may depend on the shell (one-way edge:
pages -> shell API).

```python
# mtkgui/gui/shell.py
class MainWindow(QMainWindow):
    def __init__(self, baseline_version: str = "V1.0-P2",
                 spec: StyleSpec | None = None) -> None: ...
    def register_page(self, key: str, factory: Callable[[], QWidget],
                      title: str) -> None   # duplicate/empty key -> ValueError
    def navigate(self, key: str) -> None    # lazy build + cache; unknown -> WARN log
    route_keys: list[str]; cached_pages: list[str]
    def mount_default_routes(self) -> None  # framework placeholders only
    def set_engine_state(self, state: str) -> None
    def set_devices_online(self, count: int) -> None
    def set_progress(self, done: int, total: int) -> None
    def log(self, level: str, message: str) -> None

# mtkgui/gui/log_panel.py
class LogPanelWidget(QWidget):
    def append(self, level: str, message: str) -> None  # DEBUG/INFO/WARN/ERROR
    def clear(self) -> None                             # view only, history kept
    entry_count: int; visible_count() -> int

# mtkgui/gui/status_bar.py
class StatusBarWidget(QWidget):
    def set_engine_state(self, state: str) -> None
    def set_devices_online(self, count: int) -> None
    def set_progress(self, done: int, total: int) -> None
    def tick(self) -> None   # uptime refresh (1 Hz, owned by shell)

# mtkgui/gui/theme.py
class StyleSpec: ...                 # frozen palette/font/spacing constants
def build_stylesheet(spec) -> str    # global QSS, single style source of truth
```

Rules: all P2 pages must consume `StyleSpec`/`build_stylesheet` (no hardcoded
colors); engine state/device/progress values are pushed into the shell via
the setters above — the shell never polls the engine; page cache is
build-once per route key; close is guarded by a confirm dialog, then timers
stop and resources flush (safe exit).

### 7. Visual Config System (NEW — owned by P2-2, `mtkgui/gui/`)

Schema-driven visual YAML editor.  Pure additive on top of the existing
YAML base (`mtkgui.project_config` untouched); saving mutates ONLY
registered paths and never drops unregistered keys.

```python
# mtkgui/gui/config_spec.py
SECTIONS: dict[str, tuple[FieldSpec, ...]]   # project/firmware/equipment/sharepoint
def get_path(cfg, dotted) / set_path(cfg, dotted, v) / iter_paths(cfg)
def validate_value(spec, value) -> ValidationIssue | None   # field+value+reason
def validate_config(cfg) -> list[ValidationIssue]
def coerce_value(spec, value) -> Any                        # text -> typed
```

Registered engine-consumed keys (names MUST stay exact):
`test_workflow.retry|stop_if_failure|stop_if_any_short`,
`firmware.fat_image|oobe_image`, `project.*`, `product.*`.
New additive keys (engine pass-through until wired): `test_workflow.
global_timeout_s|schedule_mode|max_parallel`, `firmware.connect_timeout_s|
write_timeout_s|verify_timeout_s|verify|version_rule`, `equipment.comm.*`,
`equipment.host.fields.*`, and the whole `sharepoint` section
(`enabled, site_url, username, password, token, upload_retry_count,
resume_on_disconnect, overwrite_policy, project_dir, archive_whitelist`).

```python
# mtkgui/gui/config_store.py
class ConfigStore:
    load(path) -> dict                      # yaml.safe_load
    save(cfg, path)                         # formatted: sort_keys=False,
                                            #   allow_unicode, stable order
    apply_and_save(cfg, updates, path, note) -> (cfg, [Change])
                                            # auto-snapshot pre-save + [CFG] audit
    save_snapshot/list_snapshots/load_snapshot/rollback(current, id)
    diff(a, b) -> [Change(path, old, new)]
apply_registered(cfg, updates) -> [Change]  # IN-PLACE; empty optional skipped;
                                            # unknown path -> KeyError
```

```python
# mtkgui/gui/config_page.py
class ConfigPage(QWidget):
    config_applied = Signal(dict)           # hot-effect hook (no restart)
    interactive: bool                       # False = headless-safe (no modals)
    on_save() -> (cfg, changes) | None      # blocked on validation issues
    on_rollback() / on_diff() / validate_form()
```

### 8. AI-Case Visual Editor (NEW — owned by P2-3, `mtkgui/gui/`)

Pure-increment GUI layer over the P1-16 casegen base (generator /
excel_io / sync stay untouched).  Route key ``cases``.

```python
# mtkgui/gui/case_store.py
GUI_EDITABLE = excel_io.EDITABLE + ("retry", "skip_if")
DIMENSIONS = ("impedance", "voltage", "timing")   # 阻抗/电压/上电时序
categorize(case) -> "电源网络"|"时钟网络"|"信号网络"|"操作流程"
coerce_field(field, raw)         # same semantics as excel_io._coerce
class LockedCaseError(RuntimeError)
class CaseStore:
    load/save(path)                              # project YAML
    save_snapshot(cfg, note) -> snap_id / load_snapshot(snap_id)
    is_locked(cfg, name) -> bool / set_locked(cfg, name, locked)
    history(cfg) -> list[dict]                   # ict_case_audit.history
    apply_case_edit(cfg, name, updates) -> [FieldChange]
        # KeyError unknown case/non-editable field, ValueError illegal
        # value, LockedCaseError when version-locked; appends an
        # ict_case_audit.history entry (source="gui-editor")
    set_dimension_enabled(cfg, dim, enabled) -> [FieldChange]
        # batch toggle; locked cases are skipped
    edit_and_save(cfg, name, updates, path) -> (new_cfg, changes)
        # snapshot pre-edit -> edit -> formatted save
```

```python
# mtkgui/gui/case_editor.py
class CaseEditorPage(QWidget):                   # route: cases
    cases_applied = Signal(dict)                 # hot-effect hook (P2-4+)
    interactive: bool                            # headless-safe flag
    refresh_tree() / reload()                    # rebuild from YAML
    on_save() -> (cfg, changes) | None           # locked/illegal -> None
    on_lock_toggle()                             # version lock/unlock
    dim_boxes: dict[str, QCheckBox]              # 阻抗/电压/上电时序开关
    # left tree: category groups with 优先级/维度/状态 badges
    # right form: thresholds, wait/timeout, retry, skip_if, priority
    # (power-tree level), instrument combo, notes, upstream/downstream
    # topology view; bottom traceability panel (AI gen + manual edits)
```

Lock state is persisted under ``ict_case_audit.locks`` (name -> meta);
manual edits append to ``ict_case_audit.history`` using the same entry
shape as the P1-16 Excel sync — both stay backward compatible.

### 9. Review-Excel GUI Import/Export (NEW — owned by P2-4, `mtkgui/gui/`)

Pure-increment GUI wrapper over P1-16 ``export_review_excel`` /
``import_review_excel`` / ``diff_rows`` / ``sync_review_excel``.
Route key ``case_io``.

```python
# mtkgui/gui/case_io_page.py
class CaseIOPage(QWidget):                       # route: case_io
    cases_applied = Signal(dict)                 # after successful import
    interactive: bool                            # headless-safe flag
    last_report: dict | None                     # last diff report
    on_export() -> path | None
        # full 17-column review workbook; auto path
        # config/review/ICT_REVIEW_<ts>.xlsx; empty case list -> None
    on_import() -> diff_report | None
        # pre-flight: dirty/empty workbook (ValueError) and
        # version-locked-case conflicts block the WHOLE import,
        # YAML untouched; then P1-16 sync_review_excel
        # (import -> diff -> apply -> ict_case_audit.history
        #  entry source="gui-import") -> post-import snapshot ->
        # formatted YAML save; diff summary dialog (interactive)
        # or in-page log; [XLS] audit lines + in-page traceability
```

Import diff report shape (P1-16 contract): ``added`` / ``removed``
/ ``changed`` (name, field, old, new; instrument re-assignment and
priority moves tagged in the GUI rendering) / ``ignored_columns``
(dirty unknown columns filtered, never silently dropped).

## Conflict Prevention Rule

If two modules need new cross-module data field, update this interface spec first.
After spec updated, rebase all active feature branches.

Procedure: propose change in the SOLO session -> STOP coding -> coordinator
reviews -> approved change is committed on `develop` as a standalone task ->
all active feature branches rebase -> sessions continue.
