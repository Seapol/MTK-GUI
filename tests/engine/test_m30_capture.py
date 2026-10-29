# -*- coding: utf-8 -*-
"""m30 unified Capture verification (engine layer).

The Sequence-tab merge introduces ONE Capture rule for every step type:
Expected must be found, Unexpected must NOT be found, both may be set.
These tests cover the pure ``judge_capture`` function and its wiring in
the Console_serial and Console_cli paths (mock channel / host runner).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mtkgui.engine.fct_test_config import ConsoleCommand, FctTestConfig
from mtkgui.engine.fct_test_runner import FctTestRunner, judge_capture


def _runner(commands) -> FctTestRunner:
    cfg = FctTestConfig.from_dict({"console": {"enabled": True}})
    cfg.console.test_commands = commands
    return FctTestRunner(cfg)


class FakeSerial:
    """Scripted pyserial-like: reply appended when the command is sent."""

    def __init__(self, script):
        self.script = script
        self.sent: list = []
        self.buffer = b""

    def reset_input_buffer(self):
        self.buffer = b""

    def write(self, data: bytes):
        cmd = data.decode().strip()
        self.sent.append(cmd)
        reply = self.script.get(cmd, "")
        self.buffer += reply if isinstance(reply, bytes) else reply.encode()
        return len(data)

    def read(self, n):
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data


class _HostResult:
    def __init__(self, exit_code, lines, reason=""):
        self.exit_code = exit_code
        self.lines = lines
        self.reason = reason


class _HostRunner:
    def __init__(self, lines, exit_code=0, reason=""):
        self._lines = lines
        self._rc = exit_code
        self._reason = reason

    def run(self, line):
        return _HostResult(self._rc, self._lines, self._reason)


# ------------------------------------------------------------------ pure fn
def test_judge_capture_three_states():
    assert judge_capture("boot READY", "READY", "") == \
        ("PASS", "capture conditions met")
    assert judge_capture("boot", "READY", "") == \
        ("FAIL", "expected not found")
    assert judge_capture("boot ERROR", "", "ERROR") == \
        ("FAIL", "unexpected found")
    assert judge_capture("boot ok", "", "ERROR") == \
        ("PASS", "capture conditions met")
    # NEITHER filled -> no assertion
    assert judge_capture("boot ok", "", "") == ("", "")
    # BOTH filled: unexpected present -> FAIL even though expected present
    assert judge_capture("READY FAILED", "READY", "FAILED") == \
        ("FAIL", "unexpected found")
    # BOTH filled: expected present + unexpected absent -> PASS
    assert judge_capture("READY ok", "READY", "FAILED") == \
        ("PASS", "capture conditions met")
    # BOTH filled: expected missing -> FAIL
    assert judge_capture("ok", "READY", "FAILED") == \
        ("FAIL", "expected not found")


# ------------------------------------------------- Console_serial (mock)
def test_console_serial_expected_only():
    s = FakeSerial({"run": "booting\r\nREADY\r\n"})
    cmd = ConsoleCommand(name="boot", kind="send", send="run",
                         wait_enabled=False, send_enabled=True,
                         capture_enabled=True, timeout=0.3,
                         capture_expected="READY", capture_unexpected="")
    res = _runner([cmd]).run_console(s)
    assert res[0].verdict == "PASS"


def test_console_serial_unexpected_found():
    s = FakeSerial({"run": "starting\r\nERROR boom\r\n"})
    cmd = ConsoleCommand(name="boot", kind="send", send="run",
                         wait_enabled=False, send_enabled=True,
                         capture_enabled=True, timeout=0.3,
                         capture_expected="", capture_unexpected="ERROR")
    res = _runner([cmd]).run_console(s)
    assert res[0].verdict == "FAIL"
    assert "unexpected found" in res[0].detail


def test_console_serial_both_filled():
    cmd = ConsoleCommand(name="boot", kind="send", send="run",
                         wait_enabled=False, send_enabled=True,
                         capture_enabled=True, timeout=0.3,
                         capture_expected="READY", capture_unexpected="FAILED")
    res = _runner([cmd]).run_console(FakeSerial({"run": "READY\r\n"}))
    assert res[0].verdict == "PASS"
    res2 = _runner([cmd]).run_console(
        FakeSerial({"run": "READY\r\nFAILED\r\n"}))
    assert res2[0].verdict == "FAIL"
    assert "unexpected found" in res2[0].detail


# --------------------------------------------------- Console_cli (mock)
def test_console_cli_unified_capture_windows_only():
    runner = FctTestRunner(FctTestConfig.from_dict(
        {"console": {"enabled": True}}))
    cmd = ConsoleCommand(
        kind="host", name="ipconfig", host_cmd_windows="ipconfig /all",
        host_cmd="ifconfig",        # legacy fallback is ignored
        capture_expected="IPv4", capture_unexpected="")
    host = _HostRunner(["Windows IP Configuration",
                        "IPv4 Address. . . 192.168.1.5"])
    verdict, detail = runner._run_host_cli(cmd, host)
    assert verdict == "PASS"
    assert "capture conditions met" in detail

    # the Windows command line wins over the legacy host_cmd
    seen = {}

    class _Spy:
        def run(self, line):
            seen["line"] = line
            return _HostResult(0, ["ok"], "")

    runner._run_host_cli(cmd, _Spy())
    assert seen["line"] == "ipconfig /all"

    # capture_unexpected hit -> FAIL even with a zero exit code
    bad = ConsoleCommand(kind="host", name="ipconfig",
                         host_cmd_windows="ipconfig /all",
                         capture_expected="", capture_unexpected="Media disconnected")
    host_bad = _HostRunner(["Adapter", "Media disconnected"])
    v, d = runner._run_host_cli(bad, host_bad)
    assert v == "FAIL" and "unexpected found" in d