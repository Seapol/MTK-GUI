# -*- coding: utf-8 -*-
"""The three operator-message presets (user direction 2026-10-14):
MessageOK / MessageYesNo / MessageGoStop - dialog presets, the
console answer semantics (y / n payloads, GoStop STOP stops the run)
and the reverse sync into the Build FCT dialog."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    ConsoleCommand,
    cases_to_console_commands,
    overlay_console_commands,
)
from mtkgui.engine.runner import TestRunner  # noqa: E402


# ------------------------------------------------------------- model
def test_consolecommand_send_payload_roundtrip():
    """send_yes / send_no survive the dict round-trip (YAML safe)."""
    cmd = ConsoleCommand(kind="message", dialog_style="yesno",
                         wait_enabled=False, send_enabled=True,
                         capture_enabled=False, timeout=4.0)
    data = cmd.to_dict()
    assert data["send_yes"] == "y" and data["send_no"] == "n"
    back = ConsoleCommand._from_dict_v2(data)
    assert back.send_yes == "y" and back.send_no == "n"
    assert back.dialog_style == "yesno" and back.timeout == 4.0


def test_cases_to_console_commands_message_rows():
    """Message rows round-trip losslessly: dialog style, answer
    payloads and the timeout (MessageOK = 0 = wait forever)."""
    cases = [
        {"kind": "MessageOK", "name": "MessageOK: Ready?",
         "op_params": {"fct_step": {"params": {
             "style": "ok", "send_yes": "y", "send_no": "n"}}}},
        {"kind": "MessageYesNo", "name": "MessageYesNo: LED ok?",
         "op_params": {"fct_step": {"params": {
             "style": "yesno", "send_yes": "y", "send_no": "n",
             "message_timeout_s": 4.0}}}},
    ]
    cmds = cases_to_console_commands(cases)
    assert [c["kind"] for c in cmds] == ["message", "message"]
    ok, yn = cmds
    assert ok["dialog_style"] == "ok" and ok["timeout"] == 0.0
    assert ok["send_enabled"] is False
    assert yn["dialog_style"] == "yesno" and yn["timeout"] == 4.0
    assert yn["send"] == "y / n" and yn["send_enabled"] is True


def test_cases_to_console_commands_skips_ops_and_maps_console():
    """Standard ops are skipped; legacy console rows map by kind with
    the payload parsed from the quoted name segment."""
    cases = [
        {"kind": "op", "name": "Init Instruments", "op_params": {}},
        {"kind": "SendtoConsole",
         "name": "SendtoConsole: COM1, 'reboot'"},
        {"kind": "WaitforConsole",
         "name": "WaitforConsole: COM1, 'Pass'"},
    ]
    cmds = cases_to_console_commands(cases)
    assert [c["kind"] for c in cmds] == ["send", "wait"]
    assert cmds[0]["send"] == "reboot"
    assert cmds[1]["expect_pass"] == "Pass"


def test_overlay_replaces_commands_keeps_other_sections():
    """overlay_console_commands swaps console.test_commands from the
    live page rows and preserves the Wi-Fi / setup sections."""
    base = ("fct_test_config:\n"
            "  dut_type: linux\n"
            "  console:\n"
            "    enabled: true\n"
            "    test_commands:\n"
            "    - kind: send\n"
            "      name: old\n"
            "  wifi:\n"
            "    enabled: true\n")
    cases = [{"kind": "MessageGoStop", "name": "MessageGoStop: Flash?",
              "op_params": {"fct_step": {"params": {
                  "style": "gostop", "send_yes": "y", "send_no": "n",
                  "message_timeout_s": 4.0}}}}]
    out = overlay_console_commands(base, cases)
    assert "MessageGoStop: Flash?" in out or "Flash?" in out
    assert "old" not in out
    assert "enabled: true" in out          # wifi section preserved


# ------------------------------------------------- dialog (Qt, offscreen)
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _panel():
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (
        FCTTestConfigPanel,
    )
    return FCTTestConfigPanel()


def test_add_message_ok_preset_all_off(qapp):
    panel = _panel()
    panel._add_message_row("ok")
    r = panel.cmd_table.rowCount() - 1
    cmd = panel._get_row_cmd(r)
    assert cmd.kind == "message" and cmd.dialog_style == "ok"
    assert cmd.timeout == 0.0 and cmd.retries == 0
    assert cmd.wait_enabled is False and cmd.capture_enabled is False
    assert cmd.send_enabled is False
    # visible columns: wait / send off, no timeout
    assert panel.cmd_table.item(r, 2).text() == "(off)"
    assert panel.cmd_table.item(r, 3).text() == "(off)"
    assert panel.cmd_table.item(r, 5).text() == "-"


def test_add_message_yesno_gostop_presets(qapp):
    panel = _panel()
    panel._add_message_row("yesno")
    panel._add_message_row("gostop")
    yn = panel._get_row_cmd(panel.cmd_table.rowCount() - 2)
    gs = panel._get_row_cmd(panel.cmd_table.rowCount() - 1)
    for cmd, style in ((yn, "yesno"), (gs, "gostop")):
        assert cmd.kind == "message" and cmd.dialog_style == style
        assert cmd.timeout == 4.0 and cmd.retries == 0
        assert cmd.wait_enabled is False and cmd.capture_enabled is False
        assert cmd.send_enabled is True
        assert cmd.send_yes == "y" and cmd.send_no == "n"
    r = panel.cmd_table.rowCount() - 2
    assert panel.cmd_table.item(r, 3).text() == "y / n"
    assert panel.cmd_table.item(r, 5).text() == "S:4s"


# --------------------------------------------------- runner semantics
class _RecordingConsole:
    """multi_console stand-in recording every write_to_channel."""

    def __init__(self):
        self.sent = []
        self.channels = {"VCOM0": {"kind": "serial", "worker": object()}}

    def channel_connected(self, key):
        return True

    def write_to_channel(self, key, payload):
        self.sent.append((key, bytes(payload)))


@pytest.fixture
def msg_env(env):
    """The headless engine env scripted for one message row: a
    recording console replaces the virtual one and the operator
    dialog answers from ``env._answers`` (timeout capture included)."""
    env.multi_console = _RecordingConsole()
    env._answers = []
    env.dialog_timeouts = []

    def _dialog(kind, name, timeout_s=0.0):
        env.dialog_timeouts.append(timeout_s)
        return env._answers.pop(0) if env._answers else "timeout"

    env._fct_message_dialog = _dialog
    return env


def _run_message(env, kind, op_params, abort_spy=None):
    env.fct_rows = ["MessageYesNo: Ready?"]
    env.fct_kinds = [kind]
    env.fct_op_params = [op_params]
    env.fct_enables = [True]
    runner = TestRunner(env)
    env.runner = runner
    if abort_spy is not None:
        # direct row execution parks in 'idle' (abort() no-ops outside
        # a running run) - spy on the abort trigger instead
        runner.abort = lambda trigger="operator": abort_spy.append(
            trigger)
    runner._exec_fct_row(0, interactive=True)
    return runner


def test_yesno_yes_sends_y_and_passes(msg_env):
    msg_env._answers = ["yes"]
    _run_message(msg_env, "MessageYesNo",
                 {"send_yes": "y", "send_no": "n",
                  "message_timeout_s": 4.0})
    assert msg_env.multi_console.sent == [("VCOM0", b"y\r\n")]
    assert msg_env.rows[("fct", 0)] == "PASS"


def test_yesno_no_sends_n_and_passes(msg_env):
    msg_env._answers = ["no"]
    _run_message(msg_env, "MessageYesNo", {"send_yes": "y",
                                           "send_no": "n"})
    assert msg_env.multi_console.sent == [("VCOM0", b"n\r\n")]
    assert msg_env.rows[("fct", 0)] == "PASS"


def test_yesno_timeout_fails_without_send(msg_env):
    msg_env._answers = ["timeout"]
    _run_message(msg_env, "MessageYesNo", {"message_timeout_s": 4.0})
    assert msg_env.multi_console.sent == []
    assert msg_env.rows[("fct", 0)] == "FAIL"


def test_message_timeout_reaches_the_dialog(msg_env):
    msg_env._answers = ["yes"]
    _run_message(msg_env, "MessageYesNo",
                 {"send_yes": "y", "send_no": "n",
                  "message_timeout_s": 4.0})
    assert msg_env.dialog_timeouts == [4.0]


def test_message_ok_does_no_console_action(msg_env):
    msg_env._answers = ["ok"]
    _run_message(msg_env, "MessageOK", {})
    assert msg_env.multi_console.sent == []
    assert msg_env.rows[("fct", 0)] == "PASS"


def test_gostop_go_sends_y_and_passes(msg_env):
    stops = []
    msg_env._answers = ["go"]
    _run_message(msg_env, "MessageGoStop",
                 {"send_yes": "y", "send_no": "n"}, abort_spy=stops)
    assert msg_env.multi_console.sent == [("VCOM0", b"y\r\n")]
    assert msg_env.rows[("fct", 0)] == "PASS"
    assert stops == []                     # the run continues


def test_gostop_stop_sends_n_fails_and_stops_run(msg_env):
    stops = []
    msg_env._answers = ["stop"]
    _run_message(msg_env, "MessageGoStop",
                 {"send_yes": "y", "send_no": "n"}, abort_spy=stops)
    assert msg_env.multi_console.sent == [("VCOM0", b"n\r\n")]
    assert msg_env.rows[("fct", 0)] == "FAIL"
    assert stops == ["operator"]           # the run stops (teardown runs)


def test_message_without_console_logs_honest_drop(msg_env):
    msg_env._answers = ["yes"]
    msg_env.multi_console = None
    _run_message(msg_env, "MessageYesNo", {})
    assert any("NOT sent" in line for line in msg_env._log_lines())
