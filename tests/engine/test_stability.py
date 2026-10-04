# -*- coding: utf-8 -*-
"""Stability primitives (P1 Task12): locks with residue sweep, bounded
queue, heartbeat reaping, circuit breaker, station inspection."""
from __future__ import annotations

import time

import pytest

from mtkgui.engine.stability import (BoundedQueue, BreakerOpen,
                                     CircuitBreaker, HeartbeatMonitor,
                                     LockHeld, QueueFull,
                                     ResourceLocks, StationInspector)


class TestResourceLocks:
    def test_acquire_release_and_nesting(self):
        locks = ResourceLocks()
        locks.acquire("rack", "flow-1")
        locks.acquire("rack", "flow-1")          # nested re-entry
        locks.release("rack", "flow-1")
        assert "rack" in locks.held()            # still nested once
        locks.release("rack", "flow-1")
        assert "rack" not in locks.held()

    def test_conflict_rejected_not_deadlocked(self):
        locks = ResourceLocks(default_timeout_s=0.05)
        locks.acquire("rack", "a")
        with pytest.raises(LockHeld, match="held by 'a'"):
            locks.acquire("rack", "b", timeout_s=0.01)

    def test_stale_holder_swept_inline(self):
        locks = ResourceLocks(default_timeout_s=0.02)
        locks.acquire("rack", "ghost")
        time.sleep(0.05)
        locks.acquire("rack", "fresh")           # inline residue sweep
        assert locks.held()["rack"] == "fresh"

    def test_periodic_sweep_releases_residue(self):
        locks = ResourceLocks(default_timeout_s=0.02)
        locks.acquire("daq", "zombie")
        time.sleep(0.05)
        assert locks.sweep() == ["daq"]
        assert locks.held() == {}

    def test_renew_extends_deadline(self):
        locks = ResourceLocks(default_timeout_s=0.02)
        locks.acquire("psu", "long-task")
        time.sleep(0.03)
        locks.renew("psu", "long-task", timeout_s=1.0)
        assert locks.sweep() == []               # renewed, survives


class TestBoundedQueue:
    def test_overflow_rejected_with_metric(self):
        q = BoundedQueue(maxsize=3)
        for i in range(3):
            q.put(i)
        with pytest.raises(QueueFull):
            q.put(4)
        assert q.rejected_count == 1 and len(q) == 3
        assert q.pop() == 0                      # FIFO intact

    def test_rejections_accumulate(self):
        q = BoundedQueue(maxsize=1)
        q.put("x")
        for _ in range(5):
            with pytest.raises(QueueFull):
                q.put("y")
        assert q.rejected_count == 5


class TestHeartbeatMonitor:
    def test_silent_hang_detected_and_reaped(self):
        lines: list[str] = []
        m = HeartbeatMonitor(log_fn=lines.append)
        m.register("worker-1", interval_s=0.01)
        time.sleep(0.05)                         # no beats: silent hang
        assert m.stale_tasks() == ["worker-1"]
        assert m.reap() == ["worker-1"]
        assert any("zombie task 'worker-1'" in line
                   for line in lines)

    def test_live_task_not_reaped(self):
        m = HeartbeatMonitor()
        m.register("worker-1", interval_s=10.0)
        m.beat("worker-1")
        assert m.reap() == []

    def test_reaped_task_terminates_once(self):
        m = HeartbeatMonitor()
        m.register("w", interval_s=0.01)
        time.sleep(0.05)
        assert m.reap() == ["w"]
        assert m.reap() == []                    # no double reap


class TestCircuitBreaker:
    def test_opens_after_consecutive_timeouts(self):
        cb = CircuitBreaker(trip_after=3)
        cb.record_timeout()
        cb.record_timeout()
        cb.check()                               # still closed
        cb.record_timeout()
        with pytest.raises(BreakerOpen):
            cb.check()
        assert cb.state == "open"

    def test_success_resets(self):
        cb = CircuitBreaker(trip_after=2)
        cb.record_timeout()
        cb.record_success()
        cb.record_timeout()
        cb.check()                               # reset by success

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(trip_after=1, cooldown_s=0.02)
        cb.record_timeout()
        assert cb.state == "open"
        time.sleep(0.03)
        assert cb.state == "half-open"
        cb.check()                               # one probe allowed
        cb.record_success()
        assert cb.state == "closed"


class TestStationInspector:
    def test_inspection_runs_all_recoveries(self):
        lines: list[str] = []
        locks = ResourceLocks(default_timeout_s=0.01)
        locks.acquire("rack", "ghost")
        q = BoundedQueue(maxsize=2)
        q.put("a")
        m = HeartbeatMonitor(log_fn=lines.append)
        m.register("w", 0.01)
        time.sleep(0.04)
        insp = StationInspector(locks, q, m, log_fn=lines.append)
        report = insp.inspect_once()
        assert report["locks_swept"] == ["rack"]
        assert report["tasks_reaped"] == ["w"]
        assert report["queue_len"] == 1
        assert report["round"] == 1
        assert any("[STAB] inspection #1" in line
                   for line in lines)

    def test_rounds_increment(self):
        insp = StationInspector(ResourceLocks(), BoundedQueue(),
                                HeartbeatMonitor(),
                                log_fn=lambda line: None)
        insp.inspect_once()
        assert insp.inspect_once()["round"] == 2
