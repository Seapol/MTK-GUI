# -*- coding: utf-8 -*-
"""M78: timeout truth, hard budget enforcement, stall watchdog.

D1  a declared 600000 ms budget is no longer clamped to 99999 ms
D2  the Wi-Fi op budget covers prepare / probe / conf / connect
D3  the iperf budget defaults to the row budget (no hidden 60 s)
D4  an overrun step is aborted with FAIL (never PASS)
D5  WaitforConsole judges only bytes arriving after the step started
D6  a silent channel fails at the 8 s stall watchdog, not at the budget
"""
from __future__ import annotations

import time

from mtkgui.engine.fct_channels import ConsoleBufferChannel, VirtualFctChannel
from mtkgui.engine.fct_exec import (
    DEFAULT_STALL_S,
    FctContext,
    FctStep,
    execute_fct_step,
)
from mtkgui.gui.yamlbuild.fct_build import STEP_MESSAGE_CHECK
from mtkgui.engine.runner import TestRunner
from mtkgui.engine.sequence import load_sequence, resolve_step_budget


def _wait_step(timeout_s: float, **params) -> FctStep:
    base = {"fct_console": True, "kind": "wait",
            "expect_pass_re": "ready"}
    base.update(params)
    return FctStep(name="Console - wait", step_type=STEP_MESSAGE_CHECK,
                   channel="ser1", timeout_s=timeout_s, params=base)


def _ctx(channel, sink: list) -> FctContext:
    return FctContext(channels={"ser1": channel}, log_sink=sink.append)


# ------------------------------------------------------ M78-1 precedence
def test_m78_single_budget_precedence():
    """Each row shape resolves to its documented field."""
    # op rows: op_params.timeout_s -> timeout_s -> timeout_ms -> args -> 60
    assert resolve_step_budget(
        {"op_params": {"timeout_s": 90}, "timeout_s": 15,
         "timeout_ms": 5000}, op=True)[:2] == (90.0, "op_params.timeout_s")
    assert resolve_step_budget({"timeout_s": 45}, op=True)[:2] \
        == (45.0, "timeout_s")
    assert resolve_step_budget({"timeout_ms": 60000}, op=True)[:2] \
        == (60.0, "timeout_ms")
    assert resolve_step_budget(
        {"params": {"args": {"timeout_s": 30}}}, op=True)[:2] \
        == (30.0, "args.timeout_s")
    assert resolve_step_budget({}, op=True)[:2] == (60.0, "default")
    # every other row: timeout_s -> timeout_ms -> typed -> 30
    assert resolve_step_budget({"timeout_s": 25})[:2] == (25.0, "timeout_s")
    assert resolve_step_budget({"timeout_ms": 60000})[:2] \
        == (60.0, "timeout_ms")
    assert resolve_step_budget(
        {"params": {"fct_rf": {"rf_timeout_s": 45}}})[:2] \
        == (45.0, "rf_timeout_s")
    assert resolve_step_budget({})[:2] == (30.0, "default")
    # M78-1/D3: the adapter's typed iperf budget defaults to the ROW
    rf = {"wifi": {"mode": "full_stack", "timeout_s": 90,
                   "cmds": {key: {"rssi_cmd": "scan"}
                            for key in ("mac", "windows", "linux")}}}
    from mtkgui.engine.rf_adapters import WifiAdapter
    adapter = WifiAdapter(rf, object())
    assert adapter.iperf_timeout_s == 90.0


def test_m78_conflicting_fields_warn_once():
    lines: list = []
    budget, source, warning = resolve_step_budget(
        {"timeout_s": 60, "timeout_ms": 5000}, op=False,
        log=lines.append)
    assert budget == 60.0 and source == "timeout_s"
    assert len(lines) == 1                     # exactly ONE warning
    text = lines[0]
    assert "timeout_s=60s" in text
    assert "timeout_ms=5s" in text
    assert "wins over" in text and "WARNING" in text
    assert warning == text


def test_m78_no_silent_clamp():
    """D1: a 600000 ms budget reaches the step unchanged."""
    cfg = {"test_workflow": {
        "overall_flow": [{"stage": "FCT", "enable": True}],
        "fct_test_cases": [
            {"name": "Serial - push test assets to the DUT",
             "kind": "MessageOK", "timeout_ms": 600000}]}}
    (step,) = load_sequence(cfg)[0].steps
    assert step.timeout_ms == 600000
    assert step.timeout_ms != 99999
    budget, source, _warn = resolve_step_budget({"timeout_ms": 600000})
    assert budget == 600.0 and source == "timeout_ms"


# ----------------------------------------------------- M78-2 budget wall
class _FakeMc:
    def __init__(self):
        self.channels = {"ser1": {"kind": "serial", "connected": True}}
        self.buf = b""

    def channel_connected(self, _key):
        return True

    def get_read_buffer(self, _key):
        return self.buf

    def write_to_channel(self, _key, payload):
        cmd = payload.decode("utf-8", "replace").strip()
        if cmd.startswith("iw dev"):
            reply = "Interface mlan0\n\ttype managed\n"
        elif cmd.startswith("dhclient") or cmd.startswith("udhcpc") \
                or cmd.startswith("ip link") or cmd.startswith("cat >") \
                or cmd.startswith("killall"):
            reply = "started\n"
        else:
            reply = "2: mlan0: <BROADCAST,MULTICAST,UP> state UP\n"
        self.buf += reply.encode()


class _FakeEnv:
    def __init__(self, mc):
        self.multi_console = mc
        self.fct_dut_ip = ""
        self.logs: list = []

    def _log(self, line):
        self.logs.append(line)


def _wifi_params(timeout_s: float) -> dict:
    return {"type": "wifi_connect", "iface": "mlan0",
            "ssid": "lab-ap", "password": "lab-pass",
            "timeout_s": timeout_s}


def test_m78_budget_exceeded_aborts():
    """D4: a step that runs past its declared budget can never PASS."""
    env = _FakeEnv(_FakeMc())
    runner = TestRunner(env)
    t0 = time.time()
    verdict = runner._run_network_op(
        "FCT", "Wi-Fi: Connect DUT to AP", _wifi_params(1.0))
    elapsed = time.time() - t0
    assert verdict == "Fail"
    assert elapsed <= 4.0                     # stopped AT the budget
    joined = " ".join(env.logs)
    assert "budget exceeded:" in joined
    assert "-> FAIL" in joined
    assert runner._last_op_error.startswith("timeout after")


def test_m78_budget_covers_association():
    """D2: the fixed 6/6/8/20 prepare/probe/conf/connect sub-waits are
    clamped by the remaining budget."""
    env = _FakeEnv(_FakeMc())
    runner = TestRunner(env)
    seen: list = []

    def spy(_mc, _key, command, wait_s=8.0, quiet_s=0.6):
        seen.append(float(wait_s))
        return ("Interface mlan0\n\ttype managed\n"
                if "iw dev" in command else "")

    runner._net_run = spy
    runner._run_network_op(
        "FCT", "Wi-Fi: Connect DUT to AP", _wifi_params(2.0))
    assert seen, "no network command ran"
    assert max(seen) <= 2.0 + 1e-6            # never more than the budget
    # prepare / probe / conf_write / connect used to be fixed 6/6/8/20
    first_four = seen[:4]
    assert len(first_four) == 4
    assert all(abs(ws - 2.0) < 0.1 for ws in first_four)


# ------------------------------------------------------ M78-3 watchdog
def test_m78_stall_watchdog_fails_fast():
    """D6: a silent channel fails at ~8 s, long before a 60 s budget."""
    channel = VirtualFctChannel()
    channel.inject_fault("no_response")
    sink: list = []
    ctx = _ctx(channel, sink)
    step = _wait_step(60.0)
    t0 = time.time()
    outcome = execute_fct_step(step, ctx)
    elapsed = time.time() - t0
    assert outcome.verdict == "FAIL"
    assert "watchdog" in outcome.reason
    assert DEFAULT_STALL_S <= elapsed < DEFAULT_STALL_S + 4.0
    assert any("watchdog: no output" in line for line in sink)


def test_m78_stall_watchdog_happy_path():
    """A match still wins instantly - the watchdog adds no delay."""
    channel = VirtualFctChannel()
    channel.inject_output("ready")
    sink: list = []
    ctx = _ctx(channel, sink)
    t0 = time.time()
    outcome = execute_fct_step(_wait_step(60.0), ctx)
    elapsed = time.time() - t0
    assert outcome.verdict == "PASS"
    assert elapsed < 2.0
    assert not any("watchdog" in line for line in sink)


# --------------------------------------------- M78-4 verdict window
class _BufferedMc:
    """A console whose read buffer already holds pre-step text."""

    def __init__(self, text: str):
        self.channels = {"ser1": {"kind": "serial", "connected": True}}
        self.buf = text.encode("utf-8")

    def channel_connected(self, _key):
        return True

    def get_read_buffer(self, _key):
        return self.buf

    def write_to_channel(self, _key, payload):
        self.buf += payload if isinstance(payload, bytes) \
            else str(payload).encode("utf-8")


def test_m78_waitforconsole_delta_window():
    """D5: stale pre-step text alone does NOT satisfy the expectation."""
    channel = ConsoleBufferChannel(_BufferedMc("boot ok\nlogin: root\n"),
                                   "ser1")
    sink: list = []
    ctx = _ctx(channel, sink)
    step = _wait_step(0.3, stall_s=0.0, expect_pass_re="boot ok")
    outcome = execute_fct_step(step, ctx)
    assert outcome.verdict == "FAIL"
    assert not any("matched pre-step" in line for line in sink)


def test_m78_match_history_optin():
    """``match_history: true`` matches history and says so."""
    channel = ConsoleBufferChannel(_BufferedMc("boot ok\nlogin: root\n"),
                                   "ser1")
    sink: list = []
    ctx = _ctx(channel, sink)
    step = _wait_step(0.3, stall_s=0.0, match_history=True,
                      expect_pass_re="boot ok")
    outcome = execute_fct_step(step, ctx)
    assert outcome.verdict == "PASS"
    assert any("matched pre-step buffered output (match_history=true)"
               in line for line in sink)


# ------------------------------------------- backward compatibility
_BENCH_STEPS = [
    ("MessageOKtoConsole", "MessageOKtoConsole", 10000),
    ("Delay - system boot wait", "Delay", 1000),
    ("Console - wait for login prompt", "WaitforConsole", 60000),
    ("Console - login to the DUT (root)", "SendtoCLI", 30000),
    ("Console - kernel version", "SendtoCLI", 6000),
    ("Serial - push test assets to the DUT", "MessageOK", 600000),
    ("Console - RF driver presence", "SendtoCLI", 6000),
    ("Console - load the RF driver", "SendtoCLI", 10000),
    ("Wi-Fi: Connect DUT to AP", "op", 90000),
    ("Wi-Fi Ping (3 segments)", "WIFI", 60000),
    ("Host: Start iperf3 server", "SendtoCLI", 20000),
    ("Wi-Fi iPerf", "WIFI", 90000),
    ("Bluetooth Pair & Connect", "Bluetooth", 45000),
    ("Bluetooth Tone / A2DP", "Bluetooth", 60000),
    ("Console serial step", "SendtoCLI", 60000),
    ("SFTP download", "MessageOK", 45000),
    ("Console - clean up", "SendtoCLI", 10000),
]


def test_m78_backward_compat_project_yaml():
    """The 17-step bench YAML keeps every name, order, kind AND budget."""
    cfg = {"test_workflow": {
        "overall_flow": [{"stage": "FCT", "enable": True}],
        "fct_test_cases": [
            {"name": name, "kind": kind, "timeout_ms": ms}
            for name, kind, ms in _BENCH_STEPS]}}
    steps = load_sequence(cfg)[0].steps
    assert len(steps) == 17
    assert [s.name for s in steps] == [n for n, _k, _ms in _BENCH_STEPS]
    assert [s.kind for s in steps] == [k for _n, k, _ms in _BENCH_STEPS]
    assert [s.timeout_ms for s in steps] == [ms for _n, _k, ms in
                                             _BENCH_STEPS]
    # D1 sanity signal: step 6 is 600000, not the old 99999 clamp
    assert steps[5].timeout_ms == 600000
