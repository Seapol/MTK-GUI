# -*- coding: utf-8 -*-
"""P3-8 batch pipeline automation tests."""
from __future__ import annotations

import pytest

from mtkgui.engine.batch_pipeline import (BP, BatchError, BatchPipeline,
                                          UnitState)


def test_create_batch_init_and_dedupe():
    bp = BatchPipeline()
    job = bp.create_batch("B1", ["SN1", "SN2", "SN1", "", "  "])
    assert list(job.units) == ["SN1", "SN2"], "dedupe + blank drop"
    assert job.stage_cursor == 0
    assert bp.batches() == ["B1"]
    with pytest.raises(BatchError):
        bp.create_batch("B1", ["X"])              # duplicate batch
    with pytest.raises(BatchError):
        bp.create_batch("B2", [])                 # empty rejected


def test_run_stage_batch_validate_isolation():
    bp = BatchPipeline()
    bp.create_batch("B1", ["SN1", "SN2", "SN3"])

    def validate(unit):
        if unit.unit_id == "SN2":
            raise ValueError("bad label")
    stats = bp.run_stage("B1", "validate", validate)
    assert stats == {"stage": "validate", "ok": 2, "fail": 1}
    snap = {u["unit_id"]: u for u in bp.snapshot("B1")}
    assert snap["SN1"]["state"] == "DONE"
    assert snap["SN2"]["state"] == "FAILED"
    assert "bad label" in snap["SN2"]["error"]
    assert snap["SN3"]["state"] == "DONE"


def test_stage_rejects_after_batch_closed():
    bp = BatchPipeline()
    bp.create_batch("B1", ["SN1"])
    bp.run_stage("B1", "s1", lambda u: None)
    job = bp.batch("B1")
    job.finished_at = "closed"
    with pytest.raises(BatchError):
        bp.run_stage("B1", "s2", lambda u: None)


def test_full_pipeline_unattended_plan():
    bp = BatchPipeline()
    bp.create_batch("B1", ["SN1", "SN2", "SN3"])
    plan = [
        ("validate", lambda u: None),
        ("test", lambda u: u.unit_id != "SN2" or
            (_ for _ in ()).throw(RuntimeError("fixture jam"))),
        ("report", lambda u: None),
        ("archive", lambda u: None),
    ]
    result = bp.execute("B1", plan)
    assert result["aborted"] is False
    assert result["stages"] == 4
    summ = bp.summarize("B1")
    assert summ["units"] == 3
    assert summ["states"]["DONE"] == 2
    assert summ["states"]["FAILED"] == 1
    assert summ["stages"]["test"]["FAIL"] == 1
    assert summ["yield"] == 0.667
    assert summ["finished_at"]
    # ledger traceable
    events = [r["event"] for r in bp.ledger_rows("B1")]
    for need in ("INIT", "validate", "test", "report", "archive",
                 "CLOSE"):
        assert need in events, need


def test_fallback_quarantine_on_failure():
    bp = BatchPipeline()
    bp.create_batch("B1", ["SN1", "SN2"])
    quarantined = []

    def test_fn(unit):
        if unit.unit_id == "SN1":
            raise RuntimeError("no response")

    def fallback(unit, exc):
        quarantined.append(unit.unit_id)

    bp.execute("B1", [("test", test_fn)],
               fallbacks={"test": fallback})
    snap = {u["unit_id"]: u for u in bp.snapshot("B1")}
    assert snap["SN1"]["state"] == "QUARANTINED"
    assert quarantined == ["SN1"]
    summ = bp.summarize("B1")
    assert summ["states"].get("QUARANTINED") == 1


def test_circuit_breaker_aborts_batch():
    bp = BatchPipeline(max_fail_ratio=0.5)
    bp.create_batch("B1", ["SN1", "SN2"])
    ran = []

    def bad(_):
        raise RuntimeError("x")

    plan = [("validate", bad),
            ("test", lambda u: ran.append(u.unit_id) or None)]
    result = bp.execute("B1", plan)
    assert result["aborted"] is True
    assert "circuit breaker" in result["reason"]
    assert ran == [], "later stages skipped after abort"
    assert bp.monitor("B1")["healthy"] is False


def test_monitor_and_unknown_batch():
    bp = BatchPipeline()
    bp.create_batch("B1", ["SN1", "SN2"])
    bp.run_stage("B1", "validate", lambda u: None)
    mon = bp.monitor("B1")
    assert mon["healthy"] is True
    assert mon["pending"] == ["SN1", "SN2"]
    assert mon["cursor"] == 1
    with pytest.raises(BatchError):
        bp.monitor("GHOST")


def test_snapshot_sorted_and_alias():
    bp = BatchPipeline()
    bp.create_batch("B", ["S2", "S1"])
    rows = bp.snapshot("B")
    assert [r["unit_id"] for r in rows] == ["S1", "S2"]
    assert rows[0]["stages"] == {}
    assert BP is BatchPipeline
