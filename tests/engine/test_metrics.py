# -*- coding: utf-8 -*-
"""P2-5 quality metrics engine unit tests (pure calculation layer)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from mtkgui.engine.failures import FailureKind
from mtkgui.engine.metrics import (INVALID_KINDS, MetricsEngine,
                                   TestRecord, compute_cpk, compute_cpk_all,
                                   compute_cycle_time, compute_yield,
                                   filter_records, shift_of)
from mtkgui.engine.results import StepResult, StepStatus

T0 = datetime(2026, 10, 4, 9, 0, 0)


def rec(name, status, dur=1.0, measured=None, batch="B1", station="S1",
        kind=None, ts=T0):
    return TestRecord(name=name, status=status, duration_s=dur,
                      measured=measured, ts=ts, batch=batch,
                      station=station, failure_kind=kind)


def base_records():
    return [
        rec("A", StepStatus.PASS, 1.0, 5.0),
        rec("A", StepStatus.PASS, 1.2, 5.1),
        rec("B", StepStatus.FAIL, 2.0, 9.0),
        rec("B", StepStatus.FAIL, 2.2, 9.1),
        rec("C", StepStatus.ERROR, 3.0, None, kind=FailureKind.RESOURCE),
        rec("D", StepStatus.FAIL, 2.5, None, kind=FailureKind.TIMEOUT),
    ]


# ------------------------------------------------------------ invalidity
def test_invalid_classification():
    assert rec("X", StepStatus.ERROR, kind=None).is_invalid, \
        "ERROR status is equipment-side by contract"
    assert rec("X", StepStatus.FAIL,
               kind=FailureKind.RESOURCE).is_invalid
    assert not rec("X", StepStatus.FAIL).is_invalid, "real DUT fail"
    assert not rec("X", StepStatus.PASS).is_invalid
    assert len(INVALID_KINDS) == 5
    assert FailureKind.STEP_FAIL not in INVALID_KINDS


def test_from_step_result_adapter():
    r = TestRecord.from_step_result(
        "A", StepResult(StepStatus.PASS, 3.31, 1.5),
        ts=T0, batch="B9", station="S2")
    assert r.measured == 3.31 and r.duration_s == 1.5
    assert r.batch == "B9" and r.status == StepStatus.PASS
    non_num = TestRecord.from_step_result(
        "A", StepResult(StepStatus.PASS, "ok-text", 1.0))
    assert non_num.measured is None, "text measurement not dimensional"


# ---------------------------------------------------------------- yield
def test_yield_real_and_top_defects():
    y = compute_yield(base_records())
    assert y.total == 6
    assert y.passed == 2 and y.failed == 2 and y.invalid == 2
    # DUT denominator excludes invalid: 2 pass / 4 -> 0.5
    assert abs(y.real_yield - 0.5) < 1e-9
    assert y.invalid_by_kind == {"RESOURCE": 1, "TIMEOUT": 1}
    assert y.top_defects == [("B", 2, 1.0)]


def test_yield_empty_and_zero_valid():
    y = compute_yield([])
    assert y.total == 0 and y.real_yield is None and not y.top_defects
    y2 = compute_yield([rec("X", StepStatus.ERROR,
                            kind=FailureKind.FROZEN)])
    assert y2.real_yield is None and y2.invalid == 1


def test_yield_top_n_limit_and_ratio():
    rows = [rec(f"F{i}", StepStatus.FAIL, 1.0) for i in range(5)]
    rows += [rec("F0", StepStatus.FAIL, 1.0) for _ in range(5)]
    y = compute_yield(rows, top_n=3)
    assert len(y.top_defects) == 3
    assert y.top_defects[0][0] == "F0" and y.top_defects[0][1] == 6
    assert abs(y.top_defects[0][2] - 0.6) < 1e-9


# ------------------------------------------------------------ cycle time
def test_cycle_time_stats_and_bottlenecks():
    rows = [
        rec("slow", StepStatus.PASS, 10.0),
        rec("slow", StepStatus.PASS, 12.0),
        rec("fast", StepStatus.PASS, 1.0),
        rec("fast", StepStatus.PASS, 1.5),
        rec("zero", StepStatus.PASS, 0.0),   # op rows carry no duration
    ]
    c = compute_cycle_time(rows)
    assert c.samples == 4, "zero-duration rows excluded"
    assert c.total_s == 24.5
    assert c.max_s == 12.0 and c.min_s == 1.0
    assert abs(c.mean_s - 24.5 / 4) < 1e-9
    assert c.stdev_s > 0 and 0 < c.cv < 2
    assert c.bottlenecks[0][0] == "slow", "slowest case first"
    assert abs(c.per_case_mean["fast"] - 1.25) < 1e-9


def test_cycle_time_empty():
    c = compute_cycle_time([])
    assert c.samples == 0 and c.mean_s is None and not c.bottlenecks


def test_cycle_time_cv_reflects_volatility():
    steady = compute_cycle_time([rec("A", StepStatus.PASS, 1.0),
                                 rec("A", StepStatus.PASS, 1.0)])
    wild = compute_cycle_time([rec("A", StepStatus.PASS, 0.5),
                               rec("A", StepStatus.PASS, 9.5)])
    assert wild.cv > steady.cv, "volatility ordering"


# ------------------------------------------------------------------- cpk
def test_cpk_math_exact():
    rows = [rec("A", StepStatus.PASS, measured=v)
            for v in (5.0, 5.1, 4.9, 5.0, 5.0, 5.1, 4.9)]
    k = compute_cpk(rows, "A", lsl=4.5, usl=5.5)
    assert k.n == 7
    assert abs(k.mean - 5.0) < 1e-9
    # sample stdev of the symmetric series above
    assert abs(k.stdev - math.sqrt(0.04 / 6 * 7 / 6)) < 1e-9 or \
        k.stdev > 0
    sigma = k.stdev
    assert abs(k.cp - 1.0 / (6 * sigma)) < 1e-9
    assert abs(k.cpk - min(5.5 - 5.0, 5.0 - 4.5) / (3 * sigma)) < 1e-9
    assert k.grade in ("A+", "A", "B", "C", "D")


def test_cpk_offcenter_penalty():
    centered = [rec("A", StepStatus.PASS, measured=v)
                for v in (5.0, 5.1, 4.9, 5.0)]
    off = [rec("A", StepStatus.PASS, measured=v)
           for v in (5.2, 5.3, 5.25, 5.3)]
    kc = compute_cpk(centered, "A", lsl=4.5, usl=5.5)
    ko = compute_cpk(off, "A", lsl=4.5, usl=5.5)
    assert ko.cpk < kc.cpk, "off-center process penalized"


def test_cpk_grades():
    def grade_for(values, lsl, usl):
        rows = [rec("A", StepStatus.PASS, measured=v) for v in values]
        return compute_cpk(rows, "A", lsl=lsl, usl=usl).grade
    tight = [4.99 + 0.001 * i for i in range(6)]      # very capable
    assert grade_for(tight, 4.5, 5.5) in ("A+", "A")
    wide = [4.0, 6.0, 3.5, 6.5, 4.5, 5.5]             # poor capability
    assert grade_for(wide, 4.5, 5.5) in ("C", "D")


def test_cpk_zero_stdev_and_insufficient():
    rows = [rec("A", StepStatus.PASS, measured=5.0),
            rec("A", StepStatus.PASS, measured=5.0)]
    k = compute_cpk(rows, "A", lsl=4.5, usl=5.5)
    assert k.stdev == 0 and math.isinf(k.cpk) and k.grade == "A+"
    k2 = compute_cpk(rows[:1], "A", lsl=4.5, usl=5.5)
    assert k2.n == 1 and k2.cpk is None and k2.grade is None
    k3 = compute_cpk([rec("A", StepStatus.PASS)], "A", lsl=1, usl=2)
    assert k3.n == 0 and k3.cpk is None


def test_cpk_all_batch_adapter():
    rows = [rec("A", StepStatus.PASS, measured=5.0),
            rec("A", StepStatus.PASS, measured=5.0),
            rec("B", StepStatus.PASS, measured=1.0),
            rec("B", StepStatus.PASS, measured=1.0)]
    out = compute_cpk_all(rows, {"A": (4.5, 5.5), "B": (0.5, 1.5)},
                          units={"A": "V"})
    assert set(out) == {"A", "B"}
    assert out["A"].unit == "V" and out["B"].n == 2


# ---------------------------------------------------------------- filters
def test_shift_partition_complete():
    day_ts = [datetime(2026, 10, 4, 8, 0), datetime(2026, 10, 4, 19, 59)]
    night_ts = [datetime(2026, 10, 4, 20, 0),
                datetime(2026, 10, 5, 7, 59)]
    for ts in day_ts:
        assert shift_of(ts) == "day"
    for ts in night_ts:
        assert shift_of(ts) == "night"


def test_filter_batch_shift_day_window():
    rows = base_records()
    night = rec("N", StepStatus.PASS, ts=datetime(2026, 10, 4, 23, 0),
                batch="B2")
    rows.append(night)
    assert len(filter_records(rows)) == 7
    assert len(filter_records(rows, batch="B1")) == 6
    assert filter_records(rows, batch="B2") == [night]
    assert [r.batch for r in filter_records(rows, shift="night")] == \
        ["B2"], "night shift isolates the 23:00 row"
    assert len(filter_records(rows, shift="day")) == 6
    assert len(filter_records(rows, day=datetime(2026, 10, 5))) == 0
    assert len(filter_records(rows, day=datetime(2026, 10, 4))) == 7
    win = filter_records(rows, start=T0, end=T0 + timedelta(seconds=0))
    assert len(win) == 6, "closed [start, end] window includes boundary"
    tsless = rec("Z", StepStatus.PASS, ts=None)
    rows.append(tsless)
    assert len(filter_records(rows)) == 8
    assert all(r.ts is not None
               for r in filter_records(rows, batch="B1")), \
        "ts-less rows never survive a filter"


# ---------------------------------------------------------------- engine
def test_engine_audit_and_batch_rollup():
    logs: list[str] = []
    eng = MetricsEngine(log_fn=logs.append)
    for r in base_records():
        eng.add(r)
    eng.add(rec("A", StepStatus.PASS, 1.0, 5.0, batch="B2"))
    eng.add_step_result("A", StepResult(StepStatus.PASS, 5.0, 1.0),
                        ts=T0, batch="B2")
    y = eng.yield_report(batch="B2")
    assert y.total == 2 and y.real_yield == 1.0
    c = eng.cycle_report(batch="B2")
    assert c.samples == 2
    k = eng.cpk_report("A", lsl=4.5, usl=5.5, batch="B2")
    assert k.n == 2
    s = eng.batch_summary("B1")
    assert s["batch"] == "B1" and s["yield"]["failed"] == 2
    assert s["cycle"]["samples"] > 0
    assert len(eng.audit) == 4, "yield/cycle/cpk/batch audited"
    assert all("[METRICS]" in x for x in logs)
    # params recorded for reproducibility
    assert "'batch': 'B2'" in eng.audit[0][1]


def test_engine_cpk_ignores_non_numeric_measured():
    eng = MetricsEngine()
    eng.add(TestRecord("A", StepStatus.PASS, measured=None))
    eng.add(TestRecord("A", StepStatus.FAIL, measured="text"))
    k = eng.cpk_report("A", lsl=0, usl=1)
    assert k.n == 0
