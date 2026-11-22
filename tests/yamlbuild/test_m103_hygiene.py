# -*- coding: utf-8 -*-
"""M103c: File menu hygiene (contract §8 / §8.1 / §8.2)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QMessageBox,
)

from mtkgui.permissions import ROLE_OPERATOR, ROLE_SUPERVISOR  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)
    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    w = MainWindow(role=ROLE_SUPERVISOR, mode="Real", fixture="ATE")
    w._ensure_secondary_ui()
    yield w
    w._run_active = False
    w.close()
    w.deleteLater()


def _capture(monkeypatch, answer=QMessageBox.StandardButton.Yes):
    calls: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: calls.append(("question", a[1], a[2])) or answer)
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: calls.append(("info", a[1], a[2])) or 0)
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: calls.append(("warn", a[1], a[2])) or 0)
    return calls


def _questions(calls):
    return [text for kind, _title, text in calls if kind == "question"]


def test_menu_labels_renamed(window):
    labels = [act.text() for act in window._file_menu.actions()]
    assert "Save Yaml (current file)" in labels
    assert "Save Yaml As… (current file)" in labels
    assert "Apply and Save Yaml" not in labels
    assert "Save as Yaml…" not in labels
    assert window.act_save_yaml.toolTip() == \
        "No current file yet - this opens Save Yaml As…"


def test_close_yaml_dirty_confirm(window, monkeypatch):
    window._project_path = None
    window.yaml_build_page.model.changed = True
    reset: list = []
    monkeypatch.setattr(window, "_reset_to_factory",
                        lambda *a, **k: reset.append(True))
    calls = _capture(monkeypatch, answer=QMessageBox.StandardButton.No)
    window.close_yaml()
    assert reset == []
    assert "The current configuration is not saved. Discard it?" in \
        _questions(calls)
    _capture(monkeypatch, answer=QMessageBox.StandardButton.Yes)
    window.close_yaml()
    assert reset == [True]


def test_pathless_load_prompts(window, monkeypatch, tmp_path):
    window._project_path = None
    window.yaml_build_page.model.changed = True
    target = str(tmp_path / "other.yaml")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (target, "")))
    from mtkgui import project_config
    monkeypatch.setattr(project_config, "load_config", lambda path: {})
    monkeypatch.setattr("mtkgui.main_window.validate_project_yaml",
                        lambda config, **k: [])
    monkeypatch.setattr("mtkgui.main_window.blocking_issues",
                        lambda issues: [])
    class _Dlg:
        def show_delayed(self):
            pass

        def close_done(self):
            pass

    monkeypatch.setattr("mtkgui.main_window.ProgressDialog",
                        lambda *a, **k: _Dlg())
    monkeypatch.setattr(window, "_yaml_load_next", lambda: None)
    calls = _capture(monkeypatch, answer=QMessageBox.StandardButton.No)
    window.load_yaml()
    assert not getattr(window, "_yaml_load_queue", None)
    assert any("The build in progress was never saved. Discard it and "
               "load other.yaml?" in text for text in _questions(calls))
    _capture(monkeypatch, answer=QMessageBox.StandardButton.Yes)
    window.load_yaml()
    assert window._yaml_load_queue
    # the staged chain never ran (spied) - leave a clean loading state
    window._yaml_loading = False
    window._yaml_load_queue = []


def test_switch_to_operator_closes_project(window, monkeypatch, tmp_path):
    window.role = ROLE_SUPERVISOR
    window._project_path = str(tmp_path / "project.yaml")
    window.yaml_build_page.model.changed = False
    monkeypatch.setattr(
        "mtkgui.main_window.LoginDialog.login",
        staticmethod(lambda *a, **k: (ROLE_OPERATOR, "Real", "ATE")))
    reset: list = []
    logs: list = []
    monkeypatch.setattr(window, "_reset_to_factory",
                        lambda *a, **k: reset.append(k))
    monkeypatch.setattr(window, "_append_event_log",
                        lambda *a, **k: logs.append(a[0]))
    window.switch_account()
    assert reset == [{"auto": True}]
    assert any("Account switched to Operator - current project closed"
               in line for line in logs)


def test_export_config_requires_loaded_yaml(window, tmp_path):
    window._project_path = None
    window._refresh_excel_menu()
    assert window.act_export_excel.isEnabled() is False
    window._project_path = str(tmp_path / "project.yaml")
    window._refresh_excel_menu()
    assert window.act_export_excel.isEnabled() is True
    # the MTK sheet export additionally needs a clean validate_all()
    assert window.act_export_ict_plan.isEnabled() is False
