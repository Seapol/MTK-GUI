# -*- coding: utf-8 -*-
"""M83 C0: shared editor layout kit.

Width locked, wrapped hints, no horizontal scrollbar, content height.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QScrollArea,
)

from mtkgui.engine.fct_test_config import (  # noqa: E402
    STEP_TYPE_DELAY,
    STEP_TYPE_SERIAL_PUT,
)
from mtkgui.gui.yamlbuild import dialog_layout as dlayout  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    widget = FCTTestConfigPanel()
    widget.set_values({})
    yield widget
    widget.deleteLater()


def _open_dialog(panel, monkeypatch, label: str) -> QDialog:
    """Add one row, open its editor with ``exec`` stubbed, return it."""
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        return 0

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    row = panel.cmd_table.rowCount()
    panel._add_row_for_label(label)
    panel._edit_current_row(row)
    assert seen, "the editor dialog never opened"
    return seen[0]


def _scroll_areas(dlg) -> list:
    return dlg.findChildren(QScrollArea)


def _hint_labels(dlg) -> list:
    return [lab for lab in dlg.findChildren(QLabel) if lab.wordWrap()]


def test_m83_delay_dialog_width_is_locked(panel, monkeypatch):
    dlg = _open_dialog(panel, monkeypatch, STEP_TYPE_DELAY)
    assert dlg.windowTitle() == "Delay editor"
    assert dlg.minimumWidth() == dlg.maximumWidth() == dlayout.WIDTH_SIMPLE
    assert dlg.width() == dlayout.WIDTH_SIMPLE


def test_m83_delay_dialog_has_no_horizontal_scrollbar(panel, monkeypatch):
    dlg = _open_dialog(panel, monkeypatch, STEP_TYPE_DELAY)
    areas = _scroll_areas(dlg)
    assert areas, "the scroll-protected body is missing"
    for area in areas:
        assert area.horizontalScrollBarPolicy() \
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_m83_delay_hint_label_wraps_and_fits(panel, monkeypatch):
    dlg = _open_dialog(panel, monkeypatch, STEP_TYPE_DELAY)
    hints = _hint_labels(dlg)
    assert hints, "the delay hint label is not word wrapped"
    for label in hints:
        assert label.maximumWidth() <= dlayout.WIDTH_SIMPLE - 2 * 8
        assert label.wordWrap() is True


def test_m83_serial_transfer_dialog_width_is_locked(panel, monkeypatch):
    dlg = _open_dialog(panel, monkeypatch, STEP_TYPE_SERIAL_PUT)
    assert dlg.windowTitle() == "Serial Push / Pull editor"
    assert dlg.minimumWidth() == dlg.maximumWidth() == dlayout.WIDTH_WIDE


def test_m83_serial_transfer_hint_wraps_and_fits(panel, monkeypatch):
    dlg = _open_dialog(panel, monkeypatch, STEP_TYPE_SERIAL_PUT)
    hints = _hint_labels(dlg)
    assert hints, "the serial transfer hint is not word wrapped"
    for label in hints:
        assert label.maximumWidth() <= dlayout.WIDTH_WIDE - 2 * 8
        assert label.wordWrap() is True
    for area in _scroll_areas(dlg):
        assert area.horizontalScrollBarPolicy() \
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_m83_helper_rejects_resize_beyond_width(qapp):
    dlg = QDialog()
    dlayout.apply_fixed_width(dlg, dlayout.WIDTH_SIMPLE)
    dlg.resize(800, 300)
    assert dlg.width() == dlayout.WIDTH_SIMPLE
    assert dlg.minimumWidth() == dlg.maximumWidth()
    label = dlayout.hint("a long sentence " * 12, dlayout.WIDTH_SIMPLE)
    assert label.wordWrap() is True
    assert label.maximumWidth() == dlayout.WIDTH_SIMPLE \
        - 2 * dlayout.HINT_MARGIN
    dlg.deleteLater()
