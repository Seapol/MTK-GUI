# -*- coding: utf-8 -*-
"""P3-6 cluster device hub & remote fleet management (pure additive).

Upgrades the P2-10 single-host scheduler view to a fleet-level middle
platform WITHOUT touching any P1/P2 device driver, lock or state
machine — it only observes and calls the frozen scheduler contract:

  * ClusterNode   — one fleet member: host, kind, status
                    (ONLINE/OFFLINE/ERROR), heartbeat stamp, load,
                    enabled flag, capabilities
  * ClusterHub    — registration center + heartbeat intake +
                    stale-timeout online/offline judgement + alert
                    subscribers (auto-fired on any transition) +
                    transition ledger (audit-friendly device history)
  * remote ops    — enable/disable a node remotely: disabling routes
                    through the P2-10 scheduler (report_fault) so the
                    running scheduler never double-books it; enable
                    uses restore_device — zero scheduler changes
  * sync_scheduler— read-only reflection of scheduler load/state into
                    the fleet board (single source of truth stays the
                    frozen scheduler)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class NodeStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


@dataclass
class ClusterNode:
    device_id: str
    host: str
    kind: str = "generic"
    status: NodeStatus = NodeStatus.ONLINE
    last_beat: float = field(default_factory=time.monotonic)
    load: int = 0
    enabled: bool = True
    capabilities: tuple = ()
    joined_at: str = ""

    def as_row(self) -> dict:
        return {"device_id": self.device_id, "host": self.host,
                "kind": self.kind, "status": self.status.value,
                "load": self.load, "enabled": self.enabled,
                "beats_ago_s": round(max(0.0, time.monotonic()
                                         - self.last_beat), 3)}


@dataclass
class LedgerEvent:
    ts: str
    device_id: str
    event: str                    # JOIN / ONLINE / OFFLINE / ERROR /
                                  # DISABLE / ENABLE / ALERT
    detail: str = ""


class ClusterHub:
    """Fleet registration center + heartbeat + remote management."""

    def __init__(self, stale_after: float = 10.0, now=None):
        self.stale_after = stale_after
        self.now = now or (lambda: __import__("datetime")
                           .datetime.now())
        self._nodes: dict[str, ClusterNode] = {}
        self._ledger: list[LedgerEvent] = []
        self._alerts: list[Callable[[ClusterNode, str], None]] = []
        self._guard = threading.Lock()

    # ------------------------------------------------------ registration
    def register_node(self, device_id: str, host: str, kind="generic",
                      capabilities=()) -> ClusterNode:
        with self._guard:
            node = self._nodes.get(device_id)
            if node is None:
                node = ClusterNode(
                    device_id=device_id, host=host, kind=kind,
                    capabilities=tuple(capabilities),
                    joined_at=f"{self.now():%Y-%m-%d %H:%M:%S}")
                self._nodes[device_id] = node
                self._ledger.append(LedgerEvent(
                    f"{self.now():%Y-%m-%d %H:%M:%S}", device_id,
                    "JOIN", f"host={host} kind={kind}"))
            else:
                node.host, node.kind = host, kind
            return node

    def node(self, device_id: str) -> ClusterNode:
        return self._nodes[device_id]

    def nodes(self) -> list[ClusterNode]:
        with self._guard:
            return list(self._nodes.values())

    # --------------------------------------------------------- heartbeat
    def heartbeat(self, device_id: str, load: int | None = None
                  ) -> None:
        """Remote node heartbeat intake (unknown id -> error alert)."""
        with self._guard:
            node = self._nodes.get(device_id)
            if node is None:
                self._ledger.append(LedgerEvent(
                    f"{self.now():%Y-%m-%d %H:%M:%S}", device_id,
                    "ALERT", "heartbeat from unknown node"))
                self._fire_locked(None, "unknown heartbeat")
                return
            node.last_beat = time.monotonic()
            if load is not None:
                node.load = load
            if node.status is not NodeStatus.ONLINE:
                self._transition_locked(node, NodeStatus.ONLINE,
                                        "heartbeat recovered")

    def monitor(self) -> int:
        """Stale-timeout sweep: silent nodes go OFFLINE."""
        with self._guard:
            n = 0
            for node in self._nodes.values():
                if node.status is NodeStatus.ONLINE and \
                        time.monotonic() - node.last_beat > \
                        self.stale_after:
                    self._transition_locked(node, NodeStatus.OFFLINE,
                                            "heartbeat timeout")
                    n += 1
            return n

    # ------------------------------------------------------- remote ops
    def set_enabled(self, device_id: str, enabled: bool,
                    scheduler=None) -> bool:
        """Remote enable/disable; routes through the frozen P2-10
        scheduler contract when one is attached."""
        with self._guard:
            node = self._nodes.get(device_id)
            if node is None:
                return False
            node.enabled = enabled
            self._ledger.append(LedgerEvent(
                f"{self.now():%Y-%m-%d %H:%M:%S}", device_id,
                "ENABLE" if enabled else "DISABLE"))
            if scheduler is not None:
                try:
                    if not enabled:
                        scheduler.report_fault(device_id,
                                               "remote disable")
                    else:
                        scheduler.restore_device(device_id)
                except Exception:                  # noqa: BLE001
                    pass                           # node not in scheduler
            return True

    # ------------------------------------------------------ observation
    def attach_scheduler(self, scheduler) -> None:
        """Read-only reflection of scheduler load/state."""
        with self._guard:
            for dev in scheduler.devices():
                node = self._nodes.get(dev["name"])
                if node is None:
                    continue
                node.load = dev["completed"]
                state = scheduler.device_state(dev["name"]).value
                if state == "ERROR" and node.enabled:
                    self._transition_locked(node, NodeStatus.ERROR,
                                            "scheduler reports fault")
                elif state != "ERROR" and node.enabled and \
                        node.status is NodeStatus.ERROR:
                    self._transition_locked(node, NodeStatus.ONLINE,
                                            "scheduler recovered")

    def snapshot(self) -> list[dict]:
        with self._guard:
            self._sort_nodes()
            return [n.as_row() for n in self._nodes.values()]

    def _sort_nodes(self) -> None:
        self._nodes = dict(sorted(self._nodes.items()))

    def ledger_rows(self, device_id: str | None = None) -> list[dict]:
        rows = [e for e in self._ledger
                if device_id is None or e.device_id == device_id]
        return [{"ts": e.ts, "device_id": e.device_id,
                 "event": e.event, "detail": e.detail}
                for e in rows]

    # ------------------------------------------------------------ alerts
    def on_alert(self, fn: Callable[[ClusterNode | None, str],
                                    None]) -> None:
        self._alerts.append(fn)

    def _fire_locked(self, node, detail: str) -> None:
        for fn in self._alerts:
            try:
                fn(node, detail)
            except Exception:                     # noqa: BLE001
                pass

    def _transition_locked(self, node: ClusterNode,
                           status: NodeStatus, detail: str) -> None:
        node.status = status
        self._ledger.append(LedgerEvent(
            f"{self.now():%Y-%m-%d %H:%M:%S}", node.device_id,
            status.value, detail))
        self._fire_locked(node, detail)


#: short public alias (concise GUI/test imports)
CH = ClusterHub
