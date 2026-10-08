# B4 — FCT Execution Design (engine, channels, GUI/CLI paths) + Report

Status: EXECUTION-PHASE DESIGN (implemented in the same phase, Virtual
mode verifiable; Real-mode on-target work is a SEPARATE later batch)
Parent spec: `docs/fct/B3-FCT-Preparation-Spec.md` (D1-A / D2-A / D4-A
signed off 2026-10-08, constraints §7.1, ops scenarios §7.2)
Branch: `feature/p3-b3-fct-prep`

---

## 1. Message judgement engine

### 1.1 Channel abstraction (`mtkgui/engine/fct_channels.py`)

One protocol, four adapters — a step never knows which transport it
uses:

```
FctChannel (protocol)
    read_lines(max_lines, timeout_s) -> list[str]   # completed lines
    write(data: str) -> None
    close() -> None
    kind -> "serial" | "ssh" | "subprocess" | "virtual"
```

| Adapter | Transport | Notes |
|---|---|---|
| `SerialFctChannel` | existing console channel worker (pyserial) | binds by channel key via the Console abstraction; no new serial code |
| `SshFctChannel` | existing SSH worker (paramiko) | credentials via the credential layer (§6) |
| `SubprocessFctChannel` | `subprocess.Popen` on the HOST | one-shot CLI command; stdout/stderr captured line-wise; exit code exposed |
| `VirtualFctChannel` | in-memory queue | **injectable**: `inject_output(lines)` pushes scripted lines; `inject_fault("no_response" / "error")` for fault-injection tests; Virtual mode + all unit tests use this |

### 1.2 Capture model

A capture is a bounded drain: loop `read_lines` until (a) a POSITIVE
keyword hits, (b) a NEGATIVE keyword hits, (c) `timeout_s` expires, or
(d) for CLI_RUN, the process exits (then one final drain).  Every
captured line is timestamped and forwarded to the Event Log sink.

### 1.3 Keyword tables (configurable, persisted)

Default tables live in `fct_build.DEFAULT_KEYWORD_PASS / _FAIL`.  A
sequence (and the product YAML section `test_workflow.fct_keywords`)
may override them; per-step `expect_pass` / `expect_fail` EXTEND the
sequence tables.  Matching: case-insensitive substring.

**Negative-wins rule:** if a negative keyword is observed at ANY point
before a positive verdict, the step FAILS immediately.

Persistence: `fct_keywords` section in the project YAML
(`pass`/`fail` lists); restored into the page model on load; edited via
the FCT sequence builder (later GUI polish; the data path is live).

### 1.4 Timeout / retry / re-read policy

| Situation | Policy |
|---|---|
| timeout with no verdict | attempt counted FAIL("timeout"); retry if retries remain |
| retry | full re-execution of the step (command re-sent, capture restarted); EventLog line `retry n/N` |
| re-read | a single grace re-drain of buffered lines (0.5 s) after a positive hit, to let a trailing ERROR line flip the verdict (negative-wins fairness) |
| no keywords configured | step FAILs with "no keywords configured" (explicit, never silently PASS) |

### 1.5 Verdict model (`mtkgui/engine/fct_exec.py`)

```
FctOutcome:
    verdict : "PASS" | "FAIL" | "ERROR" | "SKIP"
    reason  : str            # human line for the Event Log
    lines   : list[str]      # captured evidence (timestamped at sink)
```

`ERROR` = infrastructure fault (channel open failure, process spawn
failure); `FAIL` = judged out (negative keyword / timeout / human
STOP); `SKIP` = step disabled or dependency failed with on_fail=
continue semantics upstream.

---

## 2. Step executor state machine

One executor, four execution flows (per step_type), shared states:

```
IDLE -> PREPARE -> (CAPTURE | WAIT_HUMAN | SPAWN) -> JUDGE -> DONE
                    \-- retry loop back to PREPARE (n of retries) --/
```

| step_type | Flow | Channels |
|---|---|---|
| `MESSAGE_CHECK` | PREPARE(bind channel) -> CAPTURE until verdict -> JUDGE | serial / ssh / virtual |
| `GUI_CONFIRM` | WAIT_HUMAN: pop the operator dialog (MessageGoStop-style) -> human answer -> JUDGE (GO/OK=PASS, STOP/No=FAIL); timeout_s=0 waits forever, >0 auto-FAILs on expiry | none (dialog) |
| `CLI_RUN` | SPAWN: send `command` on the bound channel (or host subprocess for `resource=host`), capture + exit-code joint judgement (§4) | serial / ssh / subprocess / virtual |
| `EXTERNAL_TOOL` | launch wrapper (tool registry §5) -> capture output and/or pop GUI_CONFIRM (params.confirm) -> JUDGE | subprocess + optional dialog |

EventLog record points (EVERY line carries `[Station ID] [User]` via
`gui/identity.py`): `step start`, `channel bound`, `command sent`,
`capture n lines`, `retry n/N`, `human answer <X>`, `verdict <V>
(<reason>)`.

Integration with the existing runner: a published FCT case whose
`op_params` carries `{"fct_step": {...}}` is executed by the NEW
executor (Virtual-verifiable); legacy cases without that marker keep
the existing virtual simulation path — zero behavior change for B2
tests.

---

## 3. GUI_CONFIRM interaction spec

- Dialog = the existing MessageGoStop operator dialog style; title
  `Confirm: <step name>`; body shows `params.note` (e.g. vendor flash
  GUI instructions).
- Trigger: when the run reaches the step (fixture/power prerequisites
  already executed).
- Buttons: GO (Pass) / STOP (Fail) / Cancel-as-STOP; ESC = STOP.
- Permission: the same `MessageGoStop` answering path the FCT rows use
  today — Operator may answer (it IS an operator task); no extra
  permission key.
- Result write-back: dialog answer -> FctOutcome(verdict, reason=
  "human GO"/"human STOP") -> EventLog with identity -> table cell.
- Timeout: `timeout_s=0` (default for flash stages) waits forever;
  `>0` auto-FAIL("timeout") — Virtual tests inject answers via a
  headless answerer hook (same mechanism the smoke test uses).

---

## 4. CLI_RUN spec

- Command template: `command` may reference `{serial}` / `{baud}` /
  `{sn}` placeholders filled from the FCT context (product serial,
  bound channel params) — injected at spawn time, never stored back.
- Resource injection: `resource="console:<key>"` binds the command to
  a Channel-Allocation/console resource (B2 model reuse).
- Joint judgement: PASS requires (exit_code == expected_exit (default
  0)) AND a positive keyword hit; a negative keyword OR non-zero exit
  => FAIL; timeout => FAIL("timeout").
- Host-side tools (`resource=host`): `SubprocessFctChannel` runs the
  command locally with a working directory from `params.cwd`.

---

## 5. EXTERNAL_TOOL / RF adaptation

Tool registry: `fct_build.params.tool_family` selects the wrapper —
registry maps family -> launcher (structure in the executor; actual
binaries are environment-provided, never shipped):

| family | wrapper | example |
|---|---|---|
| `wifi` | CLI_RUN against the DUT console (`wifi_test`, `iperf3`) | `iperf3 -c {host} -t 5` -> positive `Mbits/sec` |
| `bluetooth` | CLI_RUN (`bt_test ...`) | `bt_test --scan` -> `paired` |
| `gui` (vendor tool) | launch note + GUI_CONFIRM | vendor RF GUI |

RF is NOT a special engine (D1-A): every RF item is one of the four
step types; the iperf3 / Wi-Fi / Bluetooth examples in
`yaml_plan/examples/fct_sequence_*.yaml` are the executable
adaptations.

---

## 6. D4 credential layer (`mtkgui/engine/credentials.py`)

```
get_credential(ref) -> str
    1. keyring (service "mtk-gui", account = ref)
    2. FALLBACK: environment variable  MTK_CRED_<REF uppercased>
       + explicit EventLog/UI warning  "keyring unavailable - using
       env fallback for <ref>"   (NEVER silent, NEVER plaintext file)
    3. neither -> CredentialUnavailable raised (channel open fails
       with a clear reason)
set_credential(ref, value) / delete_credential(ref)   # dialogs later
```

Windows packaging note (REAL-machine batch MUST verify): add hidden
imports `keyring.backends.Windows` (+ `keyring.backends.macOS` on the
mac build) to the specs; acceptance = store + read a credential from
the packaged exe (B2 checklist §B1).  Failure => fallback to env vars
and record it in the B3 spec §7.1.

---

## 7. Integration contracts

| Surface | Contract |
|---|---|
| 12-stage block flow | block 07 `fct_build` params = the FctSequence dict; publishing embeds steps into `fct_test_cases` (B3 §5.6 mapping, now with `op_params.fct_step`) |
| FCT sequence YAML | `fct_sequence` section + `fct_keywords` (§1.3) travel inside the project YAML; standalone docs unchanged |
| Test Work Flow table | rows render via the existing `_fill_fct_all`; execution routes through the runner hook (§2) |
| Console | serial + SSH via existing multi-console workers; SSH password resolution switches to the credential layer (§6) |
| Overall Result | FctOutcome maps to the table cells: PASS/FAIL/Error/Skip — identical semantics to the ICT column, Overall rollup unchanged |

---

## 8. Report design (Module B)

### 8.1 Data model (`mtkgui/engine/report.py`, stdlib only)

```
ReportItem:  test_name, category (ICT|Flash|FCT|RF), channel,
             measured, low, high, unit, result, timestamp
DutReport:   serial_no, station_id, user, timestamp, overall_result,
             items: list[ReportItem]
             to_csv_rows() / from_session()
BatchSummary: n_total, n_pass, n_fail, yield_pct,
              failures_by_item: {test_name: count}   (sorted desc)
```

Source of truth: the Test Work Flow session state — ICT rows, FCT
rows, flash confirmations; the generator NEVER re-judges.

### 8.2 Report types and output

| Type | Content | Output |
|---|---|---|
| DUT detail | every item with measured/limits/verdict | CSV (MES-importable flat rows) + in-app preview table + print view (HTML render via QWebEngine-free `QTextBrowser.setHtml`) |
| Batch summary | N DUTs: PASS/FAIL counts, yield %, failures-by-item ranking | CSV + preview |

Storage: `reports/<YYYY-MM-DD>/<batch>_<SN>_<HHMMSS>.csv`
(+ `_summary.csv`); the directory is created on demand; archived per
day/batch (gitignored like logs/).

### 8.3 Triggers, permissions, consistency

- Triggers: automatic at run_finished (counted product) + a manual
  **Generate Report** action (enabled after Validate/Publish).
- Permissions: Supervisor sees/exports everything; Operator = current
  session read-only (same permission keys as the report page).
- Consistency: the report is BUILT FROM the same session state the
  Overall Result and Event Log render — a unit test asserts
  report.overall_result == page result for a scripted session.

### 8.4 Module B tests

model serialization round-trip · CSV header/format · yield and
failure-ranking math · empty-report edge · auto + manual triggers ·
Operator restriction.

---

## 9. Help design (Module C)

- Content: `docs/help/*.md` (8 sections, English) rendered in-app by
  the existing Help window path (HTML conversion via a tiny
  markdown-lite renderer: headings, lists, code, bold — stdlib `re`
  only, no new dependency).
- Menu: `Help > User Guide / FAQ / About` (About = version + branch +
  build info from `gui_version`).
- Sections: Overview · Getting Started · Page Guide (one subsection
  per page) · Instruments & Connections · Test Items · Reports & Logs
  · FAQ/Troubleshooting · Security & Roles.
- Test: every section file exists, every page has a guide entry, the
  Help window opens and renders, FAQ covers the known-issues list
  (netlist "no nets found", connect failures, CSV log missing,
  credential problems).
