# B3 — FCT Preparation Spec (D1 / D2 / D4 decisions + fct_build design)

Status: PREPARATION (structure layer only — NO execution engine in this
phase)
Branch: `feature/p3-b3-fct-prep` (from `develop` @ B2 closure)
Author: TRAE (SOLO session) · 2026-10-08
Decision authority: **D1 / D2 / D4 SIGNED OFF by the USER on
2026-10-08** (all recommendations accepted; D4 carries two
implementation constraints + ops-scenario requirements — §7.1/§7.2).

---

## 0. Scope and red lines

This document is the ONLY execution standard for the P3-B3 preparation
phase.  It covers:

1. decision analysis D1 (RF scope), D2 (flash execution), D4
   (credential storage);
2. the `fct_build` module specification (Build FCT Test Work Flow
   Sequence — block 07 of the 12-stage Yaml Build flow);
3. the FCT step data model and YAML sequence schema;
4. integration points with the existing B2 assets.

Explicitly OUT of scope (red lines):

- FCT test EXECUTION logic (no message-judgement engine, no runner
  changes, no verdict computation);
- real serial / SSH / instrument runtime connections;
- changes to the B2-frozen ICT parse / test-point / path-risk cores
  and their UI;
- new third-party runtime dependencies (stdlib + PyYAML only);
- plaintext credentials in YAML (D4 forbidden option — never appears
  in any example).

Full production flow (fixed):

```
ICT ──► Flash FAT firmware ──► FCT ──► Flash OOBE firmware
```

FCT essence (user-established fact): **message testing** — a step
passes when Pass/Success-class keywords appear and fails when
Fail/Error-class keywords appear in the observed output (serial
channel, operator dialog, or terminal capture).  The keyword tables
and positive/negative matching rules are defined in §3 and stay
configurable per sequence.

---

## 1. Existing B2 assets this design aligns with (no changes)

| Asset | Location | Reuse |
|---|---|---|
| 12-stage block flow (block 07 = `fct_build`, currently disabled) | `mtkgui/gui/yamlbuild/stages.py` | this phase turns it DEFINED: data model + templates + YAML IO |
| FCT methods catalog | `mtkgui/engine/steps.py` `FCT_METHODS` | step-type mapping target (§3.4) |
| Standard op catalog (`Flash FAT Firmware`, `Flash OOBE Firmware`, fixture/power ops) | `mtkgui/engine/steps.py` `OP_STEPS` | skeleton stages |
| Project YAML FCT cases loader | `mtkgui/project_config.py` `_fct_step_from_yaml` / `apply_config` | published sequences MUST load through it unchanged |
| Channel Allocation model | `mtkgui/gui/yamlbuild/channel_allocation.py` | resource references (console channel keys) |
| Console channels (serial + SSH paramiko) | `mtkgui/test_workflow_page.py` `multi_console` | MESSAGE_CHECK / CLI_RUN channel binding |
| Event Log identity fields (Station ID / User) | `mtkgui/gui/identity.py` | audit lines for flash / confirm / parse events |
| YAML publish / load chain | `mtkgui/gui/yamlbuild/model.py` + `publish.py` | sequence documents travel inside the project YAML |

---

## 2. Decision D1 — RF tests inside FCT  **[SIGNED OFF: A]**

### 2.1 Capability list (proposed)

| RF item | Invocation | Output captured | Judged by |
|---|---|---|---|
| Wi-Fi scan / connect / RSSI / throughput (iperf3) | CLI on DUT console (`wifi_test ...`, `iperf3 -c ...`) | console read buffer lines | keyword table (§3.2) |
| Wi-Fi regulatory / country check | CLI (`wifi_test --country`) | console | keyword table |
| Bluetooth scan / pair / RSSI | CLI (`bt_test ...`) or vendor CLI | console | keyword table |
| Vendor RF GUI tool (optional, vendor-specific) | EXTERNAL_TOOL launch + GUI_CONFIRM | operator dialog verdict | human confirm |
| BLE audio / media check (sample) | EXTERNAL_TOOL + GUI_CONFIRM | dialog | human confirm |

Dependencies (host side, NOT pip packages — external executables
documented, never invented by the GUI): DUT-side `wifi_test` / `bt_test`
CLIs (firmware-provided), host `iperf3` binary for throughput, vendor
RF tool installer.  The GUI only ORCHESTRATES; it never ships these
binaries.

### 2.2 Unified abstraction (mandatory reuse)

Every RF item is expressed as one of the two generic step families —
RF is NOT a separate engine:

```
EXTERNAL_TOOL  (launch third-party tool / CLI, optional capture)
CLI_RUN        (console command -> capture -> keyword parse)
GUI_CONFIRM    (third-party GUI flow -> human Pass/Fail dialog)
MESSAGE_CHECK  (pure channel message judgement)
```

### 2.3 Options

| Option | Description | Pros | Cons | Risk |
|---|---|---|---|---|
| **D1-A (recommended)** | RF = CLI_RUN / EXTERNAL_TOOL steps inside the FCT sequence; keyword tables per step | zero engine special-casing; sequences stay data; matches "RF 与烧固件同构" | per-vendor keyword tables to maintain | low |
| D1-B | dedicated RF module with typed results (RSSI numbers etc.) | numeric limits possible | violates unified abstraction; engine growth | medium |
| D1-C | defer RF entirely | smallest scope | production gap | low now, high later |

**Recommendation: D1-A.**  Numeric-limit RF judgement (e.g. RSSI ≥ -65)
can LATER be layered as a MESSAGE_CHECK regex with capture-group limits
without changing the model.

**[SIGNED OFF: D1-A]**

---

## 3. Decision D2 — FAT / OOBE flash execution  **[SIGNED OFF: A]**

Two paths, both first-class (a sequence declares which one per flash
stage):

### 3.1 Path G — third-party flash GUI + human confirm

```
[GUI_CONFIRM step]
  1. EventLog: "Flash FAT: awaiting operator" (Station ID / User)
  2. Operator launches the vendor GUI manually (GUI never spawns it)
  3. GUI_CONFIRM pops the standard operator dialog
     (MessageGoStop-style): GO = firmware flashed OK / STOP = failed
  4. verdict recorded; STOP -> per on_fail policy (§4.3)
```

Interaction spec: dialog title `Flash <slot> Firmware — confirm`;
buttons GO / STOP; a details text area for operator notes; timeout
(optional, `timeout_s`, 0 = wait forever, default 0); every answer
lands in the Event Log with identity fields.

### 3.2 Path C — CLI flash + automatic parse

```
[CLI_RUN step]
  1. EventLog: "Flash FAT: CLI start (<command>)"
  2. command executes on the bound channel (serial console of the
     DUT's bootloader, or a host terminal wrapper)
  3. output captured until done-marker or timeout
  4. keyword parse: success keywords -> PASS, failure keywords -> FAIL
  5. retries: `retries` re-executions with the same capture rules
```

Parse rule detail: the DONE marker is a positive keyword; a negative
keyword seen at ANY time before the done-marker fails the step
immediately (negative-wins rule, §3.3).

### 3.3 Shared rules

| Aspect | Rule |
|---|---|
| Timeout | `timeout_s` per step; 0 disables; expiry = FAIL with "timeout" line |
| Retry | `retries` int (default 0); each retry re-runs the step; after the last retry the verdict stands |
| on_fail | `abort` (default: stop the sequence, Overall FAIL) / `continue` (record and go on) |
| EventLog points | start / capture markers / retry n / verdict / operator answer — each with Station ID + User |
| Sequence order | ICT → Flash FAT → FCT → Flash OOBE; a flash stage NEVER runs before its prerequisite stage passed |

### 3.4 Options

| Option | Description | Pros | Cons | Risk |
|---|---|---|---|---|
| **D2-A (recommended)** | both paths G+C as data-driven step types in ONE sequence model | per-product flexibility; matches既定框架 | none identified | low |
| D2-B | GUI path only (all flash manual) | simplest | no automation gain | low |
| D2-C | CLI path only | automation | breaks vendor-GUI-only products | medium |

**Recommendation: D2-A.**

**[SIGNED OFF: D2-A]**

---

## 4. Decision D4 — password / credential storage  **[SIGNED OFF: A + constraints]**

Scope: SSH channel passwords, DUT login credentials, future MES/Cloud
tokens.  NOT in scope: the Supervisor login password (already a
source constant per B1 — separate hardening task).

| Option | Mechanism | Security | Migration | Dependencies |
|---|---|---|---|---|
| **D4-A (recommended)** | OS keyring via `keyring` package (macOS Keychain / Windows Credential Manager), YAML stores only `credential_ref` (a lookup KEY) | OS-managed encryption, per-user | SSH channel params: replace `password` with `credential_ref`; one-time import prompt on first connect | +1 pip dependency (`keyring`) — needs explicit approval per house rule |
| D4-B | environment variables (`MTK_SSH_PASSWORD` etc.), YAML stores only the var NAME | no disk persistence; leaks via `env`/process listing; per-machine setup | same ref scheme | stdlib only |
| D4-C | encrypted config file (Fernet-style) — key still on disk → obfuscation only | weak (key beside data) | custom file format | +crypto dep |
| D4-D | plaintext YAML | **FORBIDDEN — reference only, never implement** | n/a | none |

Sequencing note: D4 does NOT block fct_build (structure layer stores
only `credential_ref` strings and never materializes secrets), but the
chosen option gates the later FCT execution phase and the SSH channel
UI.

**Recommendation: D4-A**, fallback D4-B until the `keyring`
dependency is approved.

**[PENDING USER SIGN-OFF: D4-A / D4-B / D4-C]**

---

## 5. fct_build module spec (Build FCT Test Work Flow Sequence)

Module: `mtkgui/gui/yamlbuild/fct_build.py` — pure data layer, no Qt,
no I/O beyond YAML text helpers, no execution code.

### 5.1 Step types

| step_type | Meaning | Channel binding | Verdict source (future phase) |
|---|---|---|---|
| `MESSAGE_CHECK` | judge channel messages by keywords | serial / SSH console key | keyword parse of captured lines |
| `GUI_CONFIRM` | third-party GUI flow + human Pass/Fail | operator dialog | human answer (GO/OK=pass, STOP/No=fail) |
| `CLI_RUN` | run a CLI command on a channel, capture, parse | serial / SSH / terminal | keyword parse of command output |
| `EXTERNAL_TOOL` | launch an external tool (RF etc.), optional confirm | host process + optional dialog | keyword parse and/or human confirm |

### 5.2 FctStep fields (schema `fct_sequence.steps[]`)

| Field | Type | Default | Constraint |
|---|---|---|---|
| `name` | str | required | unique within the sequence |
| `step_type` | enum | required | one of §5.1 |
| `channel` | str | `""` | console channel key (serial / SSH); `""` = dialog/host only |
| `command` | str | `""` | CLI_RUN / EXTERNAL_TOOL payload |
| `expect_pass` | list[str] | `[]` | positive keywords (case-insensitive substrings) |
| `expect_fail` | list[str] | `[]` | negative keywords; **negative-wins**: any match before a positive verdict fails the step |
| `timeout_s` | float | `30.0` | `> 0`; `0` = wait forever (GUI_CONFIRM default 0) |
| `retries` | int | `0` | `>= 0` |
| `on_fail` | enum | `abort` | `abort` \| `continue` |
| `depends` | list[str] | `[]` | names of steps that must precede it |
| `resource` | str | `""` | Channel-Allocation / inventory reference (e.g. `console:ser1`) |
| `params` | dict | `{}` | free extension dict (tool path, profile, notes) |

Validation returns a list of error strings (empty = valid); unknown
`step_type`, empty `name`, duplicate names, `timeout_s < 0`,
`retries < 0`, `on_fail` outside the enum, and `depends` referencing
unknown names are errors.

### 5.3 FctSequence

| Field | Type | Notes |
|---|---|---|
| `name` | str | sequence title |
| `flash_mode` | `gui` \| `cli` | which flash path the skeleton uses (per-stage override allowed via steps) |
| `keyword_pass` | list[str] | sequence-level positive table; per-step `expect_pass` extends it |
| `keyword_fail` | list[str] | sequence-level negative table; per-step `expect_fail` extends it |
| `steps` | list[FctStep] | ordered |

Defaults (configurable, this IS the configurable keyword table):

```
keyword_pass = ["pass", "passed", "success", "succeed", "ok", "done",
                "complete"]
keyword_fail = ["fail", "failed", "failure", "error", "timeout",
                "abort", "exception", "refused"]
```

### 5.4 Sequence generation rules (skeleton)

`build_fct_sequence(name, ict_stage_passed_note, flash_mode,
extra_steps=None)` produces the fixed production spine, using the
existing op catalog names so the document loads through the current
chain:

```
1. (reference marker) ICT stage          -> op "Init Instruments" context
2. op "Flash FAT Firmware"    (slot fat) -> step_type per flash_mode:
        gui  -> GUI_CONFIRM (dialog, timeout 0)
        cli  -> CLI_RUN     (channel-bound, expect tables apply)
3. FCT body: extra_steps (default one MESSAGE_CHECK "All Tests done.")
4. op "Flash OOBE Firmware"   (slot oobe) -> same flash_mode mapping
5. op "Power Off DUT" / "Fixture Unlock" / "Fixture Release" /
   "Reset Instruments" teardown tail
```

Generation is PURE: input data in, FctSequence out; nothing executes.

### 5.5 YAML document contract

Standalone sequence documents (and the future block-07 params) use:

```yaml
fct_sequence:
  name: <str>
  flash_mode: gui|cli
  keyword_pass: [...]
  keyword_fail: [...]
  steps:
  - name: <str>
    step_type: MESSAGE_CHECK|GUI_CONFIRM|CLI_RUN|EXTERNAL_TOOL
    channel: <str>
    command: <str>
    expect_pass: [...]
    expect_fail: [...]
    timeout_s: <float>
    retries: <int>
    on_fail: abort|continue
    depends: [...]
    resource: <str>
    params: {...}
```

### 5.6 Integration with the existing project YAML chain

`to_project_fct_cases(sequence)` converts a sequence into the EXISTING
`test_workflow.fct_test_cases` shape so the current loader
(`project_config.apply_config` consumes `kind` / `name` / `enable` /
`wait_ms` / `timeout_ms` / `op_params` directly) processes it with ZERO
changes:

| FctStep step_type | existing `kind` | name convention |
|---|---|---|
| MESSAGE_CHECK | `SendtoConsole` / `CapturefromConsole` (channel set) else `MessageOK` | `'kw1' ... (expected)` segments carry keywords |
| GUI_CONFIRM | `MessageGoStop` | `Confirm: <name>` |
| CLI_RUN | `SendtoCLI` (+ paired `CapturefromCLI`) | `'<command>' , '<done-kw>' (expected)` |
| EXTERNAL_TOOL | `WIFI` / `Bluetooth` / `MessageOK` (per `params.tool_family`) | `Tool: <name>` |

Reverse mapping (`from_project_fct_cases`) is provided for round-trip
tests; lossless for the fields the legacy shape carries (legacy
`wait_ms` maps to `timeout_s` floor of 1.0 s granularity note kept in
`params.legacy_wait_ms`).

### 5.7 GUI integration points (defined here, implemented later)

| Point | Contract |
|---|---|
| Block 07 enablement | `model.set_enabled("fct_build", True)` + params `= sequence.to_params()`; the block dialog renders the sequence table (later phase) |
| Test Work Flow table | published `fct_test_cases` render through the existing `_fill_fct_all` — no page change |
| EventLog | sequence events carry `[<Station ID>] [<User>]` prefixes from `gui/identity.py` (format fixed here, emitted in the execution phase) |
| Publish / load | sequence travels inside `yaml_build_state` / `fct_test_cases`; standalone docs load via `fct_build.sequence_from_yaml` |

---

## 6. Deliverables of THIS phase

1. this document (D1/D2/D4 + spec + integration points);
2. `mtkgui/gui/yamlbuild/fct_build.py` — data model, validation,
   skeleton generation, YAML (de)serialization, project-cases mapping;
3. `yaml_plan/examples/fct_sequence_gui_flash.yaml` — Path G example;
4. `yaml_plan/examples/fct_sequence_cli_flash.yaml` — Path C example;
5. `tests/yamlbuild/test_fct_build.py` — model / round-trip /
   generation / loader-compatibility tests;
6. the decision sign-off table below.

## 7. Decision sign-off table  **[SIGNED OFF — 2026-10-08]**

| ID | Question | Options | Recommendation | User decision |
|---|---|---|---|---|
| D1 | RF tests abstraction | A: as CLI_RUN/EXTERNAL_TOOL steps · B: dedicated RF module · C: defer | A | **A — SIGNED OFF** (RF = third-party tool/CLI + message parse, no dedicated RF module) |
| D2 | Flash FAT/OOBE execution | A: GUI-confirm + CLI-parse both · B: GUI only · C: CLI only | A | **A — SIGNED OFF** (dual path is a product fact, fixed in spec) |
| D4 | Credential storage | A: OS keyring · B: env vars · C: encrypted file · D: plaintext (FORBIDDEN) | A | **A — SIGNED OFF with two implementation constraints (below)** |

### 7.1 D4 signed-off implementation constraints

1. **Explicit fallback, never silent downgrade.**  When the OS keyring
   backend is unavailable (Linux without a secret service, frozen
   builds without the backend, headless sessions) the credential layer
   MUST fall back to D4-B (environment variables) AND surface an
   explicit warning to the operator (Event Log + UI banner on the
   affected channel dialog).  Falling back to plaintext anywhere is
   FORBIDDEN.
2. **Windows PyInstaller packaging verification is part of the
   acceptance.**  `keyring` needs hidden imports in
   `MTK_GUI_windows.spec`; the packaged exe must be verified on a
   production Windows station (store + read a credential).  If
   packaging or on-target verification fails, the execution phase
   falls back to D4-B and this spec documents the failure here.

### 7.2 D4 operations scenarios (execution-phase design scope)

The FCT execution-phase design MUST cover the shop-floor operations
scenarios below; each gets a design subsection in the execution spec:

| Scenario | Required design |
|---|---|
| Multi-PC deployment (per-station credentials) | credentials are stored PER OS USER on EACH station; a station-setup checklist (first-run credential entry, per-station keyring isolation); no cross-machine copy of secrets |
| Supervisor password reset / recovery | reset procedure clears/rotates stored credential refs WITHOUT exposing old values; operator re-enters credentials after a reset; audit line in the Event Log |
| OS reinstall / PC migration | keyring contents are NOT portable by design — a documented re-entry procedure (or optional export ONLY into an operator-supplied encrypted file, explicitly NOT the YAML; requires user approval at implementation time) |
| Keyring locked / inaccessible at runtime | explicit fallback per §7.1 constraint 1 (env vars + warning), never plaintext |

No example YAML or code contains any credential value; `credential_ref`
placeholders only.
