# -*- coding: utf-8 -*-
"""M58: FCT toolbar Undo / Redo snapshot history.

Undo rewinds one operator table change at a time (all the way back to
the last saved YAML state); Redo replays a cancelled change.  The
history only records the operator's own edits - the app never injects
steps.  A clean save (values()) clears the history.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import (QApplication, QDialog, QMessageBox,  # noqa: E402
                               QSpinBox)

from mtkgui.engine.fct_templates import TEMPLATE_BARE_METAL  # noqa: E402
from mtkgui.engine.fct_test_config import (  # noqa: E402
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_DELAY,
)
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


def _accept(monkeypatch):
    monkeypatch.setattr(QDialog, "exec",
                        lambda _dlg: QDialog.DialogCode.Accepted)


def _reject(monkeypatch):
    monkeypatch.setattr(QDialog, "exec",
                        lambda _dlg: QDialog.DialogCode.Rejected)


def _yes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)


def test_undo_last_add_and_redo_it(panel):
    panel._add_row_for_label(STEP_TYPE_DELAY)
    panel._add_row_for_label(STEP_TYPE_DELAY)
    assert panel.cmd_table.rowCount() == 2
    panel._undo_step()
    assert panel.cmd_table.rowCount() == 1
    panel._redo_step()
    assert panel.cmd_table.rowCount() == 2


def test_history_buttons_follow_the_stacks(panel):
    assert panel._undo_btn.isEnabled() is False
    assert panel._redo_btn.isEnabled() is False
    panel._add_row_for_label(STEP_TYPE_DELAY)
    assert panel._undo_btn.isEnabled() is True
    assert panel._redo_btn.isEnabled() is False
    panel._undo_step()
    assert panel._undo_btn.isEnabled() is False
    assert panel._redo_btn.isEnabled() is True
    panel._redo_step()
    assert panel._undo_btn.isEnabled() is True
    assert panel._redo_btn.isEnabled() is False


def test_multi_action_sequence_rewinds_to_the_initial_table(panel,
                                                            monkeypatch):
    initial = panel.cmd_table.rowCount()
    # 1. add a Delay row
    panel._add_row_for_label(STEP_TYPE_DELAY)
    # 2. add a second Delay row
    panel._add_row_for_label(STEP_TYPE_DELAY)
    # 3. Edit the first row (one undoable step)
    def accept_and_set(dlg):
        spins = dlg.findChildren(QSpinBox)
        if spins:
            spins[0].setValue(500)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", accept_and_set)
    panel.cmd_table.setCurrentCell(0, 0)
    panel._edit_current_row(0)
    assert panel._get_row_cmd(0).wait_ms == 500
    # 4. Move the first row down
    panel.cmd_table.setCurrentCell(0, 0)
    panel._move_down()
    assert panel._get_row_cmd(0).wait_ms != 500
    # 5. Remove the current row
    panel._remove_current()
    assert panel.cmd_table.rowCount() == 1
    # 6. Load Template (one undoable step)
    panel._load_template(TEMPLATE_BARE_METAL)
    assert panel.cmd_table.rowCount() == 9
    # 7. Clean up (one undoable step)
    _yes(monkeypatch)
    panel._clear_all_steps()
    assert panel.cmd_table.rowCount() == 0
    assert len(panel._undo_stack) == 7

    # Rewind ALL unsaved changes back to the initial table
    for _ in range(7):
        panel._undo_step()
    assert panel.cmd_table.rowCount() == initial
    assert panel._undo_stack == []

    # Redo replays them forward, one step at a time
    for _ in range(6):
        panel._redo_step()
    assert panel.cmd_table.rowCount() == 9          # after Load Template
    panel._redo_step()
    assert panel.cmd_table.rowCount() == 0          # Clean up replayed
    assert panel._redo_stack == []


def test_load_template_is_undoable_as_one_step(panel):
    panel._add_row_for_label(STEP_TYPE_DELAY)
    panel._load_template(TEMPLATE_BARE_METAL)
    assert panel.cmd_table.rowCount() == 9
    panel._undo_step()
    assert panel.cmd_table.rowCount() == 1          # pre-template rows back


def test_clean_up_is_undoable_as_one_step(panel, monkeypatch):
    panel._load_template(TEMPLATE_BARE_METAL)
    _yes(monkeypatch)
    panel._clear_all_steps()
    assert panel.cmd_table.rowCount() == 0
    panel._undo_step()
    assert panel.cmd_table.rowCount() == 9


def test_dialog_cancel_pushes_no_history_and_accept_pushes_one(panel,
                                                               monkeypatch):
    panel._add_row_for_label(STEP_TYPE_DELAY)
    assert len(panel._undo_stack) == 1
    _reject(monkeypatch)
    panel._edit_current_row(0)
    assert len(panel._undo_stack) == 1              # Cancel: no entry
    _accept(monkeypatch)
    panel._edit_current_row(0)
    assert len(panel._undo_stack) == 2              # accepted Edit: 1 entry
    panel._undo_step()
    assert panel.cmd_table.rowCount() == 1


def test_clean_save_clears_history(panel):
    panel._add_row_for_label(STEP_TYPE_DELAY)
    assert panel._undo_btn.isEnabled() is True
    panel.values()                                  # save -> save point
    assert panel._undo_stack == []
    assert panel._redo_stack == []
    assert panel._undo_btn.isEnabled() is False
    assert panel._redo_btn.isEnabled() is False


def test_failed_save_keeps_history(panel, monkeypatch):
    import mtkgui.engine.ref_resolver as ref_mod

    panel._add_row_for_label(STEP_TYPE_CONSOLE_SERIAL)
    monkeypatch.setattr(ref_mod, "validate_refs",
                        lambda *_a, **_k: ["unresolvable reference"])
    panel.values()                                  # validation error
    assert len(panel._undo_stack) >= 1
    assert panel._undo_btn.isEnabled() is True