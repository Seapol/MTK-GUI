# -*- coding: utf-8 -*-
"""P3-1 project switcher + shell tenant adaptation tests (offscreen)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mtkgui.engine.project_context import (ProjectContext,
                                           TenantRegistry)
from mtkgui.gui.project_switcher import LEGACY, ProjectSwitcher
from mtkgui.gui.shell import MainWindow


@pytest.fixture(autouse=True)
def clean_ctx():
    yield
    ProjectContext.set_current(None)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("MTKGUI_TENANT_BASE",
                       str(tmp_path / "projects"))
    monkeypatch.setenv("MTKGUI_AUDIT_LOG",
                       str(tmp_path / "audit" / "audit.jsonl"))
    monkeypatch.setenv("MTKGUI_ACCOUNTS",
                       str(tmp_path / "audit" / "accounts.json"))
    monkeypatch.setenv("MTKGUI_EXPORT_DIR",
                       str(tmp_path / "export_legacy"))
    monkeypatch.chdir(tmp_path)          # tenant base sandboxed
    win = MainWindow()
    win.interactive = False
    win.mount_default_routes()
    return win


def test_legacy_mode_untouched(env):
    win = env
    assert ProjectContext.current() is None
    assert LEGACY in [win.project_switcher.combo.itemText(i)
                      for i in range(win.project_switcher.combo
                                     .count())], "legacy entry shown"
    win.navigate("reports")
    assert "reports" in win.cached_pages


def test_switch_rebinds_stores_and_purges_pages(env, tmp_path):
    win = env
    sw = win.project_switcher
    sw.add_project("PRJ-A")
    sw.add_project("PRJ-B")
    old_engine = win.metrics_engine
    win.navigate("reports")              # cache a legacy page
    fired = []
    sw.tenant_switched.connect(fired.append)
    sw.combo.setCurrentText("PRJ-A")
    assert fired == ["PRJ-A"]
    ctx = ProjectContext.current()
    assert ctx.project_id == "PRJ-A"
    # stores rebound into the tenant workspace
    assert win.metrics_engine is not old_engine
    assert (tmp_path / "projects" / "PRJ-A" / "config").is_dir()
    assert win.export_out_dir == str(ctx.dir("export"))
    # cached pages purged -> rebuilt inside tenant on demand
    assert win.cached_pages == []
    win.navigate("reports")
    assert win.cached_pages == ["reports"]
    # tenant audit ledger got the switch entry
    assert win.audit_log.path == ctx.dir("audit") / "audit.jsonl"
    actions = [e["action"] for e in win.audit_log.entries()]
    assert "tenant_switch" in actions


def test_switch_back_to_legacy(env):
    win = env
    sw = win.project_switcher
    sw.add_project("PRJ-A")
    sw.combo.setCurrentText("PRJ-A")
    assert ProjectContext.current() is not None
    sw.combo.setCurrentText(LEGACY)
    assert ProjectContext.current() is None, "legacy mode restored"
    assert win.cached_pages == [], "pages purged again"


def test_tenant_isolation_between_projects(env):
    win = env
    sw = win.project_switcher
    sw.add_project("PRJ-A")
    sw.add_project("PRJ-B")
    sw.combo.setCurrentText("PRJ-A")
    eng_a = win.metrics_engine
    sw.combo.setCurrentText("PRJ-B")
    eng_b = win.metrics_engine
    assert eng_b is not eng_a, "per-tenant engine"
    sw.combo.setCurrentText("PRJ-A")
    # leaving a tenant clears its slot cache by design; re-entering
    # yields a FRESH engine — still fully isolated from B's engine
    assert win.metrics_engine is not eng_a
    assert win.metrics_engine is not eng_b, "never B's instance"


def test_load_existing_on_disk_project(env, tmp_path):
    win = env
    (tmp_path / "projects" / "ON-DISK" / "config").mkdir(
        parents=True)
    win.project_switcher.load_project("ON-DISK")
    win.project_switcher.combo.setCurrentText("ON-DISK")
    assert ProjectContext.current().project_id == "ON-DISK"
