# -*- coding: utf-8 -*-
"""P3-5 distributed task queue (pure incremental).

Breaks the single-machine synchronous limit by hosting mass-
production jobs in a persistent priority queue with automatic retry.
Purely additive: the P2 immediate-execution paths are untouched and
keep working exactly as before.

  * QueuedTask     — payload + priority (higher first) + status
                     PENDING/RUNNING/DONE/FAILED + attempts/max_retries
  * TaskQueue      — thread-safe worker pool over a priority heap:
                       submit(payload, priority, max_retries)
                       run(handler, workers)  — parallel drain; a
                       handler exception requeues the task
                       (attempts+1) until max_retries is exhausted,
                       then FAILED with the error captured
                       wait(timeout)  — quiescence helper
                     persistence: unfinished tasks (PENDING/RUNNING)
                     are journaled to a JSON file on every transition
                     and re-queued on restart -> tasks are never lost
                     by a process crash
  * snapshot/stats — visualizable queue state for the GUI board
"""
from __future__ import annotations

import heapq
import itertools
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass
class QueuedTask:
    payload: object
    priority: int = 0
    max_retries: int = 2
    tid: str = ""
    attempts: int = 0
    status: TaskStatus = TaskStatus.PENDING
    result: object = None
    error: str = ""
    seq: int = field(default=0, repr=False)     # FIFO tie-break

    def as_row(self) -> dict:
        return {"tid": self.tid, "priority": self.priority,
                "status": self.status.value, "attempts": self.attempts,
                "max_retries": self.max_retries,
                "payload": str(self.payload), "error": self.error}


class TaskQueue:
    """Persistent priority task queue with a parallel worker pool."""

    def __init__(self, journal_path=None, now=None,
                 sleep: Callable = time.sleep, poll: float = 0.02):
        self.journal = Path(journal_path) if journal_path else None
        self.now = now or datetime.now
        self._sleep = sleep
        self._poll = poll
        self._heap: list[tuple] = []            # (-prio, seq, task)
        self._tasks: dict[str, QueuedTask] = {}
        self._seq = itertools.count(1)
        self._guard = threading.Lock()
        self._wakeup = threading.Event()
        self._stop = threading.Event()
        self._restore()

    # -------------------------------------------------------- submit
    def submit(self, payload, priority: int = 0,
               max_retries: int = 2) -> QueuedTask:
        task = QueuedTask(payload=payload, priority=priority,
                          max_retries=max_retries,
                          tid=f"T{next(self._seq):06d}",
                          seq=next(self._seq))
        with self._guard:
            self._tasks[task.tid] = task
            heapq.heappush(self._heap,
                           (-task.priority, task.seq, task))
            self._journal()
        self._wakeup.set()
        return task

    def get(self, tid: str) -> QueuedTask:
        return self._tasks[tid]

    # -------------------------------------------------------- workers
    def run(self, handler, workers: int = 2) -> dict:
        """Drain the queue with `workers` parallel threads.  Blocking
        until quiescent; returns final stats."""
        self._stop.clear()
        threads = [threading.Thread(target=self._worker,
                                    args=(handler,), daemon=True)
                   for _ in range(max(1, workers))]
        for t in threads:
            t.start()
        self.wait()
        self._stop.set()
        self._wakeup.set()
        for t in threads:
            t.join(timeout=5)
        return self.stats()

    def wait(self, timeout: float = 30.0) -> bool:
        """Block until no PENDING/RUNNING tasks remain."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._guard:
                busy = any(t.status in (TaskStatus.PENDING,
                                        TaskStatus.RUNNING)
                           for t in self._tasks.values())
            if not busy:
                return True
            self._sleep(min(self._poll, 0.05))
        return False

    def _worker(self, handler) -> None:
        while not self._stop.is_set():
            task = self._take()
            if task is None:
                self._wakeup.wait(self._poll)
                self._wakeup.clear()
                continue
            self._set_status(task, TaskStatus.RUNNING)
            try:
                result = handler(task)
            except Exception as exc:                 # noqa: BLE001
                self._fail_or_retry(task, exc)
            else:
                with self._guard:
                    task.status = TaskStatus.DONE
                    task.result = result
                    self._journal()
                self._wakeup.set()

    def _take(self) -> QueuedTask | None:
        with self._guard:
            while self._heap:
                _, _, task = heapq.heappop(self._heap)
                if task.status is TaskStatus.PENDING:
                    return task
            return None

    def _fail_or_retry(self, task: QueuedTask, exc: Exception) -> None:
        with self._guard:
            task.attempts += 1
            task.error = f"{type(exc).__name__}: {exc}"
            if task.attempts <= task.max_retries:
                task.status = TaskStatus.PENDING     # requeue
                heapq.heappush(self._heap,
                               (-task.priority, task.seq, task))
            else:
                task.status = TaskStatus.FAILED
            self._journal()
        self._wakeup.set()

    def _set_status(self, task: QueuedTask,
                    status: TaskStatus) -> None:
        with self._guard:
            task.status = status
            self._journal()

    # ------------------------------------------------------ persistence
    def _journal(self) -> None:
        """Persist unfinished tasks (PENDING/RUNNING) so a restart
        re-queues them — tasks are never lost."""
        if self.journal is None:
            return
        unfinished = [t for t in self._tasks.values()
                      if t.status in (TaskStatus.PENDING,
                                      TaskStatus.RUNNING)]
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.journal.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            [{"tid": t.tid, "payload": t.payload,
              "priority": t.priority, "max_retries": t.max_retries,
              "attempts": t.attempts, "seq": t.seq}
             for t in unfinished], ensure_ascii=False, indent=1),
            encoding="utf-8")
        tmp.replace(self.journal)

    def _restore(self) -> None:
        if self.journal is None or not self.journal.is_file():
            return
        try:
            rows = json.loads(self.journal.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for row in rows:
            task = QueuedTask(
                payload=row["payload"], priority=row["priority"],
                max_retries=row["max_retries"],
                attempts=row["attempts"], tid=row["tid"],
                seq=row["seq"], status=TaskStatus.PENDING)
            self._tasks[task.tid] = task
            heapq.heappush(self._heap,
                           (-task.priority, task.seq, task))
        self._seq = itertools.count(max(
            [int(t.tid[1:]) for t in self._tasks.values()] or [0]) + 1)

    # ------------------------------------------------------------ view
    def snapshot(self) -> list[dict]:
        with self._guard:
            return [t.as_row() for t in
                    sorted(self._tasks.values(),
                           key=lambda t: t.seq)]

    def stats(self) -> dict:
        with self._guard:
            out = {s.value: 0 for s in TaskStatus}
            for t in self._tasks.values():
                out[t.status.value] += 1
            out["total"] = len(self._tasks)
            return out
