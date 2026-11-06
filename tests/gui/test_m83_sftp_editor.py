# -*- coding: utf-8 -*-
"""M83 C7: SFTP push/pull editor (no capture, read-only SSH channel)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QLabel,
    QLineEdit,
    QScrollArea,
)

from mtkgui.engine.fct_test_config import STEP_TYPE_SFTP_PUT  # noqa: E402
from mtkgui.gui.yamlbuild import dialog_layout as dlayout  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)

EQUIPMENT = {"equipment": {"dut": {"ssh": {
    "host": "192.168.1.20", "port": 22, "username": "root"}}}}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _open(panel, monkeypatch) -> tuple:
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._add_row_for_label(STEP_TYPE_SFTP_PUT)
    row = panel.cmd_table.rowCount() - 1
    panel._edit_current_row(row)
    assert seen, "the editor dialog never opened"
    return seen[0], row


def _labels(dlg) -> list:
    return [label.text() for label in dlg.findChildren(QLabel)]


def test_m83_sftp_editor_has_no_capture_fields(qapp, monkeypatch):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    dlg, _row = _open(panel, monkeypatch)
    texts = _labels(dlg)
    assert not any("Capture Expected:" in text for text in texts)
    assert not any("Capture Unexpected:" in text for text in texts)
    assert not any(cb.text() == "Regex"
                   for cb in dlg.findChildren(QCheckBox))
    # Case Sensitive is retained (no user direction to remove it)
    assert any("Case Sensitive" in cb.text()
               for cb in dlg.findChildren(QCheckBox))
    panel.deleteLater()


def test_m83_sftp_editor_shows_read_only_ssh_channel(qapp, monkeypatch):
    logs: list = []
    panel = FCTTestConfigPanel(equipment_provider=lambda: EQUIPMENT)
    panel.set_values({})
    panel.task_log.connect(lambda level, msg: logs.append((level, msg)))
    dlg, _row = _open(panel, monkeypatch)
    texts = _labels(dlg)
    assert any(text.startswith("SSH channel: ssh1 — 192.168.1.20:22")
               and "(from Console module)" in text for text in texts)
    # the endpoint line is a label, never an editable input
    edits = [edit.text() for edit in dlg.findChildren(QLineEdit)]
    assert not any("192.168.1.20" in text for text in edits)
    assert not any(level == "ERROR" for level, _msg in logs)
    panel.deleteLater()

    # no SSH endpoint configured -> warning, still an advisory
    bare = FCTTestConfigPanel(equipment_provider=lambda: {})
    bare.set_values({})
    bare_logs: list = []
    bare.task_log.connect(lambda level, msg: bare_logs.append((level, msg)))
    _open(bare, monkeypatch)
    assert any(level == "WARNING" and "SSH channel not configured" in msg
               for level, msg in bare_logs)
    bare.deleteLater()


def test_m83_sftp_editor_width_is_locked(qapp, monkeypatch):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    dlg, _row = _open(panel, monkeypatch)
    assert dlg.minimumWidth() == dlg.maximumWidth() == dlayout.WIDTH_FORM
    for area in dlg.findChildren(QScrollArea):
        assert area.horizontalScrollBarPolicy() \
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    panel.deleteLater()
