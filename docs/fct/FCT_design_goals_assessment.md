# FCT Design Goals and Gap Assessment

Date: 2026-11-24 · Tree: `develop = 56acf92` (m117 accepted) · Author: Mac-side
acceptance role.

This document fixes the four FCT design goals the owner set, restates each as a
measurable acceptance test, and scores the current tree against it. It is the
baseline for the next directives (m118 onward); it is not a plan for one
milestone.

## 1. The four goals (owner's wording, restated as acceptance tests)

| ID | Goal | Acceptance test (measurable) |
|---|---|---|
| G1 | Generality: the tool fits other boards, not only FRDM-IMX93 | A second board profile (any 10-row FCT) can be authored and run with **0 Python edits** and **≤ 1 engineer-day**, using the same GUI and YAML only |
| G2 | Low entry cost: someone who only knows manual serial commands must not take a wrong step | A fresh Windows machine with only the packaged exe: an engineer builds a 5-row FCT and reaches Run **without outside documentation**, asking **≤ 2 questions**, in **≤ 30 min** |
| G3 | No fake tests: every verdict rests on real evidence; no missed FAIL, no false PASS, no false FAIL | A 6-case fault battery (stale buffer text, unresolved token, wrong regex, silent DUT, truncated log, out-of-limit value) yields **6/6 correct verdicts**, and no row can report PASS without at least one matched evidence item |
| G4 | Efficiency: clearly faster than typing commands by hand, with sane durations | Manual baseline vs GUI on the same board: **≥ 3× faster end-to-end**; whole run **≤ 3 min**; every row's budget within **p95 of its last 10 measured durations** |

## 2. Scorecard

| Goal | Score | One-line verdict |
|---|---|---|
| G1 Generality | **4 / 10** | The engine is already board-agnostic, but the thing a new board actually needs (a project profile) is unversioned, unshipped, and only partly expressible without code |
| G2 Ease of use | **6 / 10** | A good wizard and a deep help set exist, but the recommended edit path is lossy today (45 → 38 rows) and prerequisites are discovered mid-run |
| G3 No fake tests | **7 / 10** | Judging is genuinely evidence-based now; two engine-level holes still allow a PASS by absence |
| G4 Efficiency | **7 / 10** | 45 rows in 3:44 is good, but budgets are stale defaults and the "≥ 3× vs manual" claim is still unmeasured |
| **Weighted** | **6.0 / 10** | Solid engine, weak onboarding surface |

## 3. G1 — Generality (4/10)

What is already right:

- The engine carries no board constants. `grep -rIn -E "FRDM-IMX93|imx93|i.MX93"
  mtkgui --include=*.py` returns 39 hits, of which 12 are demo asserts
  (`mtkgui/engine/demo_project.py`) and the rest are demos or comments; the only
  production default is `expected_name: "FRDM-IMX93-DUT"`
  (`mtkgui/engine/fct_test_config.py:54`).
- Board data lives in YAML: `equipment` (26 blocks incl. `daq973a`, `m908a_1/2`,
  `psu`, `fixture`, `dut`), `console`, `test_workflow.fct_test_cases`,
  `fct_test_config` — the right shape for a second board.
- There is a generic escape hatch: `Message` / `Console_cli` / message-check rows
  can express "send a command, judge the reply with a regex", so a board whose
  tests are CLI-driven needs data only.

What blocks a second board:

1. **No whole-project profile ships and none is versioned.** `projects/` is
   git-ignored (`.gitignore:101`) and `git ls-files projects` is empty. The
   package does ship an asset template (`assets/`, 15 files, incl. drivers /
   precheck / scripts) and three FCT *sequence* templates
   (`assets/templates/fct_linux.yaml` 113 lines, `fct_wifi_scan.yaml` 77,
   `fct_bare_metal.yaml` 36, loaded via `Load Template`,
   `mtkgui/gui/yamlbuild/FCTTestConfigWidget.py:1315`) — but no
   `equipment` / `console` / `design_input` profile. A new board still has to
   hand-copy an untracked project YAML from another machine.
2. **Step types are a closed enum.** `STEP_TYPE_LABELS`
   (`mtkgui/engine/fct_test_config.py:356-368`) lists 14 labels, 6 of them
   Wi-Fi/BT reference rows. A new test family (CAN, USB, audio, GPIO pattern…)
   needs code in `fct_exec.py` (`:1214` `fct_wifi_ping`, `:1223`
   `fct_wifi_iperf`, `:1238` `fct_bt_l2ping`, `:1249` `fct_rf`), a validator
   rule, and a Yaml Build menu entry.
3. **Command variables are a fixed table.** `_build_cmd_vars`
   (`mtkgui/engine/fct_test_runner.py:30`) substitutes exactly five tokens
   (`ssid`, `password`, `host_ip`, `bt_name`, `host_bt_addr`); any new per-board
   variable is a code edit.
4. **Validation is board-specific hygiene, not schema.** The 15 rules in
   `mtkgui/engine/yaml_validation.py` mostly retire old row types; nothing
   validates the *shape* a new board must satisfy.
5. **A generator script is the de facto onboarding path.** The untracked
   `scripts/build_frdm_imx93_yaml_v130.py` builds this board's YAML in Python —
   a new board would need its own such script, which contradicts "data only".

## 4. G2 — Ease of use (6/10)

What is already right:

- 17 help chapters (`docs/help/`), with `09_yaml_build.md` (734 lines),
  `16_example_fct.md` (318 lines, a real step-by-step) and `05_equipment.md`
  (278 lines).
- Equipment is a block diagram with per-block sub-windows; Yaml Build is a
  5-block wizard with gating (`GATING_CHAIN`) and a load-time validator.
- Three FCT sequence templates ship in the package (`assets/templates/`,
  `Load Template` in the Build FCT dialog), so a beginner starts from a working
  45-row-shaped skeleton instead of an empty table.

What still makes a beginner take a wrong step:

1. **The recommended edit path loses data.** `yaml_build_state.fct_test_cases`
   is empty in the shipped v1.3.1 file (measured: `test_workflow` 45 rows,
   `yaml_build_state` 0), so Yaml Build regenerates 38 rows from `fct_test_config`
   (m114, written, never executed). Opening and saving in Yaml Build silently
   drops the two flash rows, the OOBE pair and the log/cleanup tail.
2. **Two budget fields, one of them inert.** The UI shows `fct_step.timeout_s`;
   the engine reads `op_params.fct_step.params.args.timeout_s`. The iPerf fix
   only worked after editing the second one.
3. **Prerequisites are discovered mid-run.** Host BD address, host BLE thread,
   `iperf3 -s`, staged assets — none are checked before Run. In Run#23 those
   surfaced at rows 39-40 as ERROR.
4. **Deploy is an undocumented local ritual.** Assets live under
   `dist/work/.../assets_FRDM-IMX93`, are not in the repo, and the help chapter
   still tells the user to `scp` by hand (`docs/help/16_example_fct.md:203`).
   `Cleanup assets` then deletes what the next run needs.
5. **No "where am I / what next" state.** After loading YAML the GUI does not
   say which of the five blocks still need attention, nor which bench items are
   unconfigured.
6. **The shipped templates carry their own traps in prose.** The Linux template
   header has to warn that a "wait for login prompt" row times out when the DUT
   is already logged in (`assets/templates/fct_linux.yaml:5-12`) — a beginner
   reading only the GUI never sees that warning.

## 5. G3 — No fake tests (7/10)

What is already right:

- Judging is evidence-based: FAT rows parse `Overall result: PASS`
  (`fct_exec.py:282` `_fat_summary_outcome`), Wi-Fi RSSI judges only the reply to
  its own command (m116-A), iPerf compares measured Mbps against `min_mbps`, ICT
  compares numbers against limits.
- Stale text is largely excluded: the run-start clear pins every channel read
  offset (`_mark_channel`, `fct_exec.py:454`) and each command re-marks before
  writing (`:1259-1260`).
- Unknown host identity is refused rather than faked: an unresolved
  `{{host_bt_addr}}` makes the DUT print `BT_L2CAP_UNCONFIGURED` (m117-B).
- ERROR is distinct from FAIL, and stage rollup follows child verdicts (m116-C).
- 1168 engine tests guard the behaviour.

Remaining holes:

1. **A PASS by absence is still possible.** With `capture_is_expected: false`
   (`fct_exec.py:98`, `:325`) the executor skips `expect_pass_re` and returns
   PASS on a "clean window up to End Line" — nothing was matched, nothing was
   measured.
2. **No engine-level flush at step start.** Offsets are pinned, but a slowly
   echoed prompt from the *previous* command can still land inside the new
   step's window; the manual probe showed a 0.03 s FAIL on residual `fail`.
3. **No rule requires a judge.** None of the 15 validator rules rejects a row
   that has no `expect_pass_re`, no numeric limit, and no summary parser.
4. **Ignore is not auditable.** Run#23 had 6 Ignore rows; the report does not
   carry the per-row reason code, so "ignored" cannot be told apart from
   "skipped because misconfigured".
5. **No invariant test.** Nothing asserts "verdict PASS ⇒ ≥ 1 evidence item
   consumed" across the executor.

## 6. G4 — Efficiency (7/10)

Measured (Run#23, 2026-11-24, 45-row board):

| Item | Value |
|---|---|
| Whole run (46 rows) | **3:44** |
| FAT row | 2.8–19 s (ethernet download mode 19 s longest) |
| Wi-Fi connect | 15.86 s |
| Wi-Fi iPerf | 271.0 Mbps, budget 85 s |
| BT discoverable | 0.93 s |
| Deploy 1.24 MB @115200 | ≈ 217 s (one-off, and it is currently hidden) |

Why it is not yet "clearly faster, and stably so":

1. **Budgets are stale defaults** (60 s per FAT row, 90 s memtester, 600 s pull)
   rather than p95 of measured history; a mis-routed budget turns into a 120 s
   burn.
2. **The manual baseline was never measured**, so "≥ 3× faster" is an opinion,
   not a number. One timed manual run of a representative subset would settle it.
3. **Fixed sleeps and retry loops** (Wi-Fi connect 15.86 s) are not
   prompt-driven; detecting the shell prompt would cut seconds per row.
4. **No duration telemetry per row in the report**, so budgets cannot be
   calibrated from data.

## 7. Priority plan (proposal, not yet kicked to TRAE)

| Milestone | Serves | Content | Size |
|---|---|---|---|
| m118 | G2 + G3 | m114 restore-stored-list; one authoritative budget field; validator rules: row without judge = error, unresolved token = error, duplicate names = error; engine flush before each step; `capture_is_expected=false` may never PASS without a positive marker | M |
| m119 | G2 | Bench preflight panel: serial openable, PSU reachable, host BD address resolved, `iperf3 -s` listening, AP gateway pingable, staged assets md5 match; red blocks Run and links to the page that fixes it | M |
| m120 | G1 | Ship a tracked `templates/` project profile in the package; extensible command-token registry; promote a generic "command + judge (regex or numeric)" row so a new board needs data only | M/L |
| m121 | G4 | One timed manual baseline; per-row duration telemetry in the report; budget auto-suggestion from history | S |

Acceptance for the whole set is the four acceptance tests in §1, not a test
count.

## 8. Open decisions

1. **BT RSSI semantics.** Host-side BLE scan of the DUT's advertisement
   (measured −43…−55 dBm, but advertisement availability is intermittent), or
   wait for a BlueZ peer on the bench and judge link RSSI. The former needs a
   DUT advertise step; the latter needs hardware.
2. **Should `projects/` stay untracked?** A tracked `templates/` profile solves
   G1/G2 without shipping customer YAML; keeping the whole directory ignored
   keeps it unsolved.
3. **Code-free test kinds.** Is "any CLI test expressible in YAML" enough for
   the next board, or is a plugin/row-type registry required from the start?
