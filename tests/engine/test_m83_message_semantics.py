# -*- coding: utf-8 -*-
"""M83 C8: six Message kinds - one dialog, greyed console block,
YesNo / GoStop semantics, row-channel sends."""
from __future__ import annotations

import pytest

from mtkgui.engine.fct_test_config import (
    ConsoleCommand,
    DEFAULT_MESSAGE_SEND_OK,
)
from mtkgui.engine.runner import TestRunner
from mtkgui.engine.yaml_validation import (
    LEGACY_PLAIN_PAYLOAD_MSG,
    LEGACY_SEND_CONSOLE_ANSWER_MSG,
    SEVERITY_WARNING,
    validate_project_yaml,
)


class _FakeMc:
    def __init__(self, keys=("ser1",)):
        self.channels = {key: {"kind": "serial", "connected": True,
                               "worker": object()} for key in keys}
        self.sent: list = []
        self.buf = b""

    def get_read_buffer(self, _key):
        return self.buf

    def write_to_channel(self, key, payload):
        self.sent.append((key, bytes(payload)))

    def channel_connected(self, key):
        return key in self.channels


class _Env:
    def __init__(self, mc=None):
        self.multi_console = mc or _FakeMc()
        self.fct_timeouts = [1000]
        self.fct_kinds: list = []
        self.fct_rows: list = []
        self.logs: list = []

    def _log(self, line):
        self.logs.append(line)

    def _render_step(self, *args, **kwargs):
        pass


def _runner(env=None):
    env = env or _Env()
    runner = TestRunner(env)
    return runner


def _action(runner, kind, answer, cfg=None, channel="ser1"):
    return runner._fct_message_action(kind, "row", answer, cfg or {},
                                     channel=channel)


# ------------------------------------------------- path one semantics
def test_m83_yesno_no_fails_but_run_continues():
    runner = _runner()
    stops: list = []
    runner.abort = lambda trigger="operator": stops.append(trigger)
    assert _action(runner, "MessageYesNo", "no") == "FAIL"
    assert stops == []                    # the run continues
    assert runner.env.multi_console.sent == []


def test_m83_yesno_yes_passes():
    runner = _runner()
    assert _action(runner, "MessageYesNo", "yes") == "PASS"


def test_m83_yesno_timeout_fails_without_stop():
    runner = _runner()
    stops: list = []
    runner.abort = lambda trigger="operator": stops.append(trigger)
    assert _action(runner, "MessageYesNo", "timeout") == "FAIL"
    assert stops == []


def test_m83_gostop_stop_fails_and_stops():
    runner = _runner()
    stops: list = []
    runner.abort = lambda trigger="operator": stops.append(trigger)
    assert _action(runner, "MessageGoStop", "stop") == "FAIL"
    assert stops == ["operator"]


def test_m83_plain_kind_never_writes_console_path_one():
    runner = _runner()
    for kind, answer in (("MessageOK", "ok"), ("MessageYesNo", "yes"),
                         ("MessageYesNo", "no"), ("MessageGoStop", "go")):
        _action(runner, kind, answer, {"send_yes": "y", "send_no": "n",
                                       "send_ok": "ok"})
    assert runner.env.multi_console.sent == []


# ------------------------------------------------- path two (fct_b3)
def _b3(env, marker, answer):
    runner = TestRunner(env)
    runner.state = "running"
    env.runner = runner
    env._fct_message_dialog = lambda kind, name, timeout_s=0.0: answer
    runner._exec_fct_b3(0, str(marker.get("name")), marker, 0.0, True)
    return runner


def _dialog_marker(kind, channel="ser1", send_ok=None):
    params = {"style": "yesno", "console_dialog": True,
              "message": "Ready?", "message_kind": kind,
              "send_yes": "y", "send_no": "n", "message_timeout_s": 4.0}
    if send_ok is not None:
        params["send_ok"] = send_ok
    return {"name": "Ready?", "step_type": "GUI_CONFIRM",
            "channel": channel, "timeout_s": 5.0, "params": params}


def test_m83_plain_kind_never_writes_console_path_two():
    env = _Env()
    _b3(env, _dialog_marker("MessageYesNo"), "yes")
    assert env.multi_console.sent == []


def test_m83_toconsole_kind_writes_yes_and_no():
    env = _Env()
    _b3(env, _dialog_marker("MessageYesNotoConsole"), "yes")
    assert env.multi_console.sent == [("ser1", b"y\n")]
    env = _Env()
    runner = _b3(env, _dialog_marker("MessageYesNotoConsole"), "no")
    assert env.multi_console.sent == [("ser1", b"n\n")]
    assert runner._results[("fct", 0)] == "FAIL"


def test_m83_send_console_answer_absent_from_model():
    cmd = ConsoleCommand(kind="message", dialog_style="yesno")
    assert not hasattr(cmd, "send_console_answer")
    assert "send_console_answer" not in cmd.to_dict()
    # a legacy dict loads without the removed field and re-serialises
    # without it
    loaded = ConsoleCommand._from_dict_v2(
        {"kind": "message", "dialog_style": "yesno",
         "wait_enabled": False, "send_console_answer": True})
    assert not hasattr(loaded, "send_console_answer")
    assert "send_console_answer" not in loaded.to_dict()


def _doc_with_row(params: dict, kind: str = "MessageYesNo") -> dict:
    return {
        "test_workflow": {
            "overall_flow": [{"stage": "FCT", "enable": True}],
            "fct_test_cases": [{
                "name": "Ready?", "kind": kind,
                "op_params": {"fct_step": {
                    "name": "Ready?", "step_type": "GUI_CONFIRM",
                    "channel": "ser1", "timeout_s": 5.0,
                    "params": {"style": "yesno", "console_dialog": True,
                               **params}}}}],
        },
    }


def _warnings(doc: dict) -> list:
    return [issue for issue in validate_project_yaml(doc)
            if issue.severity == SEVERITY_WARNING]


def test_m83_legacy_send_console_answer_warns():
    warnings = _warnings(_doc_with_row({"send_console_answer": True}))
    assert any(issue.message == LEGACY_SEND_CONSOLE_ANSWER_MSG
               for issue in warnings)


def test_m83_legacy_send_payload_on_plain_row_warns():
    warnings = _warnings(_doc_with_row({"send_yes": "y", "send_no": "n"}))
    assert any(LEGACY_PLAIN_PAYLOAD_MSG in issue.message
               for issue in warnings)
    # exactly ONE line per row, even when both keys are present
    assert sum(LEGACY_PLAIN_PAYLOAD_MSG in issue.message
               for issue in warnings) == 1


def test_m83_oktoconsole_sends_default_ok():
    env = _Env()
    _b3(env, _dialog_marker("MessageOKtoConsole"), "ok")
    assert env.multi_console.sent == [
        ("ser1", (DEFAULT_MESSAGE_SEND_OK + "\n").encode("utf-8"))]


def test_m83_oktoconsole_send_ok_is_configurable():
    env = _Env()
    _b3(env, _dialog_marker("MessageOKtoConsole", send_ok="done"), "ok")
    assert env.multi_console.sent == [("ser1", b"done\n")]


def test_m83_oktoconsole_empty_payload_sends_nothing():
    env = _Env()
    _b3(env, _dialog_marker("MessageOKtoConsole", send_ok=""), "ok")
    assert env.multi_console.sent == []
    assert any("send payload is empty" in line for line in env.logs)


def test_m83_message_send_uses_row_channel():
    env = _Env(_FakeMc(("ser1", "ser2")))
    _b3(env, _dialog_marker("MessageYesNotoConsole", channel="ser2"), "yes")
    assert env.multi_console.sent == [("ser2", b"y\n")]
    # a row whose channel is not open is an ERROR up front (C3) - it
    # never downgrades to another port
    env = _Env(_FakeMc(("ser1",)))
    runner = _b3(env, _dialog_marker("MessageYesNotoConsole",
                                     channel="ser9"), "yes")
    assert env.multi_console.sent == []
    assert runner._results[("fct", 0)] == "Error"
    assert any("console channel 'ser9' is not open" in line
               for line in env.logs)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
