# -*- coding: utf-8 -*-
"""Layered scheduling (P1 Task4): case / batch / suite levels, FIFO
resource discipline, state-machine alignment and trace logging."""
from __future__ import annotations

import time
from collections import deque

import pytest

from mtkgui.engine.scheduler import (BatchJob, CaseJob, JobContext,
                                     SuiteJob, TestScheduler)


def _ok_case(name="ok"):
    return CaseJob(name, lambda ctx: "PASS")


def _fail_case(name="bad"):
    return CaseJob(name, lambda ctx: "FAIL")


def _boom_case(name="boom"):
    def fn(ctx):
        raise RuntimeError("daq exploded")
    return CaseJob(name, fn)


@pytest.fixture()
def sched():
    lines: list[str] = []
    s = TestScheduler(log_fn=lines.append)
    s.lines = lines
    yield s


def _drain(s: TestScheduler) -> None:
    s._dispatch()
    while s.state == "running":        # timer re-entry safety
        s._dispatch()


# ---------------------------------------------------------------- levels
class TestLevels:
    def test_single_case_pass(self, sched):
        job = sched.submit(_ok_case("single"))
        sched.start()
        _drain(sched)
        assert job.status == "PASS"
        assert sched.state == "idle"

    def test_single_case_fail_and_error(self, sched):
        sched.start()
        f = sched.submit(_fail_case("f"))
        e = sched.submit(_boom_case("e"))
        _drain(sched)
        assert f.status == "FAIL"
        assert e.status == "Error" and "daq exploded" in e.detail

    def test_batch_sequential_order(self, sched):
        order: list[str] = []

        def make(name):
            def fn(ctx):
                order.append(name)
                return "PASS"
            return fn

        batch = BatchJob("b", [CaseJob(n, make(n))
                               for n in ("a1", "a2", "a3")])
        sched.submit(batch)
        sched.start()
        _drain(sched)
        assert order == ["a1", "a2", "a3"]
        assert batch.status == "PASS"

    def test_batch_parallel_completes_all(self, sched):
        batch = BatchJob("par", [_ok_case(f"c{i}") for i in range(4)],
                         parallel=True, max_workers=2)
        sched.submit(batch)
        sched.start()
        _drain(sched)
        assert [c.status for c in batch.cases] == ["PASS"] * 4
        assert batch.status == "PASS"

    def test_batch_verdict_rollup(self, sched):
        batch = BatchJob("b", [_ok_case("g"), _fail_case("x")])
        sched.submit(batch)
        sched.start()
        _drain(sched)
        assert batch.verdict == "FAIL"

    def test_suite_aggregates_and_logs_levels(self, sched):
        suite = SuiteJob("s", [
            BatchJob("b1", [_ok_case("g1")]),
            BatchJob("b2", [_ok_case("g2"), _fail_case("x")]),
        ])
        sched.submit(suite)
        sched.start()
        _drain(sched)
        assert suite.verdict == "FAIL"
        text = "\n".join(sched.lines)
        assert "dispatch: suite 's'" in text
        assert "dispatch: batch 'b1'" in text
        assert "dispatch: case 'g2'" in text

    def test_invalid_case_status_is_error(self, sched):
        job = CaseJob("weird", lambda ctx: "whatever")
        sched.submit(job)
        sched.start()
        _drain(sched)
        assert job.status == "Error"

    def test_submit_rejects_unknown_level(self, sched):
        class Fake:
            level = "cluster"
        with pytest.raises(ValueError):
            sched.submit(Fake())


# ------------------------------------------------- resource competition
class TestResourceDiscipline:
    def test_fifo_no_queue_jumping(self, sched):
        slow = CaseJob("slow",
                       lambda ctx: (time.sleep(0.05), "PASS")[1])
        suite = SuiteJob("big-suite", [BatchJob("b", [_ok_case("g")])])
        sched.submit(suite)
        sched.submit(slow)              # submitted after, must run after
        sched.start()
        _drain(sched)
        text = "\n".join(sched.lines)
        assert text.index("dispatch: suite 'big-suite'") < \
            text.index("dispatch: case 'slow'")

    def test_station_busy_guard(self, sched):
        from mtkgui.engine.runner import TestRunner
        from tests.engine.conftest import make_env
        env, _ = make_env()
        runner = TestRunner(env)
        env.runner = runner
        s = TestScheduler(runner=runner, log_fn=lambda l: None)
        runner.start(1)
        ctx = JobContext(s)
        with pytest.raises(RuntimeError, match="station busy"):
            ctx.start_runner()

    def test_runner_linkage_and_resource_release(self, sched):
        from mtkgui.engine.runner import TestRunner
        from tests.engine.conftest import make_env
        env, _ = make_env()
        runner = TestRunner(env)
        env.runner = runner
        s = TestScheduler(runner=runner, log_fn=lambda l: None)

        def engine_case(ctx):
            ctx.start_runner()          # exclusive acquisition
            while runner.state == "running":
                runner._run_step()
            return runner.verdict() or "PASS"

        s.submit(CaseJob("engine-run", engine_case))
        s.start()
        _drain(s)
        assert runner.state == "idle"   # resource released, no leakage
        assert s.state == "idle"
        assert s.last_report["total"] == 1

    def test_abort_skips_queued_jobs(self, sched):
        batch = BatchJob("late", [_ok_case("x")])
        sched.submit(_ok_case("first"))
        sched.submit(batch)
        sched.start()
        sched.abort()
        assert sched.state == "aborted"
        assert sched._queue == deque()
        assert batch.status == "SKIPPED"
        assert batch.cases[0].status == "SKIPPED"

    def test_abort_propagates_to_running_runner(self, sched):
        from mtkgui.engine.runner import TestRunner
        from tests.engine.conftest import make_env
        env, _ = make_env()
        runner = TestRunner(env)
        env.runner = runner
        s = TestScheduler(runner=runner, log_fn=lambda l: None)
        runner.start(1)
        s.start()
        s.abort()
        assert s.state == "aborted"
        assert runner.state == "aborted"   # propagated, engine stopped

    def test_pause_blocks_dispatch_resume_continues(self, sched):
        a = sched.submit(_ok_case("a"))
        b = sched.submit(_ok_case("b"))
        sched.start()
        sched.pause()
        assert sched.state == "paused"
        queue_before = list(sched._queue)
        sched._dispatch()               # guarded: nothing while paused
        assert list(sched._queue) == queue_before
        assert a.status == "PENDING"
        sched.resume()
        _drain(sched)
        assert a.status == "PASS" and b.status == "PASS"
        assert sched.state == "idle"

    def test_freeze_keeps_queue_for_review(self, sched):
        sched.submit(_ok_case("a"))
        sched.start()
        stuck = _ok_case("stuck")
        sched._current = stuck          # simulate a running job
        sched.freeze("manual intervention")
        assert sched.state == "frozen"
        assert len(sched._queue) == 1   # queue kept for review
        with pytest.raises(RuntimeError, match="frozen"):
            sched.submit(_ok_case("later"))
        sched.reset_state()
        assert sched.state == "idle"

    def test_illegal_transitions_raise(self, sched):
        with pytest.raises(RuntimeError, match="illegal scheduler"):
            sched._transition("paused", "test")
        sched.start()
        with pytest.raises(RuntimeError, match="already running"):
            sched.start()
        with pytest.raises(RuntimeError, match="resume requires"):
            sched.resume()
        sched.abort()

    def test_trace_logs_have_sched_prefix(self, sched):
        sched.submit(_ok_case("a"))
        sched.start()
        _drain(sched)
        text = "\n".join(sched.lines)
        assert "[SCHED] idle -> running (trigger=operator)" in text
        assert "[SCHED] running -> idle (trigger=auto)" in text
        assert "queued at position" in text
        assert "resource released" in text


class TestMixedNesting:
    def test_suite_with_bare_case_child(self, sched):
        suite = SuiteJob("mixed", [
            BatchJob("b", [_ok_case("g")]),
            _ok_case("final"),          # bare case at suite scope
        ])
        sched.submit(suite)
        sched.start()
        _drain(sched)
        assert suite.verdict == "PASS"
        assert "dispatch: case 'final' (nested in suite 'mixed')" in \
            "\n".join(sched.lines)
