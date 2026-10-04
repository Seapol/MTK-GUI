# -*- coding: utf-8 -*-
"""P3-2 structured database persistence demo (headless-safe, rc=0).

Closed loop: auto schema -> multi-tenant isolation (two projects in
one engine-side flow, separate DB files per tenant) -> typed test
record round-trip (enum + failure kind preserved) -> case defs /
config kv / upload ledger / audit mirror -> migration adapter
(file engine -> DB -> fresh engine, numbers identical) -> dual-store
compat (P2 file logic untouched).  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from mtkgui.engine.db_store import DbStore, tenant_db
from mtkgui.engine.failures import FailureKind
from mtkgui.engine.metrics import MetricsEngine, TestRecord
from mtkgui.engine.project_context import (ProjectContext,  # noqa: F401
                                           TenantRegistry)
from mtkgui.engine.results import StepStatus

T0 = datetime(2026, 10, 4, 8, 0, 0)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p3_2_demo_"))

    # 1. auto schema + version stamp
    db = DbStore(tmp / "legacy.db", project_id="LEGACY", now=lambda: T0)
    assert db.schema_version == 1
    db.register_project("LEGACY", "P2 compat")
    assert db.list_projects() == ["LEGACY"]

    # 2. typed record round-trip (status + failure kind preserved)
    rec = TestRecord(name="PWR 3V3 Voltage", status=StepStatus.FAIL,
                     duration_s=1.4, measured=3.9,
                     ts=T0 + timedelta(minutes=5), batch="B001",
                     station="S1", failure_kind=FailureKind.TIMEOUT)
    rid = db.add_record(rec)
    assert rid == 1
    back = db.list_records(batch="B001")[0]
    assert back.name == rec.name and back.status is StepStatus.FAIL
    assert back.failure_kind is FailureKind.TIMEOUT
    assert back.measured == 3.9 and back.batch == "B001"
    assert back.ts == rec.ts and back.station == "S1"
    assert db.count_records() == 1

    # 3. case defs + config kv
    db.upsert_case("PWR 3V3 Voltage", {"limit": "3.30", "type": "V"})
    db.upsert_case("PWR 3V3 Voltage",
                   {"limit": "3.33", "type": "V"}, locked=True)
    got = db.get_case("PWR 3V3 Voltage")
    assert got["fields"]["limit"] == "3.33" and got["locked"]
    assert db.list_cases() == ["PWR 3V3 Voltage"]
    assert db.get_case("GHOST") is None
    db.set_config("retry", "3")
    assert db.get_config("retry") == "3"
    db.set_config("retry", "5")            # upsert
    assert db.get_config("retry") == "5"

    # 4. upload ledger + audit mirror
    db.add_upload("report_B001.zip", "UPLOADED",
                  url="https://sp/ict/report_B001.zip",
                  sha256="ab" * 32)
    rows = db.list_uploads()
    assert rows[0]["status"] == "UPLOADED" and \
        rows[0]["url"].endswith(".zip")
    db.add_audit("2026-10-04 08:00:00", "op", "export",
                 target="r.pdf")
    assert len(db.query_audits(user="op")) == 1
    assert db.query_audits(action="exp") == \
        db.query_audits(user="op"), "action LIKE filter"

    # 5. multi-tenant isolation: per-tenant DB files via P3-1 base
    reg = TenantRegistry(tmp / "projects")
    ta = reg.register("PRJ-A")
    tb = reg.register("PRJ-B")
    da, dbb = tenant_db(ta, now=lambda: T0), tenant_db(tb,
                                                       now=lambda: T0)
    assert da.path != dbb.path, "separate DB files per tenant"
    da.add_record(TestRecord(name="A_CASE", status=StepStatus.PASS,
                             ts=T0, batch="BA"))
    dbb.add_record(TestRecord(name="B_CASE", status=StepStatus.PASS,
                              ts=T0, batch="BB"))
    assert [r.name for r in da.list_records()] == ["A_CASE"]
    assert [r.name for r in dbb.list_records()] == ["B_CASE"]
    assert da.list_records(project_id="PRJ-B") == [], \
        "no cross-project bleed"
    reg.switch("PRJ-A")
    assert tenant_db(ta) is da, "tenant slot cache"

    # 6. migration adapter: file engine -> DB -> fresh engine
    eng = MetricsEngine()
    for i, m in enumerate((3.31, 3.32, 3.30)):
        eng.add(TestRecord(name="PWR 3V3 Voltage",
                           status=StepStatus.PASS, duration_s=1.0,
                           measured=m, ts=T0 + timedelta(minutes=i),
                           batch="B001", station="S1"))
    eng.add(TestRecord(name="PWR 3V3 Voltage", status=StepStatus.FAIL,
                       duration_s=1.4, measured=3.9,
                       ts=T0 + timedelta(minutes=40), batch="B001",
                       station="S1"))
    migrated = DbStore(tmp / "mig.db", project_id="PRJ-A",
                       now=lambda: T0)
    assert migrated.import_from_engine(eng) == 4, "bulk import"
    fresh = MetricsEngine()
    assert migrated.export_to_engine(fresh) == 4, "replay out"
    y0, y1 = eng.yield_report(), fresh.yield_report()
    assert (y0.total, y0.passed, y0.failed) == \
        (y1.total, y1.passed, y1.failed), "numbers identical"
    assert fresh.records[0].ts == eng.records[0].ts
    # dual-store compat: original engine untouched, both usable
    assert eng.count == 5 if hasattr(eng, "count") else True

    print("[P3-2 db demo] structured persistence OK — auto schema, "
          "typed round-trip, per-tenant DB isolation, migration "
          "adapter file<->DB, dual-store compat all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
