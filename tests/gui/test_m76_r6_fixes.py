# -*- coding: utf-8 -*-
"""M76 - R6 REAL-run fixes.

D1 Apply_Save keeps the authored step order (RF group at its row).
D2 MessageGoStop console answer is opt-in (send_console_answer).
D3 operator-authored Console: Login to the DUT row.
D4 send+capture rows judge only bytes received after the send.
D5 wait-only rows are bounded by wait_timeout.
D6 the Console panel renders one view per connected channel.
"""
from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6")

import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import mtkgui.engine.fct_exec as fe  # noqa: E402
from mtkgui.engine.fct_channels import (  # noqa: E402
    ConsoleBufferChannel,
    VirtualFctChannel,
)
from mtkgui.engine.fct_test_config import (  # noqa: E402
    KIND_CONSOLE_LOGIN,
    STEP_TYPE_CONSOLE_LOGIN,
    STEP_TYPE_DELAY,
    STEP_TYPE_SERIAL_PUT,
    STEP_TYPE_SFTP_GET,
    ConsoleCommand,
    FctTestConfig,
    build_fct_steps,
    console_command_for_label,
)
from mtkgui.engine.sequence import _fct_steps  # noqa: E402
from mtkgui.gui.add_menu import ADD_ENTRIES  # noqa: E402
from mtkgui.widgets.multi_console import MultiConsoleWidget  # noqa: E402
from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    widget = YamlBuildPage()
    yield widget
    widget.deleteLater()


def _emit(page, steps) -> list:
    params = {"fct_steps_yaml": yaml.safe_dump(
        {"fct": {"dut_type": "linux", "steps": steps}},
        sort_keys=False)}
    cases, errors = page._emit_fct_sequence(params)
    assert errors == [], errors
    return cases


class _FakeMc:
    """Multi-console stand-in: buffer + canned replies per written line."""

    def __init__(self, initial: str = "", replies=None):
        self.buf = initial.encode()
        self.replies = dict(replies or {})
        self.written: list = []
        self._acc = ""

    def get_read_buffer(self, key):
        return self.buf

    def write_to_channel(self, key, payload):
        # the console hardener writes character by character: replies
        # fire when the terminating newline of a full line arrives
        text = payload.decode("utf-8", "replace")
        self.written.append(text)
        self._acc += text
        if "\n" not in self._acc:
            return
        line, _sep, rest = self._acc.partition("\n")
        self._acc = rest
        tail = self.replies.get(line)
        if tail is not None:
            self.buf += str(tail).encode()


def _console_ctx(channels: dict):
    return fe.FctContext(channels=channels, log_sink=lambda line: None)


# ------------------------------------------------ D1 authored row order
_AUTHORED_STEPS = [
    {"type": "Delay", "name": "Delay - boot wait", "wait_ms": 800},
    {"type": "Operation", "name": "Wi-Fi: Connect DUT to AP",
     "op_kind": "op",
     "op_params": {"type": "op", "op": "Wi-Fi: Connect DUT to AP"}},
    {"type": "Console_serial", "name": "Console - kernel version",
     "override": {"port": "COM1"}, "send": "uname -r",
     "send_enabled": True, "wait_enabled": False,
     "capture_enabled": True, "capture_expected": "Linux",
     "timeout": 6.0},
    {"type": "Wifi_Ping", "name": "Wi-Fi Ping", "rf_subtest": "ping",
     "count": 4, "timeout_s": 5, "override": {"target": "10.0.0.1"}},
    {"type": "Serial: Push file to DUT", "name": "Serial - push assets",
     "local": "assets", "remote": "/root", "timeout": 600.0},
    {"type": "SSH SFTP: Pull file from DUT", "name": "SFTP - pull logs",
     "local": "/tmp", "remote": "/root/fat.log", "send_timeout": 30.0,
     "override": {"host": "10.0.0.2", "username": "root"}},
    {"type": "Console_serial", "name": "Console - clean up",
     "override": {"port": "COM1"}, "send": "rm -rf /tmp/x",
     "send_enabled": True, "wait_enabled": False,
     "capture_enabled": False, "timeout": 6.0},
]


def test_apply_keeps_the_authored_order_and_kinds(page):
    cases = _emit(page, _AUTHORED_STEPS)
    assert len(cases) == len(_AUTHORED_STEPS)
    names = [c["name"] for c in cases]
    # 1:1 positions: Delay / Operation / console / RF / serial / SFTP /
    # cleanup - the RF group must NOT move behind the cleanup row
    assert names[0] == "Delay - boot wait"
    assert names[1] == "Wi-Fi: Connect DUT to AP"
    assert names[2] == "Console - kernel version"
    assert names.index("Wi-Fi Ping (Host->AP / DUT->AP / DUT->Host)") \
        < names.index("Console - clean up")
    assert names.index("Wi-Fi Ping (Host->AP / DUT->AP / DUT->Host)") \
        < names.index("Serial - push assets")
    assert names.index("Serial - push assets") \
        < names.index("SFTP - pull logs")
    assert names[-1] == "Console - clean up"
    # kind downgrades are gone
    kinds = [c["kind"] for c in cases]
    idx_delay = names.index("Delay - boot wait")
    assert kinds[idx_delay] == STEP_TYPE_DELAY
    assert kinds[names.index("Serial - push assets")] \
        == STEP_TYPE_SERIAL_PUT
    assert kinds[names.index("SFTP - pull logs")] == STEP_TYPE_SFTP_GET


def test_apply_is_stable_and_engine_order_matches(page):
    cases = _emit(page, _AUTHORED_STEPS)
    twice = _emit(page, _AUTHORED_STEPS)
    assert [(c["name"], c["kind"]) for c in cases] \
        == [(c["name"], c["kind"]) for c in twice]
    # the engine executes exactly this generated region, in order
    executed = [s.name for s in _fct_steps(
        {"test_workflow": {"fct_test_cases": cases}}, "FCT")]
    assert executed == [c["name"] for c in cases]


# --------------------------------------------- D3 operator-authored login
def test_console_login_is_selectable_in_the_add_menu():
    labels = [entry.label for entry in ADD_ENTRIES]
    assert STEP_TYPE_CONSOLE_LOGIN in labels


def test_console_login_defaults_and_dict_round_trip():
    cmd = console_command_for_label(STEP_TYPE_CONSOLE_LOGIN, "Login")
    assert cmd.kind == KIND_CONSOLE_LOGIN
    assert cmd.login_prompt == "login:" and cmd.login_user == "root"
    assert cmd.shell_prompt == "#"
    cmd.login_user = "root"
    cmd.login_password = "secret"
    cmd.shell_prompt = "root@imx93frdm:~#"
    cmd.timeout = 45.0
    data = cmd.to_dict()
    back = ConsoleCommand._from_dict_v2(dict(data))
    assert back.kind == KIND_CONSOLE_LOGIN
    assert back.login_prompt == "login:"
    assert back.login_user == "root"
    assert back.login_password == "secret"
    assert back.shell_prompt == "root@imx93frdm:~#"
    assert back.timeout == 45.0


def test_console_login_survives_the_yaml_apply(page):
    """The login row travels through fct_steps_yaml -> generated cases
    with every parameter intact (the marker carries the step)."""
    steps = [{"type": STEP_TYPE_CONSOLE_LOGIN, "name": "Login to the DUT",
              "override": {"port": "COM4"}, "login_prompt": "login:",
              "login_user": "root", "login_password": "pw",
              "shell_prompt": "#", "timeout": 45}]
    cases = _emit(page, steps)
    assert len(cases) == 1
    marker = cases[0]["op_params"]["fct_step"]
    login = marker["params"]["fct_console_login"]
    assert login["login_prompt"] == "login:"
    assert login["user"] == "root"
    assert login["password"] == "pw"
    assert login["shell_prompt"] == "#"


def test_console_login_step_executes_the_sequence():
    mc = _FakeMc("imx93frdm login: ", replies={
        "root": "Password: ",
        "": "root@imx93frdm:~# ",
    })
    channel = ConsoleBufferChannel(mc, "ser1")
    step = fe.FctStep(
        name="Console: Login to the DUT", step_type="MESSAGE_CHECK",
        channel="ser1", timeout_s=5.0,
        params={"fct_console": True, "kind": "login",
                "fct_console_login": {
                    "login_prompt": "login:", "user": "root",
                    "password": "", "shell_prompt": "#",
                    "password_prompt": "pass", "timeout_s": 3.0}})
    outcome = fe.execute_fct_step(step, _console_ctx({"ser1": channel}))
    assert outcome.verdict == fe.VERDICT_PASS, outcome.reason
    assert "root\n" in mc.written and "\n" in mc.written


def test_console_login_fails_without_the_shell_prompt():
    mc = _FakeMc("imx93frdm login: ", replies={
        "root": "Password: ", "": ""})
    channel = ConsoleBufferChannel(mc, "ser1")
    step = fe.FctStep(
        name="Console: Login to the DUT", step_type="MESSAGE_CHECK",
        channel="ser1", timeout_s=0.6,
        params={"fct_console": True, "kind": "login",
                "fct_console_login": {
                    "login_prompt": "login:", "user": "root",
                    "password": "", "shell_prompt": "#",
                    "password_prompt": "pass", "timeout_s": 0.4}})
    outcome = fe.execute_fct_step(step, _console_ctx({"ser1": channel}))
    assert outcome.verdict == fe.VERDICT_FAIL


# ------------------------------------------- D4 capture offset per send
def test_send_capture_ignores_the_pre_run_boot_log():
    mc = _FakeMc("Linux version 6.6.36\r\n", replies={
        "uname -r": "6.6.36\r\n"})
    channel = ConsoleBufferChannel(mc, "ser1")
    step = fe.FctStep(
        name="Console - kernel version", step_type="MESSAGE_CHECK",
        channel="ser1", timeout_s=0.8,
        params={"fct_console": True, "kind": "send",
                "send_enabled": True, "send": "uname -r",
                "expect_pass_re": "Linux", "capture_is_expected": True,
                "case_sensitive": True})
    outcome = fe.execute_fct_step(step, _console_ctx({"ser1": channel}))
    assert outcome.verdict == fe.VERDICT_FAIL, outcome.reason
    assert "uname -r" in "".join(mc.written)


def test_wait_only_row_still_matches_the_existing_buffer():
    channel = VirtualFctChannel()
    channel.inject_output("imx93frdm login:")
    step = fe.FctStep(
        name="Console - wait for login", step_type="MESSAGE_CHECK",
        channel="ser1", timeout_s=0.8,
        params={"fct_console": True, "kind": "wait",
                "expect_pass_re": "login:", "capture_is_expected": True})
    outcome = fe.execute_fct_step(step, _console_ctx({"ser1": channel}))
    assert outcome.verdict == fe.VERDICT_PASS


# --------------------------------------------- D5 wait_timeout governs
def test_wait_only_row_uses_wait_timeout():
    cmd = console_command_for_label("Console_serial", "wait login")
    cmd.kind = "wait"
    cmd.wait_enabled = True
    cmd.send_enabled = False
    cmd.expect_pass = "login:"
    cmd.wait_timeout = 30.0
    cmd.timeout = 6.0
    cfg = FctTestConfig(dut_type="linux")
    cfg.console.port = "COM1"
    cfg.console.test_commands = [cmd]
    steps = build_fct_steps(cfg)
    assert len(steps) == 1
    assert steps[0].timeout_s == 30.0


def test_wait_only_row_is_running_at_10s():
    """Acceptance D5: wait_timeout=30 keeps the row RUNNING at 10 s.

    M78-3: the 8 s stall watchdog would fail a silent row first, so this
    M76 acceptance disables it explicitly (``stall_s: 0``) - the
    watchdog has its own M78 test."""
    channel = VirtualFctChannel()
    step = fe.FctStep(
        name="Console - wait for login", step_type="MESSAGE_CHECK",
        channel="ser1", timeout_s=30.0,
        params={"fct_console": True, "kind": "wait", "stall_s": 0.0,
                "expect_pass_re": "login:", "capture_is_expected": True})
    result: list = []
    worker = threading.Thread(
        target=lambda: result.append(
            fe.execute_fct_step(step, _console_ctx({"ser1": channel}))))
    worker.start()
    time.sleep(10.0)
    assert worker.is_alive(), "row stopped before wait_timeout"
    channel.inject_output("imx93frdm login:")
    worker.join(5.0)
    assert result and result[0].verdict == fe.VERDICT_PASS


# ---------------------------------------------------- D6 console panel
class _FakeWorker:
    def __init__(self):
        self.written: list = []
        self.stops = 0
        self._running = True

    def isRunning(self):
        return self._running

    def write(self, payload):
        self.written.append(payload)
        return len(payload)

    def stop(self):
        self.stops += 1
        self._running = False

    def wait(self, _ms=0):
        return True


def test_console_panel_shows_the_connected_channel(qapp):
    widget = MultiConsoleWidget()
    try:
        channel = widget.channels["ser1"]
        assert channel["inline"] is not None
        assert channel["inline"].isHidden()
        widget.on_connection_changed("ser1", True)
        assert not channel["inline"].isHidden()
        widget.on_connection_changed("ser1", False)
        assert channel["inline"].isHidden()
        assert widget.scroll.minimumHeight() >= 120
    finally:
        widget.deleteLater()


def test_console_panel_input_sends_and_logs(qapp):
    widget = MultiConsoleWidget()
    worker = _FakeWorker()
    logs: list = []
    widget.console_log.connect(logs.append)
    try:
        widget.channels["ser1"]["worker"] = worker
        widget.on_connection_changed("ser1", True)
        inline = widget.channels["ser1"]["inline"]
        inline.edit.setText("ls -l")
        inline.edit.returnPressed.emit()
        assert worker.written == [b"ls -l\r\n"]
        assert "console send: 'ls -l'" in inline.view.toPlainText()
        assert logs == ["console send: 'ls -l'"]
    finally:
        widget.deleteLater()


def test_console_remove_closes_the_worker_and_frees_the_port(qapp):
    widget = MultiConsoleWidget()
    worker = _FakeWorker()
    try:
        widget.channels["ser1"]["worker"] = worker
        widget.remove_channel("ser1")
        assert worker.stops == 1
        assert "ser1" not in widget.channels
    finally:
        widget.deleteLater()
