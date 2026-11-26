# -*- coding: utf-8 -*-
"""M159e: MessageYesNoToconsole is a segment boundary.

A tagged (or auto-detected) Yes / No prompt ends the preceding listen
segment, emits a GUI_CONFIRM step, and the RX that follows starts a new
listen segment - the surrounding RX is never swallowed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.fct_authoring import (  # noqa: E402
    annotations_to_steps,
    detect_yesno_points,
)
from mtkgui.gui.yamlbuild.fct_build import (  # noqa: E402
    STEP_GUI_CONFIRM,
    STEP_MESSAGE_CHECK,
    FctSequence,
    to_project_fct_cases,
)
from mtkgui.gui.yamlbuild.fct_capture import (  # noqa: E402
    ANNOTATION_EXPECT_PASS,
    ANNOTATION_INTERACTION,
    CaptureAnnotation,
    CaptureBuffer,
)
from mtkgui.widgets.console_widget import ConsoleWidget  # noqa: E402


def _ann(text, kind, position=-1):
    return CaptureAnnotation(text=text, kind=kind, channel="dut",
                             position=position)


def _select(console, needle):
    cursor = console.view.document().find(needle)
    assert not cursor.isNull(), f"{needle!r} not found in the console"
    console.view.setTextCursor(cursor)


def test_tagged_yesno_splits_two_listen_segments():
    annotations = [
        _ann("READY", ANNOTATION_EXPECT_PASS, 10),
        _ann("[y/n]", ANNOTATION_INTERACTION, 20),
        _ann("AFTER", ANNOTATION_EXPECT_PASS, 30),
    ]
    steps = annotations_to_steps(annotations, "dut")
    assert [step.step_type for step in steps] == [
        STEP_MESSAGE_CHECK, STEP_GUI_CONFIRM, STEP_MESSAGE_CHECK]
    assert steps[0].expect_pass == ["READY"]
    assert steps[2].expect_pass == ["AFTER"]
    assert steps[1].params["style"] == "yesno"
    assert steps[1].params["console_dialog"] is True
    assert "[y/n]" in steps[1].params["message"]
    # full chain: the published row is the Console-domain Yes / No dialog
    sequence = FctSequence(name="FCT", steps=steps)
    assert sequence.validate() == []
    assert [case["kind"] for case in to_project_fct_cases(sequence)] == [
        "CapturefromConsole", "MessageYesNotoConsole",
        "CapturefromConsole"]


def test_auto_detection_keeps_the_surrounding_rx():
    assert detect_yesno_points("Continue? [y/n] or (Y/N)") == \
        ["[y/n]", "(Y/N)"]
    console = ConsoleWidget("dut", "DUT", "dut.log")
    try:
        console.btn_annotate.setChecked(True)
        console.append_rx("dut", b"BEFORE\nContinue? [y/n]\nAFTER\n")
        text = console.view.toPlainText()
        assert "BEFORE" in text
        assert "Continue? [y/n]" in text
        assert "AFTER" in text
        detected = [a for a in console.annotations()
                    if a.kind == ANNOTATION_INTERACTION]
        assert [a.text for a in detected] == ["[y/n]"]
        _select(console, "BEFORE")
        assert console.annotate_selection(ANNOTATION_EXPECT_PASS) is True
        _select(console, "AFTER")
        assert console.annotate_selection(ANNOTATION_EXPECT_PASS) is True

        buffer = CaptureBuffer()
        console.set_capture_buffer(buffer)
        console.btn_generate.click()
        steps = buffer.steps()
        # log order wins: BEFORE -> confirm -> AFTER
        assert [step.step_type for step in steps] == [
            STEP_MESSAGE_CHECK, STEP_GUI_CONFIRM, STEP_MESSAGE_CHECK]
        assert steps[0].expect_pass == ["BEFORE"]
        assert steps[2].expect_pass == ["AFTER"]
    finally:
        console.hide()
        console.deleteLater()
        QApplication.processEvents()
