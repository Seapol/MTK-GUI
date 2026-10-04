# -*- coding: utf-8 -*-
"""P2-11 audit page tests (headless offscreen)."""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mtkgui.engine.auth_audit import AccessControl, AuditLog, Role
from mtkgui.gui.audit_page import AuditPage
from mtkgui.gui.shell import MainWindow

T0 = datetime(2026, 10, 4, 8, 0, 0)


@pytest.fixture()
def page(tmp_path):
    app = QApplication.instance() or QApplication([])
    audit = AuditLog(tmp_path / "audit.jsonl", now=lambda: T0)
    access = AccessControl(tmp_path / "accounts.json", audit=audit,
                           now=lambda: T0)
    access.ensure_default_accounts()
    p = AuditPage(access, audit)
    p.interactive = False
    return p


def test_login_admin_shows_badge(page):
    page.user_edit.setText("admin")
    page.pwd_edit.setText("admin123")
    fired = []
    page.logged_in.connect(fired.append)
    page.on_login()
    assert "管理员" in page.session_label.text()
    assert fired == [Role.ADMIN.value]
    page.refresh()
    assert page.table.rowCount() >= 1, "login audited in board"


def test_login_operator_badge_and_denial(page):
    page.user_edit.setText("op")
    page.pwd_edit.setText("op123")
    page.on_login()
    assert "操作员" in page.session_label.text()
    page.on_edit_config()          # guarded -> denied, audited
    page.refresh()
    actions = [page.table.item(r, 2).text()
               for r in range(page.table.rowCount())]
    assert "edit_config:DENY" in actions, "denial visible"


def test_admin_config_edit_audited_with_diff(page):
    page.user_edit.setText("admin")
    page.pwd_edit.setText("admin123")
    page.on_login()
    page.on_edit_config()          # admin passes the gate
    page.refresh()
    actions = [page.table.item(r, 2).text()
               for r in range(page.table.rowCount())]
    assert "edit_config" in actions
    row = actions.index("edit_config")
    assert page.table.item(row, 4).text() == '{"retry": 2}'
    assert page.table.item(row, 5).text() == '{"retry": 3}'


def test_bad_login_shows_unauthenticated(page):
    page.user_edit.setText("op")
    page.pwd_edit.setText("wrong")
    page.on_login()
    assert page.session_label.text() == "未登录"


def test_filters_and_export(page):
    page.access.login("admin", "admin123")
    page.audit.log("op", "upload", "r.zip")
    page.filter_action.setCurrentIndex(1)      # login
    page.refresh()
    assert all(page.table.item(r, 2).text().startswith("login")
               for r in range(page.table.rowCount()))
    page.filter_action.setCurrentIndex(0)
    page.filter_user.setText("op")
    page.refresh()
    assert all(page.table.item(r, 1).text() == "op"
               for r in range(page.table.rowCount()))
    page.filter_user.setText("")
    page.filter_text.setText("r.zip")
    page.refresh()
    assert page.table.rowCount() == 1
    # export (headless deterministic filename)
    p = page.on_export("csv")
    assert p.is_file()


def test_shell_registers_audit_route(qapp):
    win = MainWindow()
    win.interactive = False
    win.mount_default_routes()
    assert isinstance(win.audit_log, AuditLog)
    assert isinstance(win.access, AccessControl)
    assert "admin" in win.access.accounts, "bootstrapped"
    win.navigate("audit")
    assert isinstance(win.stack.currentWidget(), AuditPage)
