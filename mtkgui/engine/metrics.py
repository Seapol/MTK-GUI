# -*- coding: utf-8 -*-
"""P2-5 mass-production quality metrics engine (pure incremental).

Computes the three industrial KPIs from the P1 structured result base
(``StepResult`` rows enriched with batch / timestamp / station info):

  * Yield      — real product yield: PASS / FAIL / invalid (equipment,
                 environment, operator faults excluded from the DUT
                 denominator) + defect TOP ranking
  * CycleTime  — per-step / per-case / batch statistics: mean, max,
                 min, volatility (CV) and bottleneck ranking
  * Cp / CpK   — process capability per dimensional test parameter:
                 mean, sample stdev, Cp, CpK and capability grade

Pure calculation layer: zero changes to the runner, the report base
or any P1 module.  Every computation is logged with its exact input
parameters (``[METRICS]`` audit lines) so results stay reproducible
and reviewable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from enum import Enum

from mtkgui.engine.failures import FailureKind
from mtkgui.engine.results import StepResult, StepStatus

# failures NOT caused by the DUT -> excluded from the real yield
# denominator (equipment / environment / operator / infra faults)
INVALID_KINDS = frozenset({
    FailureKind.RESOURCE, FailureKind.ENGINE_ERROR,
    FailureKind.OPERATOR_ABORT, FailureKind.FROZEN,
    FailureKind.TIMEOUT,
})

SHIFT_DAY_START = dtime(8, 0)    # day shift   08:00 - 20:00
SHIFT_NIGHT_START = dtime(20, 0)  # night shift 20:00 - 08:00


@dataclass
class TestRecord:
    """One structured test outcome fed into the metrics engine."""
    name: str                       # case / step name
    status: StepStatus
    duration_s: float = 0.0
    measured: float | None = None   # dimensional measurement (CpK source)
    ts: datetime | None = None      # execution timestamp
    batch: str = ""                 # batch id
    station: str = ""               # station / device id
    failure_kind: FailureKind | None = None  # six-kind taxonomy

    @classmethod
    def from_step_result(cls, name: str, result: StepResult, *,
                         ts: datetime | None = None, batch: str = "",
                         station: str = "",
                         failure_kind: FailureKind | None = None
                         ) -> "TestRecord":
        return cls(name=name, status=result.status,
                   duration_s=result.duration_s,
                   measured=result.measured
                   if isinstance(result.measured, (int, float)) else None,
                   ts=ts, batch=batch, station=station,
                   failure_kind=failure_kind)

    @property
    def is_invalid(self) -> bool:
        """Non-DUT failure (equipment / environment / operator)."""
        return self.status == StepStatus.ERROR or \
            (self.failure_kind is not None
             and self.failure_kind in INVALID_KINDS)


# ================================================================= time
def filter_records(records: list[TestRecord], *, batch: str | None = None,
                   shift: str | None = None, day: datetime | None = None,
                   start: datetime | None = None,
                   end: datetime | None = None) -> list[TestRecord]:
    """Time-dimension filter: batch / shift (day|night) / calendar day
    / custom [start, end] window.  All criteria AND-combined; records
    without a timestamp only survive an empty filter."""
    empty = all(v is None for v in (batch, shift, day, start, end))
    if empty:
        return list(records)
    out = []
    for r in records:
        if r.ts is None:
            continue
        if batch is not None and r.batch != batch:
            continue
        if shift is not None and shift_of(r.ts) != shift:
            continue
        if day is not None and r.ts.date() != day.date():
            continue
        if start is not None and r.ts < start:
            continue
        if end is not None and r.ts > end:
            continue
        out.append(r)
    return out


def shift_of(ts: datetime) -> str:
    t = ts.time()
    return "day" if SHIFT_DAY_START <= t < SHIFT_NIGHT_START else "night"


# ================================================================ yield
@dataclass
class YieldReport:
    total: int = 0
    passed: int = 0
    failed: int = 0
    invalid: int = 0
    invalid_by_kind: dict = field(default_factory=dict)
    real_yield: float | None = None          # 0..1, None when no DUT rows
    top_defects: list = field(default_factory=list)  # [(name, n, ratio)]

    def to_dict(self) -> dict:
        return {"total": self.total, "passed": self.passed,
                "failed": self.failed, "invalid": self.invalid,
                "invalid_by_kind": dict(self.invalid_by_kind),
                "real_yield": self.real_yield,
                "top_defects": list(self.top_defects)}


def compute_yield(records: list[TestRecord],
                  top_n: int = 5) -> YieldReport:
    """Real product yield: equipment/environment faults are excluded
    from the denominator; defect TOP ratio is per FAIL case name."""
    rep = YieldReport(total=len(records))
    fail_names: dict[str, int] = {}
    for r in records:
        if r.is_invalid:
            rep.invalid += 1
            kind = (r.failure_kind or FailureKind.ENGINE_ERROR).value
            rep.invalid_by_kind[kind] = \
                rep.invalid_by_kind.get(kind, 0) + 1
        elif r.status == StepStatus.PASS:
            rep.passed += 1
        elif r.status == StepStatus.FAIL:
            rep.failed += 1
            fail_names[r.name] = fail_names.get(r.name, 0) + 1
    dut_rows = rep.passed + rep.failed
    rep.real_yield = (rep.passed / dut_rows) if dut_rows else None
    for name, n in sorted(fail_names.items(), key=lambda kv: -kv[1])[:top_n]:
        rep.top_defects.append((name, n, round(n / rep.failed, 4)
                                if rep.failed else 0.0))
    return rep


# ============================================================ cycle time
@dataclass
class CycleReport:
    samples: int = 0
    total_s: float = 0.0
    mean_s: float | None = None
    max_s: float | None = None
    min_s: float | None = None
    stdev_s: float | None = None             # sample stdev
    cv: float | None = None                  # volatility = stdev / mean
    per_case_mean: dict = field(default_factory=dict)
    bottlenecks: list = field(default_factory=list)  # [(name, mean_s)]

    def to_dict(self) -> dict:
        return {"samples": self.samples, "total_s": self.total_s,
                "mean_s": self.mean_s, "max_s": self.max_s,
                "min_s": self.min_s, "stdev_s": self.stdev_s,
                "cv": self.cv, "per_case_mean": dict(self.per_case_mean),
                "bottlenecks": list(self.bottlenecks)}


def compute_cycle_time(records: list[TestRecord],
                       top_n: int = 3) -> CycleReport:
    """Cycle-time statistics over step durations; bottleneck = slowest
    cases by mean duration."""
    rep = CycleReport()
    durs = [r.duration_s for r in records if r.duration_s > 0]
    rep.samples = len(durs)
    if durs:
        rep.total_s = sum(durs)
        rep.mean_s = rep.total_s / len(durs)
        rep.max_s = max(durs)
        rep.min_s = min(durs)
        if len(durs) >= 2:
            rep.stdev_s = _sample_stdev(durs)
            rep.cv = rep.stdev_s / rep.mean_s if rep.mean_s else None
    by_case: dict[str, list[float]] = {}
    for r in records:
        if r.duration_s > 0:
            by_case.setdefault(r.name, []).append(r.duration_s)
    rep.per_case_mean = {k: sum(v) / len(v)
                         for k, v in by_case.items()}
    for name, m in sorted(rep.per_case_mean.items(),
                          key=lambda kv: -kv[1])[:top_n]:
        rep.bottlenecks.append((name, round(m, 6)))
    return rep


# ================================================================== cpk
CAPability_GRADES = ((1.67, "A+"), (1.33, "A"), (1.0, "B"), (0.67, "C"))


@dataclass
class CpKReport:
    case: str = ""
    unit: str = ""
    n: int = 0
    mean: float | None = None
    stdev: float | None = None
    lsl: float | None = None
    usl: float | None = None
    cp: float | None = None
    cpk: float | None = None
    grade: str | None = None                 # A+ / A / B / C / D

    def to_dict(self) -> dict:
        return {"case": self.case, "unit": self.unit, "n": self.n,
                "mean": self.mean, "stdev": self.stdev,
                "lsl": self.lsl, "usl": self.usl,
                "cp": self.cp, "cpk": self.cpk, "grade": self.grade}


def compute_cpk(records: list[TestRecord], case: str, *,
                lsl: float, usl: float, unit: str = "") -> CpKReport:
    """Process capability of ONE dimensional test parameter.

    Cp  = (USL - LSL) / (6 sigma);  CpK = min(USL-m, m-LSL) / (3 sigma)
    using the sample stdev (ddof=1).  Grades: A+ >= 1.67, A >= 1.33,
    B >= 1.0, C >= 0.67, else D.  Needs n >= 2 measurable samples.
    """
    rep = CpKReport(case=case, unit=unit, lsl=lsl, usl=usl)
    values = [float(r.measured) for r in records
              if r.name == case and isinstance(r.measured, (int, float))]
    rep.n = len(values)
    if rep.n < 2:
        return rep                            # not enough data -> n only
    rep.mean = sum(values) / rep.n
    rep.stdev = _sample_stdev(values)
    sigma = rep.stdev
    if sigma == 0:
        # zero dispersion: capability bounded only by centering
        rep.cp = math.inf if usl > lsl else None
        rep.cpk = math.inf if (lsl < rep.mean < usl) else 0.0
    else:
        rep.cp = (usl - lsl) / (6.0 * sigma)
        rep.cpk = min(usl - rep.mean, rep.mean - lsl) / (3.0 * sigma)
    if rep.cpk is not None and not math.isinf(rep.cpk):
        rep.grade = next((g for th, g in CAPability_GRADES
                          if rep.cpk >= th), "D")
    elif rep.cpk is not None:
        rep.grade = "A+"
    return rep


def compute_cpk_all(records: list[TestRecord],
                    spec: dict[str, tuple[float, float]],
                    units: dict[str, str] | None = None
                    ) -> dict[str, CpKReport]:
    """Batch CpK for every dimensional parameter in ``spec``
    ({case: (lsl, usl)}) — adapter for all dimensional tests."""
    out: dict[str, CpKReport] = {}
    for case, (lsl, usl) in spec.items():
        out[case] = compute_cpk(records, case, lsl=lsl, usl=usl,
                                unit=(units or {}).get(case, ""))
    return out


# ============================================================== engine
def _sample_stdev(values: list[float]) -> float:
    n = len(values)
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


class MetricsEngine:
    """Collects structured records and computes the three KPI groups;
    every computation is audited ([METRICS]) with its filter parameters
    so any result can be reproduced and re-checked."""

    def __init__(self, log_fn=None) -> None:
        self.records: list[TestRecord] = []
        self.audit: list[tuple[str, str, str]] = []
        self.log = log_fn or (lambda line: None)

    # ingest -----------------------------------------------------------
    def add(self, record: TestRecord) -> None:
        self.records.append(record)

    def add_step_result(self, name: str, result: StepResult, **meta) -> None:
        self.records.append(TestRecord.from_step_result(
            name, result, **meta))

    # computations (all filter-aware) -----------------------------------
    def yield_report(self, **flt) -> YieldReport:
        rows = filter_records(self.records, **flt)
        rep = compute_yield(rows)
        self._audit("yield", flt, f"total={rep.total} "
                    f"pass={rep.passed} fail={rep.failed} "
                    f"invalid={rep.invalid} yield={rep.real_yield}")
        return rep

    def cycle_report(self, **flt) -> CycleReport:
        rows = filter_records(self.records, **flt)
        rep = compute_cycle_time(rows)
        self._audit("cycle", flt, f"samples={rep.samples} "
                    f"mean={rep.mean_s} cv={rep.cv}")
        return rep

    def cpk_report(self, case: str, lsl: float, usl: float,
                   unit: str = "", **flt) -> CpKReport:
        rows = filter_records(self.records, **flt)
        rep = compute_cpk(rows, case, lsl=lsl, usl=usl, unit=unit)
        self._audit("cpk", dict(flt, case=case, lsl=lsl, usl=usl),
                    f"n={rep.n} mean={rep.mean} cpk={rep.cpk} "
                    f"grade={rep.grade}")
        return rep

    # per-batch rollup ---------------------------------------------------
    def batch_summary(self, batch: str) -> dict:
        rows = filter_records(self.records, batch=batch)
        y, c = compute_yield(rows), compute_cycle_time(rows)
        self._audit("batch", {"batch": batch},
                    f"total={y.total} pass={y.passed} fail={y.failed} "
                    f"samples={c.samples}")
        return {"batch": batch, "yield": y.to_dict(),
                "cycle": c.to_dict()}

    # audit ----------------------------------------------------------------
    def _audit(self, action: str, params: dict, detail: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.audit.append((stamp, f"{action} {params}", detail))
        self.log(f"[METRICS] {stamp} {action} params={params}: {detail}")
