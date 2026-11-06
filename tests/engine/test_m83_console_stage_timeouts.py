# -*- coding: utf-8 -*-
"""M83 C5: two-stage console timeout truth (wait vs send/capture)."""
from __future__ import annotations

import time

from mtkgui.engine.fct_exec import (
    FctContext,
    execute_fct_step,
)
from mtkgui.engine.fct_test_config import (
    ConsoleCommand,
    _console_row_steps,
)
from mtkgui.gui.yamlbuild.fct_build import FctStep


class _DelayedChannel:
    """A channel that answers ``line`` after ``delay`` seconds."""

    def __init__(self, delay: float, line: str):
        self.delay = delay
        self.line = line
        self.started = None

    def write(self, _data):
        pass

    def read_lines(self, max_lines=200, timeout_s=0.1):
        if self.started is None:
            self.started = time.monotonic()
        if time.monotonic() - self.started >= self.delay and self.line:
            out, self.line = [self.line], ""
            return out
        return []


class _SendWindowChannel:
    """Pre-send noise is hidden after ``mark()``; the reply is delayed."""

    def __init__(self, noise: str, reply: str, delay: float):
        self.noise = noise
        self.reply = reply
        self.delay = delay
        self.marked_at = None
        self.written: list = []

    def mark(self):
        self.marked_at = time.monotonic()

    def write(self, data):
        self.written.append(str(data))
        self.marked_at = self.marked_at or time.monotonic()

    def read_lines(self, max_lines=200, timeout_s=0.1):
        if self.marked_at is None:
            return []
        if time.monotonic() - self.marked_at < self.delay:
            return []
        out, self.reply = ([self.reply], "") if self.reply else ([], "")
        return out


def _ctx(channel, watchdog_s=None):
    kw = {"watchdog_s": watchdog_s} if watchdog_s is not None else {}
    return FctContext(channels={"ser1": channel},
                      log_sink=lambda line: None, **kw)


def _wait_step(wait_timeout: float, row_timeout: float) -> FctStep:
    return FctStep(
        name="wait", step_type="MESSAGE_CHECK", channel="ser1",
        timeout_s=row_timeout,
        params={"fct_console": True, "kind": "wait",
                "expect_pass_re": "late", "capture_is_expected": True,
                "wait_timeout": wait_timeout})


def test_m83_wait_window_counts_from_step_start():
    channel = _DelayedChannel(0.5, "late")
    t0 = time.monotonic()
    out = execute_fct_step(_wait_step(1.0, 1.0), _ctx(channel))
    assert out.verdict == "PASS"
    assert time.monotonic() - t0 >= 0.4


def test_m83_wait_window_is_not_clamped_by_row_budget():
    # the row budget is 0.2 s, the wait window is 1.0 s: the old clamp
    # would have failed this, the new truth waits for the prompt.
    from mtkgui.engine.fct_exec import _console_wait

    channel = _DelayedChannel(0.5, "late")
    step = FctStep(
        name="stage", step_type="MESSAGE_CHECK", channel="ser1",
        timeout_s=0.2,
        params={"fct_console": True, "kind": "send",
                "wait_enabled": True, "wait_pattern": "late",
                "wait_timeout": 1.0})
    t0 = time.monotonic()
    out = _console_wait(channel, step, _ctx(channel), "late")
    assert out.verdict == "PASS"
    assert time.monotonic() - t0 >= 0.4


def test_m83_send_window_counts_from_send_start():
    channel = _SendWindowChannel("OK", "late", 0.35)
    step = FctStep(
        name="send", step_type="MESSAGE_CHECK", channel="ser1",
        timeout_s=0.6,
        params={"fct_console": True, "kind": "send",
                "send_enabled": True, "send": "run",
                "capture_enabled": True,
                "expect_pass_re": "late", "capture_is_expected": True,
                "capture_timeout": 0.6})
    t0 = time.monotonic()
    out = execute_fct_step(step, _ctx(channel))
    assert out.verdict == "PASS"
    assert time.monotonic() - t0 >= 0.2      # not an instant pre-send hit


def test_m83_wait_only_row_uses_wait_timeout():
    cmd = ConsoleCommand(kind="wait", name="wait", channel="ser1",
                         wait_enabled=True, send_enabled=False,
                         expect_pass="login:", wait_timeout=0.5,
                         timeout=99.0)
    (step,) = _console_row_steps(cmd, "ser1")
    assert step.timeout_s == 0.5


def test_m83_stall_watchdog_still_fires():
    class _Silent:
        def write(self, _data):
            pass

        def read_lines(self, max_lines=200, timeout_s=0.1):
            return []

    out = execute_fct_step(_wait_step(60.0, 60.0),
                           _ctx(_Silent(), watchdog_s=0.5))
    assert out.verdict == "FAIL"
    assert "watchdog" in out.reason
