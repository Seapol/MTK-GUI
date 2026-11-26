# -*- coding: utf-8 -*-
"""M159a: console Annotate toggle + the application capture buffer.

The console stays a pure log while Annotate is OFF.  While ON, a TX
selection becomes the step's command, RX selections become expected
pass / fail keywords, and Generate step drafts one FctStep into the
shared CaptureBuffer (never into the project YAML).
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.fct_build import (  # noqa: E402
    STEP_MESSAGE_CHECK,
    FctStep,
)
from mtkgui.gui.yamlbuild.fct_capture import CaptureBuffer  # noqa: E402
from mtkgui.widgets.console_widget import ConsoleWidget  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def console():
    widget = ConsoleWidget("dut", "DUT", "dut.log")
    yield widget
    widget.hide()
    widget.deleteLater()
    QApplication.processEvents()


def _select(console, needle):
    """Select the first occurrence of `needle` in the console view."""
    cursor = console.view.document().find(needle)
    assert not cursor.isNull(), f"{needle!r} not found in the console"
    console.view.setTextCursor(cursor)


def test_annotate_off_keeps_console_behaviour(console):
    console.append_rx("dut", b"login: root\n")
    console.append_message("TX", "uname -a", color="#ffcc00")
    # renderer untouched: both lines are in the log
    text = console.view.toPlainText()
    assert "login: root" in text
    assert "uname -a" in text
    # OFF by default: Generate step hidden/disabled, nothing annotatable
    assert console.btn_annotate.isChecked() is False
    assert console.btn_generate.isHidden() is True
    _select(console, "login:")
    assert console.annotate_selection("expect_pass") is False
    assert console.annotations() == []


def test_rx_selection_marks_expected_pass_and_fail(console):
    console.append_rx("dut", b"login: root\nBT_READY\n")
    console.btn_annotate.setChecked(True)
    _select(console, "login:")
    assert console.selection_kind() == "rx"
    assert console.annotate_selection("expect_pass") is True
    _select(console, "BT_READY")
    assert console.annotate_selection("expect_fail") is True
    assert [(a.text, a.kind) for a in console.annotations()] == [
        ("login:", "expect_pass"), ("BT_READY", "expect_fail")]
    assert all(a.channel == "dut" for a in console.annotations())


def test_tx_selection_is_a_command(console):
    console.append_message("TX", "uname -a", color="#ffcc00")
    console.btn_annotate.setChecked(True)
    _select(console, "uname -a")
    assert console.selection_kind() == "command"
    # a TX line can never become a keyword
    assert console.annotate_selection("expect_pass") is False
    assert console.annotate_selection("command") is True
    assert console.annotations()[0].kind == "command"


def test_generate_step_appends_to_the_buffer_only(console):
    console.append_rx("dut", b"login: root\n")
    console.append_message("TX", "uname -a", color="#ffcc00")
    console.btn_annotate.setChecked(True)
    _select(console, "uname -a")
    assert console.annotate_selection("command") is True
    _select(console, "login:")
    assert console.annotate_selection("expect_pass") is True

    buffer = CaptureBuffer()
    console.set_capture_buffer(buffer)
    assert console.btn_generate.isEnabled() is True
    console.btn_generate.click()

    steps = buffer.steps()
    assert len(steps) == 1 and buffer.is_empty() is False
    step = steps[0]
    assert isinstance(step, FctStep)
    assert step.step_type == STEP_MESSAGE_CHECK
    assert step.channel == "dut"
    assert step.command == "uname -a"
    assert step.expect_pass == ["login:"]
    assert step.expect_fail == []
    assert step.params["send_enabled"] is True
    # the console annotations were consumed; the buffer keeps its own copy
    assert console.annotations() == []
    assert len(buffer.annotations()) == 2
    # Generate step is the ONLY writer: the console itself has no model
    assert not hasattr(console, "model")
