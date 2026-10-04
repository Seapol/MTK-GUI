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

## Conflict Prevention Rule

If two modules need new cross-module data field, update this interface spec first.
After spec updated, rebase all active feature branches.

Procedure: propose change in the SOLO session -> STOP coding -> coordinator
reviews -> approved change is committed on `develop` as a standalone task ->
all active feature branches rebase -> sessions continue.
