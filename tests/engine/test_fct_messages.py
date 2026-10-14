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


def test_cases_to_console_commands_skips_ops_and_coarse_rows():
    """Only message rows and full-marker console rows map; coarse
    parameter-less page rows (ops, legacy SendtoConsole names) are
    skipped - guessing payloads from names is what destroyed the
    v1.0.3 draft's console parameters."""
    cases = [
        {"kind": "op", "name": "Init Instruments", "op_params": {}},
        {"kind": "SendtoConsole", "name": "SendtoConsole: COM1, 'reboot'"},
        {"kind": "WIFI", "name": "Wi-Fi scan"},
        {"kind": "MessageOK", "name": "FCT done.",
         "op_params": {"fct_step": {"name": "FCT done.",
                                    "step_type": "GUI_CONFIRM",
                                    "params": {"style": "ok",
                                               "message": "FCT done."}}}},
    ]
    cmds = cases_to_console_commands(cases)
    assert [c["kind"] for c in cmds] == ["message"]
    assert cmds[0]["name"] == "FCT done."
    assert cmds[0]["dialog_style"] == "ok"
    assert cmds[0]["send_enabled"] is False


def test_overlay_preserves_console_params_syncs_messages():
    """Reverse sync (user direction 2026-10-14, refined): the sync
    carries the step ORDER and the message rows only - the console
    Wait / Send / Capture parameters of the existing rows are NEVER
    rebuilt from the coarse page rows (the v1.0.3 draft lost every
    send payload / wait pattern that way)."""
    base = ("fct_test_config:\n"
            "  dut_type: linux\n"
            "  console:\n"
            "    enabled: true\n"
            "    test_commands:\n"
            "    - kind: send\n"
            "      name: Console login\n"
            "      send: root\n"
            "      wait_enabled: true\n"
            "      expect_pass: 'login:'\n"
            "      expect_pass_is_regex: false\n"
            "      timeout: 60.0\n"
            "    - kind: message\n"
            "      name: old message\n"
            "      dialog_style: ok\n"
            "  wifi:\n"
            "    enabled: true\n")
    cases = [
        {"kind": "MessageGoStop", "name": "Power on DUT",
         "op_params": {"fct_step": {"name": "Power on DUT",
                                    "step_type": "GUI_CONFIRM",
                                    "params": {"style": "gostop",
                                               "message": "Power on DUT",
                                               "send_yes": "y",
                                               "send_no": "n",
                                               "message_timeout_s": 4.0}}}},
        {"kind": "CapturefromConsole",
         "name": "Console login: 'done' (expected)",
         "op_params": {"fct_step": {
             "name": "Console login", "step_type": "MESSAGE_CHECK",
             "channel": "ser1",
             "params": {"kind": "send", "fct_console": True,
                        "wait_enabled": True, "send_enabled": True,
                        "capture_enabled": False,
                        "wait_pattern": "login:",
                        "wait_timeout": 60.0, "send_timeout": 4.0,
                        "capture_timeout": 60.0, "send": "root",
                        "capture_is_expected": False,
                        "case_sensitive": True}}}},
    ]
    import yaml as _yaml
    out = overlay_console_commands(base, cases)
    node = _yaml.safe_load(out)["fct_test_config"]
    cmds = node["console"]["test_commands"]
    # message row synced, console row kept VERBATIM (params intact)
    assert [c["name"] for c in cmds] == ["Power on DUT", "Console login"]
    gostop, login = cmds
    assert gostop["kind"] == "message" and gostop["dialog_style"] == "gostop"
    assert gostop["timeout"] == 4.0 and gostop["send"] == "y / n"
    assert login["kind"] == "send" and login["send"] == "root"
    assert login["wait_enabled"] is True
    assert login["expect_pass"] == "login:"
    assert login["timeout"] == 60.0
    assert node["wifi"]["enabled"] is True    # other sections preserved


def test_overlay_drops_removed_message_keeps_unshown_console_rows():
    """A message deleted on the page disappears (messages fully sync);
    a console command the page does not show survives (never dropped)."""
    base = ("fct_test_config:\n"
            "  console:\n"
            "    enabled: true\n"
            "    test_commands:\n"
            "    - kind: message\n"
            "      name: gone\n"
            "      dialog_style: ok\n"
            "    - kind: capture\n"
            "      name: fat.py summary\n"
            "      capture_enabled: true\n"
            "      expect_fail: 'Overall result:'\n"
            "      timeout: 420.0\n")
    import yaml as _yaml
    out = overlay_console_commands(base, [])   # page shows nothing
    cmds = _yaml.safe_load(out)["fct_test_config"]["console"]["test_commands"]
    assert [c["name"] for c in cmds] == ["fat.py summary"]
    assert cmds[0]["expect_fail"] == "Overall result:"
    assert cmds[0]["timeout"] == 420.0


def test_sync_round_trip_preserves_console_config():
    """Full round-trip: config -> FctSteps -> page cases -> overlay
    back onto the SAME config text -> every console command comes
    back byte-identical (wait+send pairs merge, SFTP/Host rows map)."""
    import yaml as _yaml
    from mtkgui.engine.fct_test_config import build_fct_steps, FctTestConfig
    from mtkgui.gui.yamlbuild.fct_build import FctSequence, \
        to_project_fct_cases
    base = ("fct_test_config:\n"
            "  dut_type: linux\n"
            "  console:\n"
            "    enabled: true\n"
            "    port: /dev/cu.usbmodemXXX\n"
            "    baudrate: 115200\n"
            "    ssh_host: 192.168.10.129\n"
            "    ssh_username: root\n"
            "    test_commands:\n"
            "    - kind: send\n"
            "      name: Console login\n"
            "      transport: serial\n"
            "      wait_enabled: true\n"
            "      send_enabled: true\n"
            "      capture_enabled: false\n"
            "      send: root\n"
            "      expect_pass: 'login:'\n"
            "      expect_pass_is_regex: false\n"
            "      timeout: 60.0\n"
            "      wait_timeout: 60.0\n"
            "      send_timeout: 4.0\n"
            "      retries: 1\n"
            "    - kind: capture\n"
            "      name: fat.py summary\n"
            "      transport: serial\n"
            "      wait_enabled: false\n"
            "      send_enabled: false\n"
            "      capture_enabled: true\n"
            "      expect_fail: 'Overall result:'\n"
            "      capture_is_expected: false\n"
            "      case_sensitive: true\n"
            "      parse_summary: true\n"
            "      timeout: 420.0\n"
            "      wait_timeout: 10.0\n"
            "      send_timeout: 4.0\n"
            "      retries: 0\n"
            "    - kind: sftp_get\n"
            "      name: Retrieve fat.log (SFTP)\n"
            "      transport: ssh\n"
            "      send_enabled: false\n"
            "      local: /tmp/fat.log\n"
            "      remote: /root/fat.log\n"
            "      timeout: 6.0\n"
            "      send_timeout: 20.0\n"
            "      retries: 0\n"
            "    - kind: host\n"
            "      name: Start iperf3 server (Host CLI)\n"
            "      send_enabled: true\n"
            "      host_cmd: iperf3 -s -D\n"
            "      host_cmd_windows: start /B iperf3 -s\n"
            "      timeout: 30.0\n"
            "      retries: 0\n"
            "  wifi:\n"
            "    enabled: false\n"
            "  bluetooth:\n"
            "    enabled: false\n"
            "  setup:\n"
            "    power_mode: none\n")
    cfg = FctTestConfig.from_dict(_yaml.safe_load(base)["fct_test_config"])
    steps = build_fct_steps(cfg)
    seq = FctSequence(name="FCT", steps=steps)
    cases = to_project_fct_cases(seq)
    out = overlay_console_commands(base, cases)
    got = _yaml.safe_load(out)["fct_test_config"]["console"]["test_commands"]
    want = _yaml.safe_load(base)["fct_test_config"]["console"]["test_commands"]
    assert [c["name"] for c in got] == [c["name"] for c in want]
    for g, w in zip(got, want):
        for key, value in w.items():
            assert g.get(key) == value, (key, g.get(key), value)


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
