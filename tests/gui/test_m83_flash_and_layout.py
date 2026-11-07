# -*- coding: utf-8 -*-
"""M83 C12: Flash_GUI read-only path + remaining editor layout."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QScrollArea,
)

from mtkgui.engine.fct_test_config import (  # noqa: E402
    STEP_TYPE_DELAY,
    STEP_TYPE_FLASH_GUI,
    STEP_TYPE_SERIAL_PUT,
)
from mtkgui.gui.yamlbuild import dialog_layout as dlayout  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)

EQUIPMENT = {"equipment": {"host": {"params": {
    "flash_tool": "C:/Tools/flash.exe"}}}}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _open(monkeypatch, label: str, equipment=EQUIPMENT) -> QDialog:
    panel = FCTTestConfigPanel(equipment_provider=lambda: equipment)
    panel.set_values({})
    panel._add_row_for_label(label)
    row = panel.cmd_table.rowCount() - 1
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(row)
    assert seen, "the editor never opened"
    seen[0]._test_panel = panel
    return seen[0]


def _labels(dlg) -> list:
    return [label.text() for label in dlg.findChildren(QLabel)]


def test_m83_flash_gui_path_is_read_only_from_equipment(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_FLASH_GUI)
    texts = _labels(dlg)
    assert any("C:/Tools/flash.exe" in text
               and "(Equipment ▸ HOST PC ▸ Flash Tool Path)" in text
               for text in texts)
    # the path is never an editable input
    assert not any("C:/Tools/flash.exe" in edit.text()
                   for edit in dlg.findChildren(QLineEdit))


def test_m83_flash_gui_missing_path_shows_warning(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_FLASH_GUI, equipment={})
    texts = _labels(dlg)
    assert any("Equipment has no Flash Tool Path configured" in text
               for text in texts)


def test_m83_flash_gui_dialog_has_no_console_send_controls(
        qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_FLASH_GUI)
    texts = _labels(dlg)
    assert not any("Send on Yes / GO:" in text for text in texts)
    assert not any("Send on No / STOP:" in text for text in texts)


def test_m83_flash_gui_placeholder_block_removed(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_FLASH_GUI)
    texts = _labels(dlg)
    assert not any("An empty GUI path fails the row." in text
                   for text in texts)
    assert dlg.minimumWidth() == dlg.maximumWidth() == dlayout.WIDTH_FORM
    for area in dlg.findChildren(QScrollArea):
        from PySide6.QtCore import Qt
        assert area.horizontalScrollBarPolicy() \
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_m83_serial_transfer_estimated_time_is_bottom_hint(
        qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_SERIAL_PUT)
    texts = _labels(dlg)
    assert not any("Estimated time (read-only):" in text for text in texts)
    hints = [label for label in dlg.findChildren(QLabel)
             if label.text().startswith("Estimated time:")
             and label.wordWrap()]
    assert hints, "the estimate is not a wrapped bottom hint"


def test_m83_serial_transfer_inputs_have_fixed_width(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_SERIAL_PUT)
    fixed = [edit for edit in dlg.findChildren(QLineEdit)
             if edit.minimumWidth() == edit.maximumWidth() == 480]
    assert len(fixed) >= 2


def test_m83_delay_hint_wraps_without_horizontal_scroll(qapp, monkeypatch):
    dlg = _open(monkeypatch, STEP_TYPE_DELAY)
    hints = [label for label in dlg.findChildren(QLabel)
             if label.wordWrap()]
    assert hints
    from PySide6.QtCore import Qt
    for area in dlg.findChildren(QScrollArea):
        assert area.horizontalScrollBarPolicy() \
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
