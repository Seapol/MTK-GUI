# -*- coding: utf-8 -*-
"""M83 C3: the per-row console channel combo in the step editors."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QDialog,
    QMessageBox,
)

from mtkgui.engine.fct_test_config import (  # noqa: E402
    ConsoleCommand,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)

CHANNELS = [
    {"key": "ser1", "kind": "serial", "connected": True},
    {"key": "ser2", "kind": "serial", "connected": False},
    {"key": "ssh1", "kind": "ssh", "connected": True},
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _panel(channels=CHANNELS) -> FCTTestConfigPanel:
    provider = (lambda: list(channels)) if channels is not None else None
    panel = FCTTestConfigPanel(console_channels_provider=provider)
    panel.set_values({})
    return panel


def _add(panel, **fields) -> int:
    cmd = ConsoleCommand(**fields)
    panel._insert_row(cmd)
    return panel.cmd_table.rowCount() - 1


def _combo_items(dlg) -> list:
    combos = dlg.findChildren(QComboBox)
    if not combos:
        return []
    (combo,) = combos
    return [combo.itemData(i) for i in range(combo.count())]


def _edit(panel, row, monkeypatch, action=None,
          result=QDialog.DialogCode.Rejected):
    """Open the editor; ``action(dlg)`` runs inside the fake exec."""
    seen = {}

    def fake_exec(dlg):
        seen["combo"] = _combo_items(dlg)
        if action is not None:
            action(dlg)
        return result

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(row)
    return seen


def test_m83_serial_editor_lists_only_serial_channels(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="ser1",
               send_enabled=True, send="uname -r")
    seen = _edit(panel, row, monkeypatch)
    assert seen["combo"] == ["", "ser1", "ser2"]
    panel.deleteLater()


def test_m83_sftp_editor_lists_only_the_ssh_channel(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="sftp_put", name="Upload", transport="ssh",
               channel="ssh1", send_enabled=True, local="a", remote="b")
    seen = _edit(panel, row, monkeypatch)
    assert seen["combo"] == ["", "ssh1"]
    panel.deleteLater()


def test_m83_channel_combo_starts_unselected(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="",
               send_enabled=True, send="uname -r")
    seen = _edit(panel, row, monkeypatch)
    assert seen["combo"][0] == ""
    panel.deleteLater()


def test_m83_ok_is_refused_until_a_channel_is_chosen(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="",
               send_enabled=True, send="uname -r")
    warnings: list = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    _edit(panel, row, monkeypatch, result=QDialog.DialogCode.Accepted)
    assert warnings
    assert panel._get_row_cmd(row).channel == ""
    panel.deleteLater()


def test_m83_ok_stores_the_selected_key(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="ser1",
               send_enabled=True, send="uname -r")

    def pick(dlg):
        (combo,) = dlg.findChildren(QComboBox)
        combo.setCurrentIndex(combo.findData("ser2"))

    _edit(panel, row, monkeypatch, pick, QDialog.DialogCode.Accepted)
    assert panel._get_row_cmd(row).channel == "ser2"
    panel.deleteLater()


def test_m83_no_provider_hides_the_combo(qapp, monkeypatch):
    panel = _panel(channels=None)
    row = _add(panel, kind="send", name="Kernel", channel="",
               send_enabled=True, send="uname -r")
    seen = _edit(panel, row, monkeypatch)
    assert seen["combo"] == []
    panel.deleteLater()
