# -*- coding: utf-8 -*-
"""P2-10 cluster scheduler tests."""
from __future__ import annotations

import threading
import time

import pytest

from mtkgui.engine.cluster_scheduler import (ClusterScheduler, Task,
                                             TaskStatus)
from mtkgui.engine.device_manager import DeviceState, DeviceStateError


@pytest.fixture()
def sch():
    s = ClusterScheduler(log_fn=lambda line: None)
    s.register_device("B1", "burner")
    s.register_device("B2", "burner")
    s.register_device("Q1", "daq")
    return s


def test_register_and_snapshot(sch):
    devs = {d["name"]: d for d in sch.devices()}
    assert set(devs) == {"B1", "B2", "Q1"}
    assert devs["B1"]["kind"] == "burner"
    snap = sch.snapshot()
    assert snap["states"] == {"B1": "IDLE", "B2": "IDLE",
                              "Q1": "IDLE"}
    assert snap["queue"] == [] and snap["running"] == []


def test_idle_first_least_load_dispatch(sch):
    for i in range(3):
        sch.submit(Task(f"T{i}", kind="burner"))
    t0, d0 = sch.assign_next()
    t1, d1 = sch.assign_next()
    assert {d0, d1} == {"B1", "B2"}, "two idle devices picked"
    assert sch.device_state(d0) == DeviceState.OCCUPIED
    # third dispatch: busy devices avoided -> only... none idle left
    # of kind burner except Q1 is daq; burner task must wait
    assert sch.assign_next() is None, "busy devices not preempted"
    assert sch.queue_depth() == 1, "task stays queued"


def test_kind_matching(sch):
    sch.submit(Task("D", kind="daq"))
    task, dev = sch.assign_next()
    assert dev == "Q1"


def test_complete_releases_and_tallies(sch):
    sch.submit(Task("X", kind="burner"))
    task, dev = sch.assign_next()
    sch.complete("X", ok=True)
    assert sch.task_status("X") == TaskStatus.DONE
    assert sch.device_state(dev) == DeviceState.IDLE
    snap = sch.snapshot()
    assert snap["devices"][0]["completed"] in (0, 1)
    total = sum(d["completed"] for d in snap["devices"])
    assert total == 1
    assert sch.task_status("ghost") is None


def test_complete_failure_tallied(sch):
    sch.submit(Task("Y", kind="burner"))
    sch.assign_next()
    sch.complete("Y", ok=False)
    assert sch.task_status("Y") == TaskStatus.FAILED
    assert any(d["failed"] == 1 for d in sch.devices())


def test_parallel_run_isolation_and_balance():
    sch = ClusterScheduler(log_fn=lambda line: None)
    for n in ("D1", "D2", "D3"):
        sch.register_device(n, "burner")
    for i in range(9):
        sch.submit(Task(f"P{i}", kind="burner"))
    held: dict[str, str] = {}
    conflicts = []
    guard = threading.Lock()

    def worker(task: Task, device: str) -> bool:
        with guard:
            if device in held:
                conflicts.append(device)   # two tasks on one device!
            held[device] = task.task_id
        time.sleep(0.03)
        with guard:
            del held[device]
        return True

    results = sch.run(worker)
    assert len(results) == 9 and all(results.values())
    assert conflicts == [], "no double-occupation ever"
    used = {d for _, d in ((t.device, d) for t, d in [])} | set()
    # balance: each device got 3 of 9
    counts = {d["name"]: d["completed"] for d in sch.devices()}
    assert set(counts.values()) == {3}, counts


def test_parallel_run_exception_is_failure():
    sch = ClusterScheduler(log_fn=lambda line: None)
    sch.register_device("D", "burner")
    sch.submit(Task("boom", kind="burner"))
    sch.submit(Task("ok", kind="burner"))

    def worker(task: Task, device: str) -> bool:
        if task.task_id == "boom":
            raise RuntimeError("worker crash")
        return True

    results = sch.run(worker)
    assert results == {"boom": False, "ok": True}
    assert sch.device_state("D") == DeviceState.IDLE


def test_fault_failover_migration(sch):
    sch.submit(Task("M1", kind="burner"))
    task, dev = sch.assign_next()
    other = "B2" if dev == "B1" else "B1"
    migrated = sch.report_fault(dev, "power loss")
    assert migrated == ["M1"]
    assert sch.device_state(dev) == DeviceState.ERROR
    t2, dev2 = sch.assign_next()
    assert dev2 == other and t2.task_id == "M1"
    sch.complete("M1", ok=True)
    assert sch.task_status("M1") == TaskStatus.DONE


def test_restore_device(sch):
    sch.submit(Task("R", kind="burner"))
    _, dev = sch.assign_next()
    sch.report_fault(dev, "fault")
    with pytest.raises(DeviceStateError):
        sch.dm.acquire(dev, "probe")      # ERROR not acquireable
    sch.restore_device(dev)
    assert sch.device_state(dev) == DeviceState.IDLE


def test_audit_trail(sch):
    sch.submit(Task("A", kind="burner"))
    _, dev = sch.assign_next()
    sch.complete("A", ok=True)
    sch.report_fault(dev, "demo")
    actions = [a for _, a, _ in sch.audit]
    for need in ("submit", "assign", "done", "failover"):
        assert need in actions, need
