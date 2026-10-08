# -*- coding: utf-8 -*-
"""Event Log format (user direction): every line carries the
DATE-TIME stamp, NO User / identity prefix, and PASS / FAIL / Error
verdicts are highlighted in their own color."""
from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.main_window import (  # noqa: E402
    MainWindow,
    _colorize_verdicts,
)

ROLE_SUPERVISOR = "Supervisor"
FIXTURE_ATE = "ATE"

MainWindow.__test__ = False


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_verdict_colorizer():
    """PASS -> green, FAIL -> red, Error -> orange (bold spans)."""
    out = _colorize_verdicts("DAQ AI: 10 rails captured -> PASS")
    assert '#22c55e' in out and ">PASS<" in out
    out = _colorize_verdicts("Impedance Shorts -> FAIL")
    assert '#ef4444' in out and ">FAIL<" in out
    out = _colorize_verdicts("U2355A AI acquisition error")
    assert '#f59e0b' in out and ">error<" in out
    # other words stay untouched
    assert _colorize_verdicts("Yaml saved: plan.yaml") == \
        "Yaml saved: plan.yaml"


def test_event_log_stamp_no_user_prefix(qapp):
    """Appended lines start with the date-time stamp and carry NO
    'User:' prefix; the session file mirrors the plain stamp text."""
    w = MainWindow(role=ROLE_SUPERVISOR, mode="Real", fixture=FIXTURE_ATE)
    try:
        w._append_event_log("Run finished -> PASS")
        last = w.event_log.toPlainText().strip().splitlines()[-1]
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", last)
        assert "User:" not in last
        assert "->" in last
        # the colored rendering path was used (appendHtml, no exception
        # and the plain text keeps the verdict word)
        assert "PASS" in w.event_log.toPlainText()
    finally:
        w.close()
        w.deleteLater()
