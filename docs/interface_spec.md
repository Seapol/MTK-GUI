# MTK-GUI Module Interface Specification

- Version: 0.3 (V4.0 contracts — sections 29-33; approved by
  coordinator 2026-10-05)
- Date: 2026-10-05
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
        # yaml_plan/review/ICT_REVIEW_<ts>.xlsx; empty case list -> None
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

### 10. Quality Metrics Engine (NEW — owned by P2-5, `mtkgui/engine/metrics.py`)

Pure-increment calculation layer over the P1 result base
(``StepResult``/``StepStatus`` + six-kind ``FailureKind``); zero
changes to runner / report / scheduler modules.  No GUI yet (P2-6).

```python
INVALID_KINDS = {RESOURCE, ENGINE_ERROR, OPERATOR_ABORT, FROZEN, TIMEOUT}
@dataclass TestRecord: name, status, duration_s, measured, ts, batch,
                       station, failure_kind
TestRecord.from_step_result(name, StepResult, *, ts, batch, station,
                            failure_kind)   # P1 adapter; non-numeric
                                            # measured -> None
filter_records(records, *, batch, shift, day, start, end)
    # AND-combined time filter; shift = day(08-20)|night; records
    # without ts never survive a non-empty filter
compute_yield(records, top_n=5) -> YieldReport
    # total/passed/failed/invalid; invalid_by_kind; real_yield =
    # passed / (passed+failed)  (invalid excluded from denominator);
    # top_defects = [(name, n, ratio)]
compute_cycle_time(records, top_n=3) -> CycleReport
    # samples/total/mean/max/min/sample-stdev/CV volatility,
    # per_case_mean, bottlenecks (slowest cases by mean)
compute_cpk(records, case, lsl, usl, unit) -> CpKReport
    # n/mean/sample-stdev/Cp/CpK/grade (A+>=1.67 A>=1.33 B>=1.0
    # C>=0.67 else D); n<2 -> capability fields None; zero stdev ->
    # inf when centered
compute_cpk_all(records, {case:(lsl,usl)}, units) -> {case: CpKReport}
class MetricsEngine:
    add(TestRecord) / add_step_result(name, StepResult, **meta)
    yield_report(**flt) / cycle_report(**flt) /
    cpk_report(case, lsl, usl, unit, **flt)   # flt = filter kwargs
    batch_summary(batch) -> {"yield":…, "cycle":…}
    audit: [(time, params, detail)]           # [METRICS] log lines;
                                              # results reproducible
```

### 11. Visual Report Dashboard (NEW — owned by P2-6, `mtkgui/gui/`)

Pure-increment visualization layer over the P2-5 MetricsEngine: read-only
consumption of engine records + `compute_*` pure functions; zero changes
to the metrics engine, runner or any core module.  Charts are self-drawn
with QPainter (`mtkgui/gui/charts.py`) — no external chart dependency.

```python
# mtkgui/gui/charts.py — self-drawn chart widgets (headless-testable)
class LineChart(QWidget):
    set_series(name, points)   # REPLACES only that named series
    add_series(name, points)   # appends a series
    point_count(name=None)     # points of one / all series
class BarChart(QWidget):
    set_data(items, highlight=None)  # items=[(label, value)];
                                     # highlight label drawn in red
    bar_count; _items; _highlight
class PieChart(QWidget):
    set_data(items)            # slices with v<=0 filtered out
    slice_count; _items

# mtkgui/gui/report_page.py — route key "reports"
class ReportPage(QWidget):
    __init__(engine: MetricsEngine | None, spec=StyleSpec(), parent=None)
    report_refreshed = Signal(int)   # emitted per refresh with the
                                     # filtered in-scope record count
    interactive: bool                # False = no modal dialogs (headless)
    cpk_case / cpk_lsl / cpk_usl     # CpK trend config (optional)
    # filter bar: batch_combo (全部 + batches), shift_combo (全部/day/
    # night), refresh_btn, reset_btn, detail_btn, auto_btn (QTimer 5s)
    refresh()            # recompute all charts from filtered records
    reset()              # combos back to 全部 + refresh
    show_detail()        # in-page detail panel (+ QDialog if interactive)
    _filtered()          # batch+shift AND-combined record view
    # charts: yield_chart (time-bucketed real_yield trend),
    # cycle_chart (per-case mean top8, slowest = bottleneck highlighted),
    # cpk_chart (per-batch CpK trend, inf/zero-dispersion excluded),
    # defect_chart (top_defects bars, #1 highlighted), pie_chart
    # (product fails + invalid-by-kind shares), batch_table
    # (批次/良率/平均工时s/测试数)
# shell wiring: shell.metrics_engine = MetricsEngine() (shared, feeds
# later stages); register_page("reports", ReportPage(engine))
```

### 12. Report Archive (NEW — owned by P2-7, `mtkgui/engine/archive.py`)

Pure-increment archival tool layer over the P1 report base (logs_dir
CSV / review files): zero changes to test flow, report writers or the
metrics engine.  Fully P1-format compatible — reports are packed
as-is, lossless.

```python
is_junk(path) -> bool        # redundant filter: hidden, .tmp/.bak/
                             # .pyc/... suffixes, __pycache__/.git dirs
file_sha256(path) -> str     # chunked hash (integrity basis)
@dataclass ArchiveEntry: zip_path, batch, ts, station, version,
                         sha256, files, hashes, bytes; to_dict()
class ArchiveManager:
    __init__(root, *, station="S1", version="v2.0.0",
             retain_days=90, max_capacity_mb=1024, now=None)
                             # now = injectable clock (tests)
    pack(files, *, batch, ts=None) -> ArchiveEntry
        # zip name {batch}_{YYYYmmdd_HHMMSS}_{station}_{version}.zip,
        # ZIP_DEFLATED, embedded manifest.json (per-file SHA-256 +
        # metadata); canonical copy in history/, copies in daily/
        # <YYYYmmdd>/ and batch/<batch>/ (3-tier layout)
    verify(entry) -> [problems]   # empty = intact: archive hash +
        # per-member hash vs manifest + unknown/missing member check
    cleanup(*, now=None) -> {"removed": [names], "kept": n,
                             "total_mb": f}
        # 1) age: remove archives older than retain_days
        # 2) capacity: history footprint > max_capacity_mb -> evict
        #    oldest first; tier copies of the same name removed together
    list_archives(*, tier="history") -> [dict]   # name/bytes/mtime
    audit: [(time, action, detail)]   # [ARCHIVE] log lines, traceable
# tier keys: "history" | "daily" | "batch"
```

### 13. SharePoint Upload Closed Loop (NEW — owned by P2-8, `mtkgui/engine/uploader.py` + `mtkgui/gui/upload_page.py`)

Pure-increment upload & monitoring layer.  Reads the P2-2 visual
config ``sharepoint.*`` section (wired since P2-2 as pass-through);
zero changes to test flow / reports / metrics / archive.

```python
BLACKLIST_SUFFIXES = {.exe .bat .cmd .sh .dll .msi}   # never uploaded
@dataclass UploadConfig: enabled, site_url, username, password, token,
                         retry_count, resume_on_disconnect,
                         overwrite_policy(overwrite|keep_both|skip),
                         project_dir, whitelist
UploadConfig.from_config(cfg_dict)     # P2-2 sharepoint.* section
class FakeSharePoint:                  # injectable transport seam
    head/mkdirs/exists/put; fail_next_put, fail_probe, deny_write,
    online; uploaded: {remote_path: bytes}
class HttpSharePoint:                  # real urllib transport, same seam
    # Bearer token / basic auth; HTTPError -> TransportError,
    # URLError -> ConnectionError
@dataclass UploadResult: name, status(UPLOADED|DEDUPED|FAILED|BLOCKED),
                         attempts, sha256, url, ts, detail
filter_allowed(name, whitelist) -> reason|None   # black/white gate
class SharePointUploader:
    __init__(outbox, *, state_dir=None, transport=None, now=None,
             sleep=time.sleep)
    apply_config(cfg)            # hot update from P2-2 dict
    precheck() -> [problems]     # connectivity + permission + writable
    upload_file(path) -> UploadResult
        # chain: filter -> configured -> sha256 dedup (ledger, by
        # name+hash) -> skip-policy -> put with retry_count+1 attempts
        # (ConnectionError retries when resume_on_disconnect,
        # TransportError aborts) -> failure keeps file in outbox
    upload_pending(source=None) -> [UploadResult]   # outbox sweep
    records() -> [dict]          # ledger book for the GUI
    ledger persisted to state_dir/upload_ledger.json (restart-safe)
    audit: [(time, action, detail)]   # [UPLOAD] log lines
# GUI: UploadPage(QWidget) route "upload"; Signal upload_done(int ok,
# int bad); apply_config(cfg) hot-update hook; on_precheck/on_upload/
# refresh; interactive flag; shell.upload_manager shared instance
# (outbox = $MTKGUI_OUTBOX_DIR or "outbox")
```

### 14. Commercial Report Export (NEW — owned by P2-9, `mtkgui/gui/report_export.py` + `mtkgui/gui/export_page.py`)

Pure-increment rendering & export layer over the P1 records + P2-5
metric reports (read-only); zero changes to any producer.

```python
sparkline(points, width, height, color) -> str   # inline SVG trend
                    # thumbnail; <2 points -> "暂无趋势数据"
doc_hash(payload) -> str    # SHA-256 provenance digest (stable json)
build_html_report(*, records, yield_report, cycle_report,
                  cpk_reports, batch_summaries=None, meta=None,
                  title=...) -> str
    # standardized sections: header (part_number/batch/station/
    # version/revision/generated_at/trace hash) -> KPI summary ->
    # anomaly stats (invalid_by_kind + top_defects) -> yield trend
    # SVG thumbnail -> CpK table -> batch comparison (yield dict from
    # engine.batch_summary) -> full test detail -> footer (full hash)
export_pdf(html_text, path) -> Path
    # QPdfWriter A4 portrait rendering of the same HTML (printable)
# GUI: ExportPage(QWidget) route "export"; Signal report_exported(str)
# preview QTextBrowser; zoom(+1/-1/0 -> %label); find box (wraps);
# export_html()/export_pdf_file()/export_batch_summary() (one HTML per
# batch + merged SUMMARY); meta dict + cpk_case/lsl/usl config;
# interactive flag; out_dir = $MTKGUI_EXPORT_DIR or "reports_export"
```

### 15. Multi-Device Cluster Scheduling (NEW — owned by P2-10, `mtkgui/engine/cluster_scheduler.py` + `mtkgui/gui/cluster_page.py`)

Pure-increment dispatch layer composed on top of the P1
`DeviceManager` (used, never modified): P1 state machine + lock
tokens provide isolation; this layer adds balancing + failover.

```python
@dataclass Task: task_id, kind="*", weight=1.0, payload,
                 status, device, token, attempts
class TaskStatus(Enum): QUEUED RUNNING DONE FAILED MIGRATED
@dataclass DeviceStats: name, kind, active, completed, failed,
                        busy_s; load = active + busy_s/3600
class ClusterScheduler:
    __init__(dm=None, log_fn=None)
    register_device(name, kind="station")   # P1 register + kind tag
    submit(Task)                            # queue
    assign_next() -> (task, device) | None
        # idle-first, least-loaded (active, then busy_s) of matching
        # kind; busy devices avoided -> task stays queued; exclusive
        # P1 lock token per task (no preemption)
    complete(task_id, ok=True)              # release + tally
    report_fault(device, reason) -> [migrated task_ids]
        # force-release + ERROR (un-acquireable); RUNNING tasks on
        # it re-queued automatically (migration)
    restore_device(device)                  # ERROR -> IDLE re-join
    task_status / queue_depth / devices / snapshot
    run(worker_fn(task, device) -> bool) -> {task_id: ok}
        # ThreadPoolExecutor parallel run; refills idle devices as
        # tasks finish; exceptions -> FAILED; blocking
    audit: [(time, action, detail)]         # [CLUSTER] log lines
# GUI: ClusterPage(QWidget) route "cluster"; Signal dispatched(int);
# device board (设备/类型/状态/活跃/完成/失败/负载) + task board
# (queue+running); on_assign/on_remove(on_restore)/refresh;
# interactive flag; shell.cluster_scheduler shared instance
```

### 16. RBAC + Operation Audit (NEW — owned by P2-11, `mtkgui/engine/auth_audit.py` + `mtkgui/gui/audit_page.py`)

Pure-increment permission & traceability layer; zero changes to the
test / device / engine core.  Pages opt in by calling the gate +
ledger.

```python
class Role(Enum): ADMIN OPERATOR
PERMISSIONS = {ADMIN: {"*"}, OPERATOR: {run_test, view,
               export_report, upload}}     # single source of truth
@dataclass Session: username, role; can(action) -> bool
class AccessControl:
    __init__(accounts_path, audit=None, now=None)
    ensure_default_accounts()   # bootstrap admin/admin123 + op/op123
                                # (idempotent, salted sha256, local JSON)
    login(user, pwd) -> Session | None   # attempts audited
        # ledger action: "login:GRANT" / "login:DENY"
    require(session, action, target="")  # permission gate
        # raises PermissionError on denial; both GRANT and DENY are
        # audited as "<action>:GRANT|DENY"
    add_account(user, pwd, role, actor)  # audited "account_add"
    role_of(user) -> Role | None
class AuditLog:
    __init__(path, now=None)    # append-only JSONL ledger
    log(user, action, target="", before=None, after=None, detail="")
        # entry: ts/user/action/target/before/after/detail
    entries() / query(action=, user=, since=, until=, text=)
        # all criteria AND-combined, substring on action & text
    export(path, fmt="csv"|"json") -> Path   # export itself audited
# GUI: AuditPage(QWidget) route "audit"; Signal logged_in(str role);
# login box + role badge, guarded 修改配置 demo (operator denial
# visible + audited), ledger table with action/user/text filters,
# CSV/JSON export; interactive flag; shell.access + shell.audit_log
# shared instances ($MTKGUI_AUDIT_LOG / $MTKGUI_ACCOUNTS)
```

### 17. P2 Freeze — Capability Map & Integration Contract (P2-12)

P2 sealed on top of the P1 frozen base.  Full-chain integration is
locked by `mtkgui/engine/demo_p2_e2e.py` (rc=0 gate) and
`tests/engine/test_p2_integration.py` (parallel soak, failover under
load, full-route mount, append-only ledger).  Zero producer changes.

| Route | Increment | Owner module | Shared store on shell |
|---|---|---|---|
| workflow | P1 engine | runners/state machine | — |
| cases | P2-3 case editor | case_store / case_editor | — |
| case_io | P2-4 YAML↔Excel | case_io_page | — |
| reports | P2-6 dashboard | report_page / charts | metrics_engine |
| upload | P2-8 cloud loop | upload_page / uploader | upload_manager |
| export | P2-9 HTML/PDF | export_page / report_export | (metrics_engine) |
| cluster | P2-10 scheduling | cluster_page / cluster_scheduler | cluster_scheduler |
| audit | P2-11 RBAC + trail | audit_page / auth_audit | access / audit_log |
| config | P2-2 visual YAML | config_page / config_store | — |

Chain of custody (all read-only over producers):
records → MetricsEngine → ReportPage → ExportPage(HTML+PDF) →
ArchiveManager(pack+verify) → SharePointUploader → audit trail.
Env seams: `MTKGUI_OUTBOX_DIR`, `MTKGUI_EXPORT_DIR`,
`MTKGUI_AUDIT_LOG`, `MTKGUI_ACCOUNTS`.  Default accounts
admin/admin123, op/op123 (change before production).  Interface
freeze: §1–§17; P3 platform work must extend, not rewrite.

### 18. Multi-Project Tenant Context (NEW — owned by P3-1, `mtkgui/engine/project_context.py` + `mtkgui/gui/project_switcher.py`)

Pure-increment platform base on top of the frozen P1+P2 core (§1–§17
untouched).  Without an active tenant everything behaves exactly as
P2 (single-project compatibility mode); legacy projects need no
migration.

```python
TENANT_DIRS = (config, cases, outbox, export, archive, audit,
               logs, metrics)          # per-tenant workspace layout
class TenantError(Exception)           # lifecycle / cross-tenant violation
@dataclass ProjectContext:
    project_id, root
    dir(name) -> Path                  # canonical tenant dir (created)
    resolve(path) -> Path              # guard: no escape from root
    slot(key, factory) -> obj          # per-tenant isolated runtime store
    clear_slots()                      # switch/reset cache reset
    set_current(ctx) / current()       # global pointer; None = legacy mode
class TenantRegistry(base_dir):
    register(pid) -> ProjectContext    # new tenant (id-safe, duplicate raise)
    load(pid) -> ProjectContext        # on-disk tenant re-open
    switch(pid) -> ProjectContext      # activate: leaving tenant slots cleared
    unload(pid)                        # detach from memory, files kept
    reset(pid)                         # wipe logs/metrics, keep config+cases
    deactivate()                       # back to P2 single-project mode
    list_projects() / get(pid)
    guard(owner) -> ProjectContext     # cross-tenant bleed gate
        # legacy -> LEGACY pseudo-tenant passes; mismatched owner raises
# GUI: ProjectSwitcher (resident in shell top-nav), Signal
# tenant_switched(str pid, ""=legacy); add_project/load_project;
# shell.tenant_registry ($MTKGUI_TENANT_BASE, default "projects");
# shell.apply_tenant(ctx): rebinds metrics_engine / upload_manager /
# cluster_scheduler / audit_log / export dir into the tenant
# workspace, purges cached pages (routes rebuild inside tenant),
# audits "tenant_switch"
```

### 19. Structured DB Persistence Base (NEW — owned by P3-2, `mtkgui/engine/db_store.py`)

Pure-increment sqlite persistence BESIDE the P2 file stores (dual
storage; file logic untouched, data never lost).  Per-tenant DB file
(``metrics/tenant.db``) via the P3-1 slot mechanism -> data isolation
by default.

```python
SCHEMA_VERSION = 1   # auto CREATE TABLE IF NOT EXISTS on open
# tables: schema_version, projects, test_records, case_defs,
#         config_kv, upload_records, audit_events
class DbStore(path, project_id="LEGACY", now=None):
    ensure_schema() / schema_version / close()   # thread-safe conn
    register_project(pid, note) / list_projects()
    add_record(TestRecord, project_id=None) -> id
    list_records(project_id=None, batch=None, name=None,
                 all_projects=False) -> [TestRecord]
        # default scope = own project (isolation by default);
        # typed round-trip keeps StepStatus/FailureKind enums + ts
    count_records(project_id=None)
    upsert_case(name, fields_dict, locked) / get_case(name)
        # -> {"fields":..., "locked":...} | None / list_cases()
    set_config(key, value) / get_config(key)     # per-project kv
    add_upload(file, status, url, sha256) / list_uploads()
    add_audit(ts, user, action, target, before, after, detail)
    query_audits(project_id=, action=LIKE, user=)
    import_from_engine(engine) -> n   # P2-5 file records -> DB
    export_to_engine(engine) -> n     # DB rows -> fresh engine
def tenant_db(ctx, now=None) -> DbStore
    # P3-1 tenant slot "db" -> ctx.dir("metrics")/tenant.db
```

### 20. Global Resource Hub & Path Hub (NEW — owned by P3-3, `mtkgui/engine/resource_hub.py`)

Pure-increment platform hub over the P3-1 tenant kernel; P1/P2 device
locks and state machines untouched.

```python
PATH_CATEGORIES = (config, cases, outbox, export, archive, audit,
                   logs, metrics)
class ResourceBusy(Exception)
@dataclass ResourceLock: rtype, name, owner, tenant, token, acquired_at
class PathHub(ctx=None):             # ctx=None -> legacy CWD mode
    path(category, *parts) -> Path   # canonical, dirs auto-created
    resolve(path) -> Path            # escape rejected (P3-1 guard)
    snapshot() -> {category: location}
class ResourceManager(now=None, default_ttl=600):
    acquire(rtype, name, owner, tenant=None, ttl=None) -> ResourceLock
        # exclusive; ResourceBusy when held; TenantError on
        # cross-tenant tag mismatch vs active tenant
    release(lock) / release_token(rtype, name, token) -> bool
    owner_of(rtype, name) / is_busy(rtype, name)
    snapshot() -> [row]              # monitoring board (sorted)
    locks_view() -> [ResourceLock]   # for token-checked release
    sweep() -> n                     # TTL auto-release orphaned locks
# GUI: ResourcePage route "resources" — live lock table, tenant path
# tree, refresh / TTL sweep / token-checked release; shell shares
# resource_manager + path_hub (path_hub rebound on tenant switch)
```

### 21. Four-Layer Service Architecture (NEW — owned by P3-4, `mtkgui/engine/service_layer.py`)

Pure WRAPPER kernel: shipped P1/P2/P3 objects are classified and
their call direction enforced; no module rewritten, no external
contract changed (shell keeps §8–§20 contracts verbatim).

```python
class LAYER(Enum): UI SERVICE CORE STORE
allowed_calls(layer) -> set[LAYER]
    # UI->{SERVICE}; SERVICE->{CORE,SERVICE}; CORE->{STORE,CORE};
    # STORE->{STORE}
check_call(caller, target)          # raises ArchError on violation
CLASSIFICATION: dict[str, LAYER]    # shipped modules -> layer
classify(name) -> LAYER
@dataclass Service: name, layer; start()/stop()/healthy
class ServiceRegistry:
    register(svc) / wrap(name, target, layer)   # classify live object
    resolve(name, caller) -> Service            # layer-checked
    call(name, caller, method, *args, **kw)     # layer-checked invoke
    start_all() / stop_all() / health() / names(layer=None)
class RouteService(Service):        # route/service decoupling
    bind(route_key, service_name) / service_for(key)
    resolve_route(registry, key, caller=UI)
    snapshot() -> {route: service}
```

### 22. Persistent Priority Task Queue (NEW — owned by P3-5, `mtkgui/engine/task_queue.py`)

Pure-increment queue capability; P2 immediate-execution paths
untouched and unaffected.

```python
class TaskStatus(Enum): PENDING RUNNING DONE FAILED
@dataclass QueuedTask: payload, priority(higher first),
    max_retries, tid, attempts, status, result, error
class TaskQueue(journal_path=None, now=None, poll=0.02):
    submit(payload, priority=0, max_retries=2) -> QueuedTask
    get(tid) -> QueuedTask
    run(handler, workers=2) -> stats     # parallel drain, blocking;
        # handler exception -> requeue (attempts+1) until
        # max_retries exhausted -> FAILED with error captured
    wait(timeout=30) -> bool             # quiescence helper
    snapshot() -> [row]                  # tid/priority/status/...
    stats() -> {PENDING,RUNNING,DONE,FAILED,total}
    # journal: unfinished tasks persisted on EVERY transition,
    # re-queued on restart -> crash never loses a task
# GUI: QueuePage route "queue" — submit box (priority+retries),
# live task table, stats bar; shell shares task_queue
# (journal: <tenant_base>/_queue_journal.json)
```

### 23. Cluster Device Hub & Fleet Management (NEW — owned by P3-6, `mtkgui/engine/cluster_hub.py`)

Pure-increment fleet middle platform over the frozen P2-10
`ClusterScheduler`: registration + heartbeat + online/offline
judgement + remote ops + ledger/alerts.  No P1 driver, P2 lock or
P2-10 scheduler code touched — remote enable/disable routes through
the frozen scheduler contract (`report_fault` / `restore_device`).

```python
class NodeStatus(str, Enum): ONLINE OFFLINE ERROR
@dataclass ClusterNode: device_id, host, kind="generic",
    status=ONLINE, last_beat(monotonic), load=0, enabled=True,
    capabilities=(), joined_at
    as_row() -> {device_id, host, kind, status, load, enabled,
                 beats_ago_s}
@dataclass LedgerEvent: ts, device_id, event, detail
    # event ∈ JOIN / ONLINE / OFFLINE / ERROR / DISABLE / ENABLE /
    #          ALERT
class ClusterHub(stale_after=10.0, now=None):   # alias: CH
    register_node(device_id, host, kind, capabilities) -> ClusterNode
        # idempotent; JOIN ledgered once
    node(id) -> ClusterNode / nodes() -> [ClusterNode]
    heartbeat(device_id, load=None)  # unknown id -> ALERT + ledger
    monitor() -> n                   # stale sweep ONLINE->OFFLINE
    set_enabled(device_id, enabled, scheduler=None) -> bool
        # disable -> scheduler.report_fault(id, "remote disable");
        # enable -> scheduler.restore_device(id); unknown scheduler
        # device tolerated (hub ledger still records ENABLE/DISABLE)
    attach_scheduler(scheduler)      # read-only load/state reflection
        # completed count -> node.load; scheduler ERROR state ->
        # NodeStatus.ERROR (recovery -> ONLINE); hub never writes
    snapshot() -> [row]              # sorted by device_id
    ledger_rows(device_id=None) -> [dict]   # audit-friendly history
    on_alert(fn)                     # subscriber on every transition
# GUI: FleetPage route "fleet" (fleet_alert Signal[str]) — node
# board (6 cols), heartbeat intake, remote enable/disable, alert
# list, stats bar; shell shares cluster_hub + cluster_scheduler
```

### 24. Cross-Host Load Balancer (NEW — owned by P3-7, `mtkgui/engine/load_balancer.py`)

Pure-increment balancing STRATEGY layer over the frozen P2-10
`ClusterScheduler` + P3-6 `ClusterHub`: both observed read-only via
public contracts; original locks, state machines and dispatch path
untouched — host-level weights, busy avoidance and cross-host
migration suggestions only.

```python
@dataclass HostLoad: host, devices, active, completed, failed,
    busy_s, offline, queue_hint
    utilization -> float (active/devices, 0..1); as_row()
@dataclass MigrationRecord: task_id, from_host, to_host, reason
class LoadBalancer(w_active=1.0, w_busy=1.0, w_offline=2.0,
                   skew=0.35):                 # alias: LB
    observe(hub, scheduler=None) -> {host: HostLoad}
        # per-HOST aggregation of hub nodes + scheduler stats/states
    observe_kinds(hub)               # device->kind/host cache
    rank() -> [HostLoad]             # weighted score: idle-first
    best_host(kind=None) -> str|None # busy avoidance (util>=1 or
        # dead host skipped), optional kind filter
    imbalance() -> float             # max-min utilization spread
    plan(hub, scheduler=None) -> [{action: MIGRATE, kind, from,
        to, reason}]                 # hot host -> cold host proposals
    record_migration(task_id, from_host, to_host, reason) / 
    migrations() -> [dict]           # cross-host migration ledger
    accel_stats(scheduler, wall_s) -> {devices, busy_s, wall_s,
        speedup, efficiency}         # parallel speedup quantified
    hosts_view() -> [row]            # sorted board rows
# GUI: BalancePage route "balance" — host load table (8 cols),
# imbalance meter, MIGRATE plan list, migration records, manual
# migration recording, speedup label; shell shares load_balancer +
# cluster_hub + cluster_scheduler
```

### 25. Batch Pipeline Automation Middle Platform (NEW — owned by P3-8, `mtkgui/engine/batch_pipeline.py`)

Pure-increment UNATTENDED mass-production orchestrator: the P2
engines (runner / metrics / uploader / archive) plug in as stage
callbacks — no engine modified.  Per-unit failure isolation, batch
circuit breaker, traceable ledger.

```python
class UnitState(Enum): PENDING DONE FAILED QUARANTINED
@dataclass BatchUnit: unit_id(SN), state, stages{stage:OK/FAIL},
    error; as_row()
@dataclass BatchJob: batch_id, units{}, stage_cursor, started_at,
    finished_at, aborted_reason; done -> bool
class BatchError(Exception)
class BatchPipeline(max_fail_ratio=0.5, now=None):   # alias: BP
    create_batch(batch_id, unit_ids) -> BatchJob  # 批量初始化:
        # dedupe + blank drop; duplicate/empty batch -> BatchError
    batch(id) / batches()
    run_stage(batch_id, stage, fn, fallback=None) -> {stage, ok, fail}
        # 批量校验/测试/报表/归档上传 via fn(unit); per-unit
        # isolation: exception -> only that unit FAILED (error kept),
        # stage continues; fallback(unit, exc) -> QUARANTINED
    execute(batch_id, plan, fallbacks=None) -> {stages, aborted,
        reason}          # unattended: plan stages in order; batch
        # circuit breaker: cumulative fail ratio > max_fail_ratio ->
        # ABORT (later stages skipped, 异常兜底)
    summarize(batch_id) -> {units, states, stages, yield,
        finished_at, aborted_reason}      # 批量统计
    monitor(batch_id) -> {pending, failed, cursor, healthy,
        aborted_reason}                   # 流水线监控 (watchdog)
    snapshot(batch_id) -> [row]           # sorted by unit_id
    ledger_rows(batch_id=None) -> [dict]  # every transition (可溯源)
# GUI: PipelinePage route "pipeline" — batch create box (batch id +
# SN list), unit table (4 cols), yield stats bar, monitor dialog;
# shell shares batch_pipeline
```

### 26. Five-Role RBAC Permission Middle Platform (NEW — owned by P3-9, `mtkgui/engine/rbac_hub.py`)

Pure-increment upgrade of the frozen P2-11 dual-role auth to an
enterprise five-role, three-plane RBAC — P2-11 `AccessControl` /
`AuditLog` reused (account storage + denial audit), never modified.

```python
class Role5(Enum): VIEWER(0) < OPERATOR(1) < ENGINEER(2)
                   < MANAGER(3) < ADMIN(4)
FROM_P2: {"ADMIN"->ADMIN, "OPERATOR"->OPERATOR}   # P2 Role compat
PERM5: dict[Role5, set[str]]    # function plane; ADMIN={"*"}
    # VIEWER view; OPERATOR +run_test/export_report/upload;
    # ENGINEER +case_edit/config_edit/queue_manage;
    # MANAGER +case_lock/device_manage/audit_view/report_manage
PAGE_ACCESS: {route_key: min_level}   # page plane; default 4
DATA_SCOPES: role -> "project"|"all"  # data plane
class RbacError(Exception)
class RbacHub(access=None):           # alias: RH
    can(role, action) -> bool         # accepts P2 Role / Role5 / str
    require(role, action, target="")  # PermissionError on denial
    page_allowed(role, route_key) -> bool
    set_page_min(route_key, role5)    # runtime page tuning
    data_scope(role) / grant_project(role, pid) /
    project_allowed(role, pid) -> bool   # multi-project isolation
    set_permission(role, action, allow)  # runtime matrix tuning
    matrix_snapshot() -> {role: [actions]} / pages_snapshot()
    add_account(actor_role, username, password, role, project_ids=())
        # escalation guard: actor cannot grant >= own level unless
        # ADMIN; denial audited as account_add:DENY
    assignable_roles(actor_role) -> [str]
# GUI: RbacPage route "rbac" — matrix tab (5 roles x actions),
# page-plane tab, account tab (escalation-guarded creation);
# shell shares rbac_hub (wired to P2-11 access)
```

### 27. Full-Chain Audit Hub & Compliance Reports (NEW — owned by P3-10, `mtkgui/engine/audit_hub.py`)

Pure-increment compliance layer over the frozen P2-11 `AuditLog`
(append-only JSONL store reused, never modified): categorized
full-chain tagging, before/after change diffs, integrity check and
ISO audit-report export.

```python
CATEGORIES = (login, config, case, task, device, data, report,
              security)          # uncategorized -> data plane
diff_of(before, after) -> [{field, old, new}]   # 前后对比
class AuditHub(audit):            # alias: AH; audit = P2-11 AuditLog
    track(user, category, action, target, before, after, detail)
        # entry action stored as "category:action"
    change(user, category, action, target, before, after)
        # change record: diff summary written into detail
    entries()                     # tolerant read (malformed skipped)
    query(category=None, **kw)    # P2-11 filters + category prefix
    changes_of(target) -> [{ts, user, action, diff}]  # 溯源
    stats() -> {total, by_category, by_user, denied, changes}
    verify() -> {raw_lines, parsed, malformed, ok}    # 篡改检测
    compliance_report(path, since=None, until=None) -> summary
        # ISO 审厂 report: coverage/uncovered_categories/
        # change_records/denied_attempts/integrity; exports
        # <path>.csv + <path>.json; export itself audited
# GUI: CompliancePage route "compliance" — coverage table
# (category counts), integrity verdict + stats bar, ISO report
# export box; shell shares audit_hub (wired to P2-11 audit_log)
```

### 28. Open API Service & MES Line Adapter (NEW — owned by P3-11, `mtkgui/engine/api_server.py`)

Zero-dependency RESTful dispatch layer over the platform middle
platforms — engines are wired in via `bind()` provider callables,
no engine modified.  HTTP framing pluggable (handler suitable for
wsgiref / any framework).

```python
SCOPES = (read, write, admin)
@dataclass ApiKey: key_id, key_hash(sha256), scopes, enabled
class ApiError(code, message)
class ApiServer(audit_log=None, now=None):        # alias: AS
    issue_key(key_id, scopes=("read",)) -> secret  # plaintext ONCE
    revoke_key(key_id)
    route(method, path, scope, fn)     # custom route registration
    bind(status_fn=, devices=, tasks=, enqueue=, report_fn=, mes=)
    request(api_key, method, path, body=None) -> (code, json)
        # framework-agnostic dispatch; scope enforcement
        # (401 invalid / 403 disabled or missing scope); every
        # call audited (api:METHOD, OK/denial code)
    routes: GET status | GET devices | GET tasks | POST tasks
            | GET reports/summary | POST mes/orders | GET audit
@dataclass MesOrder: order_id, part_no, quantity, priority,
    status(RECEIVED/QUEUED/DONE/REJECTED), result
class MesAdapter(enqueue, deliver=None, log_fn=None):  # alias: MA
    receive_order(body) -> {accepted, order_id, units, duplicate}
        # inbound work order -> one platform task per unit;
        # idempotent re-delivery (order_id dedupe); invalid rejected
    push_result(order_id, payload) -> bool   # outbound to MES;
        # delivery failure -> retry buffer (never lost)
    retry_outbox() -> n / pending_outbox() -> int
# GUI: ApiPage route "api" — key issuance (secret shown once),
# request tester (method/path -> HTTP code), MES order intake box;
# shell shares api_server + mes_adapter (audit wired to P2-11)
```

### 29. Help Center (NEW — owned by V4.0-B2, `mtkgui/gui/help_dialogs.py`)

Menu: `Help → User Guide | Developer Guide | Version History |
Readme & Quick Start`.  All four entries open BUILT-IN popup dialogs
(no external files / browser).  Content is plain structured text
served by one provider so the dialogs stay thin:

```python
HELP_KEYS = ("user_guide", "developer_guide", "version_history",
             "readme_quickstart")
def help_content(key: str) -> str        # raises KeyError on bad key
class HelpDialog(QDialog):               # title + scrollable read-only
    def __init__(self, key: str, parent=None) -> None
# mount: main_window Help menu -> HelpDialog(key); content lives in
# mtkgui/gui/help_content.py (English text, per-topic sections)
```

### 30. Report Menu (NEW — owned by V4.0-B3; reuses P2-5/P2-9/P2-11)

Menu: `Report → DUT Report | Event Log | Statistics`.

**DUT Report (PDF)** — one PDF per unit, generated with the Qt stack
(`QTextDocument.print(QPdfWriter)`; zero new dependencies), content:
product info, batch info, test time, full-project test-result
summary, complete console log dump.  File naming (FIXED):

```
DUT_[PASS/FAIL]_[Serial#]_[Core ID]_[Project Part#]_[Batch#]_[Date]_[Time].pdf
```

**Event Log (TXT)** — full GUI-lifecycle record (start -> exit):
operations, device interaction, errors, permission events, all
timestamped; export dialog for traceability (extends the existing
event/session log files under `event/`).

**Statistics (quality)** — dialog selects the range: day / week /
month / year / single batch / multiple batches; metrics: Yield,
Avg Cycle Time, UPH / UPD, CpK, Error List ranking.  Computation
reuses `mtkgui/engine/metrics.py` (P2-5); charts reuse
`mtkgui/gui/charts.py` (P2-6); archive sources reuse
`mtkgui/engine/archive.py` (P2-7).  No metric is recomputed outside
the metrics engine.

```python
class StatisticsDialog(QDialog):
    def __init__(self, metrics_engine, parent=None) -> None
class DutReportBuilder:                   # mtkgui/gui/dut_report.py
    def build(self, run_result: dict) -> str   # returns pdf path
```

### 31. Yaml Build Page (NEW — owned by V4.0-B1, `mtkgui/yaml_build_page.py` + `mtkgui/gui/yamlbuild/`)

Classic-shell tab `Yaml Build` (rightmost, fixed).  Layout: left
Workflow Block Diagram + right live YAML preview, horizontal
splitter, window-adaptive (wide screens lay blocks out in rows,
narrow screens fall back to a single column).  Top fixed buttons
(item 16): `Import from Excel | Export to Excel | Edit/Apply`
(uniform adaptive width = widest label; the Build Draft / Release
Final YAML buttons were removed - redundant YAML entry).

Fixed, irreversible workflow sequence (disabled blocks are skipped):

```
Design Input -> Configure Power On/Off DUT -> Parse nets for ICT
-> Build Impedance/Voltage/Power rails up sequence -> Build Clocks
-> Build GPIOs -> Configure Programmer/Debugger
-> Configure Peripherials -> Parse Func/Interface for FCT
-> Build Func/Interface for FCT
```

Per-block rules: single click opens the block's own config dialog
(independent save + validation); right-click Enable / Disable
(disabled block renders grayed, is skipped by the flow, is NOT
written into the effective YAML, its parameters are silently kept).
Diagram <-> YAML two-way live sync with syntax / sequence / parameter
validation and error markers.

Ten module parameter groups (one per block above): design input
(product id, part number, sw/hw versions), power on/off sequencing,
ICT net parsing, impedance/voltage/rails-up capture, clocks, GPIOs,
programmer/debugger, peripherals (Wi-Fi / Bluetooth / serial / I2C /
SPI / ADC), FCT function/interface parsing, FCT flow build.

Dual-version publishing (FIXED naming):

```
Draft:  Plan_[Core ID]_[Project Part#]_build_draft_v.1.0.0.yaml
Final:  Plan_[Core ID]_[Project Part#]_build_final_v.1.0.0.yaml
```

Draft = machine-generated, for human review; Final = released,
locked for production, version-compare + archive supported.
Backward compatibility: importing any legacy YAML enables ALL
modules by default.  Multi-tenant isolation and persistence follow
the existing project/YAML storage rules — no new storage format.

Excel exchange (B1): `Export to Excel` writes all module parameters,
thresholds, sequence order, enable state and remarks;
`Import from Excel` bulk-updates with validation and error listing.
Requires the `openpyxl` dependency (approved for V4.0).

### 32. Equipment <-> Yaml Build Sync Contract (NEW — owned by V4.0-B4, `mtkgui/gui/yamlbuild/sync.py`)

Mandatory bidirectional parameter inheritance between the Equipment
page and the Yaml Build hardware-related blocks (instruments,
peripherals, serial, debugger, PSU, clocks, Wi-Fi/BT):

* last-writer-wins: the latest SAVE wins and overwrites the other
  side's cache (no ping-pong overwrite loops);
* dirty-edit lock: while either page has unsaved edits, the other
  side's sync is read-only (no half-finished data crosses pages);
* conflict detection: on mismatch, record a conflict log entry and
  show a friendly dialog comparing old / Equipment / Yaml-Build
  values (three-value compare);
* arbitration: one-click `[Apply to Yaml]` / `[Apply to Equipment]`
  aligns everything to the chosen side;
* silent fallback: sync failure, unknown field or version mismatch
  never raises to the UI — keep the previous valid configuration and
  log the anomaly in the background;
* new projects initialize Yaml Build module parameters from the
  Equipment configuration (base template, zero first-run conflict);
* unchanged parameters are silently reused; only changed fields are
  incrementally updated (existing projects keep working).

```python
class SyncDirection(Enum): TO_YAML; TO_EQUIPMENT
@dataclass SyncConflict: field, old_value, equipment_value,
    yaml_value
class EquipmentYamlSync:                  # one instance per project
    def pull_from_equipment(self) -> int  # fields updated
    def push_to_equipment(self) -> int
    def conflicts(self) -> list[SyncConflict]
    def apply(self, direction: SyncDirection) -> int
# signals: sync_done(direction, n), conflict_found(SyncConflict)
```

### 33. Dynamic Build Versioning (NEW — V4.0, `mtkgui/version_info.py`)

Replaces the static version string everywhere.  On GUI startup the
build version is resolved ONCE (cached) from, in order:

1. `MTKGUI_VERSION` environment variable (packaged builds; the
   packaging step may set it or write a `_build_version.txt` next to
   the executable — packaging auto-alignment without touching the
   PyInstaller spec),
2. `_build_version.txt` beside the app root (frozen builds),
3. live git metadata of the working tree: nearest tag
   (`git describe --tags --abbrev=0`), branch
   (`git rev-parse --abbrev-ref HEAD`), short commit
   (`git rev-parse --short HEAD`), dirty flag (`git status
   --porcelain`),
4. the static `mtkgui.__version__` constant (last-resort fallback).

Resolution NEVER raises into the UI (silent fallback + `source`
field records where the version came from: env / file / git /
static) — full auditability of what is running.

```python
@dataclass(frozen=True)
class VersionInfo:
    tag: str; branch: str; commit: str; dirty: bool; source: str
    def display(self) -> str   # "v3.0.0 (develop @ 1a2b3c4) [dirty]"
    def suffix(self) -> str    # filename-safe: "v3.0.0-develop-1a2b3c4"
def get_version_info(force: bool = False) -> VersionInfo  # cached
```

Consumers (mandatory): status bar / home page version label,
About & Version History dialogs (V4.0-B2), every exported file
version suffix (DUT Report PDF - B3, Draft/Final Plan YAML and
statistics exports - B1) via `VersionInfo.suffix()`.  The suffix is
filename-safe (no spaces / parentheses) so exported-file naming
rules stay valid.

## Conflict Prevention Rule

If two modules need new cross-module data field, update this interface spec first.
After spec updated, rebase all active feature branches.

Procedure: propose change in the SOLO session -> STOP coding -> coordinator
reviews -> approved change is committed on `develop` as a standalone task ->
all active feature branches rebase -> sessions continue.
