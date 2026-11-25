# -*- coding: utf-8 -*-
"""M132: the Console window drops the Quick Commands row.

The `Quick:` dropdown plus `Save Cmd` / `Clear Cmd` did nothing useful:
the AT catalog and the Cmd Helper strip already cover the shortcuts.
Only the `Font...` picker stays, docked at the right end of the Send
row so the log area gains one full row of height.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.theme import THEMES  # noqa: E402
from mtkgui.widgets.console_widget import ConsoleWidget  # noqa: E402
from mtkgui.widgets.multi_console import AT_COMMANDS, ConsoleWindow  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window():
    console = ConsoleWidget("dut", "DUT", "dut.log")
    win = ConsoleWindow("dut", "DUT", "#2f6fb3", console,
                        THEMES["dark"], "#000000")
    yield win
    win.hide()
    win.deleteLater()
    QApplication.processEvents()


def test_no_quick_widgets_left(window):
    for attr in ("combo_quick", "btn_save_cmd", "btn_clear_cmd"):
        assert not hasattr(window, attr), attr


def test_quick_commands_signal_is_gone(window):
    for name in ("quick_commands_changed", "save_current_quick",
                 "clear_all_quick", "reload_quick_combo",
                 "_on_quick_picked"):
        assert not hasattr(window, name), name


def test_font_button_sits_in_the_send_row(window):
    assert window.btn_font.parentWidget() is window.send_panel
    layout = window.send_panel.layout()
    assert layout.indexOf(window.btn_font) >= 0


def test_send_line_completion_keeps_the_at_catalog(window):
    candidates = window.send_panel.edit._extra_candidates
    assert candidates == [cmd for _l, cmd, _d in AT_COMMANDS]
