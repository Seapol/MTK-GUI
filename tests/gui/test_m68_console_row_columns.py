# -*- coding: utf-8 -*-
"""M68: Console channel-row column balance.

The serial-port combo used to eat the whole row slack (Expanding +
stretch 1) and the Configure/Remove glyph buttons were capped at 32px
while the global QSS padding alone is 32px - the labels never rendered.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QFontMetrics  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QSizePolicy,
)

from mtkgui.style import build_qss  # noqa: E402
from mtkgui.widgets.multi_console import ChannelRow  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    previous = app.styleSheet()
    # the padding that clipped the old 32px glyph buttons comes from the
    # global QSS - apply it so the size hints are realistic
    app.setStyleSheet(build_qss("Light"))
    app.processEvents()
    yield app
    app.setStyleSheet(previous)
    app.processEvents()


QSS_PADDING_H = 32          # global QPushButton padding: 7px 16px


def _row(kind="serial", params=None):
    params = params or {"port": "/dev/cu.test"}
    row = ChannelRow("dut", kind, "DUT", "#2f6fb3", params)
    row.show()
    QApplication.processEvents()
    return row


def test_configure_and_remove_are_text_buttons(qapp):
    row = _row()
    try:
        assert row.btn_config.text() == "Configure"
        assert row.btn_remove.text() == "Remove"
        # tooltips + signals unchanged
        assert row.btn_config.toolTip() == "Advanced parameters"
        assert row.btn_remove.toolTip() == "Remove this channel"
    finally:
        row.deleteLater()


def test_button_labels_fit_inside_the_button(qapp):
    row = _row()
    try:
        for button, text in ((row.btn_config, "Configure"),
                             (row.btn_remove, "Remove")):
            metrics = QFontMetrics(button.font())
            text_w = metrics.horizontalAdvance(text)
            # the QSS content area is the size hint minus the 32px padding
            assert button.sizeHint().width() >= text_w + QSS_PADDING_H, text
            assert button.minimumSizeHint().width() >= text_w, text
    finally:
        row.deleteLater()


def test_no_maximum_width_cap_on_the_text_buttons(qapp):
    row = _row()
    try:
        # QPushButton's default maximum width is the "unbounded" value
        assert row.btn_config.maximumWidth() > 32
        assert row.btn_remove.maximumWidth() > 32
    finally:
        row.deleteLater()


def test_serial_combo_is_bounded(qapp):
    row = _row()
    try:
        combo = row.combo_port
        assert combo.maximumWidth() == 280
        assert combo.minimumWidth() == 150
        # no Expanding policy: the combo keeps its compact width
        assert combo.sizePolicy().horizontalPolicy() != \
            QSizePolicy.Policy.Expanding
    finally:
        row.deleteLater()


def test_serial_row_stays_within_the_window_baseline(qapp):
    row = _row()
    try:
        hint = row.sizeHint().width()
        assert hint <= 1322
        # the old expanding combo let the row grow unbounded; the cap
        # keeps the size hint stable when the row is widened
        row.resize(1322, row.height() or 40)
        QApplication.processEvents()
        assert row.combo_port.width() <= 280
    finally:
        row.deleteLater()


def test_ssh_row_keeps_its_fields(qapp):
    row = _row("ssh", {"host": "192.168.1.10", "port": 22, "user": "root"})
    try:
        assert row.edit_host.maximumWidth() == 16777215   # untouched
        assert row.spin_port.maximumWidth() == 80
        assert row.edit_user.maximumWidth() == 120
        assert row.btn_config.text() == "Configure"
        assert row.btn_remove.text() == "Remove"
    finally:
        row.deleteLater()
