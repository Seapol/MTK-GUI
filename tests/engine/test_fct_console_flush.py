# -*- coding: utf-8 -*-
"""m118 §4: drain stale console bytes before each send.

A slow echo from the previous command could land inside the next
step's capture window (measured once as a 0.03 s FAIL on residual
``fail`` output).  ``_flush_channel`` drops the pending lines first.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mtkgui.engine.fct_exec import (
    VERDICT_PASS,
    FctContext,
    FctStep,
    execute_fct_step,
)


class _Channel:
    """A console channel with preloadable pending lines.

    ``write`` accumulates the (throttled) payload and answers the
    ``uname -a`` command once its terminating newline arrives.
    """

    def __init__(self, lines=None):
        self.pending = list(lines or [])
        self.written: list = []
        self.marks = 0
        self._sent = ""

    def mark(self):
        self.marks += 1

    def write(self, data):
        text = str(data)
        self.written.append(text)
        self._sent += text
        if "\n" in self._sent:
            command, self._sent = self._sent.split("\n", 1)
            if "uname" in command:
                self.pending.append("Linux imx93 6.6.0")

    def read_lines(self, max_lines=200, timeout_s=0.1):
        out = self.pending[:max_lines]
        del self.pending[:max_lines]
        return out


def _send_step(**params) -> FctStep:
    base = {"fct_console": True, "kind": "send", "send_enabled": True,
            "send": "uname -a", "expect_pass_re": "Linux imx93",
            "capture_is_expected": True}
    base.update(params)
    return FctStep(name="Kernel check", category="Console", type="serial",
                   channel="ser1", timeout_s=1.0, params=base)


def _ctx(channel, logs: list) -> FctContext:
    return FctContext(channels={"ser1": channel}, log_sink=logs.append)


def test_stale_bytes_are_dropped_before_send():
    """The previous command's echo never reaches the new capture."""
    channel = _Channel(["stale echo from the previous command"])
    logs: list = []
    out = execute_fct_step(_send_step(), _ctx(channel, logs))
    assert out.verdict == VERDICT_PASS
    assert any("flush 1 stale line(s) before send" in line
               for line in logs)
    assert all("stale echo" not in line for line in out.lines)
    assert "".join(channel.written).startswith("uname -a")


def test_no_flush_when_the_buffer_is_clean():
    """A clean buffer emits no flush line at all."""
    channel = _Channel()
    logs: list = []
    out = execute_fct_step(_send_step(), _ctx(channel, logs))
    assert out.verdict == VERDICT_PASS
    assert not any("flush" in line for line in logs)


def test_wait_only_row_does_not_flush():
    """Wait-only rows keep their bytes: no send, no flush."""
    channel = _Channel(["login:"])
    logs: list = []
    step = FctStep(name="Boot wait", category="Console", type="serial",
                   channel="ser1", timeout_s=1.0,
                   params={"fct_console": True, "kind": "wait",
                           "wait_pattern": "login:",
                           "expect_pass_re": "login:",
                           "capture_is_expected": True})
    out = execute_fct_step(step, _ctx(channel, logs))
    assert out.verdict == VERDICT_PASS
    assert channel.written == []
    assert not any("flush" in line for line in logs)
