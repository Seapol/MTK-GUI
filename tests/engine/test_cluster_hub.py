# -*- coding: utf-8 -*-
"""P3-6 cluster hub tests."""
from __future__ import annotations

import time

import pytest

from mtkgui.engine.cluster_hub import CH, ClusterHub, NodeStatus
from mtkgui.engine.cluster_scheduler import ClusterScheduler, Task


def test_register_join_ledger():
    hub = ClusterHub()
    hub.register_node("D1", "10.0.0.1", "burner", ("flash",))
    hub.register_node("D1", "10.0.0.1", "burner")     # idempotent-ish
    assert len(hub.nodes()) == 1
    events = [e["event"] for e in hub.ledger_rows("D1")]
    assert events.count("JOIN") == 1
    assert hub.node("D1").host == "10.0.0.1"


def test_heartbeat_recovery_and_unknown():
    alerts: list[str] = []
    hub = ClusterHub()
    hub.on_alert(lambda node, d: alerts.append(d))
    hub.register_node("D1", "h1")
    hub._nodes["D1"].last_beat -= hub.stale_after + 1
    assert hub.monitor() == 1                          # timeout sweep
    assert hub.node("D1").status is NodeStatus.OFFLINE
    hub.heartbeat("D1", load=2)                        # recovery
    assert hub.node("D1").status is NodeStatus.ONLINE
    assert hub.node("D1").load == 2
    hub.heartbeat("GHOST")                             # unknown id
    assert any("unknown" in a for a in alerts)
    assert any(e["event"] == "ALERT"
               for e in hub.ledger_rows("GHOST"))


def test_monitor_stale_offline():
    hub = ClusterHub(stale_after=0.05)
    hub.register_node("D1", "h1")
    hub.register_node("D2", "h2")
    time.sleep(0.08)
    hub.heartbeat("D2")                                # fresh
    assert hub.monitor() == 1                          # only D1 stale
    assert hub.node("D1").status is NodeStatus.OFFLINE
    assert hub.node("D2").status is NodeStatus.ONLINE


def test_remote_disable_enable_via_scheduler():
    sch = ClusterScheduler(log_fn=lambda line: None)
    sch.register_device("D1", "burner")
    hub = ClusterHub()
    hub.register_node("D1", "h1", "burner")
    assert hub.set_enabled("D1", False, scheduler=sch) is True
    assert sch.device_state("D1").value == "ERROR", \
        "routed through frozen scheduler contract"
    assert hub.node("D1").enabled is False
    hub.set_enabled("D1", True, scheduler=sch)
    assert sch.device_state("D1").value == "IDLE"
    assert hub.node("D1").enabled is True
    assert hub.set_enabled("GHOST", True) is False
    events = [e["event"] for e in hub.ledger_rows("D1")]
    assert "DISABLE" in events and "ENABLE" in events


def test_scheduler_state_reflection():
    sch = ClusterScheduler(log_fn=lambda line: None)
    sch.register_device("D1", "burner")
    sch.register_device("D2", "burner")
    for i in range(4):
        sch.submit(Task(f"U{i}", kind="burner"))
    sch.run(lambda task, dev: True)
    hub = ClusterHub()
    hub.register_node("D1", "h1")
    hub.register_node("D2", "h2")
    hub.attach_scheduler(sch)
    loads = {n.device_id: n.load for n in hub.nodes()}
    assert loads == {"D1": 2, "D2": 2}, "scheduler load reflected"


def test_snapshot_rows_and_alert_subscription():
    alerts: list[tuple] = []
    hub = ClusterHub()
    hub.on_alert(lambda node, d: alerts.append(
        (node.device_id if node else None, d)))
    hub.register_node("B", "h2")
    hub.register_node("A", "h1")
    rows = hub.snapshot()
    assert [r["device_id"] for r in rows] == ["A", "B"], "sorted"
    assert rows[0]["status"] == "ONLINE"
    assert "beats_ago_s" in rows[0]
    hub._transition_locked(hub.node("A"), NodeStatus.ERROR, "x")
    assert alerts and alerts[0][0] == "A"


def test_ch_alias_export():
    assert CH is ClusterHub
