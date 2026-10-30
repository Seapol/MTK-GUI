# -*- coding: utf-8 -*-
"""M44: YAML lifecycle + FCT sequence purity + overwrite stacking.

Covers the documented lifecycle: start with no yaml, load, unified
apply save yaml (no overwrite prompt), save-then-reload (GUI == file),
the Exit prompt only when the page is dirty, and the stacking
regression (apply save twice keeps exactly the panel rows).
"""
from __future__ import annotations

import yaml

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False

FCT_TEXT = yaml.safe_dump({"fct_test_config": {
    "dut_type": "linux",
    "console": {"port": "/dev/cu.test", "test_commands": [
        {"name": "Kernel check", "send": "uname -a", "timeout": 5}]},
    # the setup node must NOT inject Power On/Off or Fixture rows (M44)
    "setup": {"power_mode": "psu", "use_fixture": True},
}}, sort_keys=False)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _sandbox_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)


@pytest.fixture()
def window(qapp):
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()


def _wait_load_done(window, qapp):
    while getattr(window, "_yaml_loading", False):
        qapp.processEvents()


def _configured(window):
    window.yaml_build_page.model.set_params(
        "fct_build", {"fct_test_config_yaml": FCT_TEXT})


def test_start_state_has_no_yaml(window):
    """The GUI starts with yaml = (none) - no project is auto-loaded."""
    assert window._project_path is None
    assert window.workflow_page.project_path in (None, "")


def test_unified_apply_save_has_no_overwrite_prompt(window, tmp_path, qapp,
                                                     monkeypatch):
    """M44: apply save yaml writes the current file directly - the old
    "Overwrite current yaml" 3-button prompt is gone."""
    box_calls: list = []
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.exec",
        lambda *a, **k: box_calls.append(a) and 0)
    _configured(window)
    path = tmp_path / "project.yaml"
    window._project_path = str(path)

    window._on_yaml_apply_committed()
    _wait_load_done(window, qapp)

    assert box_calls == []
    assert path.exists()
    assert window._project_path == str(path)


def test_apply_save_reloads_and_gui_equals_file(window, tmp_path, qapp):
    """After apply save the project is closed and reloaded, so the GUI
    shows exactly what the file holds."""
    _configured(window)
    path = tmp_path / "project.yaml"
    window._project_path = str(path)

    window._on_yaml_apply_committed()
    _wait_load_done(window, qapp)

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    yaml_cases = doc["test_workflow"]["fct_test_cases"]
    assert [c["name"] for c in yaml_cases] == ["Kernel check"]
    assert window.workflow_page.fct_rows == ["Kernel check"]
    assert window._project_path == str(path)


def test_apply_save_twice_does_not_stack(window, tmp_path, qapp):
    """Regression: edit -> apply save -> edit -> apply save keeps exactly
    the panel rows both times (no leftover / duplicated rows)."""
    _configured(window)
    path = tmp_path / "project.yaml"
    window._project_path = str(path)

    window._on_yaml_apply_committed()
    _wait_load_done(window, qapp)
    first = list(window.workflow_page.fct_rows)

    _configured(window)
    window._on_yaml_apply_committed()
    _wait_load_done(window, qapp)
    second = list(window.workflow_page.fct_rows)

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    yaml_names = [c["name"] for c in doc["test_workflow"]["fct_test_cases"]]
    assert first == ["Kernel check"]
    assert second == first
    assert yaml_names == second


def test_no_auto_injected_steps_in_applied_cases(window):
    """Iron rule: the PSU/fixture setup node never adds run-time rows."""
    cases, errors = window.yaml_build_page._emit_fct_sequence(
        {"fct_test_config_yaml": FCT_TEXT})
    assert errors == []
    assert [c["name"] for c in cases] == ["Kernel check"]
    assert not any(c.get("kind") == "op" for c in cases)


def test_exit_prompt_only_when_dirty(qapp):
    """M44: the config page's Exit asks for a decision only when the
    page holds unsaved changes."""
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    dlg = BlockConfigDialog("rails", {})
    assert dlg._is_dirty() is False
    editor = next(iter(dlg._editors.values()))
    original = editor.text()
    editor.setText(original + "1")
    assert dlg._is_dirty() is True
    editor.setText(original)
    dlg.reject()


def test_config_page_buttons_are_apply_save_and_exit(qapp):
    """M44: OK/Cancel are relabelled Apply_Save yaml / Exit."""
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    dlg = BlockConfigDialog("rails", {})
    from PySide6.QtWidgets import QDialogButtonBox
    box = dlg.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.StandardButton.Ok).text() \
        == "Apply_Save yaml"
    assert box.button(QDialogButtonBox.StandardButton.Cancel).text() \
        == "Exit"
    dlg.reject()
