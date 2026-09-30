# MTK-GUI TRAE SOLO Session Templates
> This document stores all starting prompt templates for every independent TRAE SOLO session.
> Rules recap:
> 1. One SOLO session ↔ one feature branch. **Never run multiple SOLO sessions on the same git branch.**
> 2. Each SOLO is limited to its assigned module folder. Do NOT modify files outside scope.
> 3. src/common public shared modules cannot be modified in parallel feature branches unless explicit written approval is given.
> 4. All code changes must show diff preview and wait for user confirmation before overwriting files.
> 5. Read and comply with: .traerules, docs/interface_spec.md, docs/git_workflow.md, docs/parallel_dev_plan.md
> 6. Write pytest unit tests for new code. Check interface contract, report interface-breaking risk immediately.
>
> Folder mapping note: "src/common" refers to the shared/hot file registry in
> docs/parallel_dev_plan.md §5.2 (main_window.py, style.py, theme.py, permissions.py,
> serial_worker.py, ssh_worker.py, widgets/*, etc.). Those files change on `develop` only.

## P0 Tasks (Can run in parallel; complete & merge to develop before most P1 work)

### Template 1: feature/instrument-driver

```text
# Task: Instrument Driver Module (P0)
Follow .traerules, docs/interface_spec.md, docs/git_workflow.md and
docs/parallel_dev_plan.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/instrument-driver. One session = one branch.
  Start with: git checkout develop && git pull && git checkout -b feature/instrument-driver
- Allowed to modify: mtkgui/drivers/** (new package), tests/drivers/** (new)
- Everything else is READ-ONLY, especially the shared modules listed in
  docs/parallel_dev_plan.md §5.2 (main_window.py, test_workflow_page.py,
  project_config.py, serial_worker.py, ssh_worker.py, style.py, theme.py,
  widgets/**). If a shared module must change, STOP and report — develop-first.

## Mission
Implement mtkgui/drivers/: a base driver class (open/close/write/query lifecycle
with a mocked-transport injection point) plus concrete drivers for Keysight
DAQ973A (DAQM908A / DAQM907A modules), N5747A power supply, U2355A USB
DAQ/counter/DIO, and JLink flash.
- Commands must match Keysight official programming manuals — never invent
  commands (.traerules §5).
- Instrument addresses come from config/ YAML, never hardcoded (.traerules §4).
- Every public function: type hint + English docstring (.traerules §4).

## Working rules
1. Show diff preview for every file change and wait for my confirmation before
   overwriting files.
2. Driver API must match docs/interface_spec.md. If the interface contract needs
   to change, STOP coding and report immediately — do not change it unilaterally.
3. Commits use conventional commits (see .gitmessage), e.g.
   feat(drivers): add DAQ973A driver with mocked transport
4. Forbidden without my explicit approval: git reset, git clean -f,
   git push --force, branch deletion.

## Definition of done
1. pytest tests/drivers/ all green — every driver unit-tested over a mocked
   transport (no hardware required).
2. Changed-file list + pytest output reported; merging to develop is done by the
   coordinator after integration test.
```

### Template 2: feature/testflow-engine

```text
# Task: Test Flow Engine (P0)
Follow .traerules, docs/interface_spec.md, docs/git_workflow.md and
docs/parallel_dev_plan.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/testflow-engine. One session = one branch.
  Start with: git checkout develop && git pull && git checkout -b feature/testflow-engine
- Allowed to modify: mtkgui/engine/** (new package), tests/engine/** (new), and
  test_workflow_page.py LIMITED TO extraction call-sites (replacing inline engine
  logic with calls into mtkgui/engine). No UI redesign in this task.
- Everything else is READ-ONLY, especially shared modules in
  docs/parallel_dev_plan.md §5.2 (main_window.py, project_config.py,
  virtual_*.py, widgets/**, style.py, theme.py). Shared changes: STOP and report.

## Mission
Extract test execution logic from test_workflow_page.py into mtkgui/engine/
(runner, step definitions, result model, signals), preserving current behavior:
ICT/FCT/op step execution, Wait/Timeout handling, "Stop if failure" and
"Stop if any short" strategies, Overall Result rollup, engine-side event logging.
This is a pure extraction + API task — no behavior change. Engine API must match
docs/interface_spec.md (Runner API, Step fields, result enum, signals).

## Working rules
1. Show diff preview for every file change and wait for my confirmation before
   overwriting files.
2. If the interface contract must change, STOP coding and report immediately.
3. Commits use conventional commits, e.g.
   refactor(engine): extract test runner from workflow page
4. Forbidden without my explicit approval: git reset, git clean -f,
   git push --force, branch deletion.

## Definition of done
1. pytest tests/engine/ all green: step execution, wait/timeout, stop strategies,
   result rollup.
2. python smoke_test.py passes on the branch (GUI boots, flow still runs).
3. Changed-file list + pytest + smoke output reported; coordinator merges.
```

## P1 Tasks (Start after P0 merged into develop and integration test passes)

### Template 3: feature/ui-workflow-page

```text
# Task: Test Work Flow UI Page (P1)
Follow .traerules, docs/interface_spec.md, docs/git_workflow.md and
docs/parallel_dev_plan.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/ui-workflow-page. One session = one branch.
  Prerequisite: T1 + T2 already merged into develop (see parallel_dev_plan.md §4).
  Start with: git checkout develop && git pull && git checkout -b feature/ui-workflow-page
- Allowed to modify: test_workflow_page.py (UI layer) and NEW waveform/capture
  widgets under mtkgui/widgets/.
- Everything else READ-ONLY, including mtkgui/engine/** — consume the engine via
  its public API only. Shared modules (§5.2): STOP and report, never edit.

## Mission
Rework the Test Work Flow page as a pure UI layer on top of the mtkgui/engine
API: tables, waveform plot, progress/controls subscribe to engine signals; no
step execution logic in the page. Preserve existing behaviors: Long Run/Interval
locking, Result column rendering, stop strategy display, DAQ CSV export entry
points. Follow the page spec in .traerules §7.

## Working rules
1. Show diff preview for every file change and wait for my confirmation before
   overwriting files.
2. If the interface contract must change, STOP coding and report immediately.
3. Commits use conventional commits, e.g.
   feat(workflow): bind page to engine signals
4. Forbidden without my explicit approval: git reset, git clean -f,
   git push --force, branch deletion.

## Definition of done
1. pytest green for non-UI logic; python smoke_test.py passes.
2. Manual smoke checklist (every page feature verified) included in the merge
   report.
3. Changed-file list + test evidence reported; coordinator merges.
```

### Template 4: feature/virtual-dut

```text
# Task: Virtual DUT + Fault Injection (P1)
Follow .traerules, docs/interface_spec.md, docs/git_workflow.md and
docs/parallel_dev_plan.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/virtual-dut. One session = one branch.
  Prerequisite: T2 merged into develop (engine DUT interface defined).
  Start with: git checkout develop && git pull && git checkout -b feature/virtual-dut
- Allowed to modify: virtual_dut.py, virtual_hardware.py, virtual_mode.py,
  tests/virtual/** (new).
- Everything else READ-ONLY, including mtkgui/engine/** and
  test_workflow_page.py — consume engine DUT interfaces only.

## Mission
Align the virtual layer with the engine DUT interface from interface_spec.md:
VirtualDutWorker, VirtualRack (simulated instruments), FaultPolicy (fault
injection). Preserve documented virtual behaviors: Real/Virtual mode gating
(Virtual selectable by Supervisor only), "Virtual" result prefixes, virtual
waveform profile (1–4% overshoot, 0.4% startup ripple, 0.15% steady noise),
fault injection ratios 0–100% loaded from config. Real-mode code paths must
not change.

## Working rules
1. Show diff preview for every file change and wait for my confirmation before
   overwriting files.
2. If the interface contract must change, STOP coding and report immediately.
3. Commits use conventional commits, e.g.
   feat(virtual): align VirtualRack with engine interface
4. Forbidden without my explicit approval: git reset, git clean -f,
   git push --force, branch deletion.

## Definition of done
1. pytest tests/virtual/ green: measurement generation + fault injection cases.
2. python smoke_test.py passes (it imports the virtual modules).
3. Changed-file list + test evidence reported; coordinator merges.
```

### Template 5: feature/yaml-config-editor

```text
# Task: YAML Config Editor UI (P1)
Follow .traerules, docs/interface_spec.md, docs/git_workflow.md and
docs/parallel_dev_plan.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/yaml-config-editor. One session = one branch.
  Prerequisite: T2 merged into develop (YAML schema stable).
  Start with: git checkout develop && git pull && git checkout -b feature/yaml-config-editor
- Allowed to modify: project_config.py, the NEW editor page file
  (mtkgui/config_editor_page.py), tests/config/** (new).
- Everything else READ-ONLY, including test_workflow_page.py and main_window.py.
  If page registration into MainWindow is required, report it as a
  develop-first shared change — do not edit main_window.py directly.

## Mission
Build a YAML config editor page and keep project_config.py load/build/save/apply
signatures stable per interface_spec.md. No hardcoded product parameters — all
thresholds/addresses/rail sequences come from config/ YAML (.traerules §4).
Round-trip guarantee: load → edit → save preserves YAML semantics.

## Working rules
1. Show diff preview for every file change and wait for my confirmation before
   overwriting files.
2. If the interface contract must change, STOP coding and report immediately.
3. Commits use conventional commits, e.g.
   feat(config): add YAML config editor page
4. Forbidden without my explicit approval: git reset, git clean -f,
   git push --force, branch deletion.

## Definition of done
1. pytest tests/config/ green, including load→edit→save round-trip identity
   tests against fixtures in tests/config/fixtures/.
2. python smoke_test.py passes.
3. Changed-file list + test evidence reported; coordinator merges.
```

## P2 Tasks (Start after Phase 2 merges and integration test pass)

### Template 6: feature/log-viewer

```text
# Task: Log Viewer (P2)
Follow .traerules, docs/interface_spec.md, docs/git_workflow.md and
docs/parallel_dev_plan.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/log-viewer. One session = one branch.
  Prerequisite: Phase 2 merges finished (see parallel_dev_plan.md §4).
  Start with: git checkout develop && git pull && git checkout -b feature/log-viewer
- Allowed to modify: mtkgui/logs/** (new), tests/logs/** (new), and
  main_window.py LIMITED TO the event-log section extraction.
- Everything else READ-ONLY.

## Mission
Extract the Event Log panel into mtkgui/logs/ and add listing/filtering/export
(CSV, matching the existing logs/event folder format). Preserve documented
Event Log behaviors: one session log file per GUI run, right-click
Copy/Clear/Save as, Clear keeps a marker in the session log.

## Working rules
1. Show diff preview for every file change and wait for my confirmation before
   overwriting files.
2. If the interface contract must change, STOP coding and report immediately.
3. Commits use conventional commits, e.g.
   feat(logs): extract event log viewer module
4. Forbidden without my explicit approval: git reset, git clean -f,
   git push --force, branch deletion.

## Definition of done
1. pytest tests/logs/ green: parsing, filtering, export logic.
2. python smoke_test.py passes; Event Log panel visually unchanged.
3. Changed-file list + test evidence reported; coordinator merges.
```
