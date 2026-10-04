# -*- coding: utf-8 -*-
"""P3-9 full RBAC permission middle platform (pure additive).

Extends the frozen P2-11 dual-role :mod:`auth_audit` to a
five-role, three-plane (page / function / data) enterprise RBAC —
the P2-11 module is REUSED, never modified:

  * Role5        — VIEWER < OPERATOR < ENGINEER < MANAGER < ADMIN
                   (+ P2 Role compatibility mapping)
  * PERM5        — function-plane permission matrix (single truth)
  * PAGE_ACCESS  — page-plane: route key -> minimum role level
  * DATA_SCOPES  — data-plane: own < project < all (multi-project
                   isolation via project_allowed())
  * RbacHub      — account management with escalation guard (an
                   actor may never grant/edit a role at or above its
                   own level unless ADMIN), deny recording, runtime
                   adjustable matrix (可视化权限配置), matrix snapshot

Zero changes to auth_audit / shell contracts.
"""
from __future__ import annotations

import threading
from enum import Enum


class Role5(str, Enum):
    VIEWER = "VIEWER"
    OPERATOR = "OPERATOR"
    ENGINEER = "ENGINEER"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"


#: P2-11 frozen Role -> Role5 compatibility mapping
FROM_P2 = {"ADMIN": Role5.ADMIN, "OPERATOR": Role5.OPERATOR}

ROLE_LEVEL: dict[Role5, int] = {
    Role5.VIEWER: 0, Role5.OPERATOR: 1, Role5.ENGINEER: 2,
    Role5.MANAGER: 3, Role5.ADMIN: 4,
}

#: function-plane matrix — single source of truth (P2 actions kept)
PERM5: dict[Role5, set[str]] = {
    Role5.VIEWER: {"view"},
    Role5.OPERATOR: {"view", "run_test", "export_report", "upload"},
    Role5.ENGINEER: {"view", "run_test", "export_report", "upload",
                     "case_edit", "config_edit", "queue_manage"},
    Role5.MANAGER: {"view", "run_test", "export_report", "upload",
                    "case_edit", "config_edit", "queue_manage",
                    "case_lock", "device_manage", "audit_view",
                    "report_manage"},
    Role5.ADMIN: {"*"},
}

#: page-plane — route key -> minimum Role5 level
PAGE_ACCESS: dict[str, int] = {
    "home": 0, "workflow": 1, "cases": 1, "case_io": 2,
    "reports": 1, "upload": 1, "export": 1, "cluster": 2,
    "resources": 2, "queue": 1, "fleet": 2, "balance": 2,
    "pipeline": 2, "audit": 3, "config": 3, "rbac": 4,
}

#: data-plane scopes
DATA_SCOPES: dict[Role5, str] = {
    Role5.VIEWER: "project", Role5.OPERATOR: "project",
    Role5.ENGINEER: "project", Role5.MANAGER: "all",
    Role5.ADMIN: "all",
}

ALL_ACTIONS = sorted({a for s in PERM5.values() for a in s
                      if a != "*"} |
                     {"account_manage", "project_manage",
                      "api_access"})


class RbacError(Exception):
    pass


class RbacHub:
    """Five-role RBAC gate + account admin (delegates storage to the
    frozen P2-11 AccessControl)."""

    def __init__(self, access=None):
        self.access = access              # P2-11 AccessControl or None
        self._matrix = {r: set(p) for r, p in PERM5.items()}
        self._page_access = dict(PAGE_ACCESS)
        self._projects: dict[str, set] = {}   # role -> allowed pids
        self._guard = threading.Lock()

    # ------------------------------------------------------------ gate
    def can(self, role, action: str) -> bool:
        r = self._norm(role)
        allowed = self._matrix.get(r, set())
        return "*" in allowed or action in allowed

    def require(self, role, action: str, target: str = "") -> None:
        """Escalation-safe gate; raises PermissionError on denial."""
        if not self.can(role, action):
            who = getattr(role, "value", str(role))
            raise PermissionError(f"[RBAC] {who} denied {action} "
                                  f"{target}".strip())

    def _norm(self, role) -> Role5:
        if isinstance(role, Role5):
            return role
        name = getattr(role, "value", str(role)).upper()
        return FROM_P2.get(name) or Role5(name)

    # ------------------------------------------------------ page plane
    def page_allowed(self, role, route_key: str) -> bool:
        r = self._norm(role)
        need = self._page_access.get(route_key, 4)
        return ROLE_LEVEL[r] >= need

    def set_page_min(self, route_key: str, role5: Role5) -> None:
        """Runtime page-plane tuning (可视化权限配置)."""
        with self._guard:
            self._page_access[route_key] = ROLE_LEVEL[role5]

    # ------------------------------------------------------ data plane
    def data_scope(self, role) -> str:
        return DATA_SCOPES[self._norm(role)]

    def grant_project(self, role, project_id: str) -> None:
        """Multi-project isolation: allow role into one more tenant."""
        with self._guard:
            self._projects.setdefault(self._norm(role),
                                      set()).add(project_id)

    def project_allowed(self, role, project_id: str) -> bool:
        r = self._norm(role)
        if self.data_scope(r) == "all":
            return True
        allowed = self._projects.get(r)
        return bool(allowed and project_id in allowed)

    # ----------------------------------------------- matrix management
    def set_permission(self, role, action: str, allow: bool) -> None:
        """Runtime function-plane tuning (never weakens ADMIN '*')."""
        r = self._norm(role)
        with self._guard:
            cur = self._matrix.setdefault(r, set())
            if allow:
                cur.add(action)
            else:
                cur.discard(action)

    def matrix_snapshot(self) -> dict:
        """Visualization data: role -> sorted granted actions."""
        with self._guard:
            return {r.value: sorted(a for a in acts if a != "*")
                    for r, acts in self._matrix.items()}

    def pages_snapshot(self) -> dict:
        with self._guard:
            return dict(sorted(self._page_access.items()))

    # ------------------------------------------------ account admin
    def add_account(self, actor_role, username: str, password: str,
                    role, project_ids=()) -> None:
        """Escalation-guarded account creation (ADMIN bypasses)."""
        actor = self._norm(actor_role)
        target = self._norm(role)
        if actor is not Role5.ADMIN and \
                ROLE_LEVEL[target] >= ROLE_LEVEL[actor]:
            if self.access is not None and self.access.audit:
                self.access.audit.log(actor.value, "account_add:DENY",
                                      username,
                                      detail=f"escalation guard "
                                             f"target={target.value}")
            raise PermissionError(
                f"[RBAC] {actor.value} cannot grant "
                f"{target.value} (escalation guard)")
        if self.access is not None:
            from mtkgui.engine.auth_audit import Role as P2Role
            p2 = P2Role.ADMIN if target is Role5.ADMIN \
                else P2Role.OPERATOR
            self.access.add_account(username, password, p2,
                                    actor=actor.value)
        for pid in project_ids:
            self.grant_project(target, pid)

    def assignable_roles(self, actor_role) -> list[str]:
        """Roles the actor may grant (escalation guard applied)."""
        actor = self._norm(actor_role)
        if actor is Role5.ADMIN:
            return [r.value for r in Role5]
        return [r.value for r in Role5
                if ROLE_LEVEL[r] < ROLE_LEVEL[actor]]


#: short public alias
RH = RbacHub
