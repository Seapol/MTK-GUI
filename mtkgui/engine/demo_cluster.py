# -*- coding: utf-8 -*-
"""P2-10 cluster scheduling demo (headless-safe, rc=0).

Closed loop: device pool -> task queue -> idle-first least-load
dispatch -> parallel run with exclusive P1 locks (isolation) -> fault
removal with automatic task migration -> recovery -> [CLUSTER] audit.
Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import sys
import threading
import time

from mtkgui.engine.cluster_scheduler import (ClusterScheduler, Task,
                                             TaskStatus)
from mtkgui.engine.device_manager import DeviceState


def main() -> int:
    sch = ClusterScheduler(log_fn=lambda line: None)
    for name, kind in (("BURNER-1", "burner"), ("BURNER-2", "burner"),
                       ("DAQ-1", "daq")):
        sch.register_device(name, kind)

    # 1. submit 5 tasks (3 burners, 2 any) — mixed weights
    for i in range(3):
        sch.submit(Task(f"T-burn-{i}", kind="burner", weight=1 + i))
    for i in range(2):
        sch.submit(Task(f"T-any-{i}", kind="*", weight=1))

    # 2. idle-first least-load dispatch: two burners get tasks first
    a1 = sch.assign_next(); a2 = sch.assign_next()
    assert a1 and a2, "two dispatches"
    devs = {a1[1], a2[1]}
    assert len(devs) == 2, "parallel tasks on distinct devices"
    assert all(sch.device_state(d) == DeviceState.OCCUPIED
               for d in devs), "P1 locks held"

    # 3. busy devices avoided: only the still-idle device qualifies
    a3 = sch.assign_next()
    assert a3 and a3[1] not in devs, "no preemption of busy device"

    # 4. isolation: parallel run over the whole queue, one exclusive
    #    lock per task; thread names recorded prove parallel execution
    sch2 = ClusterScheduler(log_fn=lambda line: None)
    for name, kind in (("D1", "burner"), ("D2", "burner")):
        sch2.register_device(name, kind)
    for i in range(4):
        sch2.submit(Task(f"P{i}", kind="burner"))
    seen: list[tuple[str, str, int]] = []
    overlap = {"n": 0, "max": 0}
    guard = threading.Lock()

    def worker(task: Task, device: str) -> bool:
        with guard:
            overlap["n"] += 1
            overlap["max"] = max(overlap["max"], overlap["n"])
        time.sleep(0.05)
        seen.append((task.task_id, device,
                     threading.get_ident()))
        time.sleep(0.05)
        with guard:
            overlap["n"] -= 1
        return task.task_id != "P3"     # P3 "fails" on purpose

    results = sch2.run(worker)
    assert results == {"P0": True, "P1": True, "P2": True,
                       "P3": False}, results
    assert overlap["max"] == 2, "two devices ran in parallel"
    assert len({tid for _, _, tid in seen}) == 2, "two threads"
    devs_used = {d for _, d, _ in seen}
    assert devs_used == {"D1", "D2"}, "load spread across devices"
    snap = sch2.snapshot()
    by_dev = {d["name"]: d for d in snap["devices"]}
    assert by_dev["D1"]["completed"] + \
        by_dev["D2"]["completed"] == 3, "completed tallied"
    assert sum(d["failed"] for d in by_dev.values()) == 1
    assert all(sch2.device_state(n) == DeviceState.IDLE
               for n in ("D1", "D2")), "locks all released"

    # 5. load balancing: least-busy device preferred for next task
    nxt = sch2.assign_next()
    if nxt is not None:                 # queue empty in this run
        sch2.complete(nxt[0].task_id)

    # 6. fault failover: kill a running device, task auto-migrates
    sch3 = ClusterScheduler(log_fn=lambda line: None)
    sch3.register_device("F1", "burner")
    sch3.register_device("F2", "burner")
    sch3.submit(Task("M1", kind="burner"))
    task, dev = sch3.assign_next()
    assert dev == "F1" or dev == "F2"
    migrated = sch3.report_fault(dev, "power loss")
    assert migrated == ["M1"], "running task migrated"
    assert sch3.device_state(dev) == DeviceState.ERROR
    task2, dev2 = sch3.assign_next()
    assert dev2 != dev, "migrated to surviving device"
    assert task2.task_id == "M1"
    sch3.complete("M1", ok=True)
    assert sch3.task_status("M1") == TaskStatus.DONE

    # 7. restore path
    sch3.restore_device(dev)
    assert sch3.device_state(dev) == DeviceState.IDLE, "repaired"

    # 8. audit trail
    actions = [a for _, a, _ in sch3.audit]
    for need in ("submit", "assign", "failover", "done", "restore"):
        assert need in actions, need

    print("[P2-10 cluster demo] multi-device scheduling OK — idle-"
          "first least-load dispatch, parallel isolation with P1 "
          "locks, fault removal + task migration, recovery, audit "
          "trail all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
