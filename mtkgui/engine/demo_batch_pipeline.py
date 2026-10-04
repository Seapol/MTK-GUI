# -*- coding: utf-8 -*-
"""P3-8 batch pipeline automation demo (headless-safe, rc=0).

Closed loop: batch init -> unattended plan (validate / test /
report / archive-upload) with per-unit failure isolation -> fallback
quarantine -> stats + yield -> monitor -> ledger traceability ->
PipelinePage GUI board.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mtkgui.engine.batch_pipeline import BatchPipeline


def main() -> int:
    bp = BatchPipeline(max_fail_ratio=0.5)

    # 1. batch init: dedupe + blank drop
    job = bp.create_batch("BATCH-0817",
                          ["SN1", "SN2", "SN3", "SN1", ""])
    assert list(job.units) == ["SN1", "SN2", "SN3"]

    # 2. unattended full plan: one unit jams at test stage
    def validate(unit):
        pass                        # batch validation hook

    def test_fn(unit):
        if unit.unit_id == "SN2":
            raise RuntimeError("fixture jam")

    def report(unit):
        unit.report_path = f"/outbox/{unit.unit_id}.html"

    def archive_upload(unit):
        unit.uploaded = True

    quarantined: list[str] = []

    def quarantine(unit, exc):
        quarantined.append(unit.unit_id)

    result = bp.execute(
        "BATCH-0817",
        [("validate", validate), ("test", test_fn),
         ("report", report), ("archive_upload", archive_upload)],
        fallbacks={"test": quarantine})
    assert result["aborted"] is False
    assert result["stages"] == 4

    # 3. stats: SN2 isolated, others flowed through all stages
    summ = bp.summarize("BATCH-0817")
    assert summ["states"]["DONE"] == 2
    assert summ["states"].get("QUARANTINED") == 1
    assert summ["stages"]["test"]["FAIL"] == 1
    assert summ["yield"] == 0.667
    snap = {u["unit_id"]: u for u in bp.snapshot("BATCH-0817")}
    assert snap["SN1"]["stages"]["archive_upload"] == "OK"
    assert "fixture jam" in snap["SN2"]["error"]
    assert quarantined == ["SN2"]

    # 4. monitor: unhealthy (failed unit) + ledger traceable
    mon = bp.monitor("BATCH-0817")
    assert mon["healthy"] is False
    assert mon["failed"][0]["unit_id"] == "SN2"
    events = [r["event"] for r in bp.ledger_rows("BATCH-0817")]
    for need in ("INIT", "validate", "test", "report",
                 "archive_upload", "CLOSE"):
        assert need in events, need

    # 5. circuit breaker: all-fail batch aborts before later stages
    bp.create_batch("BATCH-BAD", ["X1", "X2"])
    ran = []

    def bad(_):
        raise RuntimeError("x")

    res = bp.execute("BATCH-BAD",
                     [("test", bad),
                      ("report", lambda u: ran.append(u.unit_id))])
    assert res["aborted"] is True and "circuit breaker" in res["reason"]
    assert ran == []

    # 6. PipelinePage GUI board (headless offscreen)
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.pipeline_page import PipelinePage

    app = QApplication.instance() or QApplication([])
    page = PipelinePage(bp)
    page.interactive = False
    page.batch_edit.setText("BATCH-0901")
    page.units_edit.setText("A1,A2,A2")
    assert page.on_create() == "BATCH-0901"
    assert page.refresh() == 2, "dedupe -> two units"
    bp.execute("BATCH-0901", [("test", lambda u: None)])
    page.refresh()
    assert "BATCH-0901" in page.stats_label.text()
    assert page.table.rowCount() == 2

    print("[P3-8 batch pipeline demo] unattended pipeline OK — "
          "batch init dedupe, 4-stage plan (validate/test/report/"
          "archive_upload), per-unit failure isolation + quarantine "
          "fallback, stats & yield, monitor, circuit breaker, "
          "traceable ledger, PipelinePage board all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
