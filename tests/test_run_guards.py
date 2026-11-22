# -*- coding: utf-8 -*-
"""M103c: run-state lock on the Yaml configuration (contract §8.3)."""
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
    """Record message boxes; questions answer *answer*."""
    calls: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: calls.append(("info", a[1], a[2])) or 0)
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: calls.append(("warn", a[1], a[2])) or 0)
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: calls.append(("question", a[1], a[2])) or answer)
    return calls


def _runner(window):
    return window.workflow_page._runner


def _start(window):
    """Move the runner to ``running`` (no hardware is touched)."""
    _runner(window)._transition("running", "test")


def _stop(window):
    """Leave the active state through the legal abort edge."""
    _runner(window)._transition("aborted", "test")


def _texts(calls, kind):
    return [text for call_kind, _title, text in calls if call_kind == kind]


def test_load_refused_when_running(window, monkeypatch):
    calls = _capture(monkeypatch)
    picked: list = []
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: picked.append(True) or ("", "")))
    _start(window)
    window.load_yaml()
    assert picked == []                     # refused BEFORE the dialog
    assert any("stop it before loading another project" in text
               for text in _texts(calls, "info"))


def test_close_refused_when_running(window, monkeypatch):
    calls = _capture(monkeypatch)
    reset: list = []
    monkeypatch.setattr(window, "_reset_to_factory",
                        lambda *a, **k: reset.append(True))
    _start(window)
    window.close_yaml()
    assert reset == []
    assert any("stop it before closing the project" in text
               for text in _texts(calls, "info"))


def test_save_writes_without_reload_when_running(window, monkeypatch,
                                                 tmp_path):
    path = str(tmp_path / "project.yaml")
    window._project_path = path
    saved: list = []
    reloaded: list = []
    monkeypatch.setattr(window, "_save_yaml_to",
                        lambda p: saved.append(p) or True)
    monkeypatch.setattr(window, "_reload_saved_yaml",
                        lambda p: reloaded.append(p))
    _start(window)
    window.apply_and_save_yaml()
    assert saved == [path]
    assert reloaded == []
    assert window._pending_reload_path == path


def test_pending_reload_prompts_on_idle(window, monkeypatch, tmp_path):
    path = str(tmp_path / "project.yaml")
    calls = _capture(monkeypatch)
    reloaded: list = []
    monkeypatch.setattr(window, "_reload_saved_yaml",
                        lambda p: reloaded.append(p))
    _start(window)
    window._pending_reload_path = path
    _stop(window)
    assert reloaded == [path]
    assert any("Saved during the run. Reload now?" in text
               for text in _texts(calls, "question"))
    assert window._pending_reload_path is None


def test_no_auto_reload_after_run(window, monkeypatch, tmp_path):
    path = str(tmp_path / "project.yaml")
    _capture(monkeypatch, answer=QMessageBox.StandardButton.No)
    reloaded: list = []
    logs: list = []
    monkeypatch.setattr(window, "_reload_saved_yaml",
                        lambda p: reloaded.append(p))
    monkeypatch.setattr(window, "_append_event_log",
                        lambda *a, **k: logs.append(a[0]))
    _start(window)
    window._pending_reload_path = path
    _stop(window)
    assert reloaded == []
    assert window._pending_reload_path is None
    assert any("Reload skipped - use Load Yaml" in line for line in logs)


def test_imports_disabled_when_running(window, monkeypatch):
    calls = _capture(monkeypatch)
    reset: list = []
    monkeypatch.setattr(window, "_reset_to_factory",
                        lambda *a, **k: reset.append(True))
    _start(window)
    assert not window.act_import_excel.isEnabled()
    assert not window.act_import_ict_plan.isEnabled()
    window._import_traditional_plan_menu()
    window._import_mtk_sheet_menu()
    assert reset == []
    assert any("stop it before loading another project" in text
               for text in _texts(calls, "warn"))


def test_yaml_build_read_only_when_running(window):
    _start(window)
    assert window.yaml_build_page._edit_allowed is False
    assert window.yaml_build_page.channel_alloc._edit_allowed is False
    assert window._yaml_wizard._run_active is True
    assert window._yaml_wizard._is_editable("design_input") is False


def test_switch_account_refused_when_running(window, monkeypatch):
    calls = _capture(monkeypatch)
    logins: list = []
    monkeypatch.setattr(
        "mtkgui.main_window.LoginDialog.login",
        staticmethod(lambda *a, **k: logins.append(True) or None))
    _start(window)
    window.switch_account()
    assert logins == []
    assert any("stop it before switching accounts" in text
               for text in _texts(calls, "info"))


def test_operator_stays_locked_after_run(window):
    window.role = ROLE_OPERATOR
    window._can_yaml_build = False
    window._apply_yaml_guards()
    _start(window)
    _stop(window)
    assert window._run_active is False
    assert not window.act_import_excel.isEnabled()
    assert not window.act_export_excel.isEnabled()
    assert window.yaml_build_page._edit_allowed is False


def test_export_available_when_running(window, tmp_path):
    from tests.yamlbuild.conftest import fill_required
    model = window.yaml_build_page.model
    model.enable_all()
    fill_required(model)
    window._project_path = str(tmp_path / "project.yaml")
    _start(window)
    assert window.act_export_excel.isEnabled() is True
    assert window.act_export_ict_plan.isEnabled() is True


def test_exit_refused_when_running(window, monkeypatch):
    calls = _capture(monkeypatch)

    class _Event:
        ignored = False

        def ignore(self):
            self.ignored = True

        def accept(self):
            pass

    _start(window)
    event = _Event()
    window.closeEvent(event)
    assert event.ignored is True
    assert any("Stop the run before exiting" in text
               for text in _texts(calls, "info"))
