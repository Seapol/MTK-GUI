# -*- coding: utf-8 -*-
"""P3-7 cross-host load balancer tests."""
from __future__ import annotations

import time

import pytest

from mtkgui.engine.cluster_hub import ClusterHub, NodeStatus
from mtkgui.engine.cluster_scheduler import ClusterScheduler, Task
from mtkgui.engine.load_balancer import LB, HostLoad, LoadBalancer


def test_observe_groups_by_host():
    hub = ClusterHub()
    hub.register_node("D1", "hostA", "burner")
    hub.register_node("D2", "hostA", "burner")
    hub.register_node("D3", "hostB", "daq")
    sch = ClusterScheduler(log_fn=lambda line: None)
    for d in ("D1", "D2", "D3"):
        sch.register_device(d, hub.node(d).kind)
    for i in range(2):
        sch.submit(Task(f"T{i}", kind="burner"))
    sch.run(lambda t, d: time.sleep(0.02) or True)  # busy_s accumulated
    lb = LoadBalancer()
    hosts = lb.observe(hub, sch)
    assert set(hosts) == {"hostA", "hostB"}
    assert hosts["hostA"].devices == 2
    assert hosts["hostA"].completed == 2
    assert hosts["hostB"].completed == 0
    assert hosts["hostA"].busy_s > 0


def test_rank_idle_first():
    lb = LoadBalancer()
    lb._hosts = {"hot": HostLoad(host="hot", devices=2, active=2,
                                 busy_s=100),
                 "cold": HostLoad(host="cold", devices=2, active=0)}
    assert [h.host for h in lb.rank()] == ["cold", "hot"]


def test_best_host_busy_avoidance_and_kind():
    hub = ClusterHub()
    hub.register_node("B1", "hostA", "burner")
    hub.register_node("B2", "hostA", "burner")
    hub.register_node("Q1", "hostB", "daq")
    lb = LoadBalancer()
    lb.observe_kinds(hub)
    lb._hosts = {"hostA": HostLoad(host="hostA", devices=2, active=2),
                 "hostB": HostLoad(host="hostB", devices=1, active=0)}
    # hostA fully busy -> avoided even though it would rank first
    assert lb.best_host() == "hostB"
    # daq kind only exists on hostB
    assert lb.best_host(kind="daq") == "hostB"
    # burner kind exists only on hostA, which is busy -> None
    assert lb.best_host(kind="burner") is None
    # dead host avoided
    lb._hosts["hostB"].offline = 1
    assert lb.best_host() is None


def test_imbalance_skew_metric():
    lb = LoadBalancer()
    lb._hosts = {"a": HostLoad(host="a", devices=2, active=2),
                 "b": HostLoad(host="b", devices=2, active=0)}
    assert lb.imbalance() == 1.0
    lb._hosts["a"].active = 1
    assert lb.imbalance() == 0.5
    lb._hosts = {}
    assert lb.imbalance() == 0.0


def test_plan_proposes_hot_to_cold_migration():
    hub = ClusterHub()
    hub.register_node("B1a", "hostA", "burner")
    hub.register_node("B1b", "hostA", "burner")
    hub.register_node("B2", "hostB", "burner")
    sch = ClusterScheduler(log_fn=lambda line: None)
    for d in ("B1a", "B1b", "B2"):
        sch.register_device(d, "burner")
    # occupy both hostA devices (still RUNNING) -> hot; hostB idle
    sch.submit(Task("R1", kind="burner"))
    sch.submit(Task("R2", kind="burner"))
    d1 = sch.assign_next()
    d2 = sch.assign_next()
    assert {d1[1], d2[1]} == {"B1a", "B1b"}
    sch.submit(Task("Q9", kind="burner"))          # queued pressure
    lb = LoadBalancer(skew=0.4)
    moves = lb.plan(hub, sch)
    assert moves and moves[0]["action"] == "MIGRATE"
    assert moves[0]["from"] == "hostA" and moves[0]["to"] == "hostB"
    assert moves[0]["kind"] == "burner"


def test_migration_record_and_view():
    lb = LoadBalancer()
    lb.record_migration("T1", "hostA", "hostB", "failover")
    lb.record_migration("T2", "hostA", "hostC")
    rows = lb.migrations()
    assert rows[0] == {"task_id": "T1", "from": "hostA",
                       "to": "hostB", "reason": "failover"}
    assert len(rows) == 2


def test_accel_stats_parallel_speedup():
    sch = ClusterScheduler(log_fn=lambda line: None)
    sch.register_device("D1", "burner")
    sch.register_device("D2", "burner")
    for i in range(4):
        sch.submit(Task(f"P{i}", kind="burner"))
    t0 = time.monotonic()
    sch.run(lambda t, d: time.sleep(0.05) or True)
    wall = time.monotonic() - t0
    lb = LoadBalancer()
    st = lb.accel_stats(sch, wall)
    assert st["devices"] == 2
    # 4 x 0.05s busy over ~0.1s wall -> speedup ~2 with 2 devices
    assert st["speedup"] > 1.2, st
    assert 0 < st["efficiency"] <= 1.0


def test_hosts_view_sorted_rows_and_alias():
    lb = LoadBalancer()
    lb._hosts = {"b": HostLoad(host="b", devices=1),
                 "a": HostLoad(host="a", devices=3, active=1)}
    rows = lb.hosts_view()
    assert [r["host"] for r in rows] == ["a", "b"]
    assert rows[0]["utilization"] == 0.333
    assert LB is LoadBalancer


def test_offline_penalty_in_score_and_hub_error_state():
    hub = ClusterHub()
    hub.register_node("X1", "hostA", "burner")
    hub.register_node("Y1", "hostB", "burner")
    sch = ClusterScheduler(log_fn=lambda line: None)
    sch.register_device("X1", "burner")
    sch.register_device("Y1", "burner")
    lb = LoadBalancer()
    hub._transition_locked(hub.node("X1"), NodeStatus.OFFLINE, "gone")
    hosts = lb.observe(hub, sch)
    assert hosts["hostA"].offline == 1
    assert hosts["hostA"].devices == 1
    # offline host scores worse with zero activity everywhere
    assert lb.rank()[0].host == "hostB"


def test_lb_alias_export():
    assert LB is LoadBalancer
