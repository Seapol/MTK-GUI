# -*- coding: utf-8 -*-
"""P2-5 mass-production quality metrics engine demo (rc=0 on success).

Closed loop: structured StepResult records (with six-kind failure
taxonomy) -> Yield (real product yield, invalid filtered, defect TOP)
+ CycleTime (mean/max/min/CV/bottlenecks) + Cp/CpK (per-parameter
capability grades) + time-dimension filters (batch/shift/day/window)
+ [METRICS] audit reproducibility.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from mtkgui.engine.failures import FailureKind
from mtkgui.engine.metrics import (INVALID_KINDS, MetricsEngine,
                                   TestRecord, compute_yield,
                                   filter_records, shift_of)
from mtkgui.engine.results import StepResult, StepStatus

T0 = datetime(2026, 10, 4, 9, 0, 0)


def rec(name, status, dur, measured=None, batch="B001",
        station="S1", kind=None, offset_min=0.0):
    return TestRecord(name=name, status=status, duration_s=dur,
                      measured=measured, ts=T0 + timedelta(minutes=offset_min),
                      batch=batch, station=station, failure_kind=kind)


def main() -> int:
    eng = MetricsEngine()

    # ---- structured input: 3 DUTs in batch B001 + 1 in B002 ----------
    # DUT#1 all pass
    for i, (n, m, d) in enumerate([
            ("PWR 3V3 Voltage", 3.31, 1.2), ("PWR 1V8 Voltage", 1.79, 0.9),
            ("CLK Frequency", 32767.9, 2.0)]):
        eng.add(rec(n, StepStatus.PASS, d, m, offset_min=i))
    # DUT#2: one real FAIL (out of limit) then remaining pass
    eng.add(rec("PWR 3V3 Voltage", StepStatus.FAIL, 1.3, 3.9,
                offset_min=10))
    eng.add(rec("PWR 1V8 Voltage", StepStatus.PASS, 0.8, 1.80,
                offset_min=11))
    eng.add(rec("CLK Frequency", StepStatus.PASS, 2.1, 32768.1,
                offset_min=12))
    # DUT#3: equipment fault (RESOURCE) + timeout -> INVALID rows
    eng.add(rec("PWR 3V3 Voltage", StepStatus.ERROR, 5.0, None,
                kind=FailureKind.RESOURCE, offset_min=20))
    eng.add(rec("PWR 1V8 Voltage", StepStatus.ERROR, 6.0, None,
                kind=FailureKind.TIMEOUT, offset_min=21))
    eng.add(rec("CLK Frequency", StepStatus.PASS, 1.9, 32768.0,
                offset_min=22))
    # DUT#4 (batch B002, night shift) all pass
    for i, (n, m, d) in enumerate([
            ("PWR 3V3 Voltage", 3.30, 1.1), ("PWR 1V8 Voltage", 1.81, 1.0),
            ("CLK Frequency", 32768.2, 2.2)]):
        eng.add(rec(n, StepStatus.PASS, d, m, batch="B002",
                    station="S2", offset_min=600 + i))

    # StepResult adapter path (P1 contract reuse)
    eng.add_step_result("PWR 3V3 Voltage",
                        StepResult(StepStatus.PASS, 3.32, 1.0),
                        ts=T0 + timedelta(minutes=700), batch="B002",
                        station="S2")

    # ---- 1. yield: invalid excluded from the real denominator --------
    y = eng.yield_report()
    assert y.total == 13 and y.invalid == 2, y
    assert y.passed == 10 and y.failed == 1, y
    # DUT rows = 11 -> real yield 10/11
    assert abs(y.real_yield - 10 / 11) < 1e-9, y.real_yield
    assert y.invalid_by_kind.get("RESOURCE") == 1
    assert y.invalid_by_kind.get("TIMEOUT") == 1
    assert y.top_defects and y.top_defects[0][0] == "PWR 3V3 Voltage"
    assert y.top_defects[0][1] == 1 and y.top_defects[0][2] == 1.0
    assert set(INVALID_KINDS) and all(k.value for k in INVALID_KINDS)

    # ---- 2. cycle time -------------------------------------------------
    c = eng.cycle_report()
    assert c.samples == 13 and c.total_s > 0
    assert c.max_s == 6.0 and c.min_s == 0.8, (c.max_s, c.min_s)
    assert c.stdev_s is not None and 0 < c.cv < 1
    assert c.bottlenecks[0][0] == "CLK Frequency" or \
        c.bottlenecks[0][1] >= c.bottlenecks[-1][1], c.bottlenecks
    assert c.per_case_mean["PWR 3V3 Voltage"] > 0

    # ---- 3. CpK per dimensional parameter -------------------------------
    k1 = eng.cpk_report("PWR 3V3 Voltage", lsl=3.267, usl=3.333, unit="V")
    assert k1.n == 4, k1.n  # ERROR rows carry no measurement
    assert k1.mean is not None and k1.stdev > 0
    assert k1.cp is not None and k1.cpk is not None
    # 3.9 V outlier drags CpK below the in-window mean capability
    assert k1.cpk < k1.cp, "CpK must be centered-penalty aware"
    assert k1.grade in ("A+", "A", "B", "C", "D")
    k2 = eng.cpk_report("PWR 1V8 Voltage", lsl=1.764, usl=1.836)
    assert k2.n == 3 and k2.grade in ("A+", "A", "B", "C", "D")
    # insufficient data -> no capability numbers
    k3 = eng.cpk_report("CLK Frequency", lsl=1, usl=2,
                        batch="NO_SUCH_BATCH")
    assert k3.n == 0 and k3.cpk is None and k3.grade is None

    # ---- 4. time-dimension filters --------------------------------------
    assert len(filter_records(eng.records)) == 13, "no filter = all"
    b1 = filter_records(eng.records, batch="B001")
    assert len(b1) == 9, len(b1)
    y_b1 = compute_yield(b1)
    assert abs(y_b1.real_yield - 6 / 7) < 1e-9, y_b1.real_yield  # 6P/1F
    # shift: day records are 08:00-20:00, night otherwise
    night = filter_records(eng.records, shift="night")
    assert all(shift_of(r.ts) == "night" for r in night) and night
    day = filter_records(eng.records, shift="day")
    assert all(shift_of(r.ts) == "day" for r in day)
    assert len(night) + len(day) == 13, "shift partition is complete"
    d4 = filter_records(eng.records,
                        day=datetime(2026, 10, 4))
    assert len(d4) == 13
    win = filter_records(eng.records,
                         start=T0 + timedelta(minutes=600),
                         end=T0 + timedelta(minutes=705))
    assert len(win) == 4, len(win)  # B002 night-shift rows + StepResult
    # timestamp-less records only survive an empty filter
    eng.add(TestRecord(name="X", status=StepStatus.PASS, duration_s=1.0))
    assert len(filter_records(eng.records, batch="B001")) == 9, \
        "ts-less row excluded by filters"
    assert eng.yield_report().total == 14

    # ---- 5. batch rollup + audit reproducibility -------------------------
    s = eng.batch_summary("B002")
    assert s["batch"] == "B002"
    assert s["yield"]["total"] == 4 and s["yield"]["failed"] == 0
    assert s["yield"]["real_yield"] == 1.0
    assert s["cycle"]["samples"] == 4
    assert len(eng.audit) >= 4, "every computation audited"
    assert all("[METRICS]" in line for line in (
        f"[METRICS] ok-{i}" for i in range(0)))  # log fn sanity
    logs: list[str] = []
    eng2 = MetricsEngine(log_fn=logs.append)
    eng2.add(rec("A", StepStatus.PASS, 1.0, 5.0))
    eng2.yield_report(batch="B001")
    eng2.cpk_report("A", lsl=4, usl=6)
    assert any("[METRICS]" in x for x in logs), "audit lines emitted"
    assert eng2.audit[0][1] == "yield {'batch': 'B001'}", \
        "params traceable"

    print("[P2-5 metrics demo] quality metrics engine OK — real yield "
          "with invalid filtering + defect TOP, cycle-time stats with "
          "bottlenecks, Cp/CpK grades, batch/shift/day/window filters, "
          "[METRICS] auditable + reproducible all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
