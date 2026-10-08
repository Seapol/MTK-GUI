# -*- coding: utf-8 -*-
"""FCT channel abstraction (B4 design §1.1): one protocol, four
adapters.  A step never knows which transport it uses.

Adapters:

* :class:`VirtualFctChannel` - in-memory queue with INJECTABLE output
  and faults (Virtual mode + all unit tests);
* :class:`SubprocessFctChannel` - one-shot host CLI command (stdout /
  stderr captured line-wise, exit code exposed);
* :class:`BoundConsoleChannel` - wraps an EXISTING console channel
  worker (serial via pyserial / SSH via paramiko) by its multi-console
  key — no new transport code.

RED LINE note: no adapter here performs message JUDGING (that is
`fct_exec.judge_keywords`) and none opens hardware on import.
"""
from __future__ import annotations

import subprocess
import time


class ChannelClosed(RuntimeError):
    """The channel cannot deliver / capture anymore."""


class VirtualFctChannel:
    """In-memory channel: tests / Virtual mode inject scripted lines
    and faults; `read_lines` drains what arrived so far."""

    kind = "virtual"

    def __init__(self) -> None:
        self._lines: list = []
        self._fault: str = ""          # "" | "no_response" | "error"
        self._closed = False
        self.written: list = []        # test evidence

    # -- test/Virtual injection hooks --------------------------------
    def inject_output(self, lines) -> None:
        """Queue scripted output lines (str or list[str])."""
        if isinstance(lines, str):
            lines = [lines]
        self._lines.extend(str(line) for line in lines)

    def inject_fault(self, fault: str) -> None:
        """Simulate a channel fault: no_response / error."""
        self._fault = fault

    # -- FctChannel protocol ------------------------------------------
    def read_lines(self, max_lines: int = 100,
                   timeout_s: float = 0.0) -> list:
        if self._closed:
            raise ChannelClosed("virtual channel closed")
        if self._fault == "error":
            self._fault = ""
            raise ChannelClosed("virtual channel error (injected)")
        if self._fault == "no_response":
            return []                   # silence: nothing arrives
        got = self._lines[:max(1, max_lines)]
        del self._lines[:len(got)]
        return got

    def write(self, data: str) -> None:
        if self._closed:
            raise ChannelClosed("virtual channel closed")
        self.written.append(data)

    def close(self) -> None:
        self._closed = True


class SubprocessResult:
    """Outcome of one host CLI command (CLI_RUN joint judgement)."""

    def __init__(self, exit_code: int, lines: list) -> None:
        self.exit_code = exit_code
        self.lines = lines


def run_subprocess(command: str, timeout_s: float,
                   cwd: str = "") -> SubprocessResult:
    """One-shot host CLI command (B4 §4): stdout+stderr merged,
    line-split; never raises on non-zero exit - the exit code is part
    of the result (joint judgement in fct_exec)."""
    proc = subprocess.Popen(
        command, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace",
        cwd=cwd or None)
    lines: list = []
    deadline = time.monotonic() + max(timeout_s, 0.1)
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if line:
            lines.append(line.rstrip("\r\n"))
        elif proc.poll() is not None:
            break
        elif time.monotonic() > deadline:
            proc.kill()
            lines.append("[fct] subprocess timeout")
            break
    if proc.poll() is None:             # drain after natural exit
        for line in proc.stdout:
            lines.append(line.rstrip("\r\n"))
    proc.wait()
    return SubprocessResult(proc.returncode if proc.returncode is not None
                            else -1, lines)


class SubprocessFctChannel:
    """Host CLI channel: `write` runs the command, `read_lines` yields
    its captured output (one-shot per command)."""

    kind = "subprocess"

    def __init__(self, timeout_s: float = 30.0, cwd: str = "") -> None:
        self._timeout = timeout_s
        self._cwd = cwd
        self._result: SubprocessResult | None = None

    def write(self, data: str) -> None:
        """`data` is the command; runs it synchronously."""
        self._result = run_subprocess(data, self._timeout, self._cwd)

    def read_lines(self, max_lines: int = 100,
                   timeout_s: float = 0.0) -> list:
        if self._result is None:
            return []
        got = self._result.lines[:max(1, max_lines)]
        del self._result.lines[:len(got)]
        return got

    @property
    def exit_code(self) -> int:
        return self._result.exit_code if self._result else -1

    def close(self) -> None:
        self._result = None


class BoundConsoleChannel:
    """Binds an EXISTING multi-console channel worker (serial pyserial
    or SSH paramiko) by key - no new transport code (B4 §1.1)."""

    kind = "console"

    def __init__(self, worker) -> None:
        """`worker` = the console channel worker exposing the B2
        console interface: `send(data)`, `pop_lines()` (or read buffer)
        and `connected`."""
        self._worker = worker

    def read_lines(self, max_lines: int = 100,
                   timeout_s: float = 0.0) -> list:
        pop = getattr(self._worker, "pop_lines", None)
        if callable(pop):
            return [str(x) for x in pop(max_lines)]
        buf = getattr(self._worker, "read_buffer_snapshot", None)
        if callable(buf):
            return [str(x) for x in buf(max_lines)]
        return []

    def write(self, data: str) -> None:
        self._worker.send(data)

    def close(self) -> None:
        pass                            # the console owns the transport
