# -*- coding: utf-8 -*-
"""TestRunner behavior on the headless environment: full runs, stop
strategies, disabled steps, operator stop and result rollup."""
from __future__ import annotations

import pytest

from mtkgui.engine.demo import HeadlessConsole, HeadlessEnv
from mtkgui.engine.results import StepStatus
from mtkgui.engine.runner import TestRunner

from tests.engine.conftest import make_env

# pytest must not collect the engine class as a test case
TestRunner.__test__ = False


def run_demo(env) -> TestRunner:
    runner = TestRunner(env)
    env.runner = runner
    runner.run_demo()
    return runner


def step_run(env) -> TestRunner:
    """Drive the timer path manually (no event loop, waits are 0):
    start the run, then tick _run_step until the state machine leaves
    "running".  This is the path the headless demo exercises; only
    here the Overall Flow stop strategies apply (legacy semantics)."""
    runner = TestRunner(env)
    env.runner = runner
    runner.start(1)
    for _ in range(10000):
        if runner.state != "running":
            break
        runner._run_step()
    return runner


class TestFullPass:
    def test_run_demo_all_pass(self, env):
        runner = run_demo(env)
        assert runner.verdict() == "PASS"
        assert runner.state == "idle"
        # every stage completed
        assert env.rows[("stage", 0)] == "PASS"
        # the flash op step ran (virtual: engine-simulated J-Link)
        flash_idx = next(i for i, k in enumerate(env.fct_kinds)
                         if k == "op")
        assert env.rows[("fct", flash_idx)] == "Done"

    def test_run_finished_signal(self, env):
        runner = TestRunner(env)
        env.runner = runner
        summaries = []
        runner.run_finished.connect(summaries.append)
        runner.run_demo()
        assert summaries and summaries[0]["reason"] == "complete"
        assert summaries[0]["counted"] is True

    def test_rail_capture_populates_csv(self, env):
        run_demo(env)
        assert env.rail_csv_path is not None
        assert env.rail_csv_path.exists()
        assert env.ai_review_text is not None

    def test_disabled_stage_reports_skip(self, env):
        env._overall_en = [True, False]
        runner = run_demo(env)
        # only the ICT stage ran; no FCT row was judged
        assert runner.verdict() == "PASS"
        assert ("fct", 0) not in env.rows


class TestStopStrategies:
    def test_stop_if_failure_ict(self, env):
        env.stop_if_failure = True
        env.ict_sim_fail.add(3)   # the Power Voltage row (no short)
        runner = step_run(env)
        assert runner.verdict() == "FAIL"
        assert runner.state == "idle"
        # aborted at row 3: the later DAQ AI row was never judged
        assert ("ict", 5) not in env.rows
        # first FCT row untouched
        assert ("fct", 0) not in env.rows

    def test_stop_if_any_short(self, env):
        env.stop_if_any_short = True
        env.stop_if_failure = False
        env.ict_sim_fail.add(1)   # Impedance Shorts row
        runner = step_run(env)
        assert runner.verdict() == "FAIL"
        assert ("ict", 3) not in env.rows   # run aborted at the short

    def test_no_stop_when_policies_off(self, env):
        env.stop_if_failure = False
        env.stop_if_any_short = False
        env.ict_sim_fail.add(1)
        runner = step_run(env)
        assert runner.verdict() == "FAIL"
        # the run continued to the end: stage 0 completed, FCT judged
        assert env.rows.get(("stage", 0)) == "PASS"
        assert ("fct", 0) in env.rows

    def test_fct_failure_stops_when_enabled(self, env):
        env.stop_if_failure = True
        env.fct_sim_fail.add(1)   # the SendtoCLI row (non-op)
        runner = step_run(env)
        assert runner.verdict() == "FAIL"
        assert env.rows[("fct", 1)] == "FAIL"
        assert ("fct", 2) not in env.rows

    def test_demo_path_ignores_stop_policies(self, env):
        # legacy semantics: run_demo judges every row even with a FAIL
        env.stop_if_failure = True
        env.ict_sim_fail.add(3)
        runner = run_demo(env)
        assert runner.verdict() == "FAIL"
        assert ("fct", 0) in env.rows   # FCT still ran


class TestOperatorStop:
    def test_abort_yields_ignore_state(self, env):
        runner = TestRunner(env)
        env.runner = runner
        summaries = []
        runner.run_finished.connect(summaries.append)
        runner.start(1)
        assert runner.state == "running"
        runner.abort()
        assert runner.state == "idle"
        assert summaries[0]["reason"] == "stop"
        assert summaries[0]["counted"] is False

    def test_abort_when_idle_is_noop(self, env):
        runner = TestRunner(env)
        summaries = []
        runner.run_finished.connect(summaries.append)
        runner.abort()
        assert summaries == []


class TestDisabledSteps:
    def test_disabled_ict_row_is_ignored(self, env):
        env.ict_enables[1] = False   # the impedance row
        runner = run_demo(env)
        assert env.rows[("ict", 1)] == "Ignore"
        assert runner.verdict() == "PASS"   # Ignore never judges FAIL

    def test_disabled_fct_row_is_ignored(self, env):
        env.fct_enables[0] = False
        runner = run_demo(env)
        assert env.rows[("fct", 0)] == "Ignore"


class TestVirtualConsoleSteps:
    @staticmethod
    def _connect(env):
        """Open the scripted serial channel (the fctconn step does this
        in a real run)."""
        env.multi_console.open_channel("VCOM0")

    def test_send_cli_step_polls_to_pass(self, env):
        self._connect(env)
        runner = TestRunner(env)
        runner.state = "running"   # timer-driven context
        env.runner = runner
        runner._exec_fct_row(1, interactive=True)  # SendtoCLI row
        assert env.rows[("fct", 1)] == "RUNNING"
        runner._poll_fct_console()   # scripted DUT replies instantly
        assert env.rows[("fct", 1)] == "PASS"

    def test_wifi_row_uses_cli_path(self, env):
        self._connect(env)
        runner = TestRunner(env)
        runner.state = "running"
        env.runner = runner
        runner._exec_fct_row(2, interactive=True)  # WIFI row
        runner._poll_fct_console()
        assert env.rows[("fct", 2)] == "PASS"

    def test_no_serial_channel_reports_error(self, env):
        # replace the console with one that has no connected channel
        class DeadConsole(HeadlessConsole):
            def channel_connected(self, key):
                return False

            def open_channel(self, key):
                pass

        env.multi_console = DeadConsole()
        runner = TestRunner(env)
        env.runner = runner
        runner._exec_fct_row(1, interactive=True)
        assert env.rows[("fct", 1)] == "Error"

    def test_console_wait_timeout_no_reply_is_error(self, env):
        # arm the documented no_response one-shot fault: the scripted
        # DUT swallows the command, the buffer stays empty
        env.multi_console.open_channel("VCOM0")
        env.multi_console.channels["VCOM0"]["worker"] \
            .inject_fault("no_response")
        runner = TestRunner(env)
        runner.state = "running"
        env.runner = runner
        runner._exec_fct_row(1, interactive=True)
        # force the deadline into the past, then poll
        runner._fct_console_wait["deadline"] = 0.0
        runner._poll_fct_console()
        assert env.rows[("fct", 1)] == "Error"

    def test_console_connect_failure_aborts(self, env):
        # real-mode console with no configured endpoint: the fctconn
        # step fails and aborts the run (first FCT row -> Error)
        env.multi_console = HeadlessConsole()
        env.multi_console.virtual_mode = False
        env.multi_console.channel_endpoint = lambda key: None
        runner = TestRunner(env)
        env.runner = runner
        summaries = []
        runner.run_finished.connect(summaries.append)
        runner.start(1)
        runner._run_fct_connect_step()
        assert runner.state == "idle"
        assert summaries, "abort emitted run_finished"
        # first FCT row reports the Error, remaining were blanked
        assert env.rows[("fct", 0)] == "Error"


class TestStepSignals:
    def test_step_started_and_finished_emitted(self, env):
        runner = TestRunner(env)
        env.runner = runner
        started, finished = [], []
        runner.step_started.connect(started.append)
        runner.step_finished.connect(
            lambda index, result: finished.append((index, result)))
        runner.run_demo()
        assert started and finished
        index, result = finished[0]
        assert index == started[0]
        assert result.status.value in ("PASS", "Done", "FAIL", "ERROR")
        assert result.message  # display text carried in message


class TestLongRun:
    def test_cycle_counting(self, env):
        runner = TestRunner(env)
        env.runner = runner
        runner.start(2)
        assert runner.state == "running"
        summaries = []
        runner.run_finished.connect(summaries.append)
        # mid-cycle finish path (first of two cycles)
        runner._lr_done = 0
        runner._finish_run()
        assert summaries[-1]["reason"] == "cycle"
        assert runner.state == "running"
        # final cycle
        runner._lr_done = 1
        runner._finish_run()
        assert summaries[-1]["reason"] == "complete"
        assert runner.state == "idle"


class TestRealModeWithoutDrivers:
    def test_gateway_missing_module_reports_error(self, tmp_path):
        env, _stages = make_env(mode="real", tmp_path=tmp_path)
        assert env.gateway is not None
        if env.gateway.available:
            pytest.skip("real mtkgui.drivers importable (T1 merged)")
        assert env.gateway.available is False
        runner = TestRunner(env)
        env.runner = runner
        runner.run_demo()
        # measurement rows degrade to Error -> overall FAIL
        assert runner.verdict() == "FAIL"


class TestRealModeWithStubDrivers:
    def test_full_real_mode_pass(self, tmp_path, scripted_drivers):
        env, _stages = make_env(mode="real", tmp_path=tmp_path)
        runner = TestRunner(env)
        env.runner = runner
        runner.run_demo()
        assert runner.verdict() == "PASS"
        # the J-Link flash step ran through the gateway
        flash_idx = next(i for i, k in enumerate(env.fct_kinds)
                         if k == "op")
        assert env.rows[("fct", flash_idx)] == "Done"


class TestLegacyPlaceholderPath:
    def test_real_mode_without_gateway_keeps_placeholder(self, tmp_path):
        env, _stages = make_env(mode="real", tmp_path=tmp_path)
        env.gateway = None
        runner = TestRunner(env)
        env.runner = runner
        runner._exec_ict_row(3)   # Power Voltage row: healthy placeholder
        assert env.rows[("ict", 3)] == "PASS"

    def test_sim_fail_short_row_placeholder(self, tmp_path):
        env, _stages = make_env(mode="real", tmp_path=tmp_path)
        env.gateway = None
        env.ict_sim_fail.add(1)
        runner = TestRunner(env)
        env.runner = runner
        runner._exec_ict_row(1)   # Static Impedance row
        assert env.rows[("ict", 1)] == "FAIL"
        assert env.measured[("ict", 1)] == "0.62"


class TestStepRetry:
    """Basic fault-policy retry (test_flow.retry / --retry N): a
    FAIL/ERROR step is re-executed up to retry_count times before the
    stop policies are evaluated; default 0 keeps the legacy behavior."""

    def _capture(self, env):
        lines: list[str] = []
        orig = env._log
        env._log = lambda line: (lines.append(line), orig(line))
        return lines

    def _flaky(self, runner, kind, fail_times):
        """Replace the row executor: first `fail_times` calls produce
        FAIL, later calls PASS (marking the row via _put)."""
        calls = {"n": 0}

        def fake_exec(row):
            calls["n"] += 1
            if calls["n"] <= fail_times:
                runner._put(kind, row, StepStatus.FAIL, "flaky")
            else:
                runner._put(kind, row, StepStatus.PASS, "ok")

        return fake_exec, calls

    def test_retry_recovers_then_passes(self, env):
        runner = TestRunner(env)
        env.runner = runner
        runner.retry_count = 2
        lines = self._capture(env)
        fake, calls = self._flaky(runner, "ict", fail_times=1)
        runner._exec_ict_row = fake
        runner.start(1)
        runner._run_step()
        assert calls["n"] == 2                      # 1 fail + 1 retry
        assert runner._step_result("ict", (0,)).status is StepStatus.PASS
        assert any("Retry 1/2" in line for line in lines)

    def test_retry_exhausted_reports_fail(self, env):
        runner = TestRunner(env)
        env.runner = runner
        runner.retry_count = 2
        fake, calls = self._flaky(runner, "ict", fail_times=99)
        runner._exec_ict_row = fake
        runner.start(1)
        runner._run_step()
        assert calls["n"] == 3                      # initial + 2 retries
        assert runner._step_result("ict", (0,)).status is StepStatus.FAIL

    def test_no_retry_by_default(self, env):
        runner = TestRunner(env)
        env.runner = runner
        lines = self._capture(env)
        fake, calls = self._flaky(runner, "ict", fail_times=99)
        runner._exec_ict_row = fake
        runner.start(1)
        runner._run_step()
        assert calls["n"] == 1                      # legacy: single attempt
        assert not any("Retry" in line for line in lines)

    def test_pass_not_retried(self, env):
        runner = TestRunner(env)
        env.runner = runner
        runner.retry_count = 3
        fake, calls = self._flaky(runner, "ict", fail_times=0)
        runner._exec_ict_row = fake
        runner.start(1)
        runner._run_step()
        assert calls["n"] == 1

    def test_run_demo_path_retries_fct(self, env):
        runner = TestRunner(env)
        env.runner = runner
        runner.retry_count = 1
        calls = {"n": 0}

        def fake_fct(row, interactive=True):
            calls["n"] += 1
            if calls["n"] == 1:
                runner._put("fct", row, StepStatus.FAIL, "flaky")
            else:
                runner._put("fct", row, StepStatus.PASS, "ok")

        runner._exec_fct_row = fake_fct
        runner.run_demo()
        # first FCT row fails once, retry recovers
        assert calls["n"] >= 2
        assert runner._step_result("fct", (0,)).status is StepStatus.PASS


class TestRetryStandardization:
    """P1 retry standardization: single normalization entry point,
    traceable configuration source, operator Stop priority, and
    stop strategies firing after the retries are exhausted."""

    def test_normalize_retry_count_clamps_illegal_values(self):
        from mtkgui.engine.policies import normalize_retry_count as n
        assert n(0) == 0 and n(3) == 3
        assert n(-5) == 0                        # negative -> 0
        assert n(2.9) == 2                       # float -> truncated int
        assert n("4") == 4                       # numeric string
        assert n("abc") == 0                     # garbage -> 0
        assert n(None) == 0
        assert n(True) == 1 and n(False) == 0    # bool is an int subclass

    def test_set_retry_normalizes_and_records_source(self, env):
        runner = TestRunner(env)
        runner.set_retry(-3, source="cli")
        assert runner.retry_count == 0           # clamped, no illegal value
        assert runner.retry_source == "cli"
        runner.set_retry("2", source="yaml")
        assert runner.retry_count == 2
        assert runner.retry_source == "yaml"

    def test_start_logs_retry_source(self, env):
        lines = []
        orig = env._log
        env._log = lambda line: (lines.append(line), orig(line))
        runner = TestRunner(env)
        runner.set_retry(2, source="yaml")
        runner.start(1)
        assert any("Step retry enabled: 2 attempt(s) on FAIL/ERROR "
                   "(source: yaml)" in line for line in lines)

    def test_no_trace_log_without_retry(self, env):
        lines = []
        orig = env._log
        env._log = lambda line: (lines.append(line), orig(line))
        runner = TestRunner(env)
        runner.start(1)
        assert not any("Step retry enabled" in line for line in lines)

    def test_operator_stop_wins_over_retry(self, env):
        runner = TestRunner(env)
        env.runner = runner
        runner.set_retry(3, source="cli")
        calls = {"n": 0}

        def fake_exec(row):
            calls["n"] += 1
            runner._put("ict", row, StepStatus.FAIL, "flaky")

        runner._exec_ict_row = fake_exec
        runner.start(1)
        runner._interrupted = True               # operator Stop happened
        runner._run_step()
        assert calls["n"] == 1                   # no retry after Stop

    def test_exhausted_retries_then_stop_policy_fires(self, env):
        runner = TestRunner(env)
        env.runner = runner
        runner.set_retry(1, source="yaml")
        calls = {"n": 0}

        def fake_exec(row):
            calls["n"] += 1
            runner._put("ict", row, StepStatus.FAIL, "flaky")

        runner._exec_ict_row = fake_exec
        runner.start(1)
        for _ in range(10):
            if runner.state != "running":
                break
            runner._run_step()
        assert calls["n"] == 2                   # initial + 1 retry
        # flow closed cleanly: policy abort, run finished, FAIL counted
        assert runner.state == "idle"
        assert runner.verdict() == "FAIL"
