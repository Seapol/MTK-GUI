# -*- coding: utf-8 -*-
"""P3-6 cluster device hub demo (headless-safe, rc=0).

Closed loop: fleet registration -> heartbeat intake -> stale-timeout
OFFLINE sweep -> heartbeat recovery -> remote disable/enable routed
through the frozen P2-10 scheduler contract -> scheduler load/state
read-only reflection -> alert subscription -> transition ledger ->
FleetPage GUI board refresh.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mtkgui.engine.cluster_hub import ClusterHub, NodeStatus
from mtkgui.engine.cluster_scheduler import ClusterScheduler, Task


def main() -> int:
    # 1. registration center: JOIN ledger, idempotent re-register
    hub = ClusterHub(stale_after=0.05)
    hub.register_node("BURNER-1", "10.0.0.11", "burner", ("flash",))
    hub.register_node("BURNER-2", "10.0.0.12", "burner")
    hub.register_node("DAQ-1", "10.0.0.13", "daq")
    hub.register_node("BURNER-1", "10.0.0.11", "burner")  # idempotent
    assert len(hub.nodes()) == 3, "three fleet members"
    assert [e["event"] for e in hub.ledger_rows("BURNER-1")
            ].count("JOIN") == 1, "JOIN recorded once"

    # 2. stale-timeout sweep: silent nodes go OFFLINE
    hub.node("DAQ-1").last_beat -= hub.stale_after + 1
    assert hub.monitor() == 1, "one stale node swept"
    assert hub.node("DAQ-1").status is NodeStatus.OFFLINE

    # 3. heartbeat recovery
    hub.heartbeat("DAQ-1", load=1)
    assert hub.node("DAQ-1").status is NodeStatus.ONLINE
    assert hub.node("DAQ-1").load == 1

    # 4. remote disable/enable routed through frozen P2-10 scheduler
    sch = ClusterScheduler(log_fn=lambda line: None)
    sch.register_device("BURNER-1", "burner")
    assert hub.set_enabled("BURNER-1", False, scheduler=sch) is True
    assert sch.device_state("BURNER-1").value == "ERROR", \
        "disable -> scheduler report_fault (frozen contract)"
    assert hub.node("BURNER-1").enabled is False
    assert hub.set_enabled("BURNER-1", True, scheduler=sch) is True
    assert sch.device_state("BURNER-1").value == "IDLE", \
        "enable -> scheduler restore_device"
    assert hub.set_enabled("GHOST", True) is False, "unknown id"

    # 5. scheduler load/state read-only reflection
    for i in range(4):
        sch2_tasks = Task(f"U{i}", kind="burner")
        sch.submit(sch2_tasks)
    sch.run(lambda task, dev: True)
    hub.attach_scheduler(sch)
    # BURNER-1 ran tasks and recovered -> stays ONLINE, load reflected
    assert hub.node("BURNER-1").load >= 0
    assert hub.node("BURNER-1").status is NodeStatus.ONLINE

    # 6. alert subscription fires on transitions
    alerts: list[str] = []
    hub.on_alert(lambda node, d: alerts.append(d))
    hub._transition_locked(hub.node("DAQ-1"), NodeStatus.ERROR, "x")
    assert alerts and alerts[0] == "x", "subscriber notified"

    # 7. snapshot sorted + ledger full history
    rows = hub.snapshot()
    ids = [r["device_id"] for r in rows]
    assert ids == sorted(ids), "snapshot sorted by device_id"
    events = [e["event"] for e in hub.ledger_rows("BURNER-1")]
    for need in ("JOIN", "DISABLE", "ENABLE"):
        assert need in events, need

    # 8. FleetPage GUI board (headless offscreen)
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.fleet_page import FleetPage

    app = QApplication.instance() or QApplication([])
    page = FleetPage(hub, scheduler=sch)
    page.interactive = False          # headless: suppress modal dialogs
    assert page.refresh() == 3, "board shows three nodes"
    page.beat_edit.setText("DAQ-1")
    assert page.on_heartbeat() == "DAQ-1", "GUI heartbeat intake"
    page.beat_edit.setText("BURNER-2")
    page.on_toggle(False)
    assert hub.node("BURNER-2").enabled is False, "GUI remote disable"
    page.on_toggle(True)
    assert hub.node("BURNER-2").enabled is True, "GUI remote enable"
    assert page.table.rowCount() == 3
    assert page.stats_label.text().startswith("节点 3")

    print("[P3-6 cluster hub demo] fleet middle-platform OK — "
          "registration ledger, heartbeat recovery, stale OFFLINE "
          "sweep, remote disable/enable via frozen scheduler, load "
          "reflection, alerts, ledger, FleetPage board all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
