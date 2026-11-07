# -*- coding: utf-8 -*-
"""M83 C8: ONE Message editor - greyed Console block, Send on OK."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
)

from mtkgui.engine.fct_test_config import (  # noqa: E402
    STEP_TYPE_MESSAGE_OK,
    STEP_TYPE_MESSAGE_OK_WAIT,
    STEP_TYPE_MESSAGE_YESNO,
    STEP_TYPE_MESSAGE_YESNO_WAIT,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _open(panel, monkeypatch, label: str) -> QDialog:
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._add_row_for_label(label)
    row = panel.cmd_table.rowCount() - 1
    panel._edit_current_row(row)
    assert seen, "the message editor never opened"
    return seen[0]


def _console_box(dlg) -> QGroupBox:
    for box in dlg.findChildren(QGroupBox):
        if box.title() == "Console":
            return box
    raise AssertionError("Console group box not found")


def _labels(dlg) -> list:
    return [label.text() for label in dlg.findChildren(QLabel)]


def _panel() -> FCTTestConfigPanel:
    panel = FCTTestConfigPanel()
    panel.set_values({})
    return panel


def test_m83_console_block_disabled_for_plain_kinds(qapp, monkeypatch):
    panel = _panel()
    dlg = _open(panel, monkeypatch, STEP_TYPE_MESSAGE_YESNO)
    assert _console_box(dlg).isEnabled() is False
    panel.deleteLater()


def test_m83_console_block_enabled_for_toconsole_kinds(qapp, monkeypatch):
    panel = _panel()
    dlg = _open(panel, monkeypatch, STEP_TYPE_MESSAGE_YESNO_WAIT)
    assert _console_box(dlg).isEnabled() is True
    panel.deleteLater()


def test_m83_send_console_answer_control_removed(qapp, monkeypatch):
    panel = _panel()
    dlg = _open(panel, monkeypatch, STEP_TYPE_MESSAGE_YESNO_WAIT)
    assert not any("send_console_answer" in cb.text()
                   for cb in dlg.findChildren(QCheckBox))
    assert not any("send_console_answer" in text for text in _labels(dlg))
    panel.deleteLater()


def test_m83_oktoconsole_shows_send_on_ok_field(qapp, monkeypatch):
    panel = _panel()
    dlg = _open(panel, monkeypatch, STEP_TYPE_MESSAGE_OK_WAIT)
    ok_rows = [lab for lab in dlg.findChildren(QLabel)
               if "Send on OK:" in lab.text()]
    assert ok_rows and not ok_rows[0].isHidden()
    panel.deleteLater()
    # a plain MessageOK row never shows the field
    panel = _panel()
    dlg = _open(panel, monkeypatch, STEP_TYPE_MESSAGE_OK)
    ok_rows = [lab for lab in dlg.findChildren(QLabel)
               if "Send on OK:" in lab.text()]
    assert ok_rows and ok_rows[0].isHidden()
    panel.deleteLater()


def test_m83_send_on_ok_defaults_to_ok(qapp, monkeypatch):
    panel = _panel()
    panel._add_row_for_label(STEP_TYPE_MESSAGE_OK_WAIT)
    row = panel.cmd_table.rowCount() - 1
    cmd = panel._get_row_cmd(row)
    assert cmd.send_ok == "ok"
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(row)
    box = _console_box(seen[0])
    values = [edit.text() for edit in box.findChildren(QLineEdit)]
    assert "ok" in values
    panel.deleteLater()
