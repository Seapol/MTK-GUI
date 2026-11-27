# -*- coding: utf-8 -*-
"""m119 regressions: console judgement must not invent a verdict.

Four defects were measured on the Windows rack (2026-11-24):

* a CR-separated console let ``.*`` span lines, so the DUT's own checklist
  ("Minimum throughput per direction: 100.0 Mbits/sec") satisfied the
  iperf pattern and the row PASSed at exactly the limit with no
  measurement at all;
* the tty echo contains the sent command, so a marker string inside the
  command satisfied its own ``expect_fail_re`` 3 s after send;
* a hung iperf client owned the tty and the next row never ran, yet was
  reported as a DUT FAIL;
* "no measurement" was rendered as FAIL although it is a bench problem.

These tests pin the fixes: normalised line breaks, echo stripping, a
JSON-based iperf measurement with a tri-state verdict, and ERROR - not
FAIL - whenever nothing ran.
"""
from __future__ import annotations

import json

import pytest

from mtkgui.engine import fct_exec
from mtkgui.engine.fct_exec import (
    VERDICT_ERROR,
    VERDICT_FAIL,
    VERDICT_PASS,
    FctStep,
    _dut_verdict,
    execute_fct_step,
    make_virtual_context,
)
from mtkgui.engine.fct_test_runner import (
    _parse_iperf_mbps,
    dut_wifi_iperf,
    match_expectation,
    normalize_console_text,
    strip_sent_echo,
)
import mtkgui.engine.fct_test_runner as runner_mod


IPERF_PATTERN = r"[0-9.]+\s+[MG]bits/sec.*receiver"
BANNER = ("[ ] Minimum throughput per direction: 100.0 Mbits/sec")
SUMMARY = "[  5]   0.00-5.00   sec   152 MBytes   255 Mbits/sec   receiver"


# ------------------------------------------------------- A: CR normalisation
def test_cr_separated_banner_never_satisfies_the_iperf_pattern():
    # the DUT checklist banner + an unrelated "receiver" word: with CR
    # line ends `.*` crossed the line break and judged PASS at exactly
    # the limit while the console said "unable to connect to server"
    text = BANNER + "\r[ ] DUT receiver LED   PASS\r"
    assert match_expectation(text, IPERF_PATTERN, "", True, False, True) == \
        ("", "")
    # a real measurement on its own line still matches
    real = BANNER + "\r" + SUMMARY + "\r"
    assert match_expectation(real, IPERF_PATTERN, "", True, False,
                             True)[0] == "PASS"


def test_match_expectation_normalises_crlf_too():
    text = "Overall result: PASS\r\nnext\r\n"
    assert match_expectation(text, "Overall result: PASS", "", False, False,
                             True)[0] == "PASS"
    # a pattern that needs two lines still cannot match across them
    assert match_expectation(text, r"PASS.*next", "", True, False, True) == \
        ("", "")


# --------------------------------------------------------- B: echo stripping
def test_command_echo_never_judges_itself():
    cmd = ("[ -f /tmp/btadv.pid ] && kill $(cat /tmp/btadv.pid) 2>/dev/null; "
           "hciconfig hci0 reset && hciconfig hci0 up && "
           "hciconfig hci0 piscan && echo BT_DISCOVERABLE_OK || "
           "echo BT_DISCOVERABLE_FAIL")
    echo = "root@imx93frdm:~/fct_assets# " + cmd
    text = echo + "\nBT_DISCOVERABLE_OK\nroot@imx93frdm:~/fct_assets# "
    stripped = strip_sent_echo(text, [cmd])
    assert cmd not in stripped
    assert "BT_DISCOVERABLE_FAIL" not in stripped
    # the real marker survives, so the row can still PASS
    assert match_expectation(stripped, "BT_DISCOVERABLE_OK", "",
                             False, False, True)[0] == "PASS"
    # the echoed command still carries the FAIL marker - judged as-is
    # that is a FAIL three seconds after the send (the 21:19 run)
    assert "BT_DISCOVERABLE_FAIL" in text
    assert match_expectation(text, "", "BT_DISCOVERABLE_FAIL",
                             False, False, True)[0] == "FAIL"


def test_wrapped_echo_fragments_are_all_dropped():
    cmd = "a" * 40 + " BT_MARKER_OK " + "b" * 40
    wrapped = "root@dut:~# " + "a" * 40 + "\r\n BT_MARKER_OK \r\n" + "b" * 40
    stripped = strip_sent_echo(wrapped, [cmd])
    assert "BT_MARKER_OK" not in stripped


# ------------------------------------------------------- C: iperf measurement
def test_banner_only_text_has_no_measurement():
    assert _parse_iperf_mbps(BANNER + "\nOverall result: PASS\n") is None


def test_iperf_json_receiver_is_the_measurement():
    doc = {"end": {"sum_received": {"bits_per_second": 256_400_000.0}},
           "error": ""}
    assert _parse_iperf_mbps(json.dumps(doc)) == pytest.approx(256.4, abs=0.1)


def test_iperf_json_error_yields_no_measurement():
    doc = {"error": "unable to connect to server"}
    assert _parse_iperf_mbps(json.dumps(doc)) is None


def test_iperf_receiver_with_zero_transfer_is_not_a_measurement():
    text = ("[ ID] Interval           Transfer     Bitrate         Retr\r\n"
            "[  5]   0.00-186.30 sec  0.00 Bytes  0.00 bits/sec  receiver\r\n")
    assert _parse_iperf_mbps(text) is None


def test_iperf_text_summary_with_real_transfer_is_used():
    assert _parse_iperf_mbps(SUMMARY + "\n") == pytest.approx(255.0)


# --------------------------------------------- C/D: tri-state verdict shape
class _Feed:
    """Minimal pyserial-like object fed a fixed byte stream."""

    def __init__(self, payload: str):
        self.payload = payload.encode("utf-8")
        self.writes = []

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.writes.append(data)

    def read(self, n=4096):
        chunk, self.payload = self.payload[:n], self.payload[n:]
        return chunk


def test_no_measurement_is_error_not_fail(monkeypatch):
    monkeypatch.setattr(runner_mod, "_console_probe",
                        lambda *a, **k: ("TIMEOUT",
                                         "iperf3: error - unable to connect"))
    ser = _Feed("")
    verdict, detail = dut_wifi_iperf(ser, "iperf3", "192.168.71.8", 100.0, 5)
    assert verdict == "ERROR"
    assert detail.startswith("no iperf measurement (server 192.168.71.8")
    # a hung client must never keep the tty: Ctrl-C was sent
    assert any(b"\x03" in w for w in ser.writes)


def test_below_limit_is_fail_and_above_is_pass():
    doc = {"end": {"sum_received": {"bits_per_second": 90_000_000.0}}}
    ser = _Feed(json.dumps(doc) + "\n")
    assert dut_wifi_iperf(ser, "iperf3", "192.168.71.8", 100.0, 5)[0] == \
        "FAIL"
    doc = {"end": {"sum_received": {"bits_per_second": 256_000_000.0}}}
    ser = _Feed(json.dumps(doc) + "\n")
    assert dut_wifi_iperf(ser, "iperf3", "192.168.71.8", 100.0, 5)[0] == \
        "PASS"


def test_zero_measurement_is_error(monkeypatch):
    # 0.0 Mbps means the bench moved nothing - not a slow DUT
    doc = {"end": {"sum_received": {"bits_per_second": 0.0}}}
    ser = _Feed(json.dumps(doc) + "\n")
    verdict, detail = dut_wifi_iperf(ser, "iperf3", "192.168.71.8", 100.0, 5)
    assert verdict == "ERROR"
    assert "no iperf measurement" in detail


def test_iperf_command_carries_no_omit_flag(monkeypatch):
    """`-O 1 -J` hangs the DUT's iperf 3.16 forever (measured on the rack)."""
    seen = {}

    def fake_probe(serial, cmd, expect, budget):
        seen["cmd"] = cmd
        return "OK", json.dumps({"end": {"sum_received":
                                         {"bits_per_second": 2.5e8}}})

    monkeypatch.setattr(runner_mod, "_console_probe", fake_probe)
    ser = _Feed("")
    dut_wifi_iperf(ser, "iperf3", "192.168.71.8", 100.0, 5)
    cmd = seen["cmd"]
    assert " -O " not in f" {cmd} "
    assert "-p 5201" in cmd and "-J" in cmd


def test_dut_verdict_mapping_keeps_error_distinct():
    assert _dut_verdict("PASS") == VERDICT_PASS
    assert _dut_verdict("FAIL") == VERDICT_FAIL
    assert _dut_verdict("ERROR") == VERDICT_ERROR


# ---------------------------------------------------- E: "never ran" = ERROR
def test_budget_overrun_is_error(monkeypatch):
    ctx, _ = make_virtual_context({"ser1": []})

    def slow_exec(step, ctx):              # 0.6 s against a 0.2 s budget
        import time as _t
        _t.sleep(0.6)
        return fct_exec.FctOutcome(VERDICT_FAIL, "not executed")

    monkeypatch.setattr(fct_exec, "_execute_once", slow_exec)
    step = FctStep(name="slow", category="Console", type="serial", channel="ser1",
                   timeout_s=0.2)
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_ERROR
    assert "budget exceeded" in out.reason


def test_silent_console_timeout_is_error():
    ctx, _ = make_virtual_context({"ser1": []})
    step = FctStep(
        name="no report", category="Console", type="serial", channel="ser1",
        timeout_s=0.4,
        params={"fct_console": True, "kind": "send", "send_enabled": False,
                "capture_enabled": True, "expect_pass_re": "NEVER_THERE",
                "__watchdog_off": True})
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_ERROR
    assert "no verdict within" in out.reason


def test_output_without_the_pattern_is_still_a_dut_fail():
    ctx, _ = make_virtual_context({"ser1": ["boot: something else"]})
    step = FctStep(
        name="wrong output", category="Console", type="serial", channel="ser1",
        timeout_s=0.4,
        params={"fct_console": True, "kind": "send", "send_enabled": False,
                "capture_enabled": True, "expect_pass_re": "NEVER_THERE",
                "__watchdog_off": True})
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_FAIL


# ------------------------------------------------------- F: console busy gate
def test_busy_console_blocks_the_send(monkeypatch):
    monkeypatch.setattr(fct_exec, "IDLE_TIMEOUT_S", 0.4)
    monkeypatch.setattr(fct_exec, "IDLE_QUIET_S", 0.05)

    class Busy:
        kind = "serial"

        def read_lines(self, max_lines=200, timeout_s=0.0):
            return ["[  5]  10.00-186.30 sec  0.00 Bytes  0.00 bits/sec"]

    assert fct_exec._wait_console_idle(Busy(), None, None) is False


def test_quiet_console_passes_the_gate(monkeypatch):
    monkeypatch.setattr(fct_exec, "IDLE_TIMEOUT_S", 0.4)
    monkeypatch.setattr(fct_exec, "IDLE_QUIET_S", 0.05)

    class Quiet:
        kind = "serial"

        def read_lines(self, max_lines=200, timeout_s=0.0):
            return []

    assert fct_exec._wait_console_idle(Quiet(), None, None) is True


def test_prompt_means_idle(monkeypatch):
    monkeypatch.setattr(fct_exec, "IDLE_TIMEOUT_S", 0.4)
    monkeypatch.setattr(fct_exec, "IDLE_QUIET_S", 0.05)

    class Prompted:
        kind = "serial"

        def __init__(self):
            self.calls = 0

        def read_lines(self, max_lines=200, timeout_s=0.0):
            self.calls += 1
            return [] if self.calls > 1 else ["root@imx93frdm:~# "]

    assert fct_exec._wait_console_idle(Prompted(), None, None) is True
