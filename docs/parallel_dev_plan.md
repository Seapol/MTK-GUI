# Parallel Development Plan — Multi TRAE SOLO Sessions (mtk-gui)

- Version: 1.0
- Date: 2026-09-30
- Related docs: `.traerules`, `docs/git_workflow.md`, `docs/interface_spec.md` (to be created by Task T0)

## 1. Purpose

Define how multiple TRAE SOLO sessions work in parallel on mtk-gui with Git branch
isolation, strict folder-scope ownership, and a shared-interface change protocol, so
that code conflicts and logical interface mismatches are prevented by design.

## 2. Branch Architecture

```
main                # Stable release. Always compileable & runnable. NO direct commit.
├── develop         # Integration branch. All feature branches merge here.
    ├── feature/instrument-driver       # P0: Instrument driver module
    ├── feature/testflow-engine         # P0: Test flow engine
    ├── feature/ui-workflow-page        # P1: Test Work Flow UI page
    ├── feature/virtual-dut             # P1: Virtual DUT + fault injection
    ├── feature/yaml-config-editor      # P1: YAML config editor UI
    └── feature/log-viewer              # P2: Log viewer
```

Branch rules live in `docs/git_workflow.md`. Summary:

- `main`: only merged from `develop` after full integration test passes.
- `develop`: integration target; also the ONLY branch allowed to modify shared/base code.
- `feature/*`: exactly ONE TRAE SOLO session per branch, one topic per branch.

## 3. Task Table

| #  | Task name                   | Git branch                   | Priority | Module folder (allowed scope)                                                                 | Dependencies                                   | Acceptance criteria |
|----|-----------------------------|------------------------------|----------|-----------------------------------------------------------------------------------------------|------------------------------------------------|---------------------|
| T0 | Interface spec + baseline   | `develop` (sequential)       | P0-blocker | `docs/`, `mtkgui/drivers/`, `mtkgui/engine/`, `mtkgui/logs/`, `tests/` (scaffold only)        | Clean working tree on `develop`                | 1. All current WIP committed/stashed. 2. `docs/interface_spec.md` v0.1 written (module boundaries, public classes, signals, YAML schema pointer). 3. Scaffold packages exist with `__init__.py`. 4. `smoke_test.py` passes on `develop`. |
| T1 | Instrument driver module    | `feature/instrument-driver`  | P0       | `mtkgui/drivers/` (new) + `tests/drivers/`                                                     | T0                                             | 1. Driver classes for DAQ973A/DAQM908A/DAQM907A, N5747A, U2355A, JLink with mocked-transport pytest unit tests. 2. No commands invented beyond Keysight spec (.traerules §5). 3. Instrument addresses read from `config/` YAML, never hardcoded. 4. Type hints everywhere; no edits outside allowed scope. |
| T2 | Test flow engine            | `feature/testflow-engine`    | P0       | `mtkgui/engine/` (new) + `tests/engine/` + extraction call-sites in `test_workflow_page.py`    | T0                                             | 1. `mtkgui/engine/` exposes runner/steps/results API per `interface_spec.md`. 2. ICT/FCT/op step execution, wait/timeout, stop strategies ("Stop if failure", "Stop if any short") covered by pytest. 3. `smoke_test.py` passes after extraction. 4. No logic behavior change (pure extraction + API). |
| T3 | Test Work Flow UI page      | `feature/ui-workflow-page`   | P1       | `test_workflow_page.py` + new waveform/capture widgets under `mtkgui/widgets/`                 | T1 + T2 merged into `develop`                  | 1. Page renders tables/waveform on top of `mtkgui/engine` API (no direct step logic in page). 2. Existing features preserved (Long Run/Interval, Result column, DAQ CSV export). 3. pytest for non-UI logic; manual smoke checklist in PR description. |
| T4 | Virtual DUT + fault injection | `feature/virtual-dut`      | P1       | `virtual_dut.py`, `virtual_hardware.py`, `virtual_mode.py` + `tests/virtual/`                  | T2 merged (engine DUT interface defined)       | 1. VirtualDutWorker/VirtualRack/FaultPolicy comply with engine interface in `interface_spec.md`. 2. Fault injection ratios (0–100%) applied per spec. 3. pytest covers virtual measurement generation + fault injection. 4. Real-mode path untouched. |
| T5 | YAML config editor UI       | `feature/yaml-config-editor` | P1       | `project_config.py` + new editor page (e.g. `mtkgui/config_editor_page.py`) + `tests/config/`  | T2 merged (YAML schema stable)                 | 1. Load → edit → save round-trip produces identical YAML semantics; pytest round-trip tests. 2. Editor page integrated into MainWindow via existing pattern. 3. No hardcoded product params (.traerules §4). |
| T6 | Log viewer                  | `feature/log-viewer`         | P2       | `mtkgui/logs/` (new) + event-log section extraction in `main_window.py` + `tests/logs/`        | T2 merged; engine event logging stable         | 1. Viewer lists/filters/exports session + event logs (CSV). 2. pytest on parsing/filter/export logic. 3. `main_window.py` changes limited to log section call-sites. |

> Folder mapping note: `.traerules` §2 defines a `./src` layout; the actual code root is the
> `mtkgui/` package. This plan maps "src/common" → shared files listed in §5. Do NOT move
> existing files into new subpackages except through the owning task's scope.

## 4. Phase Plan (Sequencing)

```
Phase 0 (sequential, on develop):   T0  ── must finish before ANY feature branch is cut
Phase 1 (2 parallel SOLO sessions): T1 ∥ T2
Phase 1.5 (sequential, integrate):  merge T1 → develop, merge T2 → develop, integration test, rebase checkpoint
Phase 2 (3 parallel SOLO sessions): T3 ∥ T4 ∥ T5
Phase 2.5 (sequential, integrate):  merge T3/T4/T5 → develop one by one, integration test each
Phase 3:                            T6
Release (sequential):               develop → main, tag vX.Y.Z, build Windows exe via GitHub Actions
```

Between phases, the coordinator (user) runs:
1. `git checkout develop && git pull`
2. Merge each feature: `git merge --no-ff feature/<name>`
3. Integration test: `pytest` + `python smoke_test.py` + manual GUI startup
4. Rebase remaining active feature branches onto updated `develop`

## 5. File Ownership Map & Shared File Registry

### 5.1 Owned exclusively by one task at a time

| Path(s) | Owner during |
|---|---|
| `mtkgui/drivers/**`, `tests/drivers/**` | T1 |
| `mtkgui/engine/**`, `tests/engine/**`, `test_workflow_page.py` (extraction call-sites) | T2 (Phase 1) |
| `test_workflow_page.py`, new waveform widgets | T3 (Phase 2, after T2 merge) |
| `virtual_dut.py`, `virtual_hardware.py`, `virtual_mode.py`, `tests/virtual/**` | T4 |
| `project_config.py`, new config editor page, `tests/config/**` | T5 |
| `mtkgui/logs/**`, event-log section of `main_window.py`, `tests/logs/**` | T6 |
| `docs/interface_spec.md`, `docs/parallel_dev_plan.md` | Coordinator only (develop) |

### 5.2 Shared / hot files — develop-first rule applies

Any change to these files must be done on `develop` first, committed, then all active
feature branches rebase. A feature branch must NEVER edit them directly:

```
main.py
main_window.py            (except T6 log-section ownership in Phase 3)
equipment_page.py
style.py, theme.py
permissions.py
quick_commands.py
serial_worker.py, ssh_worker.py
ansi.py, at_commands.py, serial_params.py
widgets/multi_console.py, widgets/console_widget.py,
widgets/send_panel.py, widgets/connection_panel.py
smoke_test.py, scripts/, config/, MTK_GUI*.spec, requirements.txt, .github/
```

Rationale: `main_window.py` and `test_workflow_page.py` are the two hottest files
(nearly every page plugs into them); `serial_worker.py`/`ssh_worker.py` are shared by
console and future instrument transport; `style.py`/`theme.py` affect every widget.

## 6. Conflict Prevention Rules (hard rules, enforced per SOLO session)

1. **One SOLO session = one branch.** Never two sessions on the same branch.
2. **Folder scope restriction.** Each task edits only files in §5.1 ownership; everything
   else is read-only for that session.
3. **Shared code changes go develop-first** (§5.2), then rebase active branches:
   `git rebase develop` inside each feature branch (or `git merge develop` if rebasing
   published branches — prefer rebase, feature branches are private to one session).
4. **Interface contract**: `docs/interface_spec.md` is the single source of truth for
   cross-module APIs. Any needed interface change = stop coding, report to coordinator;
   coordinator updates `interface_spec.md` on `develop` as an independent task; all
   active branches rebase before continuing.
5. **Logical interface check at merge time.** Text-merge-clean ≠ logically compatible.
   Before every merge into `develop`, the coordinator audits: signal names, method
   signatures, YAML keys, units, and return types against `interface_spec.md` (checklist
   in §10). Report logical risks to the user.
6. **pytest must pass before every commit** (`python -m pytest tests/<area>`), plus
   `python smoke_test.py` before any merge into `develop`.
7. **Dangerous git commands** (`git reset`, `git clean -f`, `git push --force`,
   branch deletion) require explicit user approval in every session.

## 7. Interface Contract Status

`docs/interface_spec.md` v0.1 DRAFT exists (framework approved by user; concrete
v0.1 contracts grounded in existing code). T0 remaining work on `develop`:

1. User reviews and approves the draft contracts (engine Runner/StepResult/
   signals, driver base class + MeasurementResult, shared exceptions location).
2. Commit approved spec as the baseline; reference it from all SOLO templates.
3. Decide open items flagged in the spec: `config/schema/` materialization
   (T5 scope) and relocation of shared exceptions if ever needed.

## 8. SOLO Session Prompt Templates

Usage: paste ONE template into ONE new TRAE SOLO session. Do not reuse a template in a
second session.

### 8.1 T1 — Instrument driver module

```text
# Task: Instrument Driver Module (P0)
Follow .traerules and docs/interface_spec.md and docs/git_workflow.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/instrument-driver
  Start with: git checkout develop && git pull && git checkout -b feature/instrument-driver
- Allowed to modify: mtkgui/drivers/** (new package), tests/drivers/** (new)
- READ-ONLY for everything else. Especially forbidden: main_window.py,
  test_workflow_page.py, project_config.py, serial_worker.py, ssh_worker.py,
  style.py, theme.py, config/ — shared code changes must be reported, not made.

## Mission
Implement mtkgui/drivers/: a base driver class (open/close/write/query lifecycle,
mocked-transport injection point) plus concrete drivers for Keysight DAQ973A
(DAQM908A / DAQM907A modules), N5747A power supply, U2355A USB DAQ/counter/DIO,
and JLink flash. Commands must match Keysight official programming manuals —
never invent commands (.traerules §5). Instrument addresses come from config/
YAML, never hardcoded. Every public function gets a type hint, English docstring.

## Definition of done
1. pytest tests/drivers/ all green; every driver has unit tests over a mocked
   transport (no hardware required).
2. Driver API matches docs/interface_spec.md; if the spec must change, STOP and
   report — do not change the contract unilaterally.
3. Commits use conventional commits (see .gitmessage), e.g.
   feat(drivers): add DAQ973A driver with mocked transport.
4. Do not run git reset / git clean -f / git push --force without explicit approval.
5. When done: report changed-file list + pytest output; merging to develop is done
   by the coordinator after integration test.
```

### 8.2 T2 — Test flow engine

```text
# Task: Test Flow Engine (P0)
Follow .traerules and docs/interface_spec.md and docs/git_workflow.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/testflow-engine
  Start with: git checkout develop && git pull && git checkout -b feature/testflow-engine
- Allowed to modify: mtkgui/engine/** (new package), tests/engine/** (new), and
  test_workflow_page.py LIMITED TO extraction call-sites (replacing inline engine
  logic with calls into mtkgui/engine). No UI redesign in this task.
- READ-ONLY for everything else. Forbidden: main_window.py, project_config.py,
  virtual_*.py, widgets/**, style.py, theme.py.

## Mission
Extract the test execution logic from test_workflow_page.py into mtkgui/engine/
(runner, step definitions, result model, signals) preserving current behavior:
ICT/FCT/op step execution, Wait/Timeout handling, "Stop if failure" and
"Stop if any short" strategies, Overall Result rollup, engine-side event logging.
This is a pure extraction + API task: no behavior change. The engine API must
match docs/interface_spec.md (Runner API, Step fields, result enum, signals);
if the spec must change, STOP and report.

## Definition of done
1. pytest tests/engine/ all green: step execution, wait/timeout, stop strategies,
   result rollup covered.
2. python smoke_test.py passes on the branch (GUI still boots, flow still runs).
3. Conventional commits (see .gitmessage), e.g.
   refactor(engine): extract test runner from workflow page.
4. No destructive git commands without explicit approval.
5. Report changed-file list + pytest + smoke output; coordinator merges.
```

### 8.3 T3 — Test Work Flow UI page

```text
# Task: Test Work Flow UI Page (P1)
Follow .traerules and docs/interface_spec.md and docs/git_workflow.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/ui-workflow-page
  Start with: git checkout develop && git pull && git checkout -b feature/ui-workflow-page
  (only cut this branch AFTER T1+T2 are merged into develop)
- Allowed to modify: test_workflow_page.py (UI layer) and NEW waveform/capture
  widgets under mtkgui/widgets/.
- READ-ONLY for everything else, including mtkgui/engine/** — engine is consumed
  via its public API only.

## Mission
Rework the Test Work Flow page as a pure UI layer on top of the mtkgui/engine API:
tables, waveform plot, progress/controls subscribe to engine signals; no step
execution logic in the page. Preserve existing behaviors per project conventions
(Long Run/Interval locking, Result column rendering, stop strategies display,
DAQ CSV export entry points). Follow .traerules §7 page spec.

## Definition of done
1. pytest for non-UI logic green; python smoke_test.py passes.
2. Manual smoke checklist (list every page feature you verified) goes into the
   merge request description.
3. Conventional commits, e.g. feat(workflow): bind page to engine signals.
4. No destructive git commands without explicit approval.
5. Report changed-file list + test evidence; coordinator merges.
```

### 8.4 T4 — Virtual DUT + fault injection

```text
# Task: Virtual DUT + Fault Injection (P1)
Follow .traerules and docs/interface_spec.md and docs/git_workflow.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/virtual-dut
  Start with: git checkout develop && git pull && git checkout -b feature/virtual-dut
  (only cut this branch AFTER T2 is merged into develop)
- Allowed to modify: virtual_dut.py, virtual_hardware.py, virtual_mode.py,
  tests/virtual/** (new).
- READ-ONLY for everything else, including mtkgui/engine/** and
  test_workflow_page.py — consume engine DUT interfaces only.

## Mission
Align the virtual layer with the engine DUT interface from interface_spec.md:
VirtualDutWorker, VirtualRack (simulated instruments), FaultPolicy (fault
injection). Keep the documented virtual behaviors: Real/Virtual mode gating
(Virtual only for Supervisor), "Virtual" result prefixes, virtual waveform
profile (1–4% overshoot, 0.4% startup ripple, 0.15% steady noise), fault
injection ratios 0–100% loaded from config. Real-mode code paths must not change.

## Definition of done
1. pytest tests/virtual/ green: measurement generation + fault injection cases.
2. python smoke_test.py passes (it imports the virtual modules).
3. Conventional commits, e.g. feat(virtual): align VirtualRack with engine interface.
4. No destructive git commands without explicit approval.
5. Report changed-file list + test evidence; coordinator merges.
```

### 8.5 T5 — YAML config editor UI

```text
# Task: YAML Config Editor UI (P1)
Follow .traerules and docs/interface_spec.md and docs/git_workflow.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/yaml-config-editor
  Start with: git checkout develop && git pull && git checkout -b feature/yaml-config-editor
  (only cut this branch AFTER T2 is merged into develop)
- Allowed to modify: project_config.py, the NEW editor page file
  (mtkgui/config_editor_page.py), tests/config/** (new).
- READ-ONLY for everything else, including test_workflow_page.py and main_window.py;
  page registration into MainWindow must be reported to the coordinator as a
  develop-first change if required.

## Mission
Build a YAML config editor page and keep project_config.py load/build/save/apply
signatures stable per interface_spec.md. No hardcoded product parameters — all
thresholds/addresses/rail sequences come from config/ YAML (.traerules §4).
Round-trip guarantee: load → edit → save preserves YAML semantics.

## Definition of done
1. pytest tests/config/ green, including load→edit→save round-trip identity tests
   against a sample YAML in tests/config/fixtures/.
2. python smoke_test.py passes.
3. Conventional commits, e.g. feat(config): add YAML config editor page.
4. No destructive git commands without explicit approval.
5. Report changed-file list + test evidence; coordinator merges.
```

### 8.6 T6 — Log viewer

```text
# Task: Log Viewer (P2)
Follow .traerules and docs/interface_spec.md and docs/git_workflow.md strictly.

## Session binding (DO NOT change)
- Branch: work ONLY on feature/log-viewer
  Start with: git checkout develop && git pull && git checkout -b feature/log-viewer
  (only cut this branch AFTER Phase 2 merges are done)
- Allowed to modify: mtkgui/logs/** (new), tests/logs/** (new), and
  main_window.py LIMITED TO the event-log section extraction.
- READ-ONLY for everything else.

## Mission
Extract the Event Log panel into mtkgui/logs/ and add listing/filtering/export
(CSV, matching the existing logs/event folder format). Preserve existing Event
Log behaviors: session log file per GUI run, right-click Copy/Clear/Save as,
Clear keeps a marker in the session log.

## Definition of done
1. pytest tests/logs/ green: parsing, filtering, export logic.
2. python smoke_test.py passes; Event Log panel behavior unchanged visually.
3. Conventional commits, e.g. feat(logs): extract event log viewer module.
4. No destructive git commands without explicit approval.
5. Report changed-file list + test evidence; coordinator merges.
```

## 9. Risk Boundary: Parallel-Safe vs Sequential

### 9.1 Can safely run in parallel

- **T1 ∥ T2 (Phase 1)**: T1 writes a brand-new `mtkgui/drivers/`; T2 writes a brand-new
  `mtkgui/engine/` plus extraction call-sites in `test_workflow_page.py`. Zero file
  overlap. Both depend only on the T0 baseline.
- **T3 ∥ T4 ∥ T5 (Phase 2)**: ownership sets are disjoint
  (workflow page / virtual trio / config editor + project_config.py). No branch
  edits another's files.
- Any two tasks that never touch the same file AND never consume each other's
  in-flight interfaces.

### 9.2 Must run sequentially

- **T0 before everything**: interface spec + folder scaffold + clean WIP baseline.
- **T3 after T2 merge**: both touch `test_workflow_page.py`. T2 owns it during
  extraction; T3 must rebase onto the merged result.
- **T4/T5 after T2 merge**: both consume engine contracts (DUT interface, YAML
  schema) that T2 finalizes.
- **T6 after Phase 2**: extracts the log section of `main_window.py` only after
  page integrations settle.
- **Any change to §5.2 shared files**: develop-first, then rebase all active branches.
- **Merging**: feature → develop merges happen one at a time, each followed by
  integration test, never two merges racing.

### 9.3 Logical-conflict hotspots (no text conflict, but broken behavior)

| Boundary | Risk | Check at merge (see §10) |
|---|---|---|
| T2 ↔ T3 | engine signal names/args vs page subscriptions | signal list diff vs interface_spec.md |
| T2 ↔ T4 | engine DUT abstraction vs VirtualRack/FaultPolicy behavior | interface conformance test |
| T2 ↔ T5 | YAML keys written by editor vs keys read by engine | round-trip + engine load of edited YAML |
| T1 ↔ T2 | driver command maps vs engine instrument step expectations | mocked end-to-step test on develop |
| T5 ↔ T4 | fault-injection config keys | load fault config from editor-saved YAML |
| All ↔ shared QSS/themes | new widgets ignore theme tokens | run GUI in all 5 themes |

## 10. Merge-back Checklist (logical interface audit, per feature merge)

1. `git merge --no-ff feature/<name>` into `develop`.
2. `python -m pytest tests/` — full suite green.
3. `python smoke_test.py` — GUI boots, flow runs.
4. Diff the branch's public API against `docs/interface_spec.md`:
   renamed/added/removed classes, methods, signals, YAML keys.
5. Grep for accidental edits outside the task's allowed scope:
   `git diff develop@{1} develop --name-only` and compare with §5.1 ownership.
6. Launch GUI and switch all 5 themes (Light/Dark/Ocean/Forest/High Contrast).
7. Any mismatch → fix on the feature branch (or develop-first for shared code),
   re-run checklist.

## 11. Pre-Start Checklist (IMPORTANT — current repo state)

Before cutting any Phase-1 branch, the working tree must be clean because the
current tree holds uncommitted changes that overlap future task scopes
(`project_config.py`, `test_workflow_page.py`, `virtual_dut.py`,
`virtual_hardware.py` (untracked), `smoke_test.py`, `scripts/capture_preview.py`,
`preview/*.png`, `README.md`):

1. Commit this WIP to `develop` (logical groups, conventional commits) — **T0
   prerequisite**.
2. Push `develop`; cut feature branches only afterwards.
3. `main` is still 1 commit ahead of `origin/main` — push it before others clone.
