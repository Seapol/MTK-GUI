# -*- coding: utf-8 -*-
"""P3-5 task queue tests."""
from __future__ import annotations

import threading
import time

import pytest

from mtkgui.engine.task_queue import TaskQueue, TaskStatus


def test_priority_order_and_fifo_tiebreak():
    q = TaskQueue(poll=0.001)
    order: list[str] = []
    q.submit("low", priority=1)
    q.submit("high1", priority=9)
    q.submit("high2", priority=9)
    q.submit("mid", priority=5)
    q.run(lambda t: order.append(t.payload) or t.payload,
          workers=1)
    assert order == ["high1", "high2", "mid", "low"], order
    assert q.stats()["DONE"] == 4


def test_parallel_workers():
    q = TaskQueue(poll=0.001)
    for i in range(8):
        q.submit(f"j{i}")
    ran: list[str] = []
    guard = threading.Lock()

    def handler(task):
        time.sleep(0.03)
        with guard:
            ran.append(task.tid)
        return True

    assert q.run(handler, workers=4)["DONE"] == 8
    assert len(ran) == 8


def test_retry_until_exhausted():
    q = TaskQueue(poll=0.001)
    t = q.submit("boom", max_retries=2)

    def handler(task):
        raise ValueError("always fails")

    q.run(handler, workers=1)
    assert t.status is TaskStatus.FAILED
    assert t.attempts == 3, "1 initial + 2 retries"
    assert "ValueError" in t.error
    assert q.stats()["FAILED"] == 1


def test_retry_then_success():
    q = TaskQueue(poll=0.001)
    t = q.submit("flaky", max_retries=3)
    calls = {"n": 0}

    def handler(task):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("flaky")
        return "ok"

    q.run(handler, workers=1)
    assert t.status is TaskStatus.DONE and t.result == "ok"
    assert t.attempts == 2


def test_journal_restore_pending_tasks(tmp_path):
    jp = tmp_path / "queue.json"
    q1 = TaskQueue(journal_path=jp, poll=0.001)
    q1.submit("a", priority=5)
    q1.submit("b", priority=1)
    done = q1.submit("c", priority=9)
    q1.run(lambda t: "x", workers=1)      # all done; journal emptied
    assert done.status is TaskStatus.DONE
    # simulate crash mid-flight: submit then DON'T run
    q2 = TaskQueue(journal_path=jp, poll=0.001)
    q2.submit("survivor", priority=3)
    q2.submit("survivor2", priority=3)
    # new queue instance over the same journal re-queues them
    q3 = TaskQueue(journal_path=jp, poll=0.001)
    assert q3.stats()["PENDING"] == 2
    out: list[str] = []
    q3.run(lambda t: out.append(t.payload), workers=1)
    assert sorted(out) == ["survivor", "survivor2"], "nothing lost"
    assert q3.stats()["DONE"] == 2


def test_snapshot_rows_shape():
    q = TaskQueue(poll=0.001)
    q.submit("p1", priority=2, max_retries=1)
    rows = q.snapshot()
    assert rows[0]["payload"] == "p1"
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["priority"] == 2
    assert rows[0]["max_retries"] == 1


def test_immediate_execution_untouched():
    """Compat: no journal -> pure in-memory queue, P2 flows unaffected."""
    q = TaskQueue(poll=0.001)
    t = q.submit("x")
    assert q.run(lambda task: task.payload, workers=1)["DONE"] == 1
    assert t.result == "x"
