# -*- coding: utf-8 -*-
"""Regression 2026-10-15: a timed-out FCT operator dialog must answer
``"timeout"``, never an operator answer.

Qt auto-detects the NoRole button as the escape button and reports it
via ``clickedButton()`` after a timer-driven ``close()`` - the Power on
DUT GoStop dialog therefore used to return "stop" on its 4 s auto
close, sent 'n' to the DUT and failed the run although nobody had
touched the dialog (user report 2026-10-15, Event Log: ``operator
GO / STOP -> FAIL (run stops)`` + ``human answer STOP``)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    yield w
    w.deleteLater()


def test_gostop_timeout_answers_timeout(page):
    """GoStop + auto-close -> 'timeout' (no send, step FAILs - but the
    run keeps its timeout semantics and nothing reaches the DUT)."""
    answer = page._fct_message_dialog(
        "MessageGoStop", "Power on DUT: Power on DUT", timeout_s=0.3)
    assert answer == "timeout"


def test_yesno_timeout_answers_timeout(page):
    """YesNo + auto-close -> 'timeout' (the NoRole 'No' button must not
    be reported as an operator answer either)."""
    answer = page._fct_message_dialog(
        "MessageYesNo", "Step: continue?", timeout_s=0.3)
    assert answer == "timeout"


def test_real_click_semantics_unchanged(page):
    """Without a timer the fix must not touch click handling: a scripted
    click on the STOP button still maps to 'stop' (the timeout flag only
    owns the auto-close path)."""
    from PySide6.QtCore import QTimer

    from PySide6.QtWidgets import QMessageBox

    box = QMessageBox(page)
    box.setModal(True)
    go = box.addButton("GO", QMessageBox.ButtonRole.YesRole)
    stop = box.addButton("STOP", QMessageBox.ButtonRole.NoRole)
    QTimer.singleShot(50, stop, stop.click)
    box.exec()
    assert box.clickedButton() is stop
    assert box.clickedButton() is not go
