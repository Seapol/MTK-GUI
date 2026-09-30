# Task List — mtk-gui (refined after project audit)

- Date: 2026-09-30
- Source: `docs/parallel_dev_plan.md` refined by `docs/project_audit.md`
- Status legend: `done` / `pending` / `blocked (needs user decision)`
- Branch rules: `docs/git_workflow.md`. One TRAE SOLO session = one feature branch.

## Phase 0 — Baseline (sequential, on `develop`)

| ID | Task | Branch | Priority | Status | Notes / Acceptance |
|----|------|--------|----------|--------|--------------------|
| T0a | Commit all uncommitted WIP in logical groups (incl. untracked `mtkgui/virtual_hardware.py`, 3 docs); push `develop` and the 1 pending commit on `main` | `develop` | P0 | pending | Clean `git status`; audit risk R1/R9 closed |
| T0b | User reviews & approves `docs/interface_spec.md` v0.1 DRAFT (engine Runner/StepResult/signals, driver base class, exceptions location) | `develop` | P0 | pending | Spec becomes baseline; commit as `docs(interface): approve spec v0.1` |
| T0c | Scaffold `tests/` (pytest layout per module: drivers/engine/virtual/config/logs) + pytest config; decide with user whether `pytest` (+ later `pyvisa`) joins `requirements.txt` | `develop` | P0 | pending | `python -m pytest tests/` collects and passes empty baseline; audit R3 closed |
| T0d | Scaffold module packages `mtkgui/drivers/`, `mtkgui/engine/`, `mtkgui/logs/` with `__init__.py` stubs (interface-conform) | `develop` | P0 | pending | Folders exist before branches are cut (plan §3 T0) |

Gate: no `feature/*` branch may be created before Phase 0 is `done`.

## Phase 1 — P0 Foundation (2 parallel SOLO sessions)

| ID | Task | Branch | Priority | Status | Dependencies | Acceptance (audit-refined) |
|----|------|--------|----------|--------|--------------|----------------------------|
| T1 | Instrument driver module (`mtkgui/drivers/`): base driver + DAQ973A/DAQM908A/DAQM907A, N5747A, U2355A, JLink; `drivers/errors.py` shared exceptions | `feature/instrument-driver` | P0 | pending | Phase 0 | Mocked-transport pytest per driver; commands match Keysight manuals; addresses from YAML only; replaces Real-mode placeholders (`audit §3.1`) |
| T2 | Test flow engine (`mtkgui/engine/`): extract runner/steps/results/signals from `test_workflow_page.py` | `feature/testflow-engine` | P0 | pending | Phase 0 | Behavior-preserving extraction; `smoke_test.py` green; **unify `_virtual_fault_roll` with `FaultPolicy`** (audit R4); pytest covers wait/timeout/stop strategies |

Integration checkpoint I1: merge T1+T2 into `develop` one at a time; full pytest
+ smoke test + GUI boot; rebase checkpoint before Phase 2 (plan §4).

## Phase 2 — P1 Features (3 parallel SOLO sessions, after I1)

| ID | Task | Branch | Priority | Status | Dependencies | Acceptance (audit-refined) |
|----|------|--------|----------|--------|--------------|----------------------------|
| T3 | Test Work Flow UI on engine API; waveform widget **with repaint caching** (audit R7); preserve Long Run/Interval, Result column, CSV export | `feature/ui-workflow-page` | P1 | pending | T1+T2 merged | pytest non-UI logic; smoke test; manual checklist in merge report |
| T4 | Virtual DUT + fault injection alignment with engine DUT interface; single source of fault-roll logic | `feature/virtual-dut` | P1 | pending | T2 merged | pytest tests/virtual; Real-mode paths untouched; virtual behaviors preserved ("Virtual" prefixes, waveform profile) |
| T5 | YAML config editor page + `project_config.py` stability + materialize `config/schema/` (JSON Schema + reference) | `feature/yaml-config-editor` | P1 | pending | T2 merged | Load-edit-save round-trip identity tests; schema published; no hardcoded product params |

Integration checkpoint I2: merge T3/T4/T5 sequentially, integration test each.

## Phase 3 — P2 (after I2)

| ID | Task | Branch | Priority | Status | Dependencies | Acceptance |
|----|------|--------|----------|--------|--------------|------------|
| T6 | Log viewer module (`mtkgui/logs/`), extract event log from `main_window.py` | `feature/log-viewer` | P2 | pending | I2 | pytest parse/filter/export; Event Log behavior unchanged visually |

## Pending Decisions (blocked on user — do NOT start without answer)

| ID | Decision | Impact | Why blocked |
|----|----------|--------|-------------|
| D1 | Real RF test (WiFi/BLE): which host-side external CLI tools, and are they in scope for T1/T2? | Adds dependency/step types | `.traerules` forbids adding pip deps or inventing tool commands without asking |
| D2 | Automated FAT/OOBE firmware flashing via JLink: automate in T1 (driver) or keep operator-manual MessageGoStop flow? | T1 scope size | Product decision |
| D3 | Equipment page `_mock_configs()` -> YAML-driven instrument inventory: move to T1 or T5? | R5 ownership | Overlap between two task scopes |
| D4 | Supervisor password as plain constant in `permissions.py`: acceptable for shop floor, or move to env/secret? | Security hardening | User decision |
| D5 | Add `pytest` (now) and `pyvisa` (with T1) to `requirements.txt`? | CI + packaging | Dep additions need explicit approval |

## Release (sequential, after Phase 3)

| ID | Task | Status | Notes |
|----|------|--------|-------|
| REL1 | Merge `develop` -> `main`, tag `vX.Y.Z`, GitHub Actions exe build, verify packaged `config/` | pending | Full integration test first (plan §4) |
