# -*- coding: utf-8 -*-
"""P3-9 five-role RBAC middle-platform tests."""
from __future__ import annotations

import pytest

from mtkgui.engine.auth_audit import AccessControl, AuditLog, Role
from mtkgui.engine.rbac_hub import (RH, RbacHub, Role5, FROM_P2,
                                    PERM5, ROLE_LEVEL)


def test_five_roles_and_p2_compat_mapping():
    assert len(Role5) == 5
    assert [r.name for r in Role5] == ["VIEWER", "OPERATOR",
                                       "ENGINEER", "MANAGER", "ADMIN"]
    assert ROLE_LEVEL[Role5.VIEWER] < ROLE_LEVEL[Role5.OPERATOR] < \
        ROLE_LEVEL[Role5.ENGINEER] < ROLE_LEVEL[Role5.MANAGER] < \
        ROLE_LEVEL[Role5.ADMIN]
    assert FROM_P2[Role.ADMIN.value] is Role5.ADMIN
    assert FROM_P2[Role.OPERATOR.value] is Role5.OPERATOR
    hub = RbacHub()
    # frozen P2 Role objects accepted directly at the gate
    assert hub.can(Role.ADMIN, "account_manage") is True
    assert hub.can(Role.OPERATOR, "run_test") is True
    assert hub.can(Role.OPERATOR, "case_edit") is False


def test_function_plane_matrix():
    hub = RbacHub()
    assert hub.can(Role5.VIEWER, "view") is True
    assert hub.can(Role5.VIEWER, "run_test") is False
    assert hub.can(Role5.OPERATOR, "upload") is True
    assert hub.can(Role5.ENGINEER, "case_edit") is True
    assert hub.can(Role5.ENGINEER, "case_lock") is False
    assert hub.can(Role5.MANAGER, "device_manage") is True
    assert hub.can(Role5.ADMIN, "anything_at_all") is True
    with pytest.raises(PermissionError):
        hub.require(Role5.VIEWER, "config_edit")


def test_page_plane_access():
    hub = RbacHub()
    assert hub.page_allowed(Role5.VIEWER, "home") is True
    assert hub.page_allowed(Role5.VIEWER, "cases") is False
    assert hub.page_allowed(Role5.OPERATOR, "cases") is True
    assert hub.page_allowed(Role5.ENGINEER, "queue") is True
    assert hub.page_allowed(Role5.OPERATOR, "audit") is False
    assert hub.page_allowed(Role5.MANAGER, "audit") is True
    assert hub.page_allowed(Role5.ADMIN, "rbac") is True
    hub.set_page_min("queue", Role5.MANAGER)      # runtime tuning
    assert hub.page_allowed(Role5.ENGINEER, "queue") is False
    assert hub.page_allowed(Role5.MANAGER, "queue") is True
    unknown_need = hub.page_allowed(Role5.VIEWER, "ghost_page")
    assert unknown_need is False                  # default -> ADMIN


def test_data_plane_project_isolation():
    hub = RbacHub()
    assert hub.data_scope(Role5.MANAGER) == "all"
    assert hub.data_scope(Role5.ENGINEER) == "project"
    # ENGINEER: only granted projects visible
    assert hub.project_allowed(Role5.ENGINEER, "P-A") is False
    hub.grant_project(Role5.ENGINEER, "P-A")
    assert hub.project_allowed(Role5.ENGINEER, "P-A") is True
    assert hub.project_allowed(Role5.ENGINEER, "P-B") is False
    # ADMIN/MANAGER see everything (all scope)
    assert hub.project_allowed(Role5.ADMIN, "P-X") is True
    assert hub.project_allowed(Role5.MANAGER, "P-X") is True


def test_runtime_matrix_tuning_and_snapshot():
    hub = RbacHub()
    hub.set_permission(Role5.VIEWER, "export_report", True)
    assert hub.can(Role5.VIEWER, "export_report") is True
    hub.set_permission(Role5.VIEWER, "export_report", False)
    assert hub.can(Role5.VIEWER, "export_report") is False
    snap = hub.matrix_snapshot()
    assert set(snap) == {r.value for r in Role5}
    assert "run_test" in snap["OPERATOR"]
    assert "*" not in snap["ADMIN"]               # wildcard hidden
    assert set(hub.pages_snapshot()) >= {"home", "rbac"}


def test_escalation_guard_on_account_admin(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    access = AccessControl(tmp_path / "acc.json", audit=audit)
    access.ensure_default_accounts()
    hub = RbacHub(access)
    # MANAGER may grant OPERATOR/ENGINEER (below own level)
    hub.add_account(Role5.MANAGER, "eng1", "pw", Role5.ENGINEER,
                    project_ids=("P-A",))
    assert access.role_of("eng1") is Role.OPERATOR  # P2 compat store
    assert hub.project_allowed(Role5.ENGINEER, "P-A") is True
    # MANAGER may NOT grant MANAGER/ADMIN
    with pytest.raises(PermissionError):
        hub.add_account(Role5.MANAGER, "boss", "pw", Role5.MANAGER)
    with pytest.raises(PermissionError):
        hub.add_account(Role5.ENGINEER, "boss2", "pw", Role5.ADMIN)
    # ADMIN grants anyone
    hub.add_account(Role5.ADMIN, "mgr1", "pw", Role5.MANAGER)
    # P2 dual-role store is class-level (lossy by design): MANAGER
    # sits in the OPERATOR class; the five-role identity stays in
    # the hub plane (matrix/scopes)
    assert access.role_of("mgr1") is Role.OPERATOR
    assert hub.data_scope(Role5.MANAGER) == "all"
    # assignable roles respect the guard
    assert hub.assignable_roles(Role5.MANAGER) == ["VIEWER",
                                                   "OPERATOR",
                                                   "ENGINEER"]
    assert len(hub.assignable_roles(Role5.ADMIN)) == 5
    # denial recorded in the audit trail
    entries = audit.entries()
    assert any(e["action"] == "account_add:DENY" and e["user"] == "MANAGER"
               for e in entries)


def test_p2_session_still_works_through_hub(tmp_path):
    """Zero-regression: P2-11 dual-role login still gated correctly."""
    access = AccessControl(tmp_path / "acc.json")
    access.ensure_default_accounts()
    hub = RbacHub(access)
    sess = access.login("op", "op123")            # P2 OPERATOR
    assert sess is not None
    assert hub.can(sess.role, "run_test") is True
    with pytest.raises(PermissionError):
        hub.require(sess.role, "account_manage")


def test_alias_and_defaults_frozen():
    assert RH is RbacHub
    assert PERM5[Role5.ADMIN] == {"*"}
    assert ROLE_LEVEL[Role5.ADMIN] == 4
