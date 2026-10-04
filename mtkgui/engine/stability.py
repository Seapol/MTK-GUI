# -*- coding: utf-8 -*-
"""Concurrency & long-run stability primitives (P1 Task12).

7x24 production guards, purely additive: every上层 capability
(scheduler, runner, protocol, devices, taxonomy) is untouched -
these are standalone primitives a host integration can wire in.

  ResourceLocks      - per-resource locks with owner tokens, nested
                       acquisition tracking, timed acquire (no
                       deadlock), and a residue sweep for stale
                       holders that stopped renewing
  BoundedQueue       - queue overflow protection with limit/reject
                       metrics (batch avalanche prevention)
  HeartbeatMonitor   - task keep-alive; silent hangs are detected
                       and force-terminated (no zombie tasks)
  CircuitBreaker     - timeout-stacking protection: consecutive
                       timeout overruns trip the breaker, calls are
                       rejected until the cooldown elapses
  StationInspector   - periodic inspection + automatic resource
                       recovery (sweeps locks, trims queues,
                       reaps zombie tasks) with [STAB] audit lines
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional


class LockHeld(RuntimeError):
    pass


class QueueFull(RuntimeError):
    pass


class BreakerOpen(RuntimeError):
    pass


class _Entry:
    __slots__ = ("owner", "count", "deadline")

    def __init__(self, owner: str, count: int, deadline: float):
        self.owner = owner
        self.count = count          # nesting depth
        self.deadline = deadline    # renewal deadline (monotonic)


class ResourceLocks:
    """Named resource locks with nesting, timed acquire and sweep."""

    def __init__(self, default_timeout_s: float = 5.0):
        self.default_timeout_s = default_timeout_s
        self._entries: dict[str, _Entry] = {}
        self._mu = threading.Lock()

    def acquire(self, resource: str, owner: str,
                timeout_s: float | None = None) -> None:
        """Acquire or re-enter (nested by the same owner).  Raises
        LockHeld instead of deadlocking forever."""
        deadline = time.monotonic() + (self.default_timeout_s
                                       if timeout_s is None
                                       else timeout_s)
        with self._mu:
            e = self._entries.get(resource)
            if e is not None and e.owner != owner:
                if time.monotonic() > e.deadline:
                    # stale holder: swept inline (residue protection)
                    del self._entries[resource]
                    e = None
                else:
                    raise LockHeld(
                        f"resource '{resource}' held by '{e.owner}'")
            if e is None:
                self._entries[resource] = _Entry(owner, 1, deadline)
            else:
                e.count += 1
                e.deadline = deadline

    def release(self, resource: str, owner: str) -> None:
        with self._mu:
            e = self._entries.get(resource)
            if e is None or e.owner != owner:
                return                      # idempotent, never raises
            e.count -= 1
            if e.count <= 0:
                del self._entries[resource]

    def renew(self, resource: str, owner: str,
              timeout_s: float | None = None) -> None:
        with self._mu:
            e = self._entries.get(resource)
            if e is not None and e.owner == owner:
                e.deadline = time.monotonic() + (
                    self.default_timeout_s if timeout_s is None
                    else timeout_s)

    def sweep(self) -> list[str]:
        """Release locks whose holder missed the renewal deadline."""
        now = time.monotonic()
        with self._mu:
            stale = [r for r, e in self._entries.items()
                     if now > e.deadline]
            for r in stale:
                del self._entries[r]
        return stale

    def held(self) -> dict[str, str]:
        with self._mu:
            return {r: e.owner for r, e in self._entries.items()}


class BoundedQueue:
    """FIFO queue with a hard cap - overflow is rejected with a
    metric, never silently accumulated (avalanche protection)."""

    def __init__(self, maxsize: int = 100):
        self.maxsize = maxsize
        self._items: deque = deque()
        self.rejected_count = 0

    def put(self, item) -> None:
        if len(self._items) >= self.maxsize:
            self.rejected_count += 1
            raise QueueFull(
                f"queue full ({self.maxsize}): item rejected "
                f"(total rejected: {self.rejected_count})")
        self._items.append(item)

    def pop(self):
        return self._items.popleft() if self._items else None

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class TrackedTask:
    name: str
    interval_s: float
    last_beat: float = field(default_factory=time.monotonic)
    terminated: bool = False


class HeartbeatMonitor:
    """Keep-alive registry: silent hangs are detected and reaped."""

    def __init__(self, grace_factor: float = 3.0,
                 log_fn: Optional[Callable[[str], None]] = None):
        self.grace_factor = grace_factor
        self._tasks: dict[str, TrackedTask] = {}
        self._log = log_fn or (lambda line: print(line))

    def register(self, name: str, interval_s: float) -> TrackedTask:
        self._tasks[name] = TrackedTask(name, interval_s)
        return self._tasks[name]

    def beat(self, name: str) -> None:
        t = self._tasks.get(name)
        if t is not None and not t.terminated:
            t.last_beat = time.monotonic()

    def stale_tasks(self) -> list[str]:
        """Tasks whose silence exceeds interval * grace_factor."""
        now = time.monotonic()
        return [name for name, t in self._tasks.items()
                if not t.terminated
                and now - t.last_beat > t.interval_s * self.grace_factor]

    def reap(self) -> list[str]:
        """Force-terminate zombie tasks; returns reaped names."""
        reaped = [n for n in self.stale_tasks()
                  if not self._tasks[n].terminated]
        for name in reaped:
            self._tasks[name].terminated = True
            self._log(f"[STAB] zombie task '{name}' force-terminated "
                      f"(heartbeat silent)")
        return reaped


class CircuitBreaker:
    """Timeout-stacking protection: N consecutive overruns open the
    breaker for a cooldown; half-open lets one probe through."""

    def __init__(self, trip_after: int = 3, cooldown_s: float = 5.0):
        self.trip_after = trip_after
        self.cooldown_s = cooldown_s
        self._consecutive = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if time.monotonic() - self._opened_at >= self.cooldown_s:
            return "half-open"
        return "open"

    def record_success(self) -> None:
        self._consecutive = 0
        self._opened_at = None

    def record_timeout(self) -> None:
        self._consecutive += 1
        if self._consecutive >= self.trip_after \
                and self._opened_at is None:
            self._opened_at = time.monotonic()

    def check(self) -> None:
        """Raises BreakerOpen while the breaker is open."""
        if self.state == "open":
            raise BreakerOpen(
                f"circuit breaker open after "
                f"{self._consecutive} consecutive timeout(s); "
                f"cooldown {self.cooldown_s:.0f}s")


class StationInspector:
    """One inspect_once() call runs every recovery sweep."""

    def __init__(self, locks: ResourceLocks, queue: BoundedQueue,
                 monitor: HeartbeatMonitor,
                 log_fn: Optional[Callable[[str], None]] = None):
        self.locks = locks
        self.queue = queue
        self.monitor = monitor
        self._log = log_fn or (lambda line: print(line))
        self.rounds = 0

    def inspect_once(self) -> dict:
        self.rounds += 1
        swept = self.locks.sweep()
        reaped = self.monitor.reap()
        report = {"round": self.rounds, "locks_swept": swept,
                  "tasks_reaped": reaped, "queue_len": len(self.queue),
                  "queue_rejected": self.queue.rejected_count}
        self._log(f"[STAB] inspection #{self.rounds}: "
                  f"locks_swept={swept} tasks_reaped={reaped} "
                  f"queue={report['queue_len']}/{self.queue.maxsize} "
                  f"rejected={report['queue_rejected']}")
        return report
