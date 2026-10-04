# -*- coding: utf-8 -*-
"""Fine-grained failure branches (P1 Task5): six-way classification,
per-kind policies, operator-stop priority, edge cases."""
from __future__ import annotations

import pytest

from mtkgui.engine.failures import (FailureKind, classify_exception,
                                    failure_log_line, policy_for)
from mtkgui.engine.instruments import DriverUnavailable
from mtkgui.engine.runner import TestRunner
from mtkgui.engine.scheduler import (BatchJob, CaseJob, SuiteJob,
                                     TestScheduler)
from tests.engine.conftest import make_env

from PySide6.QtCore import QTimer


# ------------------------------------------------------- classification
class TestClassification:
    def test_timeout_maps_to_timeout(self):
        ev = classify_exception(TimeoutError("poll exhausted"))
        assert ev.kind is FailureKind.TIMEOUT
        assert ev.policy.action == "reset" and ev.retry_allowed

    def test_driver_unavailable_maps_to_resource(self):
        ev = classify_exception(DriverUnavailable("no drivers"))
        assert ev.kind is FailureKind.RESOURCE
        assert ev.policy.action == "abort" and not ev.retry_allowed

    def test_connection_error_maps_to_resource(self):
        assert classify_exception(ConnectionError("psu link lost")) \
            .kind is FailureKind.RESOURCE

    def test_generic_error_maps_to_engine_error(self):
        for exc in (RuntimeError("logic"), ValueError("bad input"),
                    KeyError("x")):
            assert classify_exception(exc).kind is FailureKind.ENGINE_ERROR

    def test_nested_chain_resolves_to_root(self):
        try:
            try:
                raise TimeoutError("deep root")
            except TimeoutError as cause:
                raise RuntimeError("wrapper") from cause
        except RuntimeError as exc:
            ev = classify_exception(exc)
        assert ev.kind is FailureKind.TIMEOUT          # root decides
        assert len(ev.chain) == 2
        assert ev.chain[0].startswith("RuntimeError")
        line = failure_log_line(ev)
        assert line.startswith("[EXC:TIMEOUT] source=runner")
        assert "action=reset" in line and "state_target=running" in line

    def test_policies_are_fully_differentiated(self):
        actions = {policy_for(k).action for k in FailureKind}
        assert actions == {"retry", "freeze", "abort", "reset", "none"}
        # only the business-FAIL branch allows the standard retry
        assert policy_for(FailureKind.STEP_FAIL).retry_allowed
        assert not policy_for(FailureKind.ENGINE_ERROR).retry_allowed
        assert not policy_for(FailureKind.RESOURCE).retry_allowed
        assert not policy_for(FailureKind.OPERATOR_ABORT).retry_allowed


# ------------------------------------------------------ runner branches
def _start_runner(env):
    runner = TestRunner(env)
    env.runner = runner
    runner.start(1)
    runner._run_step()          # stage 0 -> running
    return runner


class TestRunnerBranches:
    def test_engine_error_freezes_with_exc_log(self, env):
        runner = _start_runner(env)

        def boom(row):
            raise RuntimeError("logic blew up")
        runner._exec_ict_row = boom
        runner._run_step()
        assert runner.state == "frozen"
        assert "[EXC:ENGINE_ERROR]" in "\n".join(env._log_lines())

    def test_timeout_resets_and_retries_once(self, env):
        runner = _start_runner(env)
        calls = {"n": 0}

        def flaky(row):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("daq poll timeout")
            runner._put("ict", row, "PASS", "ok")
        runner._exec_ict_row = flaky
        runner._run_step()
        assert calls["n"] == 2                   # reset + retry-once
        assert runner.state == "running"         # no freeze, flow resumes
        text = "\n".join(env._log_lines())
        assert "[EXC:TIMEOUT]" in text and "reset+retry-once" in text
        for _ in range(10000):                   # run to completion
            if runner.state != "running":
                break
            runner._run_step()
        assert runner.state == "idle" and runner.verdict() == "PASS"

    def test_timeout_twice_freezes(self, env):
        runner = _start_runner(env)

        def always_timeout(row):
            raise TimeoutError("stuck")
        runner._exec_ict_row = always_timeout
        runner._run_step()
        assert runner.state == "frozen"          # second timeout -> freeze
        assert "[EXC:TIMEOUT] source=runner" in "\n".join(env._log_lines())

    def test_resource_failure_terminates_run(self, env):
        runner = _start_runner(env)

        def no_driver(row):
            raise DriverUnavailable("mtkgui.drivers missing")
        runner._exec_ict_row = no_driver
        runner._run_step()
        assert runner.state == "aborted"         # terminate, no retry
        assert "[EXC:RESOURCE]" in "\n".join(env._log_lines())
        assert "Run terminated (system)" in "\n".join(env._log_lines())

    def test_operator_abort_intercepts_automatic_handling(self, env):
        runner = _start_runner(env)
        runner.abort()                           # operator stop already
        assert runner.state == "aborted"

        def boom(row):
            raise RuntimeError("late error")
        runner._exec_ict_row = boom
        runner._handle_failure_event(classify_exception(RuntimeError("x")))
        assert runner.state == "aborted"         # untouched by auto logic

    def test_exception_while_paused_freezes(self, env):
        runner = _start_runner(env)
        runner.pause()
        runner._run_step()                       # boundary -> paused

        def boom(row):
            raise RuntimeError("error during pause")
        runner._exec_ict_row = boom
        runner._pause_requested = True           # resume path triggers
        runner.resume()
        runner._run_step()
        assert runner.state == "frozen"          # safe freeze, data kept
        assert runner._run_index == 2            # step fully attempted


# --------------------------------------------------- scheduler branches
# note: CaseJob exceptions are contained at the case level by design
# (status -> Error), so scheduler-level failure branches are exercised
# at the job-orchestration layer (_run_job) where the safety net lives

def _drain(s):
    s._dispatch()
    while s.state == "running":
        s._dispatch()


class TestSchedulerBranches:
    def test_timeout_requeues_once_then_freezes(self):
        lines: list[str] = []
        s = TestScheduler(log_fn=lines.append)
        calls = {"n": 0}
        real = s._run_job

        def flaky_run(job):
            calls["n"] += 1
            if calls["n"] <= 2:                 # fail both attempts
                raise TimeoutError("stuck")
            real(job)

        s._run_job = flaky_run
        s.submit(BatchJob("b", [CaseJob("x", lambda ctx: "PASS")]))
        s.start()
        _drain(s)
        assert calls["n"] == 2                  # requeued exactly once
        assert s.state == "frozen"              # then frozen (2nd timeout)
        text = "\n".join(lines)
        assert "[EXC:TIMEOUT] source=scheduler" in text
        assert "reset+requeue-once" in text

    def test_timeout_recovery_succeeds(self):
        lines: list[str] = []
        s = TestScheduler(log_fn=lines.append)
        calls = {"n": 0}
        real = s._run_job

        def flaky_run(job):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("glitch")
            real(job)

        s._run_job = flaky_run
        job = BatchJob("b", [CaseJob("x", lambda ctx: "PASS")])
        s.submit(job)
        s.start()
        _drain(s)
        assert calls["n"] == 2 and job.status == "PASS"
        assert s.state == "idle"                # recovered, drained
        assert s.last_report["total"] == 1      # re-run not double-counted

    def test_resource_failure_aborts_scheduler(self):
        lines: list[str] = []
        s = TestScheduler(log_fn=lines.append)

        def no_driver(job):
            raise DriverUnavailable("no drivers")
        s._run_job = no_driver
        s.submit(BatchJob("res", [CaseJob("x", lambda ctx: "PASS")]))
        s.submit(BatchJob("late", [CaseJob("y", lambda ctx: "PASS")]))
        s.start()
        _drain(s)
        assert s.state == "aborted"
        assert "[EXC:RESOURCE]" in "\n".join(lines)

    def test_engine_error_freezes_scheduler(self):
        lines: list[str] = []
        s = TestScheduler(log_fn=lines.append)

        def boom(job):
            raise RuntimeError("scheduler bug")
        s._run_job = boom
        s.submit(BatchJob("bad", [CaseJob("x", lambda ctx: "PASS")]))
        s.start()
        _drain(s)
        assert s.state == "frozen"
        assert "[EXC:ENGINE_ERROR]" in "\n".join(lines)

    def test_resource_release_never_hangs(self):
        lines: list[str] = []
        s = TestScheduler(log_fn=lines.append)
        s.submit(CaseJob("a", lambda ctx: "PASS"))
        s.start()
        _drain(s)
        assert "resource released: case 'a'" in "\n".join(lines)
        assert s._current is None               # no phantom resource
