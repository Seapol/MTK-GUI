# -*- coding: utf-8 -*-
"""M0 console port-dropdown width tests: compact collapsed width for
SER rows, full-width popup, SSH row untouched, selection intact."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit  # noqa: E402

from mtkgui.widgets.multi_console import (  # noqa: E402
    _CompactPortCombo,
    ChannelRow,
)

SERIAL_PARAMS = {"port": "COM7", "baudrate": 115200}
SSH_PARAMS = {"host": "192.168.1.10", "port": 22, "username": "root"}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ser_row(qapp):
    row = ChannelRow("k1", "serial", "SER1", "#c00", dict(SERIAL_PARAMS))
    yield row
    row.deleteLater()


@pytest.fixture()
def ssh_row(qapp):
    row = ChannelRow("k2", "ssh", "SSH1", "#060", dict(SSH_PARAMS))
    yield row
    row.deleteLater()


def test_serial_combo_is_compact_type(ser_row):
    assert isinstance(ser_row.combo_port, _CompactPortCombo)
    assert isinstance(ser_row.combo_port, QComboBox)
    assert ser_row.combo_port.isEditable()      # manual entry preserved


def test_collapsed_width_halved(ser_row, qapp):
    """Collapsed width == 50% of the natural (uncapped) size hint that
    the same items would produce."""
    reference = QComboBox()               # natural size, no cap
    reference.setEditable(True)           # same shape as the real combo
    reference.addItems([ser_row.combo_port.itemText(i)
                        for i in range(ser_row.combo_port.count())])
    natural = reference.sizeHint().width()
    expected = max(90, natural // 2)
    assert ser_row.combo_port.maximumWidth() == expected
    if natural > 90:
        # the 50% rule really bites when the natural width is large
        # (long COM descriptions): collapsed <= 50% + floor
        assert ser_row.combo_port.maximumWidth() <= natural // 2 + 90


def test_popup_expands_to_longest_item(ser_row, qapp):
    """The popup container widens past the collapsed widget so long
    port names show completely (no truncation)."""
    combo = ser_row.combo_port
    combo.resize(100, combo.sizeHint().height())
    combo.showPopup()
    QApplication.processEvents()
    try:
        container = combo.view().parentWidget()
        assert container.minimumWidth() >= combo.width()
        longest = max(combo.view().sizeHint().width() + 24,
                      combo.width())
        assert container.minimumWidth() >= longest
    finally:
        combo.hidePopup()


def test_port_selection_logic_unchanged(ser_row):
    """Enumeration / selection behavior identical (layout-only rule):
    currentData wins when the text matches an item, raw text passes
    through for manual entry."""
    combo = ser_row.combo_port
    if combo.count():
        combo.setCurrentIndex(0)
        params = ser_row.get_inline_params()
        assert params["port"] == combo.currentData() \
            or params["port"] == combo.currentText().strip()
    combo.setCurrentIndex(-1)             # detach from any item
    combo.setEditText("COM99")            # manual entry still works
    assert ser_row.get_inline_params()["port"] == "COM99"


def test_ssh_row_widths_unchanged(ssh_row):
    """SSH rows keep their original input widths (no compact rule)."""
    assert not hasattr(ssh_row, "combo_port")
    assert ssh_row.spin_port.maximumWidth() == 80
    assert ssh_row.edit_user.maximumWidth() == 120
    assert ssh_row.edit_host.maximumWidth() == 16777215   # QWIDGETSIZE_MAX
    assert isinstance(ssh_row.edit_host, QLineEdit)
