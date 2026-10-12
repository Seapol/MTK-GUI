# -*- coding: utf-8 -*-
"""fat.py Summary per-item parsing (``parse_summary`` capture rows).

A parse_summary capture row waits for fat.py to finish, parses its
``Summary:`` table (ANSI-laden, \r line ends) into ONE report row per
test line, and the row itself stays PASS so the sequence keeps running.
Only FAIL/TIMEOUT/ERROR rows count as failures (INFO/WARN/SKIP carry
their real status).  The GUI work-flow executor judges the same rows
through a one-row summary verdict.
"""
import pytest

from mtkgui.engine.fct_exec import _fat_summary_outcome, VERDICT_FAIL, \
    VERDICT_PASS
from mtkgui.engine.fct_test_config import ConsoleCommand, FctTestConfig, \
    build_fct_steps
from mtkgui.engine.fct_test_runner import (
    FctStepResult, FctTestRunner, parse_fat_summary, strip_ansi)
from mtkgui.engine.report import BatchSummary, DutReport, ReportItem
from mtkgui.gui.report_export import console_log_html


# ----------------------------------------------------------- fake serial
class FakeSerial:
    """Scripted pyserial-like: pre-loaded buffer + write-triggered
    replies (mirrors tests/engine/test_fct_test_config.py)."""

    def __init__(self, script=None, preload=b""):
        self.script = script or {}
        self.sent: list = []
        self.buffer = preload

    def reset_input_buffer(self):
        self.buffer = b""

    def write(self, data: bytes):
        cmd = data.decode().strip()
        self.sent.append(cmd)
        reply = self.script.get(cmd, "")
        self.buffer += reply.encode() if isinstance(reply, str) else reply
        return len(data)

    def read(self, n):
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data


# ------------------------------------------- realistic device sample (ANSI)
def _fat_summary_text() -> str:
    """Shape copied from the real board (rerun console log, v1.5.5):
    SGR-wrapped status with trailing spaces, \r line ends, [K clears."""
    rows = [
        (1, "Script information", 34, "INFO", "0.00s"),
        (2, "Root privilege", 32, "PASS", "0.00s"),
        (16, "Ethernet throughput", 32, "PASS", "15.80s"),
        (20, "USB1_C / USB2_A U-disk read/write speed", 31, "FAIL",
         "99.50s"),
        (22, "MQS audio playback", 31, "FAIL", "2.85s"),
        (23, "PDM audio capture", 90, "SKIP", "0.02s"),
        (38, "dmesg warning scan", 33, "WARN", "0.05s"),
    ]
    body = "".join(
        f"{idx:<8}{name:<46}\x1b[{c}m{st:<14}\x1b[0m    {dur}\r\n"
        for idx, name, c, st, dur in rows)
    return (
        "\x1b[32mJSON result saved to: /root/fat_result.json\x1b[0m\r\n"
        "\x1b[1m========== FRDM-i.MX93 FAT Board Test Report ==========\x1b[0m\r\n"
        "\x1b[1mSummary:\x1b[0m\r\n"
        + "-" * 92 + "\r\n"
        "Index   Test Name                                     Status"
        "        Duration    \r\n"
        + "-" * 92 + "\r\n"
        + body
        + "-" * 92 + "\r\n"
        "\x1b[1mResult Count:\x1b[0m\r\n"
        "  \x1b[32mPASS \x1b[0m: 22\r\n  \x1b[31mFAIL \x1b[0m: 3\r\n"
        "\x1b[31m\x1b[1mOverall result: FAIL\x1b[0m\r\n"
        "root@imx93frdm:~/frdm_imx93_board_test# ")


# ------------------------------------------------------------ strip/parse
def test_strip_ansi_removes_colors_and_normalizes_lines():
    raw = "a\x1b[32mPASS\x1b[0m\x1b[K\r\nb\rc\r\n"
    assert strip_ansi(raw) == "aPASS\nb\nc\n"


def test_parse_fat_summary_rows():
    rows = parse_fat_summary(_fat_summary_text())
    assert len(rows) == 7
    assert rows[0] == (1, "Script information", "INFO", "0.00s")
    assert (20, "USB1_C / USB2_A U-disk read/write speed", "FAIL",
            "99.50s") in rows
    assert (23, "PDM audio capture", "SKIP", "0.02s") in rows
    assert (38, "dmesg warning scan", "WARN", "0.05s") in rows


def test_parse_fat_summary_anchor_locality():
    """Only lines after the LAST Summary: anchor count — earlier chatter
    that looks like a table row must not produce phantom rows."""
    chatter = ("3       Fake earlier item                       "
               "PASS          1.00s\r\n")
    text = chatter + "\x1b[1mSummary:\x1b[0m\r\n" + _fat_summary_text()
    rows = parse_fat_summary(text)
    assert all(name != "Fake earlier item" for _i, name, _s, _d in rows)
    assert len(rows) == 7


def test_parse_fat_summary_no_anchor():
    assert parse_fat_summary("hello world, no table here") == []


# --------------------------------------------------- non-failing verdicts
def test_step_result_non_fail_statuses():
    for status in ("PASS", "INFO", "SKIP", "WARN"):
        assert FctStepResult("x", status).passed
    for status in ("FAIL", "TIMEOUT", "ERROR"):
        assert not FctStepResult("x", status).passed


# -------------------------------------------- runner capture-row expansion
def _parse_row() -> ConsoleCommand:
    return ConsoleCommand(
        kind="send", name="fat.py summary", transport="serial",
        wait_enabled=False, send_enabled=False, capture_enabled=True,
        send="", expect_pass="", expect_fail="Overall result:",
        capture_is_expected=True, parse_summary=True, timeout=5.0)


def test_capture_row_expands_summary_and_overall_fails():
    cfg = FctTestConfig()
    cfg.console.enabled = True
    cfg.console.test_commands = [_parse_row()]
    serial = FakeSerial(preload=_fat_summary_text().encode())
    out = FctTestRunner(cfg).run(serial, host_runner=None)
    results = out["results"]
    main = results[0]
    assert main.verdict == "PASS"
    assert main.name == "fat.py summary"
    assert "7 items" in main.detail
    extras = results[1:]
    assert len(extras) == 7
    assert extras[0].name == "1. Script information"
    assert extras[0].verdict == "INFO"
    fails = [r for r in extras if r.verdict == "FAIL"]
    assert [r.name for r in fails] == [
        "20. USB1_C / USB2_A U-disk read/write speed",
        "22. MQS audio playback"]
    # a single FAIL item -> overall FAIL, INFO/WARN/SKIP do not fail
    assert out["overall"] == "FAIL"


def test_sequence_continues_after_summary_fail_items():
    """The summary row PASSes (per-item FAILs live in the expanded
    rows) so following rows — e.g. Start sshd — still execute."""
    sshd = ConsoleCommand(
        kind="send", name="Start sshd", transport="serial",
        send_enabled=True, capture_enabled=True,
        send="mkdir -p /var/run/sshd; /usr/sbin/sshd",
        expect_fail="SSHD_STARTED", capture_is_expected=True, timeout=5.0)
    cfg = FctTestConfig()
    cfg.console.enabled = True
    cfg.console.test_commands = [_parse_row(), sshd]
    serial = FakeSerial(script={"mkdir -p /var/run/sshd; /usr/sbin/sshd":
                                "SSHD_STARTED\r\n"},
                        preload=_fat_summary_text().encode())
    results = FctTestRunner(cfg).run_console(serial)
    names = [r.name for r in results]
    assert "Start sshd" in names
    assert results[-1].verdict == "PASS"


def test_summary_not_found_fails_row_and_stops():
    cfg = FctTestConfig()
    cfg.console.enabled = True
    cfg.console.test_commands = [_parse_row()]
    serial = FakeSerial(preload=b"some unrelated output\r\n")
    results = FctTestRunner(cfg).run_console(serial)
    assert results[0].verdict == "FAIL"
    assert "capture timeout" in results[0].detail
    assert len(results) == 1          # sequence stops on a failed row


# -------------------------------------------------------- config plumbing
def test_config_roundtrip_parse_summary():
    row = _parse_row()
    assert ConsoleCommand._from_dict_v2(row.to_dict()).parse_summary
    assert not ConsoleCommand._from_dict_v2(
        {"kind": "send", "name": "x"}).parse_summary


def test_build_fct_steps_carries_parse_flag():
    cfg = FctTestConfig()
    cfg.console.enabled = True
    cfg.console.test_commands = [_parse_row()]
    steps = build_fct_steps(cfg)
    assert steps and steps[0].params.get("parse_summary") is True


# ------------------------------------------------------------- reporting
def test_failures_by_item_counts_only_real_failures():
    rep = DutReport(serial_no="SN1", station_id="ST", user="op")
    for name, res in [("a", "PASS"), ("b", "INFO"), ("c", "WARN"),
                      ("d", "SKIP"), ("e", "FAIL")]:
        rep.items.append(ReportItem(test_name=name, category="FCT",
                                    result=res))
    summary = BatchSummary(reports=[rep])
    assert summary.failures_by_item() == [("e", 1)]


def test_console_log_html_strips_ansi_and_escapes():
    html = console_log_html("\x1b[31mFAIL <tag>\x1b[0m\r\nline2")
    assert "\x1b" not in html
    assert "&lt;tag&gt;" in html
    assert "<h3>Console Log</h3>" in html
    assert "line2" in html


# ------------------------------------------------------- GUI parity hook
def test_fct_exec_fat_summary_outcome():
    fail = _fat_summary_outcome(_fat_summary_text())
    assert fail.verdict == VERDICT_FAIL
    assert "FAIL 2" in fail.reason
    allpass = _fat_summary_outcome(
        _fat_summary_text().replace("FAIL", "PASS"))
    assert allpass.verdict == VERDICT_PASS
    empty = _fat_summary_outcome("no table")
    assert empty.verdict == VERDICT_FAIL
    assert "no fat.py Summary" in empty.reason
