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

---

## 10. P3-B4 addendum: SSH file deployment (SFTP) + DUT driver prerequisite

### 10.1 SFTP file transfer (`SshFctChannel`, Module B addendum)

On top of message/command execution the SSH channel gains file
DEPLOYMENT via paramiko SFTP (no new dependency):

- `put_file(local_path, remote_path="")` — SFTP upload of one Host PC
  local file (Linux shell script / bin / app package) to the DUT.
  When `remote_path` is empty the file lands in the configured
  `remote_dir` under its own basename; when `remote_dir` is empty too,
  the login user's cwd is used.  An event line (`[sftp] put ...`)
  lands in the channel read buffer so the FCT judge and EventLog see
  the transfer.
- `get_file(remote_path, local_path)` — SFTP download for read-back
  verification (content comparison after upload).
- Configuration (product YAML `console.ssh`): `remote_dir` — the DUT
  target directory, e.g. `/tmp/` or `/home/root/`.
- Credentials: SFTP reuses the authenticated SSH transport; the
  password stays in the keyring credential layer (D4-A).  Nothing is
  ever stored in the YAML.

Typical deployment flow:

```
SSH connect -> sftp put (script / bin / app package, remote_dir)
           -> Console send ("sh /tmp/load_drivers.sh")
           -> read_lines() polls stdout/stderr + "[exit] N"
```

Mac verification baseline: connect the Mac's own sshd (Remote
Login), upload a test file into `/tmp/`, read it back and compare
content byte-for-byte.

### 10.2 DUT driver prerequisite (documentation note, NOT a dev task)

For Full Stack Linux DUTs (i.MX etc.): after boot, the Wi-Fi /
Bluetooth drivers MUST be loaded and ready BEFORE any RF test step
runs.  Loading is the BSP team's responsibility — either the kernel
auto-loads the modules at boot, or BSP ships a shell script (e.g.
`/home/root/load_wifi_bt.sh`).

mtk-gui does NOT implement any driver logic.  It only reserves the
ability to send the load command over the console (Console send, e.g.
`sh /tmp/load_drivers.sh`) and to judge the result through the
existing FCT keyword engine (Pass/Success vs Fail/Error).  The test
flow owner deploys the script via the SFTP flow in §10.1 and invokes
it as a regular FCT step.

### 10.3 P3-B4 real-machine acceptance record (macOS 15.5, 2026-10-09)

| Item | Mode | Result | Evidence |
|---|---|---|---|
| Serial (Module A) | socat pty pair | PASS 4/4 | normal tx/rx · timeout empty-read · 100-line burst 100/100 · disconnect ChannelClosed |
| SSH (Module B) | loopback sshd | PASS 6/6 | connect · stdout/stderr/exit framing · negative exit · SFTP put /tmp + read-back identical · same-path guard · upload+`sh` execute |
| Host CLI (Module C) | real commands | PASS 16/16 | sw_vers extract · df · ping loss% · negative exit · timeout kill · missing cmd · placeholder error · EventLog identity |
| Wi-Fi (Module D) | full_stack | PASS | home AP TP-LINK_F68E_AP: RSSI -47 dBm, ping 20/20 0% loss, gateway auto-discovered |
| Wi-Fi (Module D) | rssi_only | PASS | RSSI -50 dBm, zero connect commands issued |
| BT (Module E) | a2dp_sink | PASS | JBL Pulse 5 40-c1-f6-84-8f-c5: connect · is-connected exit 0 · RSSI -54 dBm · audio output switch · test tone · operator GUI_CONFIRM Pass · disconnect |
| BT (Module E) | rssi_only | PASS | pairing-mode inquiry hit + profiler RSSI -54 dBm, no connection |
| Platform switch (F) | unit | PASS | mac backend selected; windows `_todo` raises PlatformBackendMissing |

Full regression: 1431 passed / 3 skipped / 0 failed.

Operational findings baked into the design (verified on-site):

1. `networksetup -setairportnetwork` exits 0 even when the join fails
   ("Could not find network") — association MUST be confirmed by
   polling the RSSI source (`_wait_associated`), the exit code is not
   evidence.
2. iPhone hotspot broadcasting is intermittent; a hotspot may vanish
   from scans while its page is open.  Production DUTs (own AP) do
   not have this issue.
3. macOS auto-rejoin restores removed preferred networks on its own;
   re-adding a WPA network without its password fails (-3905) and is
   logged as a warning only.
4. `switchaudio-osx -s <name>` sets the output device by name
   (`-n` cycles to the NEXT device — not a name selector).
5. BT-classic devices are discoverable only in pairing mode; the
   rssi_only step therefore expects the DUT to advertise (bare-metal
   BLE) or the operator to put it into pairing mode.
6. SFTP `put` with identical local/remote path truncates the source
   (remote write handle opens after the local read handle) — guarded
   with an explicit error in `put_file`.

### 10.4 iperf3 throughput step (addendum, 2026-10-09)

- WifiAdapter gains a real iperf3 step: product YAML sets
  `iperf3: true` (+ optional `iperf_timeout_s`), commands provide
  `iperf_cmd: 'iperf3 -c {{ip}} -t 10 -O 2'` ({{ip}} injected from
  test vars = the DUT address running `iperf3 -s`).
- Throughput is parsed from the RECEIVER summary line; iperf3
  auto-scales the unit, so M/Gbits/sec are normalised to Mbits/sec
  (`iperf_parse` overridable, default
  `([\d.]+)\s+([MG])bits/sec\s+(?:\d+\s+\S+\s+)?receiver`).
- Informational item (`throughput` in the report items); the
  PASS/FAIL gate stays RSSI + ping loss.
- Real verification: full_stack run on TP-LINK_F68E_AP with an
  iperf3 server on the host (loopback) returned
  Pass {rssi: -52, loss_pct: 0.0, throughput: 48200.0}.  Loopback
  validates the command/parse/report chain; a meaningful Wi-Fi
  throughput figure requires the server on the real DUT.
- Unit tests: receiver-line extraction (not intermediate rows) and
  disabled-by-default behaviour (14/14 adapter tests green).

Real Wi-Fi throughput (TP-LINK_F68E_AP, server on a Windows PC):
uplink 30.4 / downlink 31.7 Mbits/sec with RSSI -48 dBm and 0% ping
loss - FULL_STACK Pass.  BOTH endpoints were wireless, so the AP
airtime is shared and the figure reflects the bottleneck, not the
station's capability; the production form is wireless DUT vs WIRED
host PC.  (Also observed: the Windows host drops ICMP echo by
firewall default while iperf3 TCP succeeds - joint exit-code/TCP
judging handles this.)

---

## 11. Console command model v2 (P3-B5 refinement, SIGNED design)

ALL FCT test commands are built from THREE primitives (user-signed):

1. **ConsoleWait**  — wait for an expected message (regex) within
   timeout; on match, IMMEDIATELY proceed to the next command.
   Timeout -> FAIL ("TIMEOUT waiting for ...").  No send.
2. **ConsoleSend**  — send one OR MULTIPLE lines to the DUT console
   (newline policy per console config: lf/crlf).  Fire-and-forget:
   verdict is Done/PASS ("sent") — judgement is the FOLLOWING
   ConsoleCapture's job.
3. **ConsoleCapture** — capture the output AFTER a ConsoleSend.
   For Linux DUTs the output may interleave with OTHER processes'
   output (weak real-time behaviour) — the capture scans the
   ACCUMULATED stream, so interleaved noise is tolerated.  Judged by
   an expected message and/or an UNEXPECTED message (fail-wins);
   timeout -> FAIL.  Regex capture-groups may feed the variable store
   (`extract`, referenced by later commands via {{var}}).

Login becomes an ordinary Wait/Send/Wait chain (no separate
login_sequence section):

    Wait "login:" -> Send "root" -> Wait "Password:" ->
    Send "" -> Wait "root@imx93frdm"

Each row carries `transport: serial | ssh` (serial default; ssh for
unstable links and SFTP file transfer rows: action sftp_put/sftp_get
with local/remote paths — B4 SshFctChannel).  Console config gains:
newline (lf|crlf), inter_cmd_delay_ms, per-row timeout override.
Variable store is shared across rows and rendered via {{var}}.

YAML row shape (test_commands, ordered):

    - {kind: wait,    name: Login,  expect_pass: "login:", timeout: 5}
    - {kind: send,    name: User,   send: root}
    - {kind: capture, name: Kernel, expect_pass: "Linux imx93frdm",
       expect_fail: "", timeout: 5, extract: "ip=(\\d+\\.\\d+\\.\\d+\\.\\d+)"}
    - {kind: send,    name: Ping,   send: "ping -c 3 {{ip}}"}

Engine mapping (all three are fct_console MESSAGE_CHECK steps):
wait -> _regex_capture (no send); send -> channel.write, PASS "sent";
capture -> send optional? NO (pure capture) — the preceding Send row
already wrote; _regex_capture judges the accumulated stream.
Legacy parity: SendtoConsole / WaitforConsole / CapturefromConsole.

dut_type gating (P3-B5): linux = full set (Wait/Send/Capture +
DUT-side ping/iperf/l2ping/piscan steps); bare_metal = Wait/Capture
only (no shell; firmware output capture + optional firmware command
Send rows), Wi-Fi/BT host-side.
