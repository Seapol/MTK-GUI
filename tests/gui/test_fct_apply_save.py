# -*- coding: utf-8 -*-
"""M22b: the block-07 "Apply & Save yaml" action and the single
refresh path.

The bug it locks out: after overwriting the project yaml the FCT Test
Results table stayed stale until the GUI was closed and reopened - the
dialog's values only reached the tables through the post-OK flow, and
no save path repainted the views that read the sequence.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import yaml  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False

FCT_TEXT = yaml.safe_dump({"fct_test_config": {
    "dut_type": "linux",
    "console": {"enabled": True, "port": "/dev/cu.test",
                "test_commands": [
                    {"name": "Kernel check", "send": "uname -a",
                     "timeout": 5}]},
    "setup": {"power_mode": "none"},
}}, sort_keys=False)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _sandbox_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # the Yaml Build page persists its state under mtkgui/config/ -
    # never let a test's fct_build params leak into the next test's
    # "restored" project (it silently made other suites see a
    # configured FCT block)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)


@pytest.fixture()
def window(qapp):
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()


def test_fct_dialog_has_apply_save_button(qapp):
    """Block 07 exposes the in-place action; clicking it calls the
    page callback and neither accepts nor rejects the dialog."""
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    calls: list = []
    dlg = BlockConfigDialog(
        "fct_build", {"fct_test_config_yaml": FCT_TEXT},
        apply_save_cb=lambda values: calls.append(values))
    assert dlg.btn_apply_save is not None
    dlg.btn_apply_save.click()
    assert calls and calls[0]["fct_test_config_yaml"]
    assert dlg.result() != BlockConfigDialog.DialogCode.Accepted
    # a callback error is shown in the dialog, no exception
    dlg2 = BlockConfigDialog(
        "fct_build", {"fct_test_config_yaml": FCT_TEXT},
        apply_save_cb=lambda values: "boom")
    dlg2.btn_apply_save.click()
    assert "boom" in dlg2.error_label.text()


def test_other_dialogs_have_no_apply_save_button(qapp):
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    dlg = BlockConfigDialog(
        "design_input", {}, apply_save_cb=lambda values: None)
    assert dlg.btn_apply_save is None


def test_apply_save_callback_emits_cases(window):
    """The page callback rebuilds the cases and broadcasts the one
    signal every view refresh hangs off."""
    got: list = []
    window.yaml_build_page.fct_sequence_applied.connect(got.append)
    err = window.yaml_build_page._apply_save_fct_params(
        {"fct_test_config_yaml": FCT_TEXT})
    assert err is None
    assert got and any("Kernel check" in c["name"] for c in got[0])


def test_apply_save_callback_reports_invalid_config(window):
    err = window.yaml_build_page._apply_save_fct_params(
        {"fct_test_config_yaml": "fct_test_config: : :\n  - broken"})
    assert err


def test_apply_refreshes_workflow_table_and_saves(window, tmp_path):
    """THE reported bug: after saving, the Test Work Flow FCT table
    shows the new sequence immediately (no reopen)."""
    model = window.yaml_build_page.model
    model.set_params("fct_build", {"fct_test_config_yaml": FCT_TEXT})
    # a STALE generated case - the save must repaint it from the model
    # (manual standard ops without the fct_step marker are legitimately
    # kept by the P3-B7 merge protection, so mark this one generated)
    window.workflow_page.load_fct_cases([{
        "name": "Stale case", "kind": "MessageOK",
        "op_params": {"fct_step": {"name": "Stale case"}}}])
    path = tmp_path / "project.yaml"

    window._save_yaml_to(str(path))

    assert path.exists()
    assert any("Kernel check" in r for r in window.workflow_page.fct_rows)
    assert "Stale case" not in window.workflow_page.fct_rows


def test_apply_save_saves_in_place_without_prompt(window, tmp_path,
                                                  monkeypatch):
    """The dialog's Apply & Save writes the CURRENT project file with no
    overwrite prompt (the operator already asked for it)."""
    asks: list = []
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.question",
        lambda *a, **k: asks.append(a) or
        __import__("PySide6.QtWidgets",
                   fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes)
    model = window.yaml_build_page.model
    model.set_params("fct_build", {"fct_test_config_yaml": FCT_TEXT})
    path = tmp_path / "inplace.yaml"
    window._project_path = str(path)

    cases, errors = window.yaml_build_page._emit_fct_sequence(
        {"fct_test_config_yaml": FCT_TEXT})
    assert errors == []
    window._on_fct_sequence_applied(cases)

    assert Path(path).exists()
    assert asks == []
    assert any("Kernel check" in r for r in window.workflow_page.fct_rows)
