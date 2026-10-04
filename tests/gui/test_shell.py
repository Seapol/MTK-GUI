# -*- coding: utf-8 -*-
"""P2-1 GUI shell framework unit tests (headless, offscreen)."""
from __future__ import annotations

import pytest

from PySide6.QtWidgets import QMessageBox

from mtkgui.gui.log_panel import LogPanelWidget
from mtkgui.gui.shell import MainWindow, PlaceholderPage
from mtkgui.gui.theme import StyleSpec, build_stylesheet
from mtkgui.gui.status_bar import StatusBarWidget


# --------------------------------------------------------------- theme
def test_stylesheet_contains_palette_and_zones(qapp):
    spec = StyleSpec()
    qss = build_stylesheet(spec)
    for zone in ("TopNav", "SideDock", "StatusBar", "CentralArea"):
        assert zone in qss
    assert spec.ACCENT in qss and spec.BG_DARK in qss


def test_spec_is_frozen(qapp):
    spec = StyleSpec()
    with pytest.raises(Exception):
        spec.ACCENT = "#fff"  # type: ignore[misc]


# --------------------------------------------------------------- status bar
def test_status_bar_updates(qapp):
    sb = StatusBarWidget("V1.0")
    sb.set_engine_state("running")
    sb.set_devices_online(3)
    sb.set_progress(2, 8)
    sb.tick()
    assert "running" in sb.state_label.text()
    assert "3" in sb.devices_label.text()
    assert "25%" in sb.progress_label.text()
    assert "V1.0" in sb.baseline_label.text()
    assert sb.uptime_label.text().startswith("uptime:")


def test_status_bar_zero_total_progress(qapp):
    sb = StatusBarWidget("V1.0")
    sb.set_progress(0, 0)
    assert "0/0" in sb.progress_label.text()


# --------------------------------------------------------------- log panel
def test_log_panel_append_and_levels(qapp):
    lp = LogPanelWidget()
    lp.append("INFO", "hello")
    lp.append("debug", "noise")     # lower-case level normalizes to DEBUG
    lp.append("BOGUS", "defaults")  # unknown level -> INFO
    assert lp.entry_count == 3
    text = lp.view.toPlainText()
    assert "hello" in text and "noise" in text and "defaults" in text


def test_log_panel_level_filter(qapp):
    lp = LogPanelWidget()
    lp.append("INFO", "a")
    lp.append("ERROR", "b")
    lp.append("ERROR", "c")
    lp.level_combo.setCurrentText("ERROR")
    assert lp.visible_count() == 2
    lp.level_combo.setCurrentText("INFO")
    assert lp.visible_count() == 1


def test_log_panel_keyword_filter(qapp):
    lp = LogPanelWidget()
    lp.append("INFO", "route home ok")
    lp.append("INFO", "flash image ok")
    lp.keyword_edit.setText("flash")
    assert lp.visible_count() == 1
    lp.keyword_edit.setText("")
    assert lp.visible_count() == 2


def test_log_panel_clear_keeps_history_state(qapp):
    lp = LogPanelWidget()
    lp.append("INFO", "x")
    lp.clear_btn.click()
    assert lp.visible_count() == 0
    assert lp.entry_count == 1  # history retained for re-filter


# --------------------------------------------------------------- shell
def test_shell_registers_routes_and_navigates(qapp):
    win = MainWindow(baseline_version="V1.0-P2-1")
    win.mount_default_routes()
    assert win.route_keys == ["home", "workflow", "cases", "reports",
                              "config"]
    win.navigate("workflow")
    win.navigate("reports")
    assert sorted(win.cached_pages) == ["home", "reports", "workflow"]
    # cached: navigating back must not rebuild
    win.navigate("home")
    assert win.cached_pages.count("home") == 1


def test_shell_duplicate_route_rejected(qapp):
    win = MainWindow()
    win.register_page("x", lambda: PlaceholderPage("x"), "X")
    with pytest.raises(ValueError):
        win.register_page("x", lambda: PlaceholderPage("x"), "X")


def test_shell_empty_route_key_rejected(qapp):
    win = MainWindow()
    with pytest.raises(ValueError):
        win.register_page("", lambda: PlaceholderPage("e"), "E")


def test_shell_unknown_route_no_crash(qapp):
    win = MainWindow()
    win.navigate("ghost")
    assert "ghost" not in win.cached_pages


def test_shell_broken_factory_fallback(qapp):
    def bad():
        raise RuntimeError("boom")
    win = MainWindow()
    win.register_page("bad", bad, "Bad")
    win.navigate("bad")
    assert "bad" in win.cached_pages
    assert win.log_panel.entry_count >= 1  # ERROR path logged


def test_shell_engine_state_logging(qapp):
    win = MainWindow()
    base = win.log_panel.entry_count
    win.set_engine_state("running")
    win.set_devices_online(2)
    win.set_progress(1, 4)
    assert win.status.state_label.text().endswith("running")
    assert win.log_panel.entry_count == base + 1  # only state change logs


def test_shell_close_event_accept_after_confirm(qapp, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    monkeypatch.setattr("mtkgui.gui.shell.QMessageBox.exec",
                        lambda self: int(QMessageBox.StandardButton.Yes),
                        raising=False)  # Yes
    win = MainWindow()
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert ev.isAccepted()
    assert win._close_confirmed
    assert not win._ticker.isActive()


def test_shell_close_event_cancelled(qapp, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    win = MainWindow()
    monkeypatch.setattr("mtkgui.gui.shell.QMessageBox.exec",
                        lambda self: int(QMessageBox.StandardButton.No),
                        raising=False)  # No
    ev = QCloseEvent()
    win.closeEvent(ev)
    assert not ev.isAccepted()
    assert win._ticker.isActive()  # still alive
