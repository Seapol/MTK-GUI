# -*- coding: utf-8 -*-
"""P3-9 five-role RBAC demo (headless-safe, rc=0).

Closed loop: five-role ladder -> P2 dual-role compatibility ->
function/page/data three-plane gating -> runtime matrix tuning ->
escalation-guarded account admin (denial audited) -> multi-project
isolation -> RbacPage GUI board.  Exit 0 = all checkpoints.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mtkgui.engine.auth_audit import AccessControl, AuditLog, Role
from mtkgui.engine.rbac_hub import RbacHub, Role5


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="rbac_demo_"))
    audit = AuditLog(tmp / "audit.jsonl")
    access = AccessControl(tmp / "acc.json", audit=audit)
    access.ensure_default_accounts()
    hub = RbacHub(access)

    # 1. five-role ladder + P2 frozen Role compatibility
    assert len(Role5) == 5
    assert hub.can(Role.ADMIN, "account_manage")
    assert hub.can(Role.OPERATOR, "run_test")
    assert not hub.can(Role.OPERATOR, "case_edit")

    # 2. function-plane: ladder capability grows with level
    ladder = [Role5.VIEWER, Role5.OPERATOR, Role5.ENGINEER,
              Role5.MANAGER, Role5.ADMIN]
    assert hub.can(ladder[0], "view")
    assert hub.can(ladder[2], "config_edit")
    assert hub.can(ladder[3], "case_lock")
    assert hub.can(ladder[4], "api_access")

    # 3. page-plane: rbac page is ADMIN-only, audit is MANAGER+
    assert hub.page_allowed(ladder[0], "home")
    assert not hub.page_allowed(ladder[1], "audit")
    assert hub.page_allowed(ladder[3], "audit")
    assert not hub.page_allowed(ladder[3], "rbac")
    assert hub.page_allowed(ladder[4], "rbac")

    # 4. runtime tuning: open queue page to MANAGER only
    hub.set_page_min("queue", Role5.MANAGER)
    assert not hub.page_allowed(ladder[2], "queue")
    hub.set_page_min("queue", Role5.OPERATOR)      # restore

    # 5. escalation guard: MANAGER cannot grant at/above own level
    hub.add_account(ladder[4], "mgr1", "pw", ladder[3])  # ADMIN creates
    try:
        hub.add_account(ladder[3], "engX", "pw", ladder[4])
        raise SystemExit("escalation guard failed")
    except PermissionError:
        pass
    hub.add_account(ladder[4], "eng1", "pw", ladder[2],
                    project_ids=("P-A",))
    assert any(e["action"] == "account_add:DENY"
               and e["user"] == "MANAGER"
               for e in audit.entries()), "denial audited"

    # 6. multi-project data isolation
    assert hub.project_allowed(ladder[2], "P-A") is True
    assert hub.project_allowed(ladder[2], "P-B") is False
    assert hub.project_allowed(ladder[4], "P-B") is True

    # 7. P2 session through the hub (zero regression)
    sess = access.login("op", "op123")
    assert sess is not None and hub.can(sess.role, "run_test")

    # 8. RbacPage GUI board (headless offscreen)
    from PySide6.QtWidgets import QApplication
    from mtkgui.gui.rbac_page import RbacPage

    app = QApplication.instance() or QApplication([])
    page = RbacPage(hub)
    page.interactive = False
    assert page.refresh() == 5, "matrix shows five roles"
    assert page.matrix.rowCount() == 5
    assert page.pages.rowCount() >= 15
    page.user_edit.setText("viewer1")
    page.pwd_edit.setText("pw1")
    page.role_combo.setCurrentText(Role5.VIEWER.value)
    assert page.on_add() == ("viewer1", "VIEWER")
    page.user_edit.setText("viewer2")
    page.pwd_edit.setText("pw2")
    assert page.on_add() == ("viewer2", "VIEWER")
    assert "五角色" in page.stats_label.text()

    print("[P3-9 RBAC demo] five-role middle platform OK — "
          "role ladder, P2 compat, function/page/data three-plane "
          "gating, runtime tuning, escalation guard with audited "
          "denial, multi-project isolation, RbacPage board all "
          "validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
