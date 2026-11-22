# -*- coding: utf-8 -*-
"""M104a: Report menu hygiene (R1 rename + R4 SharePoint re-enable)."""
from __future__ import annotations

import inspect

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.permissions import ROLE_OPERATOR, ROLE_SUPERVISOR  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _window(role, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)
    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    return MainWindow(role=role, mode="Real", fixture="ATE")


def _report_actions(window):
    return [act for act in window.report_menu.actions() if act.text()]


def test_report_menu_event_log_renamed(qapp, tmp_path, monkeypatch):
    w = _window(ROLE_SUPERVISOR, tmp_path, monkeypatch)
    try:
        labels = [act.text() for act in _report_actions(w)]
        assert "Event Log Folder…" in labels
        assert "Event Log" not in labels
        assert w._open_report_event_log.__doc__.splitlines()[0] == \
            "Report > Event Log Folder…: open the Event Log folder - the"
    finally:
        w.close()
        w.deleteLater()


def test_report_menu_sharepoint_supervisor_enabled_operator_disabled(
        qapp, tmp_path, monkeypatch):
    supervisor = _window(ROLE_SUPERVISOR, tmp_path, monkeypatch)
    try:
        assert supervisor.sp_upload_action.isEnabled() is True
        # Qt falls back to the action text when the tooltip is cleared
        assert "Supervisor only" not in \
            supervisor.sp_upload_action.toolTip()
    finally:
        supervisor.close()
        supervisor.deleteLater()
    operator = _window(ROLE_OPERATOR, tmp_path, monkeypatch)
    try:
        assert operator.sp_upload_action.isEnabled() is False
        assert operator.sp_upload_action.toolTip() == "Supervisor only"
    finally:
        operator.close()
        operator.deleteLater()


def test_report_menu_sharepoint_handler_has_no_disabled_guard(
        qapp, tmp_path, monkeypatch):
    from mtkgui.main_window import MainWindow
    source = inspect.getsource(MainWindow._open_sharepoint_upload)
    assert "temporarily disabled" not in source.lower()
    assert "isEnabled()" not in source


def test_report_menu_statistics_open_for_all_roles(qapp, tmp_path,
                                                   monkeypatch):
    for role in (ROLE_SUPERVISOR, ROLE_OPERATOR):
        w = _window(role, tmp_path, monkeypatch)
        try:
            stats = next(act for act in _report_actions(w)
                         if act.text() == "Statistics")
            assert stats.isEnabled() is True, role
        finally:
            w.close()
            w.deleteLater()


def test_report_menu_items_not_run_locked(qapp, tmp_path, monkeypatch):
    w = _window(ROLE_SUPERVISOR, tmp_path, monkeypatch)
    try:
        runner = w.workflow_page._runner
        runner._transition("running", "test")
        try:
            assert w._run_active is True
            actions = _report_actions(w)
            assert [act.text() for act in actions] == [
                "DUT Report", "Event Log Folder…", "Statistics",
                "SharePoint Upload…"]
            assert all(act.isEnabled() for act in actions)
        finally:
            runner._transition("aborted", "test")
            w._run_active = False
    finally:
        w.close()
        w.deleteLater()
