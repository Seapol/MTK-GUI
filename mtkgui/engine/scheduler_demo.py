# -*- coding: utf-8 -*-
"""Headless layered-scheduling demo (no hardware, no GUI).

Demonstrates the three scheduling levels over the FIFO scheduler:

  suite "Line-1 morning suite"
    batch "ICT sanity batch"      (3 cases, sequential)
    batch "FCT RF batch"          (2 cases, parallel pool of 2)
    case  "final visual check"    (single case at suite scope)

Run:  python -m mtkgui.engine.scheduler_demo [--fail]
Exit: 0 when the whole suite passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import sys
import time

from PySide6.QtCore import QCoreApplication

from .scheduler import BatchJob, CaseJob, SuiteJob, TestScheduler


def _case(name: str, ok: bool = True, delay: float = 0.05):
    def fn(ctx) -> str:
        ctx.log(f"case '{name}' running")
        time.sleep(delay)
        return "PASS" if ok else "FAIL"
    return fn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="layered scheduling demo (case / batch / suite)")
    parser.add_argument("--fail", action="store_true",
                        help="make one case FAIL to exercise the "
                             "failure path")
    args = parser.parse_args(argv)

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    lines: list[str] = []
    sched = TestScheduler(log_fn=lines.append)
    sched.last_report = None

    suite = SuiteJob("Line-1 morning suite", [
        BatchJob("ICT sanity batch", [
            CaseJob("ict continuity", _case("ict continuity")),
            CaseJob("ict impedance", _case("ict impedance")),
            CaseJob("ict voltage", _case("ict voltage")),
        ]),
        BatchJob("FCT RF batch", [
            CaseJob("wifi scan", _case("wifi scan")),
            CaseJob("bt scan", _case("bt scan",
                                     ok=not args.fail)),
        ], parallel=True, max_workers=2),
        CaseJob("final visual check", _case("final visual check",
                                            delay=0.02)),
    ])
    sched.submit(suite)
    sched.start()
    while sched.state != "idle" or sched.last_report is None:
        app.processEvents()
        if sched.state == "frozen":
            break
    for line in lines:
        print(line)
    print(f"Suite verdict: {suite.verdict}")
    return 0 if suite.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
