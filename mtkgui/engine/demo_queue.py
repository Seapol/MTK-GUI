# -*- coding: utf-8 -*-
"""P3-5 task queue demo (headless-safe, rc=0).

Closed loop: priority ordering -> parallel drain -> retry-then-
success + retry-exhausted-FAILED -> crash journal restore (nothing
lost) -> GUI queue board submit/refresh.  Exit 0 = passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.task_queue import TaskQueue, TaskStatus  # noqa: E402
from mtkgui.gui.queue_page import QueuePage  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="p3_5_demo_")

    # 1. priority + parallel drain
    q = TaskQueue(journal_path=os.path.join(tmp, "q.json"),
                  poll=0.001)
    order: list[str] = []
    guard = threading.Lock()
    for p, name in ((1, "low"), (9, "high1"), (9, "high2"),
                    (5, "mid")):
        q.submit(name, priority=p)
    q.run(lambda t: (guard.locked() or None,
                     order.append(t.payload)), workers=2)
    assert order[:2] == ["high1", "high2"], order
    assert q.stats()["DONE"] == 4

    # 2. retry then success
    q2 = TaskQueue(poll=0.001)
    t = q2.submit("flaky", max_retries=3)
    calls = {"n": 0}

    def flaky(task):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("flaky")
        return "ok"

    q2.run(flaky, workers=1)
    assert t.status is TaskStatus.DONE and t.result == "ok"
    assert t.attempts == 2

    # 3. retry exhausted -> FAILED with error captured
    q3 = TaskQueue(poll=0.001)
    bad = q3.submit("boom", max_retries=1)
    q3.run(lambda task: 1 / 0, workers=1)
    assert bad.status is TaskStatus.FAILED and bad.attempts == 2
    assert "ZeroDivisionError" in bad.error

    # 4. crash journal restore — tasks never lost
    jp = os.path.join(tmp, "crash.json")
    qa = TaskQueue(journal_path=jp, poll=0.001)
    qa.submit("S1", priority=3)
    qa.submit("S2", priority=3)
    qb = TaskQueue(journal_path=jp, poll=0.001)   # "restart"
    assert qb.stats()["PENDING"] == 2
    got: list[str] = []
    qb.run(lambda task: got.append(task.payload), workers=1)
    assert sorted(got) == ["S1", "S2"]

    # 5. GUI board
    qg = TaskQueue(poll=0.001)
    page = QueuePage(qg)
    page.interactive = False
    page.payload_edit.setText("BATCH-001 full flow")
    page.prio_spin.setValue(7)
    page.on_submit()
    stats = page.refresh()
    assert stats["PENDING"] == 1 and page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "7", "priority shown"
    qg.run(lambda task: task.payload, workers=1)
    assert page.refresh()["DONE"] == 1

    print("[P3-5 queue demo] task queue OK — priority order, "
          "parallel drain, retry policies, crash journal restore, "
          "visual board all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
