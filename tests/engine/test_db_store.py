# -*- coding: utf-8 -*-
"""P3-2 database persistence tests."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from mtkgui.engine.db_store import DbStore, tenant_db
from mtkgui.engine.failures import FailureKind
from mtkgui.engine.metrics import MetricsEngine, TestRecord
from mtkgui.engine.project_context import (ProjectContext,
                                           TenantRegistry)
from mtkgui.engine.results import StepStatus

T0 = datetime(2026, 10, 4, 8, 0, 0)


@pytest.fixture()
def db(tmp_path):
    d = DbStore(tmp_path / "t.db", project_id="P1", now=lambda: T0)
    yield d
    d.close()


def rec(name="C", status=StepStatus.PASS, **kw):
    base = dict(duration_s=1.0, measured=3.3, ts=T0, batch="B",
                station="S")
    base.update(kw)
    return TestRecord(name=name, status=status, **base)


def test_auto_schema_and_version(tmp_path):
    d = DbStore(tmp_path / "a.db", now=lambda: T0)
    assert d.schema_version == 1
    d.close()
    d2 = DbStore(tmp_path / "a.db", now=lambda: T0)   # reopen idempotent
    assert d2.schema_version == 1
    d2.close()


def test_register_project_idempotent(db):
    db.register_project("P1")
    db.register_project("P1", "dup ignored")
    assert db.list_projects() == ["P1"]


def test_record_round_trip_all_fields(db):
    r = rec(status=StepStatus.ERROR, measured=None, batch="B9",
            station="ST7", failure_kind=FailureKind.RESOURCE,
            ts=T0 + timedelta(hours=1))
    db.add_record(r)
    out = db.list_records()[0]
    assert out.status is StepStatus.ERROR
    assert out.failure_kind is FailureKind.RESOURCE
    assert out.measured is None and out.batch == "B9"
    assert out.station == "ST7"
    assert out.ts == T0 + timedelta(hours=1)


def test_record_filters(db):
    db.add_record(rec(name="A", batch="B1"))
    db.add_record(rec(name="B", batch="B2"))
    db.add_record(rec(name="A", batch="B2", status=StepStatus.FAIL))
    assert len(db.list_records(batch="B2")) == 2
    assert [r.name for r in db.list_records(name="A")] == ["A", "A"]
    assert db.list_records(batch="B1")[0].name == "A"
    assert db.count_records() == 3
    assert db.count_records(project_id="NOPE") == 0


def test_project_scoped_queries(db):
    db.add_record(rec(name="MINE"))
    db.add_record(rec(name="OTHER"), project_id="P2")
    assert [r.name for r in db.list_records()] == ["MINE"]
    assert [r.name for r in
            db.list_records(project_id="P2")] == ["OTHER"]
    assert db.count_records(project_id="P2") == 1


def test_case_upsert_and_lock(db):
    db.upsert_case("C1", {"limit": 1})
    db.upsert_case("C1", {"limit": 2}, locked=True)
    got = db.get_case("C1")
    assert got == {"fields": {"limit": 2}, "locked": True}
    assert db.list_cases() == ["C1"]


def test_config_upsert(db):
    assert db.get_config("k") is None
    db.set_config("k", "1")
    db.set_config("k", "2")
    assert db.get_config("k") == "2"
    assert db.get_config("k", project_id="P2") is None, \
        "config isolated per project"


def test_upload_ledger_and_audit_query(db):
    db.add_upload("a.zip", "UPLOADED", url="u", sha256="s")
    db.add_upload("b.zip", "FAILED")
    rows = db.list_uploads()
    assert [r["status"] for r in rows] == ["UPLOADED", "FAILED"]
    db.add_audit("t1", "op", "login:GRANT", target="op")
    db.add_audit("t2", "admin", "edit_config:DENY")
    assert len(db.query_audits(user="op")) == 1
    assert len(db.query_audits(action="DENY")) == 1
    assert len(db.query_audits(project_id="P1")) == 2


def test_migration_adapter_round_trip(db, tmp_path):
    eng = MetricsEngine()
    for i in range(5):
        eng.add(rec(name=f"C{i}", batch=f"B{i % 2}",
                    measured=3.3 + i * 0.01))
    db.register_project("P1")
    assert db.import_from_engine(eng) == 5
    fresh = MetricsEngine()
    assert db.export_to_engine(fresh) == 5
    assert len(fresh.records) == 5
    y0, y1 = eng.yield_report(), fresh.yield_report()
    assert (y0.total, y0.passed) == (y1.total, y1.passed)


def test_tenant_db_per_project_isolated(tmp_path):
    reg = TenantRegistry(tmp_path / "projects")
    ta = reg.register("A")
    tb = reg.register("B")
    reg.switch("A")
    da = tenant_db(ta, now=lambda: T0)
    reg.switch("B")
    dbb = tenant_db(tb, now=lambda: T0)
    assert da.path.name == "tenant.db"
    assert da.path != dbb.path
    assert da.project_id == "A" and dbb.project_id == "B"
    da.add_record(rec(name="XA"))
    assert dbb.list_records() == [], "isolation by default scope"
    assert tenant_db(tb) is dbb, "active tenant slot cached"
    reg.switch("A")                      # leaves B -> B slots cleared
    assert tenant_db(ta) is not da, "re-entering yields fresh store"
    ProjectContext.set_current(None)
