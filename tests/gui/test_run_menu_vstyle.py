# -*- coding: utf-8 -*-
"""Item 15: Main UI Menu Bar & Toolbar Layout Refactor (VS style).

* Top-level Run menu with the standard Visual Studio shortcut mapping
* Main top toolbar carries ONLY the two core buttons Run / Stop
* Auto-SN entry lives in the Settings menu (configuration function)
* Adaptive top layout: the Run Control panel keeps only the run
  configuration (Long Run / Interval), no redundant button height
* Function consistency: the menu actions are the very same QAction
  objects the state machine syncs (start / continue / stop / step /
  breakpoint logic unchanged, GUI layer only).
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QMessageBox,
    QPushButton,
    QToolBar,
    QTableWidgetItem,
)

from mtkgui.main_window import MainWindow  # noqa: E402

#: VS standard shortcut mapping (strict compliance): menu text -> key
VS_SHORTCUTS = (
    ("Start / Continue Run", "F5"),
    ("Run Without Debug", "Ctrl+F5"),
    ("Stop Run", "Shift+F5"),
    ("Restart Run", "Ctrl+Shift+F5"),
    ("Step Over (Single Node Run)", "F10"),
    ("Step Into", "F11"),
    ("Step Out", "Shift+F11"),
    ("Toggle Breakpoint", "F9"),
    ("Clear All Breakpoints", "Ctrl+Shift+F9"),
    ("Run to Cursor", "Ctrl+F10"),
)


@pytest.fixture(scope="module")
def window():
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    yield w
    w.close()


def _fill_ict(wf, rows=3):
    """Ensure the ICT table has real rows for the breakpoint tests."""
    wf.ict.setRowCount(rows)
    for r in range(rows):
        for c in range(8):
            if wf.ict.item(r, c) is None:
                wf.ict.setItem(r, c, QTableWidgetItem(
                    str(r + 1) if c == 0 else ""))


def _fill_fct(wf, rows=3):
    wf.fct.setRowCount(rows)
    for r in range(rows):
        for c in range(6):
            if wf.fct.item(r, c) is None:
                wf.fct.setItem(r, c, QTableWidgetItem(
                    str(r + 1) if c == 0 else ""))


# ------------------------------------------------------------- Run menu
def test_run_menu_items_and_vs_shortcuts(window):
    items = [(a.text(), a.shortcut().toString())
             for a in window.run_menu.actions() if a.text()]
    assert items == [(t, k) for t, k in VS_SHORTCUTS]


def test_run_menu_position_after_tools(window):
    """Top-level Run menu sits between Tools and Report (Report / Help
    stay the rightmost menus of the fixed final order)."""
    names = [a.text() for a in window.menuBar().actions()]
    assert names.index("Tools") < names.index("Run") < \
        names.index("Report") < names.index("Help")


def test_run_menu_actions_are_page_actions(window):
    """Function consistency: the menu holds the shared page QActions -
    enable-state sync and trigger targets are the original ones."""
    wf = window.workflow_page
    acts = [a for a in window.run_menu.actions() if a.text()]
    assert acts[0] is wf.btn_run and acts[2] is wf.btn_stop
    assert acts[4] is wf.btn_step and acts[6] is wf.btn_continue
    assert acts[0].isEnabled()      # idle: F5 ready to start


def test_shortcut_context_global(window):
    """Shortcuts stay effective application-wide (window context)."""
    wf = window.workflow_page
    for act in (wf.btn_run, wf.btn_stop, wf.btn_step,
                wf.act_toggle_breakpoint):
        assert act.shortcutContext() in (
            Qt.ShortcutContext.WindowShortcut,
            Qt.ShortcutContext.ApplicationShortcut)


# ------------------------------------------------------------- toolbar
def test_main_toolbar_removed(window):
    """Item 17 rollback: the main top toolbar is gone entirely (Run /
    Stop returned to the Run Control panel) - adaptive height with no
    redundant toolbar reservation."""
    assert not [tb for tb in window.findChildren(QToolBar)
                if tb.objectName() == "run_toolbar"]


def test_run_stop_primary_buttons_in_panel(window):
    """Run / Stop are back in the Run Control panel as the most
    prominent primary buttons: accent colours + enlarged layout; the
    button widgets mirror the shared QAction state (menu / shortcuts /
    page buttons always agree)."""
    wf = window.workflow_page
    run_btn, stop_btn = wf.btn_run_button, wf.btn_stop_button
    # enlarged, prominent primary buttons (inline QSS min-height 48
    # overrides the global button rule during polish)
    assert run_btn.minimumWidth() >= 140
    assert run_btn.minimumHeight() >= 44
    assert "#1d7a3c" in run_btn.styleSheet()      # green Run
    assert "#b3261e" in stop_btn.styleSheet()     # red Stop
    # item 19: enlarged play / stop symbols, clearly visible
    from PySide6.QtCore import QSize
    assert run_btn.iconSize() == QSize(30, 30)
    assert stop_btn.iconSize() == QSize(30, 30)
    assert not run_btn.icon().pixmap(60).isNull()
    assert not stop_btn.icon().pixmap(60).isNull()
    # enabled-state mirroring (idle: Run on, Stop off)
    assert run_btn.isEnabled() and not stop_btn.isEnabled()
    wf.btn_stop.setEnabled(True)
    assert stop_btn.isEnabled()
    wf.btn_stop.setEnabled(False)
    assert not stop_btn.isEnabled()
    # clicking the page button drives the same action as the menu
    from PySide6.QtWidgets import QMessageBox
    monkey = pytest.MonkeyPatch()
    monkey.setattr(QMessageBox, "warning",
                   staticmethod(lambda *a, **k: 0))
    try:
        # clicking the page button drives run_or_continue (the F5
        # action): without a project the run gate blocks, state stays
        # idle and the button remains available
        run_btn.click()
        assert wf.run_state == "idle"
        assert run_btn.isEnabled()
    finally:
        monkey.undo()


def test_debug_buttons_stay_out_of_the_panel(window):
    """Step / Continue remain menu-only (Run menu holds the debug
    entries); the panel carries only Run / Stop + run configuration."""
    wf = window.workflow_page
    leftover = {b.text() for b in wf.findChildren(QPushButton)
                if b.text() in ("Step", "Continue")}
    assert not leftover


# ------------------------------------------------------ F5 / semantics
def test_f5_start_continue_semantics(window, monkeypatch):
    """F5 when idle starts the run (blocked without a YAML project ->
    warning popup, no engine start); run state stays idle."""
    wf = window.workflow_page
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: warnings.append(a[1]) or 0))
    wf.run_or_continue()
    assert warnings == ["No Test Project"]
    assert wf.run_state == "idle"


def test_run_without_debug_ignores_breakpoints(window):
    wf = window.workflow_page
    wf.ict_breakpoints.add(0)
    wf._run_steps = [("ict", 0)]
    try:
        wf._no_debug = False
        assert wf._breakpoint_hit(0) is True
        wf._no_debug = True          # Ctrl+F5 armed for this run
        assert wf._breakpoint_hit(0) is False
    finally:
        wf.ict_breakpoints.clear()
        wf._no_debug = False


# ------------------------------------------------------- breakpoints F9
def test_f9_toggle_and_clear_all_breakpoints(window):
    wf = window.workflow_page
    _fill_ict(wf)
    _fill_fct(wf)
    wf.ict.setCurrentCell(0, 0)
    wf.ict_breakpoints.clear()
    try:
        wf.toggle_breakpoint_current()          # F9 on
        assert 0 in wf.ict_breakpoints
        assert wf.ict.item(0, 0).text().startswith("●")
        wf.toggle_breakpoint_current()          # F9 off again
        assert 0 not in wf.ict_breakpoints
        assert wf.ict.item(0, 0).text() == "1"
        # Ctrl+Shift+F9 clears everything (both tables, markers reset)
        wf.ict_breakpoints.update({0, 2})
        wf.fct_breakpoints.add(1)
        wf.clear_all_breakpoints()
        assert not wf.ict_breakpoints and not wf.fct_breakpoints
        assert wf.ict.item(0, 0).text() == "1"
        assert wf.fct.item(1, 0).text() == "2"
    finally:
        wf.ict_breakpoints.clear()
        wf.fct_breakpoints.clear()


def test_run_to_cursor_temporary_breakpoint(window, monkeypatch):
    wf = window.workflow_page
    _fill_ict(wf)
    wf.ict.setCurrentCell(1, 0)
    wf.ict_breakpoints.clear()
    # no project loaded: F5 falls into the "No Test Project" gate after
    # the temporary breakpoint has been placed
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: 0))
    try:
        wf.run_to_cursor()
        assert 1 in wf.ict_breakpoints
        assert wf._temp_bp is not None
    finally:
        wf.ict_breakpoints.clear()
        wf._temp_bp = None


# --------------------------------------------- Auto-SN entry migration
def test_auto_sn_entry_in_settings_menu(window):
    texts = [a.text() for a in window.settings_menu.actions()]
    assert "Auto-SN (virtual serial, +1 per run)" in texts


def test_auto_sn_menu_action_syncs_checkbox(window):
    wf = window.workflow_page
    act = wf.act_auto_sn
    assert not wf.auto_sn.isVisible()      # removed from the main UI
    try:
        act.setChecked(True)
        assert wf.auto_sn.isChecked()
        wf.auto_sn.setChecked(False)
        assert not act.isChecked()
    finally:
        act.setChecked(False)


def test_auto_sn_permission_mirrors_action(window):
    from mtkgui.permissions import DEFAULT_PERMISSIONS
    wf = window.workflow_page
    wf.apply_permissions(DEFAULT_PERMISSIONS, supervisor=False)
    assert not wf.act_auto_sn.isEnabled()
    granted = dict(DEFAULT_PERMISSIONS)
    granted["run_policy_auto_sn"] = True
    wf.apply_permissions(granted, supervisor=False)
    assert wf.act_auto_sn.isEnabled()
