# -*- coding: utf-8 -*-
"""P3-10 audit middle platform & compliance report tests."""
from __future__ import annotations

import json

import pytest

from mtkgui.engine.audit_hub import AH, AuditHub, CATEGORIES, diff_of
from mtkgui.engine.auth_audit import AuditLog


def _hub(tmp_path):
    return AuditHub(AuditLog(tmp_path / "audit.jsonl"))


def test_diff_of_field_comparison():
    assert diff_of({"a": 1, "b": 2}, {"a": 1, "b": 3}) == \
        [{"field": "b", "old": 2, "new": 3}]
    assert diff_of(None, {"x": 1}) == [{"field": "x", "old": None,
                                        "new": 1}]
    assert diff_of({"x": 1}, {"x": 1}) == []


def test_track_categorizes_full_chain(tmp_path):
    hub = _hub(tmp_path)
    hub.track("op1", "login", "login", "op1")
    hub.track("op1", "config", "edit", "config.yaml")
    hub.track("op1", "case", "lock", "CASE-1")
    hub.track("op1", "task", "submit", "T1")
    hub.track("op1", "device", "disable", "D1")
    hub.track("op1", "bogus", "x", "Y")          # -> data plane
    acts = [e["action"] for e in hub.entries()]
    for need in ("login:login", "config:edit", "case:lock",
                 "task:submit", "device:disable", "data:x"):
        assert need in acts, need
    rows = hub.query(category="config")
    assert len(rows) == 1 and rows[0]["action"] == "config:edit"


def test_change_records_before_after(tmp_path):
    hub = _hub(tmp_path)
    hub.change("eng1", "config", "edit", "config.yaml",
               before={"voltage": 3.3, "retries": 2},
               after={"voltage": 3.5, "retries": 2})
    entries = hub.entries()
    e = entries[-1]
    assert e["before"] and e["after"]
    assert "voltage: 3.3->3.5" in e["detail"]
    hist = hub.changes_of("config.yaml")
    assert len(hist) == 1
    assert hist[0]["diff"] == [{"field": "voltage",
                                "old": 3.3, "new": 3.5}]


def test_stats_coverage_and_denials(tmp_path):
    hub = _hub(tmp_path)
    hub.track("op1", "login", "login:GRANT", "op1")
    hub.track("ghost", "security", "login:DENY", "ghost")
    hub.track("op1", "task", "submit", "T1")
    st = hub.stats()
    assert st["total"] == 3
    assert st["by_category"]["security"] == 1
    assert st["denied"] == 1
    assert st["by_user"]["op1"] == 2


def test_verify_integrity(tmp_path):
    hub = _hub(tmp_path)
    hub.track("op1", "task", "submit", "T1")
    assert hub.verify()["ok"] is True
    # corrupt the ledger with a malformed line
    with open(hub.audit.path, "a", encoding="utf-8") as fh:
        fh.write("NOT-JSON\n")
    v = hub.verify()
    assert v["ok"] is False and v["malformed"] == 1


def test_compliance_report_exports(tmp_path):
    hub = _hub(tmp_path)
    hub.track("op1", "login", "login", "op1")
    hub.track("op1", "config", "edit", "cfg.yaml",
              before={"a": 1}, after={"a": 2})
    hub.track("ghost", "security", "login:DENY", "ghost")
    out = tmp_path / "reports" / "iso_audit"
    summary = hub.compliance_report(out)
    assert summary["total_entries"] >= 3
    assert summary["coverage"]["config"] == 1
    assert summary["change_records"] == 1
    assert summary["denied_attempts"] == 1
    assert summary["integrity"] is True
    # both artifacts written
    assert out.with_suffix(".json").is_file()
    assert out.with_suffix(".csv").is_file()
    data = json.loads(out.with_suffix(".json").read_text("utf-8"))
    assert data["summary"] == summary
    assert len(data["entries"]) >= 3
    # period filter honored
    narrow = hub.compliance_report(tmp_path / "r2",
                                   since="2999-01-01")
    assert narrow["total_entries"] == 0
    assert len(narrow["uncovered_categories"]) == len(CATEGORIES)


def test_alias_and_categories_frozen():
    assert AH is AuditHub
    assert "login" in CATEGORIES and "security" in CATEGORIES
