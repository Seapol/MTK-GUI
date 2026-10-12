# -*- coding: utf-8 -*-
"""FCT console sequence TIMING DISCIPLINE (v1.0.2) - reverse-validation
tests for the Wait -> Send -> Capture fresh-window semantics.

The user-visible bugs these lock out:

  * a row RAN AHEAD of the still-running previous command because its
    WAIT matched a prompt that was printed long before (session
    history / stale OS buffer);
  * a DUT that is POWERED OFF still PASSed rows (a silent capture
    window with no End Line 'survived clean');
  * a capture-only row could not see content (fat.py Summary) that
    was printed while an earlier row was still reading.

Engine rules under test (fct_test_runner.FctTestRunner._run_pipeline):

  WAIT    judges only the FRESH WINDOW = bytes received since the
          last SEND (a recurring prompt must appear AGAIN);
  SEND    resets the OS input buffer and restarts the window;
  CAPTURE on a send row judges only post-send bytes; a capture-only
          row looks back through the WHOLE session transcript;
  SILENCE a window with zero received bytes always FAILs.
"""
import yaml

import pytest

from mtkgui.engine.fct_test_config import ConsoleCommand, FctTestConfig
from mtkgui.engine.fct_test_runner import FctTestRunner

PROMPT = "root@imx93frdm:~# "


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


def _cmd(**kw):
    base = dict(kind="send", wait_timeout=0.5, send_timeout=0.4,
                timeout=0.5)
    base.update(kw)
    return ConsoleCommand(**base)


def _runner(commands):
    cfg = FctTestConfig.from_dict({"console": {"enabled": True}})
    cfg.console.test_commands = commands
    return FctTestRunner(cfg)


# ----------------------------------------------------------- no running ahead
def test_wait_ignores_prompt_printed_before_last_send():
    """THE rush-ahead bug: row1's reply carries the shell prompt, then a
    long command starts (no prompt yet).  The next row's WAIT must NOT
    match the prompt printed before the long command was sent - it may
    only match a prompt that appears AFTER it.  (Old engine matched the
    session history and fired the next command while the DUT was busy.)"""
    s = FakeSerial({
        "echo hi": f"hi\r\n{PROMPT}",
        "sleep 999": "",                    # long command: prompt NOT back
    })
    cmds = [
        _cmd(name="echo hi", send="echo hi",
             capture_enabled=True, expect_fail="hi",
             capture_is_expected=True),
        _cmd(name="long command", send="sleep 999", capture_enabled=False),
        _cmd(name="next row", wait_enabled=True, expect_pass="root@imx93frdm",
             expect_pass_is_regex=True, wait_timeout=0.5,
             send="echo next", capture_enabled=False),
    ]
    res = _runner(cmds).run_console(s)
    # rows 1-2 pass; row 3 FAILS its wait (sequence aborts there)
    assert [r.verdict for r in res] == ["PASS", "PASS", "FAIL"]
    assert "wait timeout" in res[2].detail
    # the next command was NEVER sent - no running ahead
    assert "echo next" not in s.sent


def test_trailing_prompt_of_previous_reply_satisfies_next_wait():
    """No-race guarantee in the other direction: the prompt that arrives
    WITH the previous command's output (consumed by that row's early-
    stopping capture) is preserved in the fresh window, so the next
    row's WAIT matches it without a spurious timeout."""
    s = FakeSerial({
        "uname -a": f"Linux imx93frdm 6.6.36\r\n{PROMPT}",
    })
    cmds = [
        _cmd(name="kernel", send="uname -a",
             capture_enabled=True, expect_fail="Linux imx93frdm",
             capture_is_expected=True),
        _cmd(name="next row", wait_enabled=True, expect_pass="root@imx93frdm",
             expect_pass_is_regex=True, wait_timeout=0.5,
             send="echo next", capture_enabled=False),
    ]
    res = _runner(cmds).run_console(s)
    assert [r.verdict for r in res] == ["PASS", "PASS"]


def test_sequence_aborts_when_dut_goes_silent_midrun():
    """DUT dies after two commands: the next WAIT must time out to FAIL
    and the whole sequence must stop (later rows must not execute)."""
    s = FakeSerial({
        "echo a": f"a\r\n{PROMPT}",
        "echo b": f"b\r\n{PROMPT}",
        # 'echo c' never answered: DUT dead
    })
    cmds = [
        _cmd(name="a", send="echo a", capture_enabled=True,
             expect_fail="a", capture_is_expected=True),
        _cmd(name="b", send="echo b", capture_enabled=True,
             expect_fail="b", capture_is_expected=True),
        # DUT died after 'echo b': the wait legitimately matches the
        # prompt that came with b's reply, but the capture after the
        # send never sees any output -> FAIL, sequence aborts
        _cmd(name="c", wait_enabled=True, expect_pass="root@imx93frdm",
             expect_pass_is_regex=True, wait_timeout=0.4,
             send="echo c", capture_enabled=True,
             expect_fail="c done", capture_is_expected=True),
        _cmd(name="d", send="echo d", capture_enabled=False),
    ]
    res = _runner(cmds).run_console(s)
    assert [r.verdict for r in res] == ["PASS", "PASS", "FAIL"]
    assert "echo d" not in s.sent


# ------------------------------------------------- silence can never PASS
def test_silent_wait_times_out_to_fail():
    """Reverse validation: a powered-off DUT fails its WAIT (nothing
    fresh ever arrives)."""
    s = FakeSerial({})                       # dead DUT: silence
    cmds = [_cmd(name="login", wait_enabled=True,
                 expect_pass="imx93frdm login:", wait_timeout=0.4,
                 send="root", capture_enabled=False)]
    res = _runner(cmds).run_console(s)
    assert res[0].verdict == "FAIL"
    assert "wait timeout" in res[0].detail


def test_silent_send_capture_expected_fails():
    s = FakeSerial({})                       # dead DUT: no echo, no output
    cmds = [_cmd(name="kernel", send="uname -a", capture_enabled=True,
                 expect_fail="Linux imx93frdm", capture_is_expected=True)]
    res = _runner(cmds).run_console(s)
    assert res[0].verdict == "FAIL"


def test_silent_negative_capture_is_fail_not_pass():
    """THE powered-off-PASS hole: expected=no capture with no End Line
    used to PASS on timeout ('survived the window clean').  Silence is
    no evidence - it must FAIL."""
    s = FakeSerial({})
    cmds = [_cmd(name="clean window", send="somecmd", capture_enabled=True,
                 expect_fail="never arrives", capture_is_expected=False)]
    res = _runner(cmds).run_console(s)
    assert res[0].verdict == "FAIL"
    assert "no console output" in res[0].detail


def test_negative_capture_with_output_still_passes_clean_window():
    """The legitimate case keeps working: the DUT speaks (no unwanted
    line) within the window -> clean-window PASS."""
    s = FakeSerial({"somecmd": f"all good\r\n{PROMPT}"})
    cmds = [_cmd(name="clean window", send="somecmd", capture_enabled=True,
                 expect_fail="never arrives", capture_is_expected=False)]
    res = _runner(cmds).run_console(s)
    assert res[0].verdict == "PASS"


# ------------------------------------------------- capture-only lookback
def test_capture_only_reads_summary_from_session_transcript():
    """Capture-only fat.py summary row: the Summary table was printed
    inside the PREVIOUS row's read window (consumed there) - the
    capture-only row must still find it by looking back through the
    whole session transcript, and parse it into per-item rows."""
    summary = ("Summary:\r\n"
               "1       Root privilege                        PASS          0.00s\r\n"
               "2       Memory                                PASS          0.86s\r\n"
               "3       Ethernet ports                        FAIL          0.03s\r\n"
               "Overall result: FAIL\r\n")
    s = FakeSerial({
        "y": f"Operator confirmed all RGB LED colors\r\n{summary}",
    })
    cmds = [
        _cmd(name="fat.py: RGB LED colors", send="y",
             capture_enabled=True, expect_fail="Operator confirmed all "
             "RGB LED colors", capture_is_expected=True),
        _cmd(name="fat.py summary", send_enabled=False,
             capture_enabled=True, expect_fail="Overall result:",
             capture_is_expected=True, timeout=0.5, parse_summary=True),
    ]
    res = _runner(cmds).run_console(s)
    # res[0] = interactive row, res[1] = summary main row (execution
    # success - per-item FAILs live in the expanded rows), res[2:] =
    # one row per Summary line
    assert res[0].verdict == "PASS"
    assert res[1].verdict == "PASS"
    expanded = res[2:]
    assert [r.verdict for r in expanded] == ["PASS", "PASS", "FAIL"]
    assert expanded[2].name.startswith("3. Ethernet ports")


def test_capture_only_empty_session_fails():
    """A capture-only row on a DUT that never said anything FAILs (the
    transcript is empty - nothing to look back through)."""
    s = FakeSerial({})
    cmds = [_cmd(name="fat.py summary", send_enabled=False,
                 capture_enabled=True, expect_fail="Overall result:",
                 capture_is_expected=True, timeout=0.4, parse_summary=True)]
    res = _runner(cmds).run_console(s)
    assert res[0].verdict == "FAIL"


# --------------------------------------------------------- yaml v1.0.2 guard
def _v102_test_commands():
    from pathlib import Path
    yml = (Path(__file__).resolve().parents[2] / "yaml_plan" / "examples"
           / "imx93frdm" / "FRDM-IMX93_FCT_Demo_v1.0.2.yaml")
    if not yml.exists():                     # generator not run yet
        pytest.skip("FRDM-IMX93_FCT_Demo_v1.0.2.yaml not generated yet")
    data = yaml.safe_load(yml.read_text(encoding="utf-8"))
    node = data.get("fct_test_config")
    if not isinstance(node, dict) or "test_commands" not in (
            node.get("console") or {}):
        # published form: the config travels as the embedded string in
        # modules.fct_build.params.fct_test_config_yaml
        emb = (data.get("modules", {}).get("fct_build", {})
               .get("params", {}).get("fct_test_config_yaml", ""))
        parsed = yaml.safe_load(emb) if emb else None
        if isinstance(parsed, dict) and "fct_test_config" in parsed:
            parsed = parsed["fct_test_config"]
        node = parsed
    return (node or {}).get("console", {}).get("test_commands", [])


def test_v102_every_send_row_waits_first():
    """Timing discipline: every Send row (except the Console wake row
    and the SSH SFTP row) must wait for a prompt/question BEFORE it
    sends - no row may fire while the previous command is still
    running."""
    rows = _v102_test_commands()
    for row in rows:
        if row.get("kind") in ("sftp_put", "sftp_get"):
            continue
        if not row.get("send_enabled"):
            continue
        is_wake = row.get("name") == "Console wake"
        if not is_wake:
            assert row.get("wait_enabled"), \
                f"{row.get('name')!r}: send row without wait"
            assert row.get("expect_pass"), \
                f"{row.get('name')!r}: send row without a wait pattern"


def test_v102_first_row_is_wake_send():
    rows = _v102_test_commands()
    first = rows[0]
    assert first.get("name") == "Console wake"
    assert first.get("send_enabled") and first.get("send", "").strip() == ""
    assert not first.get("wait_enabled") and not first.get("capture_enabled")


def test_v102_capture_anchor_never_in_echo():
    """Echo-safety: the capture anchor must not be a substring of the
    command line itself - the DUT echoes the command before running it,
    so an echo-contained anchor would PASS from the echo alone (even
    with the DUT hung).  Quote-split markers (echo SSHD_"STARTED")
    keep the literal out of the command text."""
    rows = _v102_test_commands()
    for row in rows:
        if row.get("kind") in ("sftp_put", "sftp_get"):
            continue
        if not (row.get("send_enabled") and row.get("capture_enabled")):
            continue
        anchor = str(row.get("expect_fail") or "")
        cmd = str(row.get("send") or "")
        if not anchor:
            continue
        if row.get("expect_fail_is_regex"):
            # regex anchors: strip the regex scaffolding for the check
            anchor = anchor.replace("\\", "").replace("^", "") \
                           .replace("$", "").replace("*", "").replace(".", "")
        assert anchor not in cmd, \
            f"{row.get('name')!r}: anchor {anchor!r} appears in the " \
            f"command echo - capture would self-match"
