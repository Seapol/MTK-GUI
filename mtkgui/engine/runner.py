# -*- coding: utf-8 -*-
"""Test flow runner - the run state machine (mtkgui.engine.TestRunner).

Extracted verbatim from mtkgui.test_workflow_page.py (task T2, pure
extraction + API, no behavior change): ICT/FCT/op step execution, the
100 ms run timer with per-step Wait/Timeout handling, the pre-FCT
console connect step, Virtual-mode console/RF steps, the power-rails
capture row, stop strategies ("Stop if failure" / "Stop if any
short"), Long Run cycles, result rollup and the abort paths.

Contract (docs/interface_spec.md §3):
  * signals: step_started(int), step_finished(int, StepResult),
    run_finished(dict summary), plus the page bridge signals
    cycle_reset() / stage_skipped(int, str).
  * control: start(lr_total), abort(), run_demo(), reset_results().

The runner is UI-free. It reaches the live run-control data through
the "RunnerEnv" bridge implemented by the workflow page (and by the
headless demo environment): steps / enables / waits / rails / rack /
multi_console plus the rendering hooks _render_step, _store_rail_capture,
_log, _set_phase, ...  Real-mode instrument access goes through the
optional env.gateway (mtkgui.engine.instruments.RealGateway); Virtual
mode keeps the VirtualRack; without both the legacy placeholder
verdicts are kept (no behavior change).
"""
from __future__ import annotations

import random
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .failures import FailureKind, classify_exception, failure_log_line
from .policies import normalize_retry_count, policy_abort_reason, rollup
from .rails import ai_wave_review
from .results import StepResult, StepStatus
from .steps import (
    CONSOLE_KINDS,
    console_keyword_fallback,
    display_text,
    is_impedance_short,
    meas_instrument_abbr,
    op_instrument_abbr,
    op_status_lines,
    parse_console_step,
)

# display text -> StepStatus (inverse of steps.display_text)
_STATUS_TO_ENUM = {
    "PASS": StepStatus.PASS, "Done": StepStatus.PASS,
    "FAIL": StepStatus.FAIL, "Error": StepStatus.ERROR,
    "Ignore": StepStatus.IGNORED, "RUNNING": StepStatus.RUNNING,
}


class TestRunner(QObject):
    """Executes one test cycle: the step list produced by the page's
    _steps_template / the headless sequence template."""

    # --- interface_spec.md §3 signals ---
    step_started = Signal(int)                  # step index
    step_finished = Signal(int, object)         # step index + StepResult
    run_finished = Signal(dict)                 # summary report
    # --- page bridge signals (rendering side effects) ---
    cycle_reset = Signal()
    stage_skipped = Signal(int, str)            # stage row + log text

    def __init__(self, env):
        super().__init__(env if isinstance(env, QObject) else None)
        self.env = env
        # run-control state machine (P1 standardization):
        #   idle    ready to start
        #   running cycle in progress
        #   paused  operator pause: checkpoint kept, resumable
        #   aborted operator terminate: run ended, IGNORE result
        #   frozen  safety freeze: unexpected error / intervention
        # Terminal states (aborted / frozen) must be reset back to idle
        # (reset_state / start auto-reset) before a new run can start.
        self.state = "idle"
        self._pause_requested = False
        self._interrupted = False
        self._timeout_retried = False
        self._wait_done = False
        self._run_steps: list[tuple] = []
        self._run_index = 0
        # pre-FCT console connect step ("fctconn"): open every console
        # channel the project YAML defines. The worker threads run in
        # the background, so the step polls until they are up or the
        # timeout (seconds) elapses.
        self.fct_connect_timeout = 10.0
        self._fctconn_pending: list[str] = []
        self._fctconn_failed: list[str] = []
        self._fctconn_deadline = 0.0
        # pending FCT console step (Virtual mode): the step sent its
        # command / armed its keyword wait on the simulated DUT and the
        # run timer polls the channel read buffer until a keyword shows
        # up or the step timeout elapses
        self._fct_console_wait: dict | None = None
        # FCT message tests open a modal operator dialog during a real
        # run; the run timer keeps ticking (100 ms) and must not
        # re-enter _run_step while the dialog is open
        self._fct_dialog_open = False
        # long run: repeat whole cycles with a pause in between
        self._lr_total = 1
        self._lr_done = 0
        self._run_start = 0.0
        self._stage_start = 0.0
        # per-step verdict tracking for the engine-side result rollup
        # (replaces reading the UI table cells)
        self._results: dict[tuple, str] = {}
        self._measured: dict[tuple, object] = {}
        self._run_timer = QTimer(self)
        self._run_timer.setInterval(100)  # one test step every 100 ms
        self._run_timer.timeout.connect(self._run_step)
        self._lr_wait_timer = QTimer(self)
        self._lr_wait_timer.setSingleShot(True)
        self._lr_wait_timer.timeout.connect(self._start_next_cycle)
        # basic fault-policy retry: 0 = off (legacy behavior).  Set via
        # set_retry(count, source) so the parameter stays normalized and
        # its origin stays traceable (default / yaml / cli)
        self.retry_count = 0
        self.retry_source = "default"

    def set_retry(self, count, source: str = "default") -> None:
        """Configure the basic fault-policy retry (spec §3).

        The count is normalized through the single clamping entry point
        (policies.normalize_retry_count: non-negative integer, invalid
        input -> 0) and the configuration source is recorded so every
        run start can trace where the setting came from."""
        self.retry_count = normalize_retry_count(count)
        self.retry_source = str(source)

    # ------------------------------------------------- state machine (P1)
    # strictly legal transitions; anything else raises RuntimeError so
    # no illegal state flow can leave residual state behind
    _LEGAL_TRANSITIONS = {
        "idle": {"running"},
        "running": {"paused", "aborted", "frozen", "idle"},
        "paused": {"running", "aborted", "frozen", "idle"},
        "aborted": {"idle"},
        "frozen": {"idle"},
    }

    def _transition(self, new_state: str, trigger: str) -> None:
        """Move to new_state via the legal-transition table and leave a
        structured, traceable log line (state change + trigger)."""
        legal = self._LEGAL_TRANSITIONS.get(self.state, set())
        if new_state not in legal:
            raise RuntimeError(
                f"illegal state transition: {self.state} -> {new_state}")
        old = self.state
        self.state = new_state
        self.env._log(f"[STATE] {old} -> {new_state} (trigger={trigger})")

    @property
    def can_start(self) -> bool:
        """True when start() may begin a run from the current state."""
        return self.state in ("idle", "aborted", "frozen")

    def pause(self) -> None:
        """Operator pause: takes effect at the next step boundary (a
        safe checkpoint).  The checkpoint is the run index itself: no
        completed step is re-executed and no collected result is lost."""
        if self.state != "running":
            raise RuntimeError(
                f"pause requires state 'running' (got '{self.state}')")
        self._pause_requested = True
        self._run_timer.stop()      # stop further scheduling
        self.env._log("Pause requested -> takes effect at the next "
                      "step boundary")

    def resume(self) -> None:
        """Continue a paused run from the stored checkpoint (no cycle
        reset, no re-execution of finished steps)."""
        if self.state != "paused":
            raise RuntimeError(
                f"resume requires state 'paused' (got '{self.state}')")
        self._pause_requested = False
        self._transition("running", "operator")
        self._run_timer.start()

    def freeze(self, reason: str = "unexpected error") -> None:
        """Safety freeze: park the engine in a stable, non-running
        state without losing collected data (no dangling timers or
        pending waits).  Used for unexpected exceptions and manual
        intervention; reset_state() / start() unfreezes."""
        if self.state not in ("running", "paused"):
            return
        self._run_timer.stop()
        self._lr_wait_timer.stop()
        self._fct_console_wait = None
        self._pause_requested = False
        self._transition("frozen", "system")
        self.env._log(f"Engine frozen: {reason}")
        self.run_finished.emit(
            {"reason": "stop", "progress": False, "total": 0,
             "cycle_s": time.monotonic() - self._run_start,
             "reset_phase": True, "remaining": [], "counted": False})

    def reset_state(self) -> str:
        """Roll a terminal / paused engine back to 'idle' (results and
        logs are kept; the next start() opens a fresh cycle)."""
        if self.state == "idle":
            return "idle"
        self._run_timer.stop()
        self._lr_wait_timer.stop()
        self._fct_console_wait = None
        self._pause_requested = False
        self._transition("idle", "reset")
        return self.state

    # ------------------------------------------------------------ result
    def reset_results(self) -> None:
        """Clear the engine-side verdict tracking (clear_results)."""
        self._results.clear()
        self._measured.clear()

    def verdict(self) -> str | None:
        """Overall Result rollup: "FAIL" if any non-ignored step
        FAIL/ERROR, "PASS" if any step judged good, None when nothing
        judged yet (policies.rollup)."""
        return rollup(self._results)

    def _put(self, kind: str, row: int, status, measured=None,
             duration: float | None = None) -> None:
        """Render one step result through the env and track it."""
        key = (kind, row)
        if isinstance(status, StepStatus):
            hint = self._kind_hint(kind, row)
            self._results[key] = display_text(status, hint)
        else:  # legacy verdict string ("PASS"/"Done"/"FAIL"/"Error")
            self._results[key] = status
        if measured is not None:
            self._measured[key] = measured
        self.env._render_step(kind, row, status, measured, duration)

    def _kind_hint(self, kind: str, row: int) -> str:
        """"op" for operation steps (they display "Done" on success)."""
        env = self.env
        try:
            if kind == "ict":
                return "op" if env.ict_steps[row][0] == "op" else ""
            if kind == "fct":
                k = env.fct_kinds[row] if row < len(env.fct_kinds) else ""
                return "op" if k == "op" else ""
        except (IndexError, KeyError, TypeError):
            return ""
        return ""

    def _step_result(self, kind: str, args: tuple) -> StepResult:
        """Build the StepResult payload for the step_finished signal."""
        if not args:
            return StepResult(status=StepStatus.PASS)
        key = (kind, args[0])
        text = self._results.get(key, "")
        return StepResult(
            status=_STATUS_TO_ENUM.get(text, StepStatus.RUNNING),
            measured=self._measured.get(key),
            duration_s=max(0.0, time.monotonic()
                           - getattr(self, "_step_t0", self._run_start)),
            message=text)

    def _step_label(self, kind: str, row: int) -> str:
        """Human-readable step name for log lines."""
        env = self.env
        try:
            if kind == "ict":
                return env.ict_steps[row][1]
            if kind == "fct":
                return env.fct_rows[row]
        except (IndexError, TypeError):
            pass
        return f"{kind}#{row}"

    def _exec_with_retry(self, kind: str, args: tuple,
                         interactive: bool | None = None) -> None:
        """Execute one step; on FAIL/ERROR re-execute it up to
        ``retry_count`` times (basic fault-policy retry, default 0 =
        off).  Retry happens BEFORE the stop policies are evaluated, so
        a step that recovers never aborts the run; if the operator
        aborted during the step (e.g. Stop pressed while a message
        dialog was open) no retry is made."""
        retries = normalize_retry_count(
            getattr(self, "retry_count", 0) or 0)
        attempt = 0
        while True:
            if kind == "ict":
                self._exec_ict_row(args[0])
            elif kind == "fct":
                if interactive is None:
                    self._exec_fct_row(args[0])
                else:
                    self._exec_fct_row(args[0], interactive=interactive)
            else:
                self._complete_stage(args[0])
            if (attempt >= retries or self._interrupted
                    or self._step_result(kind, args).status
                    not in (StepStatus.FAIL, StepStatus.ERROR)):
                return
            attempt += 1
            self.env._log(
                f"{self._step_label(kind, args[0])} -> FAIL/ERROR "
                f"(attempt {attempt - 1}) -> Retry {attempt}/{retries}")

    # ------------------------------------------------------- op helpers
    def _run_op(self, tag: str, name: str, params: dict | None) -> str:
        """Execute one standard operation step; returns "Done"/"Error".

        Virtual mode drives the simulated rack (flash steps run
        engine-side in every mode); Real mode goes through the
        optional RealGateway; otherwise the legacy placeholder lines
        are logged (no behavior change)."""
        env = self.env
        gw = getattr(env, "gateway", None)
        is_flash = (params or {}).get("type") == "flash"
        if is_flash:
            if gw is not None:
                out = gw.execute_op(name, params)
            else:  # engine-side simulated flash (virtual / legacy)
                out = None
        elif env.rack is not None:
            m = env.rack.execute_op(name, params)
            for line in m.lines:
                env._log(f"{tag} op {name}: {line}")
            if m.verdict == "Error":
                env._instrument_error(op_instrument_abbr(params))
                return "Error"
            env._log(f"{tag} op {name}: Done")
            return "Done"
        elif gw is not None:
            out = gw.execute_op(name, params)
        else:
            out = None
        if is_flash and out is None:
            out = _SimulatedOutcome(op_status_lines(name, params))
        if out is not None:
            for line in out.lines:
                env._log(f"{tag} op {name}: {line}")
            if getattr(out, "verdict", "Done") == "Error":
                env._instrument_error(op_instrument_abbr(params))
                return "Error"
        env._log(f"{tag} op {name}: Done")
        return "Done"

    # ------------------------------------------------------ ICT staging
    def _exec_ict_row(self, r: int) -> None:
        """Execute one ICT test-case row.

        Virtual mode drives the simulated rack: op steps move the
        fixture / PSU state machines, measurement rows receive
        stochastic instrument readings judged against the YAML limits,
        and the DAQ AI row captures the power-rails up sequence.  Rows
        flagged through the context menu (ict_sim_fail) force a FAIL.
        Real mode goes through the optional instrument gateway; without
        a gateway the legacy placeholder verdict is kept until the
        instrument bring-up is complete."""
        env = self.env
        env._fill_ict_row(r, placeholder=False)
        env._highlight_step("ict", r)
        step = env.ict_steps[r]
        kind, name = step[0], step[1]
        unit, measured, lo, hi = step[2], step[3], step[4], step[5]
        params = step[6] if len(step) > 6 else None

        if kind == "DAQ AI":
            # power rails up sequence: samples (volts) + CSV + AI review
            self._exec_rail_capture_row(r)
            return

        if kind == "op":
            status = self._run_op("ICT", name, params)
            self._put("ict", r,
                      StepStatus.PASS if status == "Done"
                      else StepStatus.ERROR)
            return

        # ------------------------------------------------ measurement rows
        gw = getattr(env, "gateway", None)
        if env.rack is not None:
            force = "FAIL" if r in env.ict_sim_fail else None
            m = env.rack.measure_row(kind, name, unit, lo, hi, force=force)
            for line in m.lines:
                env._log(f"ICT {name}: {line}")
            if m.verdict == "Error":
                self._put("ict", r, StepStatus.ERROR, m.text)
                env._instrument_error(meas_instrument_abbr(kind, name))
            else:
                self._put("ict", r, StepStatus.PASS
                          if m.verdict == "PASS" else StepStatus.FAIL,
                          m.text)
            return
        if gw is not None:
            force = "FAIL" if r in env.ict_sim_fail else None
            out = gw.measure_row(kind, name, unit, lo, hi, force=force)
            for line in out.lines:
                env._log(f"ICT {name}: {line}")
            if out.verdict == "Error":
                self._put("ict", r, StepStatus.ERROR, out.text)
                env._instrument_error(meas_instrument_abbr(kind, name))
            else:
                self._put("ict", r, StepStatus.PASS
                          if out.verdict == "PASS" else StepStatus.FAIL,
                          out.text)
            return

        # legacy placeholder path (Real mode, instrument drivers pending)
        if r in env.ict_sim_fail:
            if is_impedance_short(step):
                self._put("ict", r, StepStatus.FAIL, "0.62")
                env._log(f"ICT {name}: 0.62 OHM below 1.5 OHM (short "
                         f"risk) -> FAIL")
            else:
                self._put("ict", r, StepStatus.FAIL)
                env._log(f"ICT {name}: {measured} {unit} out of limit "
                         f"({lo}..{hi}) -> FAIL")
            return
        fault = env._virtual_fault_roll()
        if fault == "Error":
            self._put("ict", r, StepStatus.ERROR)
            env._instrument_error("DAQM")
            env._log(f"ICT {name}: random equipment / serial fault "
                     f"(virtual) -> Error")
        elif fault == "FAIL":
            self._put("ict", r, StepStatus.FAIL)
            env._log(f"ICT {name}: {measured} {unit} out of limit "
                     f"({lo}..{hi}) (virtual fail) -> FAIL")
        else:
            self._put("ict", r, StepStatus.PASS)
            env._log(f"ICT {name}: {measured} {unit} "
                     f"(threshold {lo}..{hi}) -> PASS")

    def _exec_rail_capture_row(self, r: int) -> None:
        """Power-rails up-sequence capture (the ICT 'DAQ AI' row).

        The virtual U2355A acquires every rail in volts (CSV + AI
        review, plot stays hidden during a run).  A test-fail fault
        corrupts one rail so the AI review flags it; an equipment fault
        aborts the acquisition."""
        env = self.env
        name = env.ict_steps[r][1]
        if not env.rails:
            self._put("ict", r, StepStatus.ERROR)
            env._instrument_error("DAQ")
            env._log(f"ICT {name}: no rails defined (load a project "
                     f"YAML first) -> Error")
            return
        force = "FAIL" if r in env.ict_sim_fail else None
        if env.rack is not None:
            frac, volts, anomaly = env.rack.capture_rails(
                env.rails, env.cap_start, env.cap_end, env.cap_rate,
                force=force)
            if anomaly == "error":
                self._put("ict", r, StepStatus.ERROR)
                env._instrument_error("DAQ")
                env._log(f"ICT {name}: U2355A AI acquisition error "
                         f"(virtual) -> Error")
                return
            rail_samples, rail_volts = frac, volts
        else:
            rail_samples, rail_volts = env._generate_rail_samples()
            anomaly = None
        plot_cache = env._rail_plot_data(rail_samples)
        tag = " (virtual)" if env.virtual_mode else ""
        if env.csv_export:
            path = env._write_csv(rail_samples, rail_volts)
            # grade the CURRENT capture (page state is stored below)
            review = ai_wave_review(env.rails, rail_samples,
                                    env.cap_start, env.cap_end,
                                    env.cap_rate, env.virtual_mode)
            rpath = path.with_name(path.stem + "_ai_review.txt")
            try:
                rpath.write_text(review, encoding="utf-8")
                saved = (f"CSV saved ({path.name}), "
                         f"AI review ({rpath.name})")
            except OSError:
                saved = f"CSV saved ({path.name}), AI review save failed"
        else:
            path = None
            review = ai_wave_review(env.rails, rail_samples,
                                    env.cap_start, env.cap_end,
                                    env.cap_rate, env.virtual_mode)
            saved = "display only, CSV export off"
        env._store_rail_capture(rail_samples, rail_volts, plot_cache,
                                path, review)
        n = len(env.rails)
        if anomaly:
            self._put("ict", r, StepStatus.FAIL)
            env._log(f"ICT {name}: {n} rails captured{tag}, {saved}; "
                     f"AI review flags '{anomaly}' (abnormal waveform, "
                     f"virtual fail) -> FAIL")
        else:
            self._put("ict", r, StepStatus.PASS)
            env._log(f"ICT {name}: {n} rails captured{tag}, {saved} "
                     f"-> PASS")

    # ------------------------------------------------------ FCT staging
    def _exec_fct_row(self, r: int, interactive: bool = True) -> None:
        """Execute one FCT test case row.

        interactive=True (Run button): the MessageOK / MessageYesNo /
        MessageGoStop methods pop a modal operator dialog and the
        operator's answer judges the row.  interactive=False (Run Demo
        / smoke test): the operator answer is simulated (PASS); the
        sim-fail context-menu hook and the Virtual fault injection
        still apply.  Real mode routes WIFI / Bluetooth rows through
        the optional RF test drivers (gateway)."""
        env = self.env
        env._highlight_step("fct", r)
        t0 = time.monotonic()
        name = env.fct_rows[r] if r < len(env.fct_rows) else ""
        kind = (env.fct_kinds[r] if r < len(env.fct_kinds) else "")
        if kind == "op":
            # standard operation step: move fixture / PSU state, log
            # every sub-action, Done or Error (equipment fault)
            params = (env.fct_op_params[r]
                      if r < len(env.fct_op_params) else None)
            verdict = self._run_op("FCT", name, params)
            self._put("fct", r,
                      StepStatus.PASS if verdict == "Done"
                      else StepStatus.ERROR,
                      None, time.monotonic() - t0)
            return
        verdict = None
        if r in env.fct_sim_fail:
            verdict = "FAIL"
            env._log(f"FCT {name}: expected pass marker not found -> FAIL")
        elif (interactive and env.virtual_mode
                and kind in CONSOLE_KINDS + ("WIFI", "Bluetooth")):
            # Virtual mode: console / RF methods run for real against
            # the simulated DUT behind the virtual serial channel
            self._exec_fct_console(r, kind, name, t0)
            return
        elif (not env.virtual_mode
                and getattr(env, "gateway", None) is not None
                and kind in ("WIFI", "Bluetooth")):
            # Real mode: RF connectivity test via the T1 RF drivers
            cfg = (env.fct_op_params[r]
                   if r < len(env.fct_op_params) else None)
            out = env.gateway.rf_test(kind, name, cfg)
            for line in out.lines:
                env._log(line)
            if out.verdict == "Error":
                env._instrument_error("DAQ")
            self._put("fct", r,
                      StepStatus.PASS if out.verdict == "PASS"
                      else StepStatus.FAIL if out.verdict == "FAIL"
                      else StepStatus.ERROR,
                      out.text, time.monotonic() - t0)
            return
        elif interactive and kind in ("MessageOK", "MessageYesNo",
                                      "MessageGoStop"):
            verdict = env._fct_message_dialog(kind, name)
        if verdict is None:
            fault = env._virtual_fault_roll()
            if fault == "Error":
                verdict = "Error"
                env._instrument_error(random.choice(("DAQ", "PSU")))
                env._log(f"FCT {name}: random equipment / serial fault "
                         f"(virtual) -> Error")
            elif fault == "FAIL":
                verdict = "FAIL"
                env._log(f"FCT {name}: unexpected reply (virtual fail) "
                         f"-> FAIL")
            else:
                verdict = "PASS"
                if kind in ("MessageOK", "MessageYesNo", "MessageGoStop"):
                    env._log(f"FCT {name}: operator confirmed -> PASS")
                elif r < 5:
                    env._log(f"FCT {name}: output contained 'Pass' "
                             f"-> PASS")
                else:
                    env._log(f"FCT {name}: operator confirmed PASS")
        self._put("fct", r,
                  StepStatus.PASS if verdict == "PASS"
                  else StepStatus.FAIL if verdict == "FAIL"
                  else StepStatus.ERROR,
                  None, time.monotonic() - t0)

    # ------------------------------------------------ FCT console (virtual)
    def _pick_serial_channel(self):
        """First connected serial console channel (the simulated DUT
        lives there); None when no serial channel is online."""
        mc = self.env.multi_console
        for key, ch in mc.channels.items():
            if ch["kind"] == "serial" and mc.channel_connected(key):
                return key
        return None

    def _exec_fct_console(self, r: int, kind: str, name: str,
                          t0: float) -> None:
        """Execute one FCT console-method step against the simulated
        DUT (Virtual mode).  The step parameters are embedded in the
        name: SendtoConsole / SendtoCLI send the first quoted segment
        as a command line, WaitforConsole / WaitforCLI poll the channel
        read buffer for the quoted keyword(s) (any match -> PASS), and
        CapturefromConsole / CapturefromCLI search the whole buffer at
        once.  Random Virtual faults arm the DUT: equipment error ->
        no reply (timeout with no bytes -> Error), test fail -> a reply
        without the expected keyword (-> FAIL)."""
        env = self.env
        quotes, rest = parse_console_step(name)
        # WIFI / Bluetooth rows exercise the same simulated CLI path
        # with the standard RF test commands and Pass/Success markers
        if kind == "WIFI" and not quotes:
            kind = "SendtoCLI"
            name = 'SendtoCLI: "wifi_test --scan"'
            quotes = ["wifi_test --scan", "Pass", "Success"]
        elif kind == "Bluetooth" and not quotes:
            kind = "SendtoCLI"
            name = 'SendtoCLI: "bt_test --scan"'
            quotes = ["bt_test --scan", "Pass", "Success"]
        mc = env.multi_console
        key = self._pick_serial_channel()

        def finish(verdict: str, log: str) -> None:
            self._put("fct", r, verdict, None, time.monotonic() - t0)
            env._log(log)

        if key is None:
            finish("Error", f"FCT {name}: no connected serial console "
                            f"channel -> Error")
            return
        worker = mc.channels[key]["worker"]
        timeout_ms = (env.fct_timeouts[r]
                      if r < len(env.fct_timeouts) else 5000)

        if kind == "SendtoConsole":
            # send only: the step passes when the payload was written
            fault = env._virtual_fault_roll()
            if fault == "Error":
                finish("Error", f"FCT {name}: random serial fault "
                                f"(virtual) -> Error")
                return
            payload = (quotes[0] if quotes
                       else console_keyword_fallback(rest))
            payload = payload.strip().strip("'\"").strip()
            if payload:
                mc.write_to_channel(key,
                                    (payload + "\r\n").encode("utf-8"))
            finish("PASS", f"FCT {name}: sent '{payload}' to the "
                           f"simulated DUT -> PASS")
            return

        if kind == "SendtoCLI":
            fault = env._virtual_fault_roll()
            if fault == "Error":
                worker.inject_fault("no_response")
            elif fault == "FAIL":
                worker.inject_fault("wrong_reply")
            payload = (quotes[0] if quotes
                       else rest.split(",")[0].strip())
            payload = payload.strip().strip("'\"").strip()
            keywords = [q for q in quotes[1:] if q]
            from_len = len(mc.get_read_buffer(key))
            if payload:
                mc.write_to_channel(key,
                                    (payload + "\r\n").encode("utf-8"))
            env._log(f"FCT {name}: sent '{payload}', waiting for "
                     f"{' / '.join(keywords) or 'a reply'} ...")
            self._fct_console_wait = {
                "row": r, "key": key, "name": name,
                "keywords": keywords, "from_len": from_len,
                "t0": t0,
                "deadline": time.monotonic()
                + max(0.1, timeout_ms / 1000.0),
            }
            self._put("fct", r, StepStatus.RUNNING)
            return

        if kind in ("WaitforConsole", "WaitforCLI"):
            # search the whole accumulated buffer: the boot log may
            # already contain the expected keyword
            fault = env._virtual_fault_roll()
            if fault == "Error":
                finish("Error", f"FCT {name}: random serial fault "
                                f"(virtual) -> Error")
                return
            if fault == "FAIL":
                finish("FAIL", f"FCT {name}: expected keyword never "
                               f"observed in the console output "
                               f"(virtual fail) -> FAIL")
                return
            keywords = [q for q in quotes if q]
            if not keywords:
                fallback = console_keyword_fallback(rest)
                keywords = [fallback] if fallback else []
            env._log(f"FCT {name}: waiting for "
                     f"{' / '.join(keywords) or 'output'} ...")
            self._fct_console_wait = {
                "row": r, "key": key, "name": name,
                "keywords": keywords, "from_len": 0,
                "t0": t0,
                "deadline": time.monotonic()
                + max(0.1, timeout_ms / 1000.0),
            }
            self._put("fct", r, StepStatus.RUNNING)
            return

        # CapturefromConsole / CapturefromCLI: instant buffer capture
        fault = env._virtual_fault_roll()
        if fault == "Error":
            finish("Error", f"FCT {name}: random serial/equipment fault "
                            f"(virtual) -> Error")
            return
        keywords = [q for q in quotes if q]
        if not keywords:
            fallback = console_keyword_fallback(rest)
            keywords = [fallback] if fallback else []
        text = mc.get_read_buffer(key).decode("utf-8", "replace")
        healthy = (not keywords) or any(k in text for k in keywords)
        if fault == "FAIL":
            healthy = False
        if healthy:
            finish("PASS", f"FCT {name}: buffer contains "
                           f"{' / '.join(keywords)} -> PASS")
        else:
            expect = " / ".join(keywords) or "the expected output"
            finish("FAIL", f"FCT {name}: buffer does not contain "
                           f"{expect} -> FAIL")

    def _poll_fct_console(self) -> None:
        """Poll the pending console step: finish as soon as one of the
        keywords shows up in the channel read buffer, or judge
        Error (no reply at all) / FAIL (reply without the keyword) on
        timeout."""
        w = self._fct_console_wait
        if self.state != "running":
            self._fct_console_wait = None
            return
        mc = self.env.multi_console
        if w["key"] not in mc.channels:
            self._finish_console_wait(
                "Error", f"FCT {w['name']}: console channel removed "
                         f"-> Error")
            return
        buf = mc.get_read_buffer(w["key"])
        text = buf[w["from_len"]:].decode("utf-8", "replace")
        if w["keywords"] and any(k in text for k in w["keywords"]):
            self._finish_console_wait(
                "PASS", f"FCT {w['name']}: found "
                        f"{' / '.join(w['keywords'])} -> PASS")
            return
        if time.monotonic() < w["deadline"]:
            return  # keep waiting
        if len(buf) - w["from_len"] == 0:
            self.env._instrument_error("DAQ")
            self._finish_console_wait(
                "Error", f"FCT {w['name']}: timeout, no reply from the "
                         f"DUT -> Error")
        else:
            expect = " / ".join(w["keywords"]) or "the expected output"
            self._finish_console_wait(
                "FAIL", f"FCT {w['name']}: timeout, reply without "
                        f"{expect} -> FAIL")

    def _finish_console_wait(self, verdict: str, log: str) -> None:
        """Finalize the pending console step (verdict + duration)."""
        w = self._fct_console_wait
        self._fct_console_wait = None
        if w is None:
            return
        self._put("fct", w["row"], verdict, None,
                  time.monotonic() - w["t0"])
        self.env._log(log)

    # -------------------------------------------------- console connect
    def _fct_connect_targets(self) -> list[str]:
        """Console channels that must be connected before the FCT stage:
        the channels defined by the loaded project YAML (fallback: every
        channel with an endpoint configured) that are still offline."""
        mc = self.env.multi_console
        keys = mc.yaml_channel_keys()
        if keys is None:
            keys = [k for k in mc.channels if mc.channel_endpoint(k)]
        return [k for k in keys if not mc.channel_connected(k)]

    def _run_fct_connect_step(self) -> None:
        """("fctconn",) step: make sure every console channel from the
        project YAML is connected before FCT starts. Channels the user
        connected manually beforehand are skipped, missing ones are
        opened now. Channels that cannot be connected stop the run with
        an error popup and Overall Result FAIL (first FCT row -> Error)."""
        targets = self._fct_connect_targets()
        if not targets:
            self._run_index += 1
            self._wait_done = False
            return  # run timer continues with the FCT stage
        self._wait_done = True
        self._run_timer.stop()
        self.env._set_phase("Connecting console...")
        self.env._log("Connecting console channel(s) before FCT: "
                      + ", ".join(targets))
        self._fctconn_failed = []
        self._fctconn_pending = []
        mc = self.env.multi_console
        for key in targets:
            if mc.virtual_mode or mc.channel_endpoint(key):
                mc.open_channel(key)  # asynchronous worker thread
                self._fctconn_pending.append(key)
            else:
                # Real mode, endpoint not configured -> cannot connect
                self._fctconn_failed.append(key)
        self._fctconn_deadline = time.monotonic() \
            + self.fct_connect_timeout
        self._poll_fct_connect()

    def _poll_fct_connect(self) -> None:
        """Poll the connecting channels every 300 ms until all of them
        are up, their connect attempt has ended without a connection
        (worker thread finished) or the timeout elapses (Stop pressed
        -> just leave)."""
        if self.state != "running":
            return
        mc = self.env.multi_console
        still = []
        for key in self._fctconn_pending:
            if mc.channel_connected(key):
                continue  # endpoint open
            worker = mc.channels[key]["worker"]
            if (worker is None
                    or (hasattr(worker, "_running")
                        and not worker.isRunning())):
                # connect attempt ended without a connection
                self._fctconn_failed.append(key)
            else:
                still.append(key)  # worker alive, still connecting
        self._fctconn_pending = still
        if (self._fctconn_pending
                and time.monotonic() < self._fctconn_deadline):
            QTimer.singleShot(300, self._poll_fct_connect)
            return
        self._fctconn_failed.extend(self._fctconn_pending)
        self._fctconn_pending = []
        self._finish_fct_connect()

    def _finish_fct_connect(self) -> None:
        """Connect phase over: resume the run, or abort it with an error
        popup when any channel could not be connected."""
        if self._fctconn_failed:
            labels = ", ".join(
                self.env.multi_console.channels[k]["label"]
                for k in self._fctconn_failed)
            # the first FCT row reports the Error (legacy behavior)
            error_rows = ([("fct", 0)]
                          if self.env._fct_row_count() > 0 else [])
            self._abort_run(
                f"Stop: console channel(s) {labels} could not be "
                f"connected before FCT. Overall Result: FAIL",
                error_rows=error_rows)
            self.env._connect_failed_popup(labels)
            return
        self.env._log("Console channel(s) connected.")
        self.env._set_phase("Processing...")
        self._run_index += 1
        self._wait_done = False
        # polling stopped the run timer -> resume stepping from the
        # next step (the timer drives the per-step wait handling)
        self._run_timer.start()

    # ------------------------------------------------------- stop policy
    def _policy_abort_reason(self, kind: str, args: tuple) -> str | None:
        """Check the just-finished step against the Overall Flow stop
        strategies (mtkgui.engine.policies). Returns an abort log
        message, or None to continue."""
        if kind == "ict":
            r = args[0]
            result = self._results.get(("ict", r))
            name = self.env.ict_steps[r][1]
            stop_fail, stop_short = self.env._stop_flags()
            return policy_abort_reason(
                "ict", result, name,
                is_short=is_impedance_short(self.env.ict_steps[r]),
                stop_if_failure=stop_fail,
                stop_if_any_short=stop_short)
        if kind == "fct":
            r = args[0]
            result = self._results.get(("fct", r))
            name = (self.env.fct_rows[r]
                    if r < len(self.env.fct_rows) else "")
            stop_fail, _stop_short = self.env._stop_flags()
            return policy_abort_reason(
                "fct", result, name, stop_if_failure=stop_fail)
        return None

    # -------------------------------------------------------- run control
    def _complete_stage(self, r: int) -> None:
        """Mark one Overall Flow stage PASS and record its duration (s)."""
        duration = time.monotonic() - self._stage_start
        self._put("stage", r, StepStatus.PASS, None, duration)
        self._stage_start = time.monotonic()

    def start(self, lr_total: int = 1) -> None:
        """Start the run state machine (the page performs the run
        gates, button state and product input locking first).

        Terminal states (aborted / frozen) are rolled back to idle
        automatically first — the composite transition is legal and
        traced.  Starting from 'paused' or 'running' is illegal and
        raises: resume() / abort() decide those states' fate."""
        if self.state == "paused":
            raise RuntimeError(
                "cannot start from 'paused': resume() or abort() first")
        if self.state == "running":
            raise RuntimeError("cannot start: a run is already active")
        if self.state in ("aborted", "frozen"):
            self._transition("idle", "reset")
        self._transition("running", "operator")
        self._interrupted = False
        self._lr_total = max(1, int(lr_total))
        self._lr_done = 0
        if self.retry_count:
            self.env._log(
                f"Step retry enabled: {self.retry_count} attempt(s) on "
                f"FAIL/ERROR (source: {self.retry_source})")
        self._begin_cycle()

    def _begin_cycle(self) -> None:
        env = self.env
        self.reset_results()
        self.cycle_reset.emit()
        env._set_phase("Init...")
        self._interrupted = False
        self._wait_done = False
        self._fct_console_wait = None
        self._run_start = time.monotonic()
        self._stage_start = self._run_start
        # stages disabled in Overall Flow are skipped, Status -> Skip
        for r, on in enumerate(env.overall_en()):
            if not on:
                self.stage_skipped.emit(
                    r, f"Overall Flow {env._stage_name(r)} "
                       f"-> Skip (disabled)")
        self._run_steps = env._steps_template(
            len(env.ict_steps), env._fct_row_count())
        self._run_index = 0
        if self._lr_total > 1:
            env._log(f"Long Run cycle {self._lr_done + 1}/"
                     f"{self._lr_total} started.")
        else:
            env._log("Run started.")
        self._run_timer.start()

    def _start_next_cycle(self) -> None:
        """Long Run pause elapsed -> auto-increment SN and start again."""
        if self.state != "running":
            return  # stopped during the interval
        self.env._next_serial()
        self._begin_cycle()

    def _run_step(self) -> None:
        if self._fct_dialog_open:
            return  # operator message dialog open: timer ticks paused
        # operator pause takes effect at this step boundary: the run
        # index IS the checkpoint (finished steps stay finished, their
        # results stay collected); resume() continues from here
        if self._pause_requested:
            self._pause_requested = False
            self._transition("paused", "operator")
            return
        try:
            self._run_step_body()
        except Exception as exc:
            # P1 Task5: fine-grained failure branches replace the old
            # blanket freeze (the state machine / retry core is
            # untouched; this is the safety-net handler only)
            self._handle_failure_event(classify_exception(exc,
                                                          source="runner"))

    def _run_step_body(self) -> None:
        if self._fct_console_wait is not None:
            # a console FCT step is waiting for the DUT reply: poll the
            # channel read buffer instead of advancing to the next step
            self._poll_fct_console()
            return
        env = self.env
        if self._run_index >= len(self._run_steps):
            self._finish_run()
            return
        env._emit_progress(self._run_index, len(self._run_steps))
        kind, *args = self._run_steps[self._run_index]
        # disabled ICT / FCT steps are marked Ignore
        if kind == "ict" and not env.ict_enables[args[0]]:
            self._put("ict", args[0], StepStatus.IGNORED)
            env._log(f"ICT {env.ict_steps[args[0]][1]} "
                     f"-> Ignore (disabled)")
            self._run_index += 1
            self._wait_done = False
            return
        if kind == "fct" and not env.fct_enables[args[0]]:
            self._put("fct", args[0], StepStatus.IGNORED)
            env._log(f"FCT {env.fct_rows[args[0]]} -> Ignore (disabled)")
            self._run_index += 1
            self._wait_done = False
            return
        # console channels must be connected before the FCT stage starts
        if kind == "fctconn":
            self._run_fct_connect_step()
            return
        # per-step wait time (ms): pause before executing
        if kind in ("ict", "fct", "stage"):
            if kind == "ict":
                wait = env.ict_waits[args[0]]
            elif kind == "fct":
                wait = env.fct_waits[args[0]]
            else:
                wait = 0
            if wait > 0 and not self._wait_done:
                self._wait_done = True
                env._log(f"Wait {wait} ms ...")
                self._run_timer.stop()
                QTimer.singleShot(wait, self._resume_step)
                return
        self._wait_done = False
        self._timeout_retried = False   # one reset+retry per step
        step_index = self._run_index
        self._run_index += 1
        env._set_phase("Processing...")
        self.step_started.emit(step_index)
        self._step_t0 = time.monotonic()
        if kind == "ict":
            self._exec_with_retry("ict", args)
        elif kind == "fct":
            self._exec_with_retry("fct", args)
        elif kind == "stage":
            self._complete_stage(args[0])
        env._update_result()
        self.step_finished.emit(step_index, self._step_result(kind, args))
        # Overall Flow stop strategies (stop if failure / any short)
        # -- evaluated AFTER the retry attempts are exhausted
        reason = self._policy_abort_reason(kind, args)
        if reason:
            self._abort_run(reason)

    def _resume_step(self) -> None:
        """Per-step wait elapsed -> continue the sequence."""
        if self.state != "running":
            return  # paused or stopped during the wait
        self._run_step()
        if self.state == "running":
            self._run_timer.start()

    def _handle_failure_event(self, event) -> None:
        """Differentiated handling of one classified failure.

        Priority: an operator abort intercepts every automatic branch.
        TIMEOUT gets one reset+retry per step; RESOURCE terminates the
        run; everything else freezes the engine (alarm + keep data)."""
        if self._interrupted or self.state not in ("running", "paused"):
            return  # operator stop wins; nothing to do when stopped
        if event.kind is FailureKind.TIMEOUT and not self._timeout_retried:
            # timeout-specific reset strategy: clear the wait state and
            # re-dispatch the same step exactly once
            self._timeout_retried = True
            self._wait_done = False
            self.env._log(failure_log_line(event, "reset+retry-once"))
            try:
                self._run_step_body()
                return
            except Exception as exc2:
                # the retry failed too: fall through to the generic
                # handling with the retry's own classification
                event = classify_exception(exc2, source="runner")
                self.env._log(failure_log_line(event, "retry failed"))
        action = ("abort" if event.kind is FailureKind.RESOURCE
                  else "freeze")
        self.env._log(failure_log_line(event, action))
        if event.kind is FailureKind.RESOURCE:
            self.abort(trigger="system")   # terminate: no auto retry
        else:
            self.freeze(f"{event.kind.value}: {event.message}")

    def _finish_run(self) -> None:
        """One cycle completed without interruption -> judge result;
        Long Run may start the next cycle after the pause."""
        self._run_timer.stop()
        total = len(self._run_steps)
        cycle_s = time.monotonic() - self._run_start
        self._lr_done += 1
        if self._lr_done < self._lr_total:
            wait = self.env._interval_s()
            self.env._log(f"Long Run cycle {self._lr_done}/"
                          f"{self._lr_total} finished; next cycle in "
                          f"{wait:g} s")
            self.env._set_phase(f"Waiting {wait:g} s ...")
            self.run_finished.emit(
                {"reason": "cycle", "progress": True, "total": total,
                 "cycle_s": cycle_s, "reset_phase": False,
                 "remaining": [], "counted": True})
            self._lr_wait_timer.start(int(wait * 1000))
            return  # still "running": Run disabled, Stop enabled
        # all cycles done
        self._transition("idle", "auto")
        if self.verdict() == "FAIL":
            self.env._log("Run finished with failures (stop policy off) "
                          "-> Overall Result: FAIL")
        else:
            self.env._log("Overall flow: ICT -> FCT all PASS")
        if self._lr_total > 1:
            self.env._log(f"Long Run complete: {self._lr_total} cycles.")
        self.run_finished.emit(
            {"reason": "complete", "progress": True, "total": total,
             "cycle_s": cycle_s, "reset_phase": True,
             "remaining": [], "counted": True})

    def _abort_run(self, reason: str, *, counted: bool = True,
                   reset_phase: bool = True,
                   error_rows: list | None = None) -> None:
        """Stop-policy abort: a FAIL/short triggered an Overall Flow
        policy (or the console connect failed). Remaining items are
        blanked and the product is counted FAIL — unlike the operator
        Stop button, which yields IGNORE.  error_rows are rendered as
        Error instead of being blanked (e.g. the first FCT row after a
        console connect failure)."""
        self._run_timer.stop()
        self._lr_wait_timer.stop()
        self._fct_console_wait = None
        error_set = {tuple(x) for x in (error_rows or [])}
        for kind, row in error_rows or []:
            self._put(kind, row, StepStatus.ERROR)
        remaining = [
            s for s in self._run_steps[self._run_index:]
            if (s[0], s[1] if len(s) > 1 else -1) not in error_set]
        self._transition("idle", "auto")
        self._interrupted = False
        if reset_phase:
            self.env._clear_highlight()
        self.env._log(reason)
        self.run_finished.emit(
            {"reason": "complete", "progress": False,
             "total": len(self._run_steps),
             "cycle_s": time.monotonic() - self._run_start,
             "reset_phase": reset_phase, "remaining": remaining,
             "counted": counted})

    def abort(self, trigger: str = "operator") -> None:
        """Stop / terminate the run from 'running' or 'paused'
        (trigger 'operator' for the Stop button, 'system' when a
        resource-classified failure terminates the run).  Remaining
        test items are left blank and the Overall Result is IGNORE;
        the engine parks in the 'aborted' terminal state (start()
        auto-resets it, or reset_state() rolls back)."""
        if self.state not in ("running", "paused"):
            return
        self._run_timer.stop()
        self._lr_wait_timer.stop()
        self._fct_console_wait = None
        self._pause_requested = False
        self._interrupted = True
        self._transition("aborted", trigger)
        who = "operator" if trigger == "operator" else trigger
        self.env._log(f"Run terminated ({who}) -> "
                      "Overall Result: IGNORE")
        self.run_finished.emit(
            {"reason": "stop", "progress": False, "total": 0,
             "cycle_s": 0.0, "reset_phase": True,
             "remaining": list(self._run_steps[self._run_index:]),
             "counted": False})

    def run_demo(self) -> None:
        """Synchronous full pass (used by smoke test); honors the
        Overall Flow EN checkboxes.  The operator answer is simulated
        (PASS) and no message dialogs pop up."""
        env = self.env
        t0 = time.monotonic()
        self.reset_results()
        self._stage_start = t0
        en = env.overall_en()
        if en[0]:
            for r in range(len(env.ict_steps)):
                if env.ict_enables[r]:
                    self.step_started.emit(r)
                    self._step_t0 = time.monotonic()
                    self._exec_with_retry("ict", (r,))
                    self.step_finished.emit(r,
                                            self._step_result("ict", (r,)))
                else:
                    env._fill_ict_row(r, placeholder=False)
                    self._put("ict", r, StepStatus.IGNORED)
                    env._log(f"ICT {env.ict_steps[r][1]} "
                             f"-> Ignore (disabled)")
            self._complete_stage(0)
        else:
            self.stage_skipped.emit(0, "Overall flow: ICT -> Skip "
                                       "(disabled)")
        if en[1]:
            for r in range(env._fct_row_count()):
                if env.fct_enables[r]:
                    self.step_started.emit(r)
                    self._step_t0 = time.monotonic()
                    self._exec_with_retry("fct", (r,), interactive=False)
                    self.step_finished.emit(r,
                                            self._step_result("fct", (r,)))
                else:
                    self._put("fct", r, StepStatus.IGNORED)
                    env._log(f"FCT {env.fct_rows[r]} "
                             f"-> Ignore (disabled)")
            self._complete_stage(1)
        else:
            self.stage_skipped.emit(1, "Overall flow: FCT -> Skip "
                                       "(disabled)")
        env._log("Overall flow: ICT -> FCT all PASS")
        self.run_finished.emit(
            {"reason": "complete", "progress": False, "total": 0,
             "cycle_s": time.monotonic() - t0, "reset_phase": False,
             "remaining": [], "counted": True})


class _SimulatedOutcome:
    """Duck-typed op outcome for the engine-side simulated flash step
    (verdict always "Done"; the lines carry the J-Link sub-actions)."""

    def __init__(self, lines: list[str]):
        self.verdict = "Done"
        self.lines = lines
        self.text = ""
        self.value = None
