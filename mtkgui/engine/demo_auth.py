# -*- coding: utf-8 -*-
"""P2-11 RBAC + audit demo (headless-safe, rc=0).

Closed loop: bootstrap accounts -> operator/admin login -> permission
gate (operator denied on config/case edit, allowed to run/export/
upload) -> full-chain audit (config edit with before/after, case
edit, import/export, report delete, cloud upload) -> query/filter ->
CSV/JSON export.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from mtkgui.engine.auth_audit import (AccessControl, AuditLog, Role,
                                      Session)

T0 = datetime(2026, 10, 4, 8, 0, 0)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p2_11_demo_"))
    audit = AuditLog(tmp / "audit.jsonl", now=lambda: T0)
    access = AccessControl(tmp / "accounts.json", audit=audit,
                           now=lambda: T0)

    # 1. bootstrap default accounts (local, salted hashes)
    access.ensure_default_accounts()
    raw = json.loads((tmp / "accounts.json").read_text("utf-8"))
    assert set(raw) == {"admin", "op"}, raw
    assert raw["admin"]["hash"] != "admin123", "password hashed"
    assert raw["admin"]["hash"] != raw["op"]["hash"], "salted"
    access.ensure_default_accounts()          # idempotent
    assert set(access.accounts) == {"admin", "op"}

    # 2. login: correct + wrong password
    admin = access.login("admin", "admin123")
    assert admin and admin.role is Role.ADMIN
    op = access.login("op", "op123")
    assert op and op.role is Role.OPERATOR
    assert access.login("op", "wrong") is None, "bad pwd rejected"
    assert access.login("ghost", "x") is None, "unknown user"

    # 3. permission gate: operator denied config/case edit, allowed
    #    run/view/export/upload; admin full
    for act in ("edit_config", "edit_case", "report_delete"):
        try:
            access.require(op, act, "target")
            raise AssertionError(f"{act} must be denied")
        except PermissionError:
            pass                              # denial audited
    for act in ("run_test", "view", "export_report", "upload"):
        access.require(op, act, "target")     # must pass
    for act in ("edit_config", "edit_case", "report_delete",
                "run_test"):
        access.require(admin, act, "target")  # admin: all pass
    try:
        access.require(None, "edit_config")   # anonymous
        raise AssertionError("anonymous must be denied")
    except PermissionError:
        pass

    # 4. full-chain operation audit with before/after diff
    audit.log("admin", "edit_config", "project.yaml",
              before={"retry": 2}, after={"retry": 3},
              detail="GUI 提交")
    audit.log("admin", "edit_case", "case PWR_3V3",
              before={"limit": "3.30"}, after={"limit": "3.33"},
              detail="终审锁定解除后修改")
    audit.log("op", "import", "cases.xlsx", detail="17列导入")
    audit.log("op", "export", "report_B001.pdf", detail="成品导出")
    audit.log("op", "upload", "report_B001.zip",
              detail="SharePoint 归档")
    audit.log("admin", "report_delete", "report_old.pdf",
              before="exists", after="deleted")
    entries = audit.entries()
    assert len(entries) >= 14, entries        # logins+denials+ops
    e0 = entries[-1]
    assert e0["ts"].startswith("2026-10-04T08"[:16]) or \
        e0["ts"].startswith("2026-10-04 08"), e0["ts"]
    assert e0["user"] == "admin" and e0["after"] == "deleted"

    # 5. query & filter
    assert all(e["user"] == "op"
               for e in audit.query(user="op")), "user filter"
    assert all("export" in e["action"]
               for e in audit.query(action="export"))
    denies = audit.query(action="DENY")
    assert denies, "denied attempts traced"
    assert all("锁定" in json.dumps(e, ensure_ascii=False)
               for e in audit.query(text="锁定")), "text search"
    assert audit.query(user="nobody") == []

    # 6. export CSV + JSON (export itself is audited too)
    csv_path = audit.export(tmp / "audit.csv", fmt="csv")
    js_path = audit.export(tmp / "audit.json", fmt="json")
    assert csv_path.is_file() and js_path.is_file()
    head = csv_path.read_text("utf-8-sig").splitlines()[0]
    assert head.startswith("ts,user,action"), head
    assert len(json.loads(js_path.read_text("utf-8"))) == \
        len(audit.entries()) - 1, \
        "lossless json export (export itself audited after write)"

    # 7. admin account management
    access.add_account("lead", "lead456", Role.OPERATOR,
                       actor="admin")
    assert access.role_of("lead") is Role.OPERATOR
    assert access.login("lead", "lead456") is not None

    print("[P2-11 auth demo] RBAC + audit OK — dual roles, local "
          "salted accounts, login, precise denial (audited), "
          "before/after trail, query/filter, CSV/JSON export all "
          "validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
