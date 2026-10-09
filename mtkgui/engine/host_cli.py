# -*- coding: utf-8 -*-
"""P3-B4 Module C: generic Host PC CLI executor.

EVERY host-side command (RF CLI, flashing CLI, environment probes)
goes through :class:`HostCliRunner` so execution control and judging
are uniform:

* command templates with ``{{placeholder}}`` parameters injected from
  the YAML config / channel allocation / test variables;
* working directory, extra environment variables, timeout (seconds)
  with a forced kill on overrun;
* stdout / stderr separated, exit code captured;
* keyword judging (Pass/Success -> pass, Fail/Error -> fail) plus
  optional regex extraction of measured values (RSSI, throughput,
  versions, serial numbers) into report items;
* configurable JOINT judgement: ``require_exit_zero`` means the
  verdict is pass only when the exit code is 0 AND no negative
  keyword appears;
* one EventLog line per command carrying ``[Station ID] [User]``.

UI-free and hardware-free: commands run only when the caller invokes
:py:meth:`HostCliRunner.run`.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time

#: positive keywords - any one of these in the output means "pass"
PASS_KEYWORDS = ("Pass", "Success")
#: negative keywords - any one of these means "fail" (negative wins)
FAIL_KEYWORDS = ("Fail", "Error")
#: line prefix recorded when a command is killed on timeout
TIMEOUT_MARK = "[host_cli] timeout"


class HostCliError(RuntimeError):
    """The command template is malformed / placeholders unresolved."""


def render_template(template: str, params: dict) -> str:
    """Substitute ``{{name}}`` placeholders from `params`.

    Unknown placeholders raise :class:`HostCliError` (explicit, never
    silently left in the command line).
    """
    def _sub(match):
        name = match.group(1).strip()
        if name not in params:
            raise HostCliError(
                f"unresolved placeholder '{{{{{name}}}}}' in command "
                f"template: {template}")
        return str(params[name])

    return re.sub(r"\{\{(\w+)\}\}", _sub, template)


def judge_keywords(lines, require_exit_zero: bool = False,
                   exit_code: int = 0) -> tuple:
    """Joint verdict (negative wins, same policy as fct_exec).

    Returns ``(verdict, reason)`` with verdict in ``"Pass"|"Fail"``.
    With ``require_exit_zero`` a non-zero exit code alone fails even
    without a negative keyword in the output.
    """
    text = "\n".join(lines)
    for kw in FAIL_KEYWORDS:
        if kw in text:
            return "Fail", f"negative keyword '{kw}'"
    if require_exit_zero and exit_code != 0:
        return "Fail", f"exit code {exit_code} != 0"
    for kw in PASS_KEYWORDS:
        if kw in text:
            return "Pass", f"positive keyword '{kw}'"
    # no keyword at all: fall back to the exit code
    if require_exit_zero or exit_code == 0:
        return "Pass", "exit code 0 (no keywords)"
    return "Fail", f"exit code {exit_code} (no keywords)"


def extract_items(lines, regex_extracts: dict) -> dict:
    """Run named regexes over the output; first match wins per name.

    ``regex_extracts`` maps item name -> regex string (group 1 is the
    captured value).  Returns ``{name: value}`` for report items;
    unmatched names are simply absent.
    """
    text = "\n".join(lines)
    items: dict = {}
    for name, pattern in (regex_extracts or {}).items():
        match = re.search(pattern, text)
        if match:
            items[name] = match.group(1) if match.groups() else match.group(0)
    return items


class HostCliResult:
    """One executed command: lines, exit code, elapsed, verdict, items."""

    def __init__(self, command: str, lines: list, exit_code: int,
                 elapsed_s: float, verdict: str, reason: str,
                 items: dict) -> None:
        self.command = command
        self.lines = lines
        self.exit_code = exit_code
        self.elapsed_s = elapsed_s
        self.verdict = verdict
        self.reason = reason
        self.items = items


class HostCliRunner:
    """Uniform host-side command executor (P3-B4 Module C)."""

    def __init__(self, log_sink=None, station_id: str = "",
                 user: str = "") -> None:
        """`log_sink` receives one EventLog string per command (the
        GUI runner passes its ``_log``); identity fields travel with
        every line per the global red line."""
        self._log = log_sink or (lambda _msg: None)
        self.station_id = station_id
        self.user = user

    def _identity(self) -> str:
        return f"[{self.station_id}] [{self.user}]"

    def run(self, template: str, params: dict | None = None,
            timeout_s: float = 30.0, cwd: str = "",
            env_extra: dict | None = None,
            regex_extracts: dict | None = None,
            require_exit_zero: bool = False,
            split_stderr: bool = True) -> HostCliResult:
        """Render, execute and judge one command template."""
        command = render_template(template, params or {})
        env = None
        if env_extra:
            env = dict(os.environ)
            env.update({str(k): str(v) for k, v in env_extra.items()})

        proc = subprocess.Popen(
            command, shell=True, cwd=cwd or None, env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if split_stderr
            else subprocess.STDOUT,
            text=True, errors="replace")

        lines: list = []
        err_lines: list = []
        start = time.monotonic()
        # collector threads: both pipes are read concurrently so a
        # chatty stderr can never deadlock against stdout polling
        out = proc.stdout
        err = proc.stderr

        def _pump(stream, sink, prefix=""):
            for line in stream:
                sink.append(f"{prefix}{line.rstrip(chr(13) + chr(10))}"
                            if prefix else line.rstrip("\r\n"))

        t_out = threading.Thread(target=_pump, args=(out, lines),
                                 daemon=True)
        t_err = (threading.Thread(
            target=_pump, args=(err, err_lines, "[stderr] "))
            if err is not None else None)
        t_out.start()
        if t_err:
            t_err.start()

        killed = False
        try:
            proc.wait(timeout=max(timeout_s, 0.1))
            killed = False
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            killed = True
        t_out.join(2.0)
        if t_err:
            t_err.join(2.0)
        lines.extend(err_lines)
        if killed:
            lines.append(f"{TIMEOUT_MARK} after {timeout_s}s")
        exit_code = proc.returncode if proc.returncode is not None else -1
        elapsed = time.monotonic() - start

        verdict, reason = judge_keywords(
            lines, require_exit_zero=require_exit_zero,
            exit_code=exit_code)
        items = extract_items(lines, regex_extracts)
        self._log(
            f"{self._identity()} host_cli: {command} | "
            f"{elapsed:.2f}s exit={exit_code} -> {verdict} ({reason})")
        return HostCliResult(command, lines, exit_code, elapsed,
                             verdict, reason, items)

    @staticmethod
    def _read_available(stream) -> list:
        """Read whatever stderr bytes are buffered right now."""
        out: list = []
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                out.append(str(line).rstrip("\r\n"))
        except (ValueError, OSError):
            pass
        return out
