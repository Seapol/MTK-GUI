# -*- coding: utf-8 -*-
"""M125 - performance timing log: default on, runtime switch, live view.

The freeze the user reports ("clicking a node and the window stops
answering") has no evidence in the old log because (a) the probe was
off unless the operator had pre-enabled it and restarted, and (b) a
frozen event loop logs nothing.  M125 adds: ON by default, a switch
that applies to the running session, a heartbeat watchdog writing a
``[STALL]`` line that names the blocked operation, and a window that
shows the same lines without leaving the GUI.
"""
from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mtkgui import startup_timing as st


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_development_default_is_on(monkeypatch):
    monkeypatch.delenv("MTK_TIMING", raising=False)
    assert st.saved_enabled() is True
    assert st.stall_threshold() > 0


def test_recent_lines_keep_the_session_in_memory(monkeypatch):
    monkeypatch.setattr(st, "_ENABLED", True)
    st.mark("m125: in-memory marker")
    assert any("m125: in-memory marker" in ln
               for ln in st.recent_lines(50))
    assert st.recent_count() > 0


def test_log_file_is_created_lazily_on_first_line(monkeypatch, tmp_path):
    monkeypatch.setattr(st, "_ENABLED", True)
    monkeypatch.setattr(st, "_LOG", None)
    monkeypatch.setattr(st, "_LOG_RESOLVED", False)
    from mtkgui import app_paths
    monkeypatch.setattr(app_paths, "logs_dir", lambda: tmp_path,
                        raising=False)
    path = st.log_file_path()
    assert path is not None and path.parent == tmp_path
    assert not path.exists(), "the file appears with the first line, not before"
    st.mark("m125: first line")
    path = st.log_file_path()
    assert path.exists()
    assert "m125: first line" in path.read_text(encoding="utf-8")


def test_runtime_switch_flips_this_session(monkeypatch):
    assert st.set_runtime_enabled(True) is True
    assert st.is_enabled() is True
    st.mark("m125: after enable")
    assert st.set_runtime_enabled(False) is False
    assert st.is_enabled() is False
    st.mark("m125: while off")
    assert not any("m125: while off" in ln for ln in st.recent_lines(50))
    assert st.set_runtime_enabled(True) is True


def test_stall_line_names_the_blocking_operation(qapp, monkeypatch):
    monkeypatch.setenv("MTK_TIMING_TESTS", "1")
    monkeypatch.setattr(st, "_ENABLED", True)
    monkeypatch.setattr(st, "_STALL_TIMER", None)
    st.install_stall_watchdog(interval_ms=50)

    def block() -> None:
        st.begin("m125: node 02 build dialog", category="yamlbuild")
        time.sleep(0.9)
        st.end("m125: node 02 build dialog")

    QTimer.singleShot(60, block)
    deadline = time.time() + 4.0
    found = ""
    while time.time() < deadline:
        qapp.processEvents()
        # the buffer is shared with earlier tests - look for OUR label,
        # not merely for "some" STALL line
        for ln in st.recent_lines(80):
            if "[STALL" in ln and "m125: node 02 build dialog" in ln:
                found = ln
                break
        if found:
            break
        time.sleep(0.02)
    st.stop_stall_watchdog()
    assert found, "a blocked GUI thread must produce a STALL line naming it"


def test_viewer_shows_lines_and_filters(qapp, monkeypatch):
    from mtkgui.gui.perf_log_view import PerfLogDialog, show_log
    monkeypatch.setattr(st, "_ENABLED", True)
    st.mark("m125: viewer line")
    st.log_stall(1.5, "m125: viewer freeze")
    dlg = show_log(None)
    try:
        qapp.processEvents()
        text = dlg.view.toPlainText()
        assert "m125: viewer line" in text
        assert "m125: viewer freeze" in text
        dlg.chk_stalls.setChecked(True)
        qapp.processEvents()
        filtered = dlg.view.toPlainText()
        assert "m125: viewer line" not in filtered
        assert "m125: viewer freeze" in filtered
        dlg.chk_stalls.setChecked(False)
        dlg.chk_record.setChecked(False)
        assert st.is_enabled() is False
        dlg.chk_record.setChecked(True)
        assert st.is_enabled() is True
        assert isinstance(dlg, PerfLogDialog)
    finally:
        dlg.close()


# ------------------------------------------------- File > Restart GUI
def test_restart_gui_action_lives_in_the_file_menu(qapp):
    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    window = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    try:
        assert window.act_restart.text() == "Restart GUI"
        assert window.act_restart in window._file_menu.actions()
        # the entry sits right before Exit
        actions = window._file_menu.actions()
        assert actions.index(window.act_restart) < actions.index(window.act_exit)
    finally:
        window.close()
        window.deleteLater()


def test_restart_gui_is_refused_while_a_run_is_active(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    shown: list = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(a)))
    window = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    calls: list = []
    monkeypatch.setattr(window, "_spawn_new_instance",
                        lambda: calls.append("spawn"))
    try:
        window._run_active = True
        window.act_restart.trigger()
        assert shown and "restarting" in shown[-1][2]
        assert not window._restart_requested
        assert calls == [], "nothing may be started while the rack drives"
    finally:
        window._run_active = False
        window.close()
        window.deleteLater()


def test_restart_gui_closes_cleanly_then_spawns(qapp, monkeypatch):
    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    window = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    spawned: list = []
    monkeypatch.setattr(window, "_spawn_new_instance",
                        lambda: spawned.append("spawn"))
    window.act_restart.trigger()
    assert spawned == ["spawn"], "the replacement starts during close"
    assert window._restart_requested is False
    window.deleteLater()
