# -*- coding: utf-8 -*-
"""M38 GUI: the fixture expectation is editable in the shared step
editor and round-trips into op_params (renders in cmd / params, never
the Capture column)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QComboBox,  # noqa: E402
                               QDialog)

from mtkgui.gui.steps_editor import StepsEditorDialog  # noqa: E402
from mtkgui.test_workflow_page import _SequenceEditorDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _level_combos(widget):
    return [cb for cb in widget.findChildren(QComboBox)
            if [cb.itemText(i) for i in range(cb.count())]
            == ["", "High", "Low"]]


def test_fixture_expectation_round_trip(qapp, monkeypatch):
    step = ("op", "Fixture Lock", "—", "—", "—", "—",
            {"type": "fixture", "signal": "inpos", "level": "H"})
    dlg = _SequenceEditorDialog("ict", [step], [True], [100], [5000])
    seen = {}

    def fake_exec(widget):
        combos = _level_combos(widget)
        seen["count"] = len(combos)
        assert len(combos) == 2          # Expect + Unexpected
        combos[0].setCurrentText("High")
        combos[1].setCurrentText("Low")
        return QDialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        assert seen["count"] == 2
        assert dlg._steps[0][6] == {
            "type": "fixture", "signal": "inpos", "level": "H",
            "expect": "High", "unexpected": "Low"}
    finally:
        dlg.deleteLater()


def test_fixture_expectation_preserved_on_reopen(qapp, monkeypatch):
    step = ("op", "Fixture Lock", "—", "—", "—", "—",
            {"type": "fixture", "signal": "inpos", "level": "H",
             "expect": "High", "unexpected": "Low"})
    dlg = StepsEditorDialog("ict", [step], [True], [100], [5000])
    seen = {}

    def fake_exec(widget):
        combos = _level_combos(widget)
        seen["values"] = [cb.currentText() for cb in combos]
        return QDialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        assert seen["values"] == ["High", "Low"]
        params = dlg._steps[0][6]
        assert params["expect"] == "High"
        assert params["unexpected"] == "Low"
    finally:
        dlg.deleteLater()


def test_fixture_without_expectation_stays_write_style(qapp, monkeypatch):
    step = ("op", "Fixture Clamp Down", "—", "—", "—", "—",
            {"type": "fixture", "signal": "press", "level": "H"})
    dlg = StepsEditorDialog("ict", [step], [True], [100], [5000])

    def fake_exec(widget):
        return QDialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        assert dlg._steps[0][6] == {
            "type": "fixture", "signal": "press", "level": "H"}
    finally:
        dlg.deleteLater()
