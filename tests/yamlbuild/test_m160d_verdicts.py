# -*- coding: utf-8 -*-
"""M160d: dialog close-window and ExternalGui verdict semantics."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.runner import TestRunner  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeMc:
    def __init__(self):
        self.channels = {"ser1": {"kind": "serial", "connected": True,
                                  "worker": object()}}
        self.sent = []

    def write_to_channel(self, key, payload):
        self.sent.append((key, bytes(payload)))

    def channel_connected(self, key):
        return key in self.channels


class _Env:
    def __init__(self, answer="ok"):
        self.multi_console = _FakeMc()
        self.fct_rows = ["row"]
        self.fct_kinds = ["MessageYesNo"]
        self.fct_op_params = [None]
        self.fct_enables = [True]
        self.fct_timeouts = [1000]
        self.logs = []
        self.answer = answer
        self.dialogs = []

    def _log(self, line):
        self.logs.append(line)

    def _render_step(self, *args, **kwargs):
        pass

    def _fct_message_dialog(self, kind, name, timeout_s=0.0):
        self.dialogs.append(kind)
        return self.answer


def _marker(category, sub_type, name, params=None):
    return {"name": name, "category": category, "type": sub_type,
            "channel": "", "timeout_s": 0.0, "params": dict(params or {})}


def _run_b3(env, marker, answer):
    env.answer = answer
    runner = TestRunner(env)
    runner.state = "running"
    env.runner = runner
    stops = []
    runner.abort = lambda trigger="operator": stops.append(trigger)
    runner._exec_fct_b3(0, str(marker.get("name", "")), marker, 0.0, True)
    return runner, stops


def _close_active_modal():
    box = QApplication.activeModalWidget()
    if box is None:
        QTimer.singleShot(20, _close_active_modal)
    else:
        box.close()


def _close_answer(kind):
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    try:
        QTimer.singleShot(0, _close_active_modal)
        return page._fct_message_dialog(kind, "Step: message")
    finally:
        page.deleteLater()
        QApplication.processEvents()


def test_close_window_answers_by_message_style():
    assert _close_answer("MessageOK") == "ok"
    assert _close_answer("MessageYesNo") == "no"
    assert _close_answer("MessageGoStop") == "stop"


def test_close_window_gostop_fails_and_aborts():
    env = _Env(answer="stop")
    runner, stops = _run_b3(
        env, _marker("Message", "gostop_console", "Prompt",
                     {"console_dialog": True, "message": "Ready?",
                      "message_kind": "MessageGoStoptoConsole"}),
        "stop")
    assert runner._results[("fct", 0)] == "FAIL"
    assert stops == ["operator"]


def test_yesno_console_no_is_fail_not_continue():
    env = _Env()
    runner = TestRunner(env)
    stops = []
    runner.abort = lambda trigger="operator": stops.append(trigger)
    verdict = runner._fct_message_action(
        "MessageYesNotoConsole", "row", "no", {}, channel="ser1")
    assert verdict == "FAIL"
    assert stops == []                      # the run continues
    assert env.multi_console.sent == [("ser1", b"n\n")]


def test_external_gui_test_no_fails_and_aborts():
    env = _Env()
    runner, stops = _run_b3(
        env, _marker("ExternalGui", "test", "External test",
                     {"message": "Did the tool pass?"}), "no")
    assert env.dialogs == ["MessageYesNo"]
    assert runner._results[("fct", 0)] == "FAIL"
    assert stops == ["operator"]


def test_external_gui_flash_stop_fails_and_aborts():
    env = _Env()
    runner, stops = _run_b3(
        env, _marker("ExternalGui", "flash", "Flash FAT",
                     {"slot": "fat"}), "stop")
    assert env.dialogs == ["MessageGoStop"]
    assert runner._results[("fct", 0)] == "FAIL"
    assert stops == ["operator"]
