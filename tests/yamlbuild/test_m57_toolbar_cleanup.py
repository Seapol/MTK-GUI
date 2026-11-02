# -*- coding: utf-8 -*-
"""M57: FCT toolbar "Clean up" clears ALL steps; "Remove" (renamed
from "Remove selected") keeps removing exactly the selected rows."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QItemSelectionModel  # noqa: E402
from PySide6.QtWidgets import (QApplication, QMessageBox,  # noqa: E402
                               QPushButton)

from mtkgui.engine.fct_templates import TEMPLATE_BARE_METAL  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    p = FCTTestConfigPanel()
    p.set_values({})
    return p


def _accept(monkeypatch, answer=QMessageBox.StandardButton.Yes):
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: answer)


def _select(panel, rows) -> None:
    model = panel.cmd_table.selectionModel()
    panel.cmd_table.clearSelection()
    for r in rows:
        model.select(panel.cmd_table.model().index(r, 0),
                     QItemSelectionModel.SelectionFlag.Select
                     | QItemSelectionModel.SelectionFlag.Rows)


def test_toolbar_order_and_labels(panel):
    seq = panel.tabs.widget(0)
    texts = [b.text() for b in seq.findChildren(QPushButton)]
    assert texts == ["Add", "Load Template", "Clean up", "Remove",
                     "Duplicate", "Edit", "Move Up", "Move Down",
                     "Undo", "Redo"]


def test_clean_up_clears_every_row_after_confirmation(panel, monkeypatch):
    logs = []
    panel.task_log.connect(lambda level, msg: logs.append((level, msg)))
    panel._load_template(TEMPLATE_BARE_METAL)
    assert panel.cmd_table.rowCount() == 9
    _accept(monkeypatch)
    panel._clear_all_steps()
    assert panel.cmd_table.rowCount() == 0
    assert ("INFO", "Clean up: cleared 9 row(s)") in logs


def test_clean_up_no_leaves_the_table_untouched(panel, monkeypatch):
    panel._load_template(TEMPLATE_BARE_METAL)
    _accept(monkeypatch, QMessageBox.StandardButton.No)
    panel._clear_all_steps()
    assert panel.cmd_table.rowCount() == 9


def test_clean_up_on_an_empty_table_is_a_noop(panel, monkeypatch):
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.No)
    panel._clear_all_steps()
    assert panel.cmd_table.rowCount() == 0
    assert asked == []          # no confirmation prompt on an empty table


def test_remove_removes_the_selection_and_stays_gated(panel):
    panel._load_template(TEMPLATE_BARE_METAL)
    assert panel._remove_sel_btn.text() == "Remove"
    assert panel._remove_sel_btn.isEnabled() is False
    _select(panel, [1, 3, 5])
    assert panel._remove_sel_btn.isEnabled() is True
    panel._remove_selected()
    assert panel.cmd_table.rowCount() == 6
