# -*- coding: utf-8 -*-
"""P3-7 cross-host load balancing & distributed scheduling upgrade
(pure additive).

A fleet-level BALANCING STRATEGY layer composed on top of the frozen
P2-10 :class:`ClusterScheduler` and the P3-6 :class:`ClusterHub` —
both are observed read-only through their public contracts, neither
is modified:

  * HostLoad       — per-HOST (machine, not device) aggregated load:
                     devices, active, completed, failed, busy seconds,
                     offline count, utilization 0..1
  * LoadBalancer   — weighted host scoring (idle-first, busy-time and
                     offline penalties) -> rank() / best_host() gives
                     idle-first + busy-avoidance host selection;
                     imbalance() quantifies skew; plan() proposes
                     cross-host MIGRATE moves from hot hosts to cold
                     ones; migrations are recorded for audit;
                     accel stats quantify parallel speedup

Zero changes to cluster_scheduler / cluster_hub / device_manager.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class HostLoad:
    """Aggregated load of one host (machine) in the cluster."""

    host: str
    devices: int = 0
    active: int = 0                 # tasks running on the host now
    completed: int = 0
    failed: int = 0
    busy_s: float = 0.0
    offline: int = 0                # OFFLINE/ERROR/disabled devices
    queue_hint: int = 0             # queued tasks best served here

    @property
    def utilization(self) -> float:
        """Fraction of the host's devices currently busy (0..1)."""
        return self.active / max(1, self.devices)

    def as_row(self) -> dict:
        return {"host": self.host, "devices": self.devices,
                "active": self.active, "completed": self.completed,
                "failed": self.failed,
                "busy_s": round(self.busy_s, 3),
                "offline": self.offline,
                "queue_hint": self.queue_hint,
                "utilization": round(self.utilization, 3)}


@dataclass
class MigrationRecord:
    task_id: str
    from_host: str
    to_host: str
    reason: str = ""


class LoadBalancer:
    """Cross-host balancing strategy over hub + scheduler (read-only)."""

    def __init__(self, w_active: float = 1.0, w_busy: float = 1.0,
                 w_offline: float = 2.0, skew: float = 0.35):
        self.w_active = w_active      # weight: running tasks
        self.w_busy = w_busy          # weight: accumulated busy hours
        self.w_offline = w_offline    # weight: dead devices
        self.skew = skew              # utilization spread threshold
        self._hosts: dict[str, HostLoad] = {}
        self._migrations: list[MigrationRecord] = []
        self._guard = threading.Lock()

    # ---------------------------------------------------------- scoring
    def _score(self, h: HostLoad) -> float:
        return (self.w_active * h.active
                + self.w_busy * h.busy_s / 3600.0
                + self.w_offline * h.offline)

    # -------------------------------------------------------- observe
    def observe(self, hub, scheduler=None) -> dict[str, HostLoad]:
        """Rebuild per-host load from hub nodes (+ scheduler stats)."""
        with self._guard:
            hosts: dict[str, HostLoad] = {}
            nodes = {n.device_id: n for n in hub.nodes()}
            states = {}
            running: dict[str, int] = {}
            if scheduler is not None:
                snap = scheduler.snapshot()
                states = snap["states"]
                for t in snap["running"]:
                    running[t["device"]] = running.get(t["device"], 0) + 1
            for dev, node in nodes.items():
                h = hosts.setdefault(node.host, HostLoad(host=node.host))
                h.devices += 1
                st = states.get(dev)
                bad = st in ("ERROR",) or not node.enabled or \
                    node.status.value == "OFFLINE"
                if bad:
                    h.offline += 1
                h.active += running.get(dev, 0)
                if scheduler is not None:
                    for d in scheduler.devices():
                        if d["name"] == dev:
                            h.completed += d["completed"]
                            h.failed += d["failed"]
                            h.busy_s += d["busy_s"]
                            break
            self._hosts = hosts
            return {k: v for k, v in hosts.items()}

    # -------------------------------------------------------- ranking
    def rank(self) -> list[HostLoad]:
        """Hosts sorted by score: idle-first, least-loaded wins."""
        with self._guard:
            return sorted(self._hosts.values(),
                          key=lambda h: (self._score(h), h.host))

    def best_host(self, kind: str | None = None) -> str | None:
        """Preferred host for the next task (busy avoidance).

        Skips hosts whose devices are ALL busy (utilization >= 1) or
        fully offline; if ``kind`` is given, only hosts owning a
        matching enabled device qualify (see observe_kinds).
        """
        with self._guard:
            cands = sorted(self._hosts.values(),
                           key=lambda h: (h.active > 0, self._score(h),
                                          h.host))
            dev_host = dict(getattr(self, "_dev_host", {}))
            dev_kind = dict(getattr(self, "_dev_kinds", {}))
        for h in cands:
            if h.devices == 0 or h.utilization >= 1.0:
                continue                      # busy avoidance
            if h.offline >= h.devices:
                continue                      # dead host
            if kind is not None and kind != "*":
                ok = any(dev_host.get(d) == h.host and
                         dev_kind.get(d) == kind
                         for d in dev_host)
                if not ok:
                    continue
            return h.host
        return None

    def observe_kinds(self, hub) -> None:
        """Cache device->kind map so best_host(kind=...) can filter."""
        with self._guard:
            self._dev_kinds = {n.device_id: n.kind for n in hub.nodes()}
            self._dev_host = {n.device_id: n.host for n in hub.nodes()}

    def _host_devs(self, host: str) -> list[str]:
        return [d for d, hh in getattr(self, "_dev_host", {}).items()
                if hh == host]

    # -------------------------------------------------------- skewness
    def imbalance(self) -> float:
        """max-min utilization spread across hosts (0..1)."""
        with self._guard:
            utils = [h.utilization for h in self._hosts.values()
                     if h.devices]
        return round(max(utils) - min(utils), 3) if utils else 0.0

    # ------------------------------------------------------ migration
    def plan(self, hub, scheduler=None) -> list[dict]:
        """Propose cross-host MIGRATE moves: hot host -> cold host
        with a matching enabled device of the queued task's kind."""
        self.observe_kinds(hub)
        self.observe(hub, scheduler)
        with self._guard:
            hosts = dict(self._hosts)
            dev_host = dict(getattr(self, "_dev_host", {}))
            dev_kind = dict(getattr(self, "_dev_kinds", {}))
        queue_kinds: list[str] = []
        if scheduler is not None:
            queue_kinds = [t["kind"] for t in
                           scheduler.snapshot()["queue"]]
        hot = [h for h in hosts.values()
               if h.devices and h.utilization >= self.skew]
        cold = [h for h in hosts.values()
                if h.devices and h.utilization < self.skew
                and h.offline < h.devices]
        moves: list[dict] = []
        for h in sorted(hot, key=lambda x: -x.utilization):
            for c in sorted(cold, key=lambda x: x.utilization):
                for k in queue_kinds:
                    ok = any(dev_host.get(d) == c.host and
                             (k == "*" or dev_kind.get(d) == k)
                             for d in self._host_devs(c.host))
                    if ok:
                        moves.append({
                            "action": "MIGRATE", "kind": k,
                            "from": h.host, "to": c.host,
                            "reason": f"util {h.utilization:.2f} -> "
                                      f"{c.utilization:.2f}"})
                        break
                break
        return moves

    def record_migration(self, task_id: str, from_host: str,
                         to_host: str, reason: str = "") -> None:
        with self._guard:
            self._migrations.append(MigrationRecord(
                task_id, from_host, to_host, reason))

    def migrations(self) -> list[dict]:
        with self._guard:
            return [{"task_id": m.task_id, "from": m.from_host,
                     "to": m.to_host, "reason": m.reason}
                    for m in self._migrations]

    # ------------------------------------------------------ accel stats
    def accel_stats(self, scheduler, wall_s: float) -> dict:
        """Parallel speedup: summed device busy time vs wall clock."""
        busy = sum(d["busy_s"] for d in scheduler.devices())
        n = max(1, len(scheduler.devices()))
        return {"devices": n, "busy_s": round(busy, 3),
                "wall_s": round(max(0.0, wall_s), 3),
                "speedup": round(busy / max(wall_s, 1e-9), 3),
                "efficiency": round(busy / max(wall_s, 1e-9) / n, 3)}

    def hosts_view(self) -> list[dict]:
        with self._guard:
            rows = [h.as_row() for h in
                    sorted(self._hosts.values(), key=lambda h: h.host)]
        return rows


#: short public alias
LB = LoadBalancer
