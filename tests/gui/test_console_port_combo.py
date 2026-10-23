# -*- coding: utf-8 -*-
"""M0/M10-FIX2 console port-dropdown width tests: the SER port combo
takes the row slack (no truncation), the popup still widens to the
longest item, SSH rows are untouched, selection is intact."""
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


def test_port_combo_takes_the_row_slack(ser_row, qapp):
    """M10-FIX2 F5: the device combo is no longer capped to half its
    hint - a long path (/dev/cu.BLTH - n/a) must render untruncated,
    so the combo takes the row slack while the baud box stays fixed."""
    from PySide6.QtWidgets import QSizePolicy
    combo = ser_row.combo_port
    assert combo.maximumWidth() == 16777215      # QWIDGETSIZE_MAX
    assert combo.minimumWidth() >= 180
    assert combo.sizePolicy().horizontalPolicy() \
        == QSizePolicy.Policy.Expanding
    assert ser_row.combo_baud.maximumWidth() == 100
    ser_row.resize(900, 40)
    ser_row.show()
    QApplication.processEvents()
    assert combo.width() > combo.minimumWidth()


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


def test_console_button_renamed_for_all_rows(ser_row, ssh_row):
    """P3-B1 closure: 'Show Console' renamed to 'Console' for every
    SER / SSH row; the click signal is unchanged."""
    for row in (ser_row, ssh_row):
        assert row.btn_console.text() == "Console"
        received = []
        row.show_console_requested.connect(received.append)
        row.btn_console.click()
        assert received == [row.key]
