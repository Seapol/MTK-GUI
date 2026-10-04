# -*- coding: utf-8 -*-
"""Layered test scheduling - single case / batch / suite (P1 Task4).

The engine runs ONE test flow at a time (the TestRunner state machine
owns the station hardware).  On top of that fixed resource this module
adds industrial layered scheduling WITHOUT touching the runner core:

  case   - the smallest scheduling unit: one callable that returns
           "PASS" / "FAIL" / "Error"; light and fast
  batch  - an ordered list of cases; sequential by default, optional
           parallel execution with a bounded worker pool
  suite  - an ordered list of batches under one uniform state control;
           aggregated verdict, abort/pause propagate to every level

Scheduling discipline (station-resource contention):
  * strict FIFO - jobs never overtake queued jobs (no queue jumping)
  * the station (runner) is an exclusive token: a runner-backed job
    only starts when the runner is idle (can_start); the scheduler
    propagates pause/abort to the bound runner and releases it
    afterwards (no resource leakage)
  * cooperative cancellation - case functions poll ctx.cancelled so a
    suite/batch abort stops between cases, never mid-measurement
  * every scheduler-level change leaves a structured "[SCHED]" log
    line (state transitions use the same five states as the runner)

The scheduler is UI-free and PySide6-optional: it uses a QTimer for
event-loop dispatch but executes jobs synchronously between timer
ticks, so plain pytest can drive it without an event loop.
"""
from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

CASE_STATUSES = ("PASS", "FAIL", "Error")
JOB_STATUSES = ("PENDING", "PASS", "FAIL", "Error",
                "SKIPPED", "ABORTED")


class JobContext:
    """Handed to every case function: logging, cancellation flag and
    (optionally) the bound runner for engine-backed cases."""

    def __init__(self, scheduler: "TestScheduler"):
        self._scheduler = scheduler

    @property
    def cancelled(self) -> bool:
        return self._scheduler._cancel_token

    @property
    def runner(self):
        return self._scheduler.runner

    def log(self, message: str) -> None:
        self._scheduler._log(f"job: {message}")

    def start_runner(self, lr_total: int = 1) -> None:
        """Run one engine cycle with the bound runner (exclusive)."""
        runner = self.runner
        if runner is None:
            raise RuntimeError("no runner bound to the scheduler")
        if not runner.can_start:
            raise RuntimeError(
                f"station busy: runner state '{runner.state}'")
        runner.start(lr_total)


@dataclass
class CaseJob:
    """Level 1 - a single lightweight test case."""
    name: str
    fn: Callable[[JobContext], str]
    level: str = "case"
    status: str = "PENDING"
    detail: str = ""
    duration_s: float = 0.0

    def run(self, ctx: JobContext) -> None:
        t0 = time.monotonic()
        try:
            status = str(self.fn(ctx))
            self.status = status if status in CASE_STATUSES else "Error"
            if self.status == "Error":
                self.detail = f"invalid case status {status!r}"
        except Exception as exc:            # case-level containment
            self.status = "Error"
            self.detail = f"{type(exc).__name__}: {exc}"
        self.duration_s = time.monotonic() - t0


@dataclass
class BatchJob:
    """Level 2 - an ordered batch of cases (sequential or parallel)."""
    name: str
    cases: list[CaseJob]
    parallel: bool = False
    max_workers: int = 2
    level: str = "batch"
    status: str = "PENDING"
    duration_s: float = 0.0

    @property
    def verdict(self) -> str:
        statuses = {c.status for c in self.cases}
        if "Error" in statuses:
            return "Error"
        if "FAIL" in statuses:
            return "FAIL"
        if statuses <= {"PASS"}:
            return "PASS"
        return "Error"                      # incomplete / skipped


@dataclass
class SuiteJob:
    """Level 3 - batches under one uniform state control."""
    name: str
    batches: list[BatchJob]
    level: str = "suite"
    status: str = "PENDING"
    duration_s: float = 0.0

    @property
    def verdict(self) -> str:
        verdicts = {
            b.verdict if isinstance(b, BatchJob) else b.status
            for b in self.batches}
        if "Error" in verdicts:
            return "Error"
        if "FAIL" in verdicts:
            return "FAIL"
        if verdicts <= {"PASS"}:
            return "PASS"
        return "Error"


def _verdict_of(job) -> str:  # kept for external verdict lookups
    if isinstance(job, SuiteJob) or isinstance(job, BatchJob):
        return job.verdict
    return job.status if job.status in CASE_STATUSES else "Error"


class TestScheduler(QObject):
    """FIFO layered scheduler with runner-state-machine alignment."""

    job_started = Signal(object)
    job_finished = Signal(object)
    queue_drained = Signal(dict)            # final report

    # same five states and legal transitions as TestRunner
    _LEGAL_TRANSITIONS = {
        "idle": {"running"},
        "running": {"paused", "aborted", "frozen", "idle"},
        "paused": {"running", "aborted", "frozen", "idle"},
        "aborted": {"idle"},
        "frozen": {"idle"},
    }

    def __init__(self, runner=None, log_fn: Optional[Callable[[str], None]]
                 = None, parent=None):
        super().__init__(parent)
        self.runner = runner
        self._log_fn = log_fn or (lambda line: print(line))
        self.state = "idle"
        self._queue: deque = deque()
        self._current = None
        self._cancel_token = False
        self._executed: list = []
        self.last_report: dict | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._dispatch)

    # ------------------------------------------------------------ state
    def _transition(self, new_state: str, trigger: str) -> None:
        legal = self._LEGAL_TRANSITIONS.get(self.state, set())
        if new_state not in legal:
            raise RuntimeError(
                f"illegal scheduler transition: {self.state} -> {new_state}")
        old = self.state
        self.state = new_state
        self._log(f"[SCHED] {old} -> {new_state} (trigger={trigger})")

    def _log(self, line: str) -> None:
        self._log_fn(f"[SCHED] {line}" if not line.startswith("[")
                     else line)

    def start(self) -> None:
        if self.state == "paused":
            raise RuntimeError(
                "cannot start from 'paused': resume() or abort() first")
        if self.state == "running":
            raise RuntimeError("cannot start: scheduler already running")
        if self.state in ("aborted", "frozen"):
            self._transition("idle", "reset")
        self._transition("running", "operator")
        self._cancel_token = False
        self._timer.start()

    def pause(self) -> None:
        if self.state != "running":
            raise RuntimeError(
                f"pause requires state 'running' (got '{self.state}')")
        self._transition("paused", "operator")
        # propagate to the engine: pause takes effect at the next step
        if self.runner is not None and self.runner.state == "running":
            self.runner.pause()

    def resume(self) -> None:
        if self.state != "paused":
            raise RuntimeError(
                f"resume requires state 'paused' (got '{self.state}')")
        self._transition("running", "operator")
        if self.runner is not None and self.runner.state == "paused":
            self.runner.resume()
        self._timer.start()

    def abort(self) -> None:
        """Operator terminate: the running job is cancelled
        cooperatively, everything still queued is marked SKIPPED."""
        if self.state not in ("running", "paused"):
            return
        self._cancel_token = True
        if self.runner is not None and self.runner.state in (
                "running", "paused"):
            self.runner.abort()
        for job in self._queue:
            _mark_skipped(job)
        self._queue.clear()
        if self._current is not None and self._current.status == "PENDING":
            self._current.status = "ABORTED"
        self._transition("aborted", "operator")

    def freeze(self, reason: str = "unexpected error") -> None:
        """Safety freeze: stop dispatching, keep the queue for review."""
        if self.state not in ("running", "paused"):
            return
        self._transition("frozen", "system")
        self._log(f"scheduler frozen: {reason}")

    def reset_state(self) -> str:
        if self.state == "idle":
            return "idle"
        self._timer.stop()
        self._cancel_token = False
        self._transition("idle", "reset")
        return self.state

    # ------------------------------------------------------------ queue
    def submit(self, job) -> object:
        """Queue a job (case / batch / suite).  Strict FIFO: the job
        never overtakes earlier submissions (no queue jumping)."""
        if job.level not in ("case", "batch", "suite"):
            raise ValueError(f"unknown job level {job.level!r}")
        if self.state == "frozen":
            raise RuntimeError("scheduler frozen: reset_state() first")
        self._queue.append(job)
        self._log(f"queue: {job.level} '{job.name}' queued at position "
                  f"{len(self._queue)}")
        return job

    def _report(self) -> dict:
        jobs = list(self._executed)
        totals: dict[str, int] = {}
        for job in jobs:
            totals[job.status] = totals.get(job.status, 0) + 1
        return {"total": len(jobs), "by_status": totals}

    def _dispatch(self) -> None:
        """Timer tick: dispatch the queue head while running."""
        while True:
            if self.state != "running":
                self._timer.stop()
                return
            if self._current is not None:
                self._timer.stop()
                return
            if not self._queue:
                self._timer.stop()
                report = self._report()
                self.last_report = report
                self._transition("idle", "auto")
                self._log(f"queue drained: {report['total']} job(s) "
                          f"{report['by_status']}")
                self.queue_drained.emit(report)
                return
            job = self._queue.popleft()
            self._log(f"dispatch: {job.level} '{job.name}' "
                      f"(resource: station)")
            self._current = job
            self.job_started.emit(job)
            requeued = False
            try:
                self._run_job(job)
            except Exception as exc:
                # P1 Task5: fine-grained failure branches (timeout gets
                # one reset+requeue, resource aborts, rest freezes)
                requeued = self._handle_failure(exc, job)
                if not requeued:
                    self._current = None
                    return
            self._current = None
            self._release_current(job)
            if requeued:
                continue            # timeout reset: re-run, no bookkeeping
            self._executed.append(job)
            self.job_finished.emit(job)

    def _handle_failure(self, exc: Exception, job) -> bool:
        """Classify a dispatch-time failure and apply its policy.
        Returns True when dispatching may continue."""
        from .failures import FailureKind, classify_exception, \
            failure_log_line
        event = classify_exception(exc, source="scheduler")
        retried = getattr(job, "_timeout_retried", False)
        if event.kind is FailureKind.TIMEOUT and not retried:
            job._timeout_retried = True
            self._log(failure_log_line(event, "reset+requeue-once"))
            self._queue.appendleft(job)     # reset strategy: re-run once
            return True
        action = ("abort" if event.kind is FailureKind.RESOURCE
                  else "freeze")
        self._log(failure_log_line(event, action))
        if event.kind is FailureKind.RESOURCE:
            self.abort()
        else:
            self.freeze(f"{event.kind.value}: {event.message}")
        return False

    def _release_current(self, job) -> None:
        """Release the station token; a failed release must never
        leave the scheduler hanging on a phantom resource."""
        try:
            self._log(f"resource released: {job.level} '{job.name}'")
        except Exception as exc:            # release failure -> freeze
            self.freeze(f"resource release failed: {exc!r}")

    def _run_job(self, job) -> None:
        ctx = JobContext(self)
        t0 = time.monotonic()
        if isinstance(job, SuiteJob):
            for child in job.batches:   # batches or bare cases
                if ctx.cancelled:
                    _mark_skipped(child)
                    continue
                self._log(f"dispatch: {child.level} '{child.name}' "
                          f"(nested in suite '{job.name}')")
                if isinstance(child, BatchJob):
                    self._run_job(child)
                else:
                    child.run(ctx)
            job.status = job.verdict
        elif isinstance(job, BatchJob):
            if job.parallel and len(job.cases) > 1:
                self._log(f"dispatch (parallel x{job.max_workers}): "
                          f"{len(job.cases)} case(s) of batch "
                          f"'{job.name}'")
                with ThreadPoolExecutor(
                        max_workers=max(1, job.max_workers)) as pool:
                    list(pool.map(lambda c: c.run(ctx), job.cases))
            else:
                for case in job.cases:
                    if ctx.cancelled:
                        case.status = "SKIPPED"
                        continue
                    self._log(f"dispatch: case '{case.name}' "
                              f"(nested in batch '{job.name}')")
                    case.run(ctx)
            job.status = job.verdict
        else:
            job.run(ctx)
        job.duration_s = time.monotonic() - t0
        self._log(f"done: {job.level} '{job.name}' -> {job.status} "
                  f"({job.duration_s:.2f} s, resource released)")


def _mark_skipped(job) -> None:
    if isinstance(job, SuiteJob):
        for batch in job.batches:
            _mark_skipped(batch)
        job.status = "SKIPPED"
    elif isinstance(job, BatchJob):
        for case in job.cases:
            if case.status == "PENDING":
                case.status = "SKIPPED"
        job.status = "SKIPPED"
    elif job.status == "PENDING":
        job.status = "SKIPPED"
