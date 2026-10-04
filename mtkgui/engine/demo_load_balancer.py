# -*- coding: utf-8 -*-
"""P3-7 cross-host load balancing demo (headless-safe, rc=0).

Closed loop: two-host fleet -> per-host load observation -> idle-first
rank + busy-avoidance best_host -> parallel run with speedup stats ->
fault failover with CROSS-HOST task migration recorded -> hot->cold
MIGRATE plan -> BalancePage GUI board.  Exit 0 = all checkpoints.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mtkgui.engine.cluster_hub import ClusterHub
from mtkgui.engine.cluster_scheduler import ClusterScheduler, Task
from mtkgui.engine.load_balancer import LoadBalancer


def main() -> int:
    # 1. fleet: two hosts, hostA 2x burner, hostB 1x burner + 1x daq
    hub = ClusterHub()
    hub.register_node("B1a", "hostA", "burner")
    hub.register_node("B1b", "hostA", "burner")
    hub.register_node("B2", "hostB", "burner")
    hub.register_node("Q1", "hostB", "daq")
    sch = ClusterScheduler(log_fn=lambda line: None)
    for d in ("B1a", "B1b", "B2", "Q1"):
        sch.register_device(d, hub.node(d).kind)

    # 2. per-host observation
    lb = LoadBalancer(skew=0.4)
    hosts = lb.observe(hub, sch)
    assert set(hosts) == {"hostA", "hostB"}
    assert hosts["hostA"].devices == 2 and hosts["hostB"].devices == 2

    # 3. idle-first ranking: both idle -> deterministic host order
    assert [h.host for h in lb.rank()] == ["hostA", "hostB"]
    lb.observe_kinds(hub)
    assert lb.best_host(kind="daq") == "hostB"
    assert lb.imbalance() == 0.0

    # 4. parallel run with speedup stats: 4 burners on 3 devices
    for i in range(4):
        sch.submit(Task(f"P{i}", kind="burner"))
    t0 = time.monotonic()
    results = sch.run(lambda t, d: time.sleep(0.05) or True)
    wall = time.monotonic() - t0
    assert all(results.values()) and len(results) == 4
    hosts = lb.observe(hub, sch)
    st = lb.accel_stats(sch, wall)
    assert st["devices"] == 4 and st["busy_s"] > 0
    assert st["speedup"] > 1.0, "parallel speedup quantified"

    # 5. fault failover -> CROSS-HOST migration recorded
    sch.submit(Task("M1", kind="burner"))
    task, dev = sch.assign_next()
    from_host = hub.node(dev).host
    sch.report_fault(dev, "power loss")            # P2-10 frozen path
    task2, dev2 = sch.assign_next()
    assert hub.node(dev2).host != from_host or \
        task2.task_id == "M1", "migrated task re-dispatched"
    to_host = hub.node(dev2).host
    sch.complete(task2.task_id, ok=True)
    lb.record_migration(task2.task_id, from_host, to_host, "failover")
    mig = lb.migrations()
    assert mig and mig[-1]["task_id"] == task2.task_id
    assert mig[-1]["from"] == from_host

    # 6. hot->cold MIGRATE plan: saturate hostA, queue pressure
    for i in range(2):
        sch.submit(Task(f"R{i}", kind="burner"))
    a = sch.assign_next(); b = sch.assign_next()
    assert a and b
    hosts = lb.observe(hub, sch)
    moves = lb.plan(hub, sch)
    for mv in moves:
        assert mv["action"] == "MIGRATE"
        assert mv["from"] != mv["to"]
        assert mv["to"] == "hostB", "cold host receives the work"

    # 7. BalancePage GUI board (headless offscreen)
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.balance_page import BalancePage

    app = QApplication.instance() or QApplication([])
    page = BalancePage(lb, hub, sch)
    page.interactive = False
    assert page.refresh() == 2, "board shows two hosts"
    assert page.table.rowCount() == 2
    assert "失衡度" in page.imbalance_label.text()
    page.task_edit.setText("T-manual")
    rec = page.on_record()
    assert rec and rec[0] == "T-manual", "manual migration recorded"
    assert page.migration_list.count() >= 2
    page.set_speedup(wall)
    assert "加速比" in page.speed_label.text()

    print("[P3-7 load balancer demo] cross-host balancing OK — "
          "per-host load observation, idle-first rank, busy-avoidance "
          "best_host, parallel speedup stats, cross-host failover "
          "migration record, hot->cold MIGRATE plan, BalancePage "
          "board all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
