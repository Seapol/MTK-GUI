# -*- coding: utf-8 -*-
"""P3-8 batch pipeline automation middle platform (pure additive).

An UNATTENDED mass-production orchestrator composed on top of the
existing P2 engines — runner / metrics / uploader / archive are used
as stage callbacks, never modified:

  * BatchUnit / BatchJob — per-SN unit state machine + batch job
  * BatchPipeline        — stage execution kernel:
      create_batch   批量初始化  (dedupe + non-empty SN list)
      run_stage      批量校验/测试/报表/归档上传 — any named stage,
                     per-unit try/except isolation: one failing unit
                     NEVER blocks the others (异常兜底), its error is
                     captured and the optional fallback fn runs
      execute        whole plan unattended: stages in order, batch
                     aborted (FAILED) only when the failed-unit ratio
                     exceeds max_fail_ratio (批级熔断)
      monitor        流水线监控: pending units + stage checkpoint
      summarize      批量统计: per-stage pass/fail/pending counts
      snapshot       ledger of every stage transition (可溯源)

Zero changes to runner / metrics / uploader / archive / task_queue.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum


class UnitState(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"     # rejected at validation stage


@dataclass
class BatchUnit:
    unit_id: str                    # serial number
    state: UnitState = UnitState.PENDING
    stages: dict = field(default_factory=dict)   # stage -> "OK"/"FAIL"
    error: str = ""

    def as_row(self) -> dict:
        return {"unit_id": self.unit_id, "state": self.state.value,
                "stages": dict(self.stages), "error": self.error}


@dataclass
class BatchJob:
    batch_id: str
    units: dict = field(default_factory=dict)    # unit_id -> BatchUnit
    stage_cursor: int = 0           # stages completed so far
    started_at: str = ""
    finished_at: str = ""
    aborted_reason: str = ""

    @property
    def done(self) -> bool:
        return bool(self.finished_at or self.aborted_reason)


class BatchError(Exception):
    pass


class BatchPipeline:
    """Unattended batch pipeline kernel (stage isolation + fallback)."""

    def __init__(self, max_fail_ratio: float = 0.5, now=None):
        self.max_fail_ratio = max_fail_ratio
        self.now = now or (lambda: __import__("datetime")
                           .datetime.now())
        self._jobs: dict[str, BatchJob] = {}
        self._ledger: list[dict] = []    # every stage transition
        self._guard = threading.Lock()

    # ------------------------------------------------------------ log
    def _log(self, batch_id: str, event: str, detail: str) -> None:
        self._ledger.append({
            "ts": f"{self.now():%Y-%m-%d %H:%M:%S}",
            "batch_id": batch_id, "event": event, "detail": detail})

    # ------------------------------------------------------ 批量初始化
    def create_batch(self, batch_id: str, unit_ids: list) -> BatchJob:
        ids = [str(u).strip() for u in (unit_ids or [])]
        ids = [u for u in ids if u]
        if not ids:
            raise BatchError("empty unit list")
        if batch_id in self._jobs:
            raise BatchError(f"batch {batch_id} already exists")
        job = BatchJob(batch_id=batch_id,
                       started_at=f"{self.now():%Y-%m-%d %H:%M:%S}")
        for u in dict.fromkeys(ids):       # dedupe, keep order
            job.units[u] = BatchUnit(unit_id=u)
        self._jobs[batch_id] = job
        self._log(batch_id, "INIT",
                  f"{len(job.units)} units (from {len(ids)})")
        return job

    def batch(self, batch_id: str) -> BatchJob:
        job = self._jobs.get(batch_id)
        if job is None:
            raise BatchError(f"unknown batch {batch_id}")
        return job

    def batches(self) -> list[str]:
        return list(self._jobs)

    # ------------------------------------------------------ 批量阶段
    def run_stage(self, batch_id: str, stage: str, fn,
                  fallback=None) -> dict:
        """Run `fn(unit)` for every pending unit of the batch.

        Per-unit isolation: an exception marks only that unit FAILED
        (error captured) and the stage continues — 兜底 `fallback`
        (fn(unit, error)) may run.  Returns stage stats.
        """
        job = self.batch(batch_id)
        if job.done:
            raise BatchError(f"batch {batch_id} already closed")
        ok = fail = 0
        for unit in list(job.units.values()):
            if unit.state in (UnitState.FAILED,
                              UnitState.QUARANTINED):
                continue                       # terminal -> isolated
            try:
                fn(unit)
                unit.stages[stage] = "OK"
                unit.state = UnitState.DONE    # flows to next stage
                ok += 1
                self._log(batch_id, stage, f"{unit.unit_id} OK")
            except Exception as exc:                    # noqa: BLE001
                unit.stages[stage] = "FAIL"
                unit.state = UnitState.FAILED
                unit.error = f"{stage}: {exc}"
                fail += 1
                self._log(batch_id, stage,
                          f"{unit.unit_id} FAIL ({exc})")
                if fallback is not None:
                    try:
                        fallback(unit, exc)
                        unit.state = UnitState.QUARANTINED
                    except Exception:                   # noqa: BLE001
                        pass
        job.stage_cursor += 1
        return {"stage": stage, "ok": ok, "fail": fail}

    # ---------------------------------------------------- 无人值守执行
    def execute(self, batch_id: str, plan: list,
                fallbacks: dict | None = None) -> dict:
        """Run the whole stage plan unattended, in order.

        plan = [(stage_name, fn), ...].  Batch-level circuit breaker:
        if the cumulative FAILED ratio exceeds max_fail_ratio the
        batch aborts (remaining stages skipped) — 异常兜底.
        """
        fallbacks = fallbacks or {}
        total = 0
        for stage, fn in plan:
            stats = self.run_stage(batch_id, stage, fn,
                                   fallbacks.get(stage))
            total += stats["fail"]
            job = self.batch(batch_id)
            failed_ratio = total / max(1, len(job.units))
            if failed_ratio > self.max_fail_ratio:
                job.aborted_reason = (
                    f"circuit breaker: fail ratio "
                    f"{failed_ratio:.2f} > {self.max_fail_ratio} "
                    f"after stage {stage}")
                self._log(batch_id, "ABORT", job.aborted_reason)
                return {"stages": job.stage_cursor,
                        "aborted": True,
                        "reason": job.aborted_reason}
        job = self.batch(batch_id)
        job.finished_at = f"{self.now():%Y-%m-%d %H:%M:%S}"
        self._log(batch_id, "CLOSE",
                  f"pipeline finished ({job.stage_cursor} stages)")
        return {"stages": job.stage_cursor, "aborted": False,
                "reason": ""}

    # ------------------------------------------------------ 批量统计
    def summarize(self, batch_id: str) -> dict:
        job = self.batch(batch_id)
        per_state: dict[str, int] = {}
        for u in job.units.values():
            per_state[u.state.value] = \
                per_state.get(u.state.value, 0) + 1
        stages: dict[str, dict] = {}
        for u in job.units.values():
            for stage, res in u.stages.items():
                s = stages.setdefault(stage, {"OK": 0, "FAIL": 0})
                s[res] += 1
        return {"batch_id": batch_id, "units": len(job.units),
                "states": per_state, "stages": stages,
                "yield": round(per_state.get("DONE", 0)
                               / max(1, len(job.units)), 3),
                "finished_at": job.finished_at,
                "aborted_reason": job.aborted_reason}

    # ------------------------------------------------------ 流水线监控
    def monitor(self, batch_id: str) -> dict:
        """Watchdog view: flowing/pending units + failed details."""
        job = self.batch(batch_id)
        pending = [u.unit_id for u in job.units.values()
                   if u.state in (UnitState.PENDING, UnitState.DONE)]
        failed = [{"unit_id": u.unit_id, "error": u.error}
                  for u in job.units.values()
                  if u.state in (UnitState.FAILED,
                                 UnitState.QUARANTINED)]
        healthy = not failed and not job.aborted_reason
        return {"batch_id": batch_id, "pending": pending,
                "failed": failed, "cursor": job.stage_cursor,
                "healthy": healthy,
                "aborted_reason": job.aborted_reason}

    def snapshot(self, batch_id: str) -> list[dict]:
        return [u.as_row() for u in
                sorted(self.batch(batch_id).units.values(),
                       key=lambda u: u.unit_id)]

    def ledger_rows(self, batch_id: str | None = None) -> list[dict]:
        return [r for r in self._ledger
                if batch_id is None or r["batch_id"] == batch_id]


#: short public alias
BP = BatchPipeline
