# -*- coding: utf-8 -*-
"""P2-10 multi-device parallel scheduling & load balancing (pure
incremental).

Cluster dispatch layer composed ON TOP of the P1
:class:`DeviceManager` (state machine + lock authority) — the P1
module is used, never modified:

  * register_device / submit       — device pool (kind-tagged) + task
                                     queue with weight (est. effort)
  * assign_next()                  — smart balancing: idle devices
                                     first, least-loaded wins (active
                                     tasks then accumulated busy
                                     seconds), busy devices are
                                     avoided (queued instead)
  * parallel run                   — ThreadPoolExecutor, one exclusive
                                     P1 lock token per task => tasks
                                     are isolated, no preemption
  * fault failover                 — report_fault() removes the device
                                     (P1 ERROR state), re-queues its
                                     running tasks on other devices
                                     automatically (migration)
  * progress + stats               — per-task status, per-device load
                                     snapshot, [CLUSTER] audit lines

Zero changes to runner / scheduler / device_manager.
"""
from __future__ import annotations

import concurrent.futures
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from mtkgui.engine.device_manager import (DeviceManager, DeviceState,
                                          DeviceStateError)

TASK_STATES = ("QUEUED", "RUNNING", "DONE", "FAILED", "MIGRATED")


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    MIGRATED = "MIGRATED"   # re-queued after device fault


@dataclass
class Task:
    task_id: str
    kind: str = "*"                 # required device kind (* = any)
    weight: float = 1.0             # estimated effort for balancing
    payload: object = None
    status: TaskStatus = TaskStatus.QUEUED
    device: str = ""                # current/last device
    token: str = ""                 # P1 lock token (acquire result)
    attempts: int = 0


@dataclass
class DeviceStats:
    name: str
    kind: str
    active: int = 0                 # tasks currently running
    completed: int = 0
    failed: int = 0
    busy_s: float = 0.0             # accumulated busy seconds

    @property
    def load(self) -> float:
        """Balancing score: active tasks dominate, then busy time."""
        return self.active + self.busy_s / 3600.0

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind,
                "active": self.active, "completed": self.completed,
                "failed": self.failed,
                "busy_s": round(self.busy_s, 3)}


class ClusterScheduler:
    """Smart multi-device dispatcher over the P1 device lock base."""

    def __init__(self, dm: DeviceManager | None = None,
                 log_fn: Callable[[str], None] | None = None):
        self.dm = dm or DeviceManager(
            log_fn=lambda line: self._log("device", line))
        self._stats: dict[str, DeviceStats] = {}
        self._queue: list[Task] = []
        self._running: dict[str, Task] = {}     # task_id -> Task
        self._history: dict[str, TaskStatus] = {}  # finished tasks
        self._lock = threading.Lock()
        self.audit: list[tuple[str, str, str]] = []
        self._log_fn = log_fn

    # ------------------------------------------------------------ log
    def _log(self, action: str, detail: str) -> None:
        stamp = f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
        self.audit.append((stamp, action, detail))
        if self._log_fn is not None:
            self._log_fn(f"[CLUSTER] {action}: {detail}")

    # --------------------------------------------------------- devices
    def register_device(self, name: str, kind: str = "station") -> None:
        self.dm.register(name)
        with self._lock:
            self._stats[name] = DeviceStats(name=name, kind=kind)

    def devices(self) -> list[dict]:
        with self._lock:
            return [s.to_dict() for s in self._stats.values()]

    def device_state(self, name: str) -> DeviceState:
        return self.dm.state(name)

    # ----------------------------------------------------------- tasks
    def submit(self, task: Task) -> None:
        task.status = TaskStatus.QUEUED
        task.attempts = 0
        with self._lock:
            self._queue.append(task)
        self._log("submit", f"{task.task_id} kind={task.kind} "
                            f"weight={task.weight}")

    def queue_depth(self) -> int:
        return len(self._queue)

    def task_status(self, task_id: str) -> TaskStatus | None:
        for t in (*self._queue, *self._running.values()):
            if t.task_id == task_id:
                return t.status
        return self._history.get(task_id)

    # ------------------------------------------------------- balancing
    def _candidates(self, kind: str) -> list[DeviceStats]:
        """Idle-first, least-loaded candidates of the wanted kind."""
        avail = [(n, s) for n, s in self._stats.items()
                 if (kind == "*" or s.kind == kind or kind == "*")
                 and self.dm.state(n) == DeviceState.IDLE
                 and self.dm.acquireable(n)]
        # idle devices first (active == 0), then lowest load score
        avail.sort(key=lambda p: (p[1].active > 0, p[1].load,
                                  p[1].busy_s, p[0]))
        return [s for _, s in avail]

    def assign_next(self) -> tuple[Task, str] | None:
        """Dispatch one queued task onto the best idle device.

        Returns (task, device) or None (nothing dispatchable — busy
        devices are avoided, the task stays queued)."""
        with self._lock:
            for idx, task in enumerate(self._queue):
                for stats in self._candidates(task.kind):
                    try:
                        token = self.dm.acquire(stats.name,
                                                f"task:{task.task_id}")
                    except DeviceStateError:
                        continue        # lost the race -> next device
                    task.device = stats.name
                    task.token = token
                    task.status = TaskStatus.RUNNING
                    task.attempts += 1
                    stats.active += 1
                    stats._start = time.monotonic()  # type: ignore
                    self._running[task.task_id] = task
                    del self._queue[idx]
                    self._log("assign", f"{task.task_id} -> "
                                        f"{stats.name} "
                                        f"(attempt {task.attempts})")
                    return task, stats.name
        return None

    # --------------------------------------------------------- results
    def complete(self, task_id: str, ok: bool = True) -> None:
        with self._lock:
            task = self._running.pop(task_id, None)
            if task is None:
                return
            stats = self._stats[task.device]
            stats.active = max(0, stats.active - 1)
            start = getattr(stats, "_start", None)
            if start is not None:
                stats.busy_s += time.monotonic() - start
                stats._start = None    # type: ignore
            self.dm.release(task.device, task.token)
            if ok:
                task.status = TaskStatus.DONE
                stats.completed += 1
                self._log("done", f"{task.task_id} on {task.device}")
            else:
                task.status = TaskStatus.FAILED
                stats.failed += 1
                self._log("failed", f"{task.task_id} on {task.device}")
            self._history[task.task_id] = task.status

    # --------------------------------------------------------- failover
    def report_fault(self, device: str, reason: str = "fault") -> list[str]:
        """Remove a faulty device and migrate its running tasks.

        The P1 lock is force-released, the device goes to ERROR (no
        further acquisition), every RUNNING task on it is re-queued
        as MIGRATED for re-dispatch on the remaining cluster."""
        # force-release first (any state -> IDLE), then ERROR so the
        # device cannot be acquired until restored
        if self.dm.state(device) == DeviceState.OCCUPIED:
            self.dm.force_release(device, reason)
        self.dm.mark_error(device, reason)
        migrated: list[str] = []
        with self._lock:
            for task_id, task in list(self._running.items()):
                if task.device != device:
                    continue
                self._running.pop(task_id)
                stats = self._stats.get(device)
                if stats:
                    stats.active = max(0, stats.active - 1)
                    task.status = TaskStatus.MIGRATED
                    task.device = ""
                    task.status = TaskStatus.QUEUED   # back to queue
                    self._queue.append(task)
                    migrated.append(task_id)
        self._log("failover", f"device {device} removed ({reason}), "
                              f"migrated {migrated}")
        return migrated

    def restore_device(self, device: str) -> None:
        """Re-join a repaired device to the pool."""
        self.dm.clear_error(device)
        self._log("restore", f"device {device} back to pool")

    # ----------------------------------------------------------- stats
    def snapshot(self) -> dict:
        """GUI overview: devices + queue + running tasks."""
        with self._lock:
            return {
                "devices": [s.to_dict() for s in
                            self._stats.values()],
                "states": {n: self.dm.state(n).value
                           for n in self._stats},
                "queue": [{"task_id": t.task_id, "kind": t.kind,
                           "weight": t.weight,
                           "status": t.status.value,
                           "device": t.device}
                          for t in self._queue],
                "running": [{"task_id": t.task_id,
                             "device": t.device,
                             "status": t.status.value}
                            for t in self._running.values()],
            }

    # --------------------------------------------------------- parallel
    def run(self, worker_fn: Callable[[Task, str], bool],
            max_workers: int | None = None) -> dict[str, bool]:
        """Run the whole queue in parallel; returns task_id -> ok.

        Each task holds an exclusive P1 lock token on its device for
        the whole run (isolation, no preemption).  As soon as a device
        finishes, the next queued task is dispatched to it.  Blocking.
        """
        results: dict[str, bool] = {}

        def one(task: Task, device: str) -> None:
            try:
                ok = bool(worker_fn(task, device))
            except Exception:                       # noqa: BLE001
                ok = False
            self.complete(task.task_id, ok)
            results[task.task_id] = ok

        with ThreadPoolExecutor(
                max_workers=max_workers or max(
                    1, len(self._stats))) as pool:
            pending: set = set()
            while self._queue or pending:
                while True:                         # fill idle devices
                    nxt = self.assign_next()
                    if nxt is None:
                        break
                    pending.add(pool.submit(one, *nxt))
                if not pending:
                    break
                done, pending = concurrent_wait(pending)
                for f in done:
                    f.result()
        return results


def concurrent_wait(pending: set):
    """FIRST_COMPLETED wait (thin wrapper for testability)."""
    return concurrent.futures.wait(
        pending, return_when=concurrent.futures.FIRST_COMPLETED)
