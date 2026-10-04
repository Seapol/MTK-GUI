# -*- coding: utf-8 -*-
"""P2-11 RBAC + audit tests."""
from __future__ import annotations

from datetime import datetime

import pytest

from mtkgui.engine.auth_audit import (AccessControl, AuditLog, Role,
                                      Session)

T0 = datetime(2026, 10, 4, 8, 0, 0)


@pytest.fixture()
def env(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl", now=lambda: T0)
    access = AccessControl(tmp_path / "accounts.json", audit=audit,
                           now=lambda: T0)
    access.ensure_default_accounts()
    return access, audit, tmp_path


def test_bootstrap_accounts_local_and_salted(env):
    access, _, tmp_path = env
    import json
    raw = json.loads((tmp_path / "accounts.json").read_text("utf-8"))
    assert set(raw) == {"admin", "op"}
    assert raw["admin"]["hash"] != "admin123"
    assert raw["admin"]["hash"] != raw["op"]["hash"], "per-user salt"
    access.ensure_default_accounts()      # idempotent
    assert set(access.accounts) == {"admin", "op"}


def test_login_success_and_failure(env):
    access, audit, _ = env
    admin = access.login("admin", "admin123")
    assert admin is not None and admin.role is Role.ADMIN
    assert access.login("op", "nope") is None
    assert access.login("ghost", "x") is None
    denials = audit.query(action="login:DENY")
    assert len(denials) == 2, "failed logins traced"
    assert audit.query(action="login:GRANT")[-1]["user"] == "admin"


def test_operator_permissions_boundary(env):
    access, audit, _ = env
    op = access.login("op", "op123")
    for act in ("edit_config", "edit_case", "report_delete"):
        with pytest.raises(PermissionError):
            access.require(op, act, "t")
    for act in ("run_test", "view", "export_report", "upload"):
        access.require(op, act, "t")          # allowed
    # every denial audited with user + action
    denies = audit.query(action="edit_config:DENY")
    assert denies and denies[-1]["user"] == "op"


def test_admin_full_and_anonymous_denied(env):
    access, audit, _ = env
    admin = access.login("admin", "admin123")
    for act in ("edit_config", "edit_case", "report_delete",
                "run_test", "view", "export_report", "upload"):
        access.require(admin, act, "t")       # all allowed
    with pytest.raises(PermissionError):
        access.require(None, "view")
    denies = audit.query(action="view:DENY")
    assert denies[-1]["user"] == "anonymous"


def test_audit_before_after_and_fields(env):
    access, audit, _ = env
    e = audit.log("admin", "edit_config", "project.yaml",
                  before={"retry": 2}, after={"retry": 3},
                  detail="GUI")
    assert e["ts"] == "2026-10-04 08:00:00"
    assert e["before"] == '{"retry": 2}' and e["after"] == \
        '{"retry": 3}'
    assert e["user"] == "admin" and e["target"] == "project.yaml"
    assert audit.entries()[-1]["detail"] == "GUI"


def test_query_filters_combined(env):
    access, audit, _ = env
    audit.log("op", "export", "a.pdf", detail="x")
    audit.log("op", "upload", "a.zip", detail="y")
    audit.log("admin", "export", "b.pdf", detail="z")
    assert len(audit.query(user="op", action="export")) == 1
    assert len(audit.query(action="export")) == 2
    assert len(audit.query(text="a.zip")) == 1
    assert audit.query(since="2099-01-01") == []
    # fixture bootstrap logged 2 account_add entries + 3 ops
    assert len(audit.query(until="2099-01-01")) == 5


def test_export_csv_and_json(env):
    access, audit, tmp_path = env
    audit.log("op", "import", "cases.xlsx")
    csv_path = audit.export(tmp_path / "a.csv", fmt="csv")
    import csv as csvmod
    with open(csv_path, encoding="utf-8-sig") as fh:
        rows = list(csvmod.DictReader(fh))
    assert rows and rows[-1]["action"] == "import"
    js_path = audit.export(tmp_path / "a.json", fmt="json")
    import json
    data = json.loads(js_path.read_text("utf-8"))
    # json written before its own audit line -> last row is the
    # earlier csv export entry
    assert data[-1]["target"].endswith("a.csv")


def test_add_account_by_admin(env):
    access, audit, _ = env
    access.add_account("lead", "lead456", Role.OPERATOR,
                       actor="admin")
    assert access.role_of("lead") is Role.OPERATOR
    s = access.login("lead", "lead456")
    assert s is not None and s.username == "lead"
    adds = audit.query(action="account_add")
    assert adds[-1]["user"] == "admin", "account mgmt audited"


def test_session_can_helper():
    op = Session("op", Role.OPERATOR)
    assert op.can("run_test") and not op.can("edit_config")
    admin = Session("admin", Role.ADMIN)
    assert admin.can("anything")
