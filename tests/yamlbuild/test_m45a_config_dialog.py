# -*- coding: utf-8 -*-
"""M45a: config-page button de-dup + dirty-Exit dialog order +
Parse Nets no-NET immediate stop.

Owner reports 2026-10-30:
* the FCT config page showed TWO apply-save buttons (bottom-left
  "Apply & Save yaml" + bottom-right "Apply_Save yaml");
* the dirty-Exit prompt's buttons were ordered "Save as new yaml |
  Cancel (discard changes) | Apply_Save yaml" (a QMessageBox reorders
  by platform role) - the owner requires the fixed left-to-right
  order Apply_Save yaml | Save as new yaml | Cancel;
* "Parse Nets for ICT" with no NET file warned and then still entered
  the "Working..." 0% state - it must stop immediately.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

import mtkgui.gui.yamlbuild.blocks as blocks  # noqa: E402
from mtkgui.gui.yamlbuild.blocks import (  # noqa: E402
    BlockConfigDialog,
    ExitPromptDialog,
)
from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _button_texts(dlg: BlockConfigDialog) -> list[str]:
    return [b.text() for b in dlg.findChildren(QPushButton)]


# ------------------------------------------------- button de-duplication
@pytest.mark.parametrize("module_key,params", [
    ("rails", {}),
    ("parse_ict", {}),
    ("fct_build", {"fct_test_config_yaml": ""}),
    ("design_input", {}),
])
def test_one_apply_save_and_one_exit(qapp, module_key, params):
    """Every config page shows EXACTLY ONE Apply_Save yaml + ONE Exit
    (the M22b extra "Apply & Save yaml" button is gone)."""
    dlg = BlockConfigDialog(
        module_key, params,
        apply_save_cb=(lambda values: None)
        if module_key == "fct_build" else None)
    texts = _button_texts(dlg)
    assert texts.count("Apply_Save yaml") == 1
    assert texts.count("Exit") == 1
    assert "Apply & Save yaml" not in texts


def test_fct_apply_save_callback_runs_on_the_single_button(qapp):
    """Block 07's in-place apply/save still runs - from the ONE
    Apply_Save yaml button."""
    calls: list = []
    dlg = BlockConfigDialog(
        "fct_build", {"fct_test_config_yaml": ""},
        apply_save_cb=lambda values: calls.append(values))
    from PySide6.QtWidgets import QDialogButtonBox
    box = dlg.findChild(QDialogButtonBox)
    box.button(QDialogButtonBox.StandardButton.Ok).click()
    assert calls
    assert dlg.result() == BlockConfigDialog.DialogCode.Accepted


# ------------------------------------------------------- Exit prompt
def test_exit_prompt_button_order(qapp):
    """The dirty-Exit prompt lays out Apply_Save yaml | Save as new yaml
    | Cancel left-to-right (no "(discard changes)" suffix)."""
    prompt = ExitPromptDialog()
    assert [b.text() for b in prompt.buttons_in_order()] == [
        "Apply_Save yaml", "Save as new yaml", "Cancel"]


class _FakePrompt:
    """Records construction and returns a scripted choice."""

    APPLY = ExitPromptDialog.APPLY
    SAVE_AS = ExitPromptDialog.SAVE_AS
    CANCEL = ExitPromptDialog.CANCEL
    created: list = []

    def __init__(self, parent=None):
        _FakePrompt.created.append(self)
        self.choice = _FakePrompt.CANCEL

    def exec(self) -> int:
        return 0


def _dirty_dialog(params=None, **kwargs) -> BlockConfigDialog:
    # a valid rails parameter set: "sequence" is required, so an empty
    # default would make _on_accept() fail validation and block on the
    # modal QMessageBox under the offscreen platform
    dlg = BlockConfigDialog("rails", params or {"sequence": "V1:0.5"})
    editor = next(iter(dlg._editors.values()))
    editor.setText(editor.text() + "1")
    for key, value in kwargs.items():
        setattr(dlg, key, value)
    return dlg


def test_clean_exit_shows_no_prompt(qapp, monkeypatch):
    monkeypatch.setattr(blocks, "ExitPromptDialog", _FakePrompt)
    _FakePrompt.created = []
    dlg = BlockConfigDialog("rails", {})
    assert dlg._is_dirty() is False
    dlg._on_exit()
    assert _FakePrompt.created == []
    assert dlg.result() != BlockConfigDialog.DialogCode.Accepted


def test_dirty_exit_cancel_discards(qapp, monkeypatch):
    monkeypatch.setattr(blocks, "ExitPromptDialog", _FakePrompt)
    _FakePrompt.created = []
    saved: list = []
    dlg = _dirty_dialog(_save_as_cb=lambda values: saved.append(values))
    dlg._on_exit()
    assert len(_FakePrompt.created) == 1
    assert saved == []
    assert dlg.result() != BlockConfigDialog.DialogCode.Accepted


def test_dirty_exit_apply_saves(qapp, monkeypatch):
    # never let a validation failure block on the modal warning
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: 0)
    _FakePrompt.created = []
    calls: list = []

    class _ApplyPrompt(_FakePrompt):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.choice = ExitPromptDialog.APPLY

    monkeypatch.setattr(blocks, "ExitPromptDialog", _ApplyPrompt)
    dlg = _dirty_dialog()
    dlg._apply_save_cb = lambda values: calls.append(values)
    dlg._on_exit()
    assert calls
    assert dlg.result() == BlockConfigDialog.DialogCode.Accepted


def test_dirty_exit_save_as_new(qapp, monkeypatch):
    _FakePrompt.created = []

    class _SaveAsPrompt(_FakePrompt):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.choice = ExitPromptDialog.SAVE_AS

    monkeypatch.setattr(blocks, "ExitPromptDialog", _SaveAsPrompt)
    saved: list = []
    dlg = _dirty_dialog(_save_as_cb=lambda values: saved.append(values))
    dlg._on_exit()
    assert saved
    assert dlg.result() != BlockConfigDialog.DialogCode.Accepted


# -------------------------------------------- Parse Nets no-NET stop
@pytest.fixture()
def panel(qapp):
    w = ParseNetsPanel()
    yield w
    w.deleteLater()


def _no_net_stops(panel, monkeypatch, trigger) -> None:
    shown: list = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a) or 0)
    progress: list = []

    def _capture(percent, label):
        progress.append((percent, label))

    panel.task_progress.connect(_capture)
    trigger()
    assert shown and "no NET file loaded" in shown[0][2]
    # no "Working..." state: the pre-check never emits progress
    assert progress == []
    assert getattr(panel, "_parse_dlg", None) is None
    assert getattr(panel, "_parse_worker", None) is None


def test_parse_nets_button_no_net_stops(panel, monkeypatch):
    panel.set_net_source("", "")
    _no_net_stops(panel, monkeypatch, panel._on_parse_clicked)


def test_parse_nets_direct_no_net_stops(panel, monkeypatch):
    panel.set_net_source("", "")
    _no_net_stops(panel, monkeypatch, panel.parse_nets)
