# -*- coding: utf-8 -*-
"""M83 C3: per-row console channel + no silent channel fallback."""
from __future__ import annotations

from types import SimpleNamespace

from mtkgui.engine.fct_test_config import (
    FctTestConfig,
    build_fct_steps,
    channel_problems,
    ConsoleCommand,
)
from mtkgui.gui.yamlbuild.fct_build import FctStep
from mtkgui.engine.runner import TestRunner


def _cfg(**row) -> FctTestConfig:
    row.setdefault("kind", "send")
    row.setdefault("name", "Console step")
    return FctTestConfig.from_dict({
        "dut_type": "linux",
        "console": {"port": "COM1", "baudrate": 115200,
                    "test_commands": [dict(row)]},
    })


# --------------------------------------------------------------- build
def test_m83_empty_channel_is_build_error():
    cfg = _cfg(channel="")
    errors = cfg.validate()
    assert any("row 1 (Console step): console channel not selected — pick "
               "one, or open Config DUT Console to add a channel" in e
               for e in errors)


def test_m83_row_channel_is_emitted_and_read_back():
    cmd = ConsoleCommand(kind="send", name="Kernel check", channel="ser2",
                         send_enabled=True, send="uname -r")
    back = ConsoleCommand._from_dict_v2(dict(cmd.to_dict()))
    assert back.channel == "ser2"
    cfg = _cfg(channel="ser2", send="uname -r")
    step = build_fct_steps(cfg, include_fallback=False,
                           include_teardown=False)[0]
    assert step.channel == "ser2"
    assert FctStep.from_dict(step.to_dict()).channel == "ser2"


def test_m83_empty_channel_never_reaches_the_runner():
    cfg = _cfg(channel="")
    assert channel_problems(cfg.console.test_commands, None)
    assert cfg.validate()                    # the build gate refuses it
    step = build_fct_steps(cfg, include_fallback=False,
                           include_teardown=False)[0]
    assert step.channel == ""


def test_m83_post_rf_row_channel_is_honoured():
    cfg = FctTestConfig.from_dict({
        "dut_type": "linux",
        "console": {"port": "COM1", "baudrate": 115200,
                    "post_rf_commands": [
                        {"kind": "send", "name": "Clean up",
                         "channel": "ser3", "send_enabled": True,
                         "send": "rm -rf /tmp/x"}]},
    })
    assert cfg.validate() == []
    steps = build_fct_steps(cfg, include_fallback=False,
                            include_teardown=True)
    assert steps[-1].channel == "ser3"


def test_m83_sftp_row_carries_ssh1_not_ssh():
    cfg = _cfg(kind="sftp_put", name="Upload", transport="ssh",
               channel="ssh1", send_enabled=True, send_timeout=30.0,
               local="assets", remote="/root")
    assert cfg.validate() == []
    step = build_fct_steps(cfg, include_fallback=False,
                           include_teardown=False)[0]
    assert step.channel == "ssh1"
    assert step.params["kind"] == "sftp_put"


def test_m83_serial_row_on_ssh1_is_error():
    cfg = _cfg(channel="ssh1", send="uname -r")
    errors = cfg.validate(["ssh1"])
    assert any("is an SSH channel but the row is a serial console row" in e
               for e in errors)


def test_m83_unknown_channel_key_is_error():
    cfg = _cfg(channel="ser3", send="uname -r")
    errors = cfg.validate(["ser1", "ser2"])
    assert any("row 1 (Console step): console channel 'ser3' is not "
               "configured" in e for e in errors)


def test_m83_no_serial_channel_at_all_is_error_with_config_hint():
    cfg = _cfg(channel="ser1", send="uname -r")
    errors = cfg.validate(["ssh1"])
    assert any("no console serial channel is configured — click Config DUT "
               "Console to add one" in e for e in errors)


# -------------------------------------------------------------- runner
class _FakeMc:
    def __init__(self, keys):
        self.channels = {key: {"kind": "serial", "connected": True,
                               "worker": object()} for key in keys}
        self.buf = b""

    def get_read_buffer(self, _key):
        return self.buf

    def write_to_channel(self, _key, _payload):
        pass

    def channel_connected(self, key):
        return key in self.channels


class _Env:
    def __init__(self, mc):
        self.multi_console = mc
        self.fct_timeouts = [1000]
        self.fct_kinds = ["MESSAGE_CHECK"]
        self.logs: list = []

    def _log(self, line):
        self.logs.append(line)

    def _render_step(self, *args, **kwargs):
        pass


def test_m83_runner_reports_unbound_channel_without_fallback():
    env = _Env(_FakeMc(["ser1"]))
    runner = TestRunner(env)
    marker = {"name": "Console step", "step_type": "MESSAGE_CHECK",
              "channel": "ser2", "timeout_s": 1.0,
              "params": {"fct_console": True, "kind": "send",
                         "send_enabled": True, "send": "uname -r"}}
    runner._exec_fct_b3(0, "Console step", marker, 0.0, False)
    assert runner._results[("fct", 0)] == "Error"
    assert any("console channel 'ser2' is not open" in line
               for line in env.logs)
    # the first connected serial channel (ser1) was NOT used
    assert not any("ser1" in line for line in env.logs)


def test_m83_run_refuses_to_start_without_connected_serial():
    pytest = __import__("pytest")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from mtkgui.test_workflow_page import TestWorkFlowPage

    app = QApplication.instance() or QApplication([])   # noqa: F841
    page = TestWorkFlowPage()
    try:
        step = SimpleNamespace(op_params={"fct_step": {
            "name": "Console step", "channel": "ser1"}})
        page._runner._run_steps = [step]
        for key in list(page.multi_console.channels):
            page.multi_console.remove_channel(key)
        reason = page._console_precondition_error()
        assert reason == ("No console serial channel is connected — add or "
                          "connect one in the Console panel "
                          "(Config DUT Console).")
    finally:
        page.deleteLater()
