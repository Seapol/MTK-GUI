# -*- coding: utf-8 -*-
"""Shared infrastructure for the host-side RF test wrappers (WiFi /
Bluetooth).

The RF wrappers drive the Host PC's built-in wireless adapters through
documentated Windows command line tools (``netsh``, ``ping``,
``iperf3``) and PowerShell + WinRT probe scripts.  The tool execution
is abstracted behind :class:`CommandExecutor` - the injection point for
the mocked executor used by the unit tests and the headless demo.

Result objects follow docs/interface_spec.md section 2:
:class:`~mtkgui.drivers.base.MeasurementResult`.  The aggregated
verdict of a full RF test sequence is an
:class:`RFTestReport` (additive type, see interface risk note in the
module owners' report).
"""

from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from mtkgui.drivers.base import MeasurementResult, Status
from mtkgui.drivers.errors import InstrumentIOError, InstrumentTimeoutError


@dataclass
class CommandOutcome:
    """Result of one executed command line tool invocation.

    Attributes:
        command:    Argument list that was executed.
        returncode: Process exit code.
        stdout:     Decoded standard output.
        stderr:     Decoded standard error output.
    """

    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class CommandExecutor(ABC):
    """Abstract command runner (injection point for tests / demo).

    Concrete implementations run one argument list and collect the
    output.  Failures are mapped to the shared driver error types:
    a command timeout raises
    :class:`~mtkgui.drivers.errors.InstrumentTimeoutError`, an
    environment error (missing tool) raises
    :class:`~mtkgui.drivers.errors.InstrumentIOError`.
    """

    @abstractmethod
    def run(self, command: list[str], timeout_s: float) -> CommandOutcome:
        """Execute one command.

        Args:
            command:   Argument list (argv style, no shell).
            timeout_s: Wall clock timeout in seconds.

        Returns:
            :class:`CommandOutcome` with the exit code and outputs.

        Raises:
            InstrumentTimeoutError: The command exceeded the timeout.
            InstrumentIOError:      The tool could not be executed.
        """


class SubprocessExecutor(CommandExecutor):
    """Real executor: runs the command via :mod:`subprocess` (no
    shell), maps failures to the shared error types."""

    def run(self, command: list[str], timeout_s: float) -> CommandOutcome:
        """Execute one command via ``subprocess.run``.

        Args:
            command:   Argument list (argv style, no shell).
            timeout_s: Wall clock timeout in seconds.

        Returns:
            :class:`CommandOutcome` with the exit code and outputs.

        Raises:
            InstrumentTimeoutError: The command exceeded the timeout.
            InstrumentIOError:      The tool could not be executed
                                    (missing binary, permissions).
        """
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True,
                timeout=max(0.1, float(timeout_s)), check=False)
        except subprocess.TimeoutExpired as exc:
            raise InstrumentTimeoutError(
                f"command timed out after {timeout_s}s: "
                f"{' '.join(command)}") from exc
        except OSError as exc:
            raise InstrumentIOError(
                f"cannot execute {command[0]!r}: {exc}") from exc
        return CommandOutcome(
            command=list(command), returncode=proc.returncode,
            stdout=proc.stdout or "", stderr=proc.stderr or "")


class ScriptedExecutor(CommandExecutor):
    """Deterministic executor for tests and the headless demo.

    Script keys are space-joined command prefixes and are matched
    against the executed command with the longest-prefix rule, so
    ``"netsh"`` matches every netsh invocation while
    ``"netsh wlan show interfaces"`` selects the exact subcommand.
    Values are canned :class:`CommandOutcome` objects or exceptions to
    raise.  Every executed command is recorded in ``history`` so tests
    and the demo can assert on the exact tool invocations.
    """

    def __init__(
        self,
        script: dict[str, CommandOutcome | Exception] | None = None,
    ) -> None:
        """Create the executor.

        Args:
            script: Mapping from a command prefix (space-joined tokens)
                    to the outcome (or the exception to raise).
        """
        self.script = dict(script or {})
        self.history: list[list[str]] = []

    def _select(self, tokens: list[str]):
        """Find the scripted entry with the longest matching prefix.

        Args:
            tokens: The executed command's argument list.

        Returns:
            The scripted outcome / exception, or ``None`` when no key
            matches.
        """
        best_key = None
        best_len = -1
        for key in self.script:
            parts = key.split()
            if len(parts) > len(tokens):
                continue
            if tokens[:len(parts)] == parts and len(parts) > best_len:
                best_key, best_len = key, len(parts)
        return self.script.get(best_key) if best_key else None

    def run(self, command: list[str], timeout_s: float) -> CommandOutcome:
        """Return the scripted outcome for the command.

        Args:
            command:   Argument list; the longest matching prefix key
                       selects the outcome.
            timeout_s: Ignored (scripted).

        Returns:
            The scripted :class:`CommandOutcome`.

        Raises:
            InstrumentIOError:   No script entry matches.
            (as scripted):      The scripted exception, re-raised.
        """
        cmd = list(command)
        self.history.append(cmd)
        entry = self._select(cmd)
        if entry is None:
            raise InstrumentIOError(
                f"ScriptedExecutor: no scripted outcome for "
                f"{' '.join(cmd[:3])!r}")
        if isinstance(entry, Exception):
            raise entry
        return entry


@dataclass
class RFTestReport:
    """Structured verdict + measurement values of one full RF test.

    Attributes:
        verdict: Overall status.  ``Status.OK`` means every measured
                 value is within the caller-supplied limits; FAIL
                 means at least one limit is violated, one step
                 reported ERROR/TIMEOUT, or the DUT was not found.
        results: Every phase measurement as a spec
                 :class:`MeasurementResult`.
        summary: Human readable one-line summary for logs / CSV.
    """

    verdict: Status
    results: list[MeasurementResult] = field(default_factory=list)
    summary: str = ""

    def add(self, result: MeasurementResult) -> None:
        """Append one phase result.

        Args:
            result: The measurement to append.
        """
        self.results.append(result)


def netsh_signal_to_dbm(percent: int) -> float:
    """Convert the netsh ``Signal : NN%`` value to an RSSI estimate.

    netsh reports signal quality as a percentage; the widely used
    linear mapping for Windows WLAN reports is ``dBm = pct / 2 - 100``
    (100% -> -50 dBm, 50% -> -75 dBm, 0% -> -100 dBm).  This is an
    estimate, not a calibrated reading - VERIFY against the station's
    reference tooling at bring-up.

    Args:
        percent: Signal quality percentage (0..100).

    Returns:
        RSSI estimate in dBm.
    """
    return (max(0, min(100, int(percent))) / 2.0) - 100.0


def parse_ping_windows(output: str, expected: int) -> tuple[float, float]:
    """Parse Windows ``ping -n <count>`` output.

    Args:
        output:   Raw ping stdout.
        expected: Number of echo requests sent.

    Returns:
        ``(avg_latency_ms, packet_loss_pct)`` tuple.  When no reply
        was received at all, ``(0.0, 100.0)`` is returned; the loss
        percentage falls back to counting replies when the localized
        summary line cannot be parsed.

    Raises:
        InstrumentIOError: The output contains no parsable statistics
                           at all (e.g. wrong tool output).
    """
    import re

    times = [float(v) for v in
             re.findall(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", output or "")]
    loss_match = re.search(r"Lost\s*=\s*\d+\s*\((\d+(?:\.\d+)?)%", output)
    if loss_match is not None:
        loss = float(loss_match.group(1))
    elif expected > 0:
        loss = round((expected - len(times)) / expected * 100.0, 1)
    else:
        loss = 100.0
    if not times and loss >= 100.0 and "Lost" not in (output or ""):
        raise InstrumentIOError("ping output contains no statistics")
    avg = round(sum(times) / len(times), 2) if times else 0.0
    return avg, min(loss, 100.0)


def parse_iperf_json(payload: str) -> float:
    """Extract the received throughput (Mbit/s) from ``iperf3 -J``.

    Args:
        payload: Raw JSON stdout of ``iperf3 -c <host> -t <sec> -J``.

    Returns:
        Throughput in Mbit/s (``end.sum_received.bits_per_second``).

    Raises:
        InstrumentIOError: Missing tool, malformed JSON or a failed
                           iperf run (``error`` element present).
    """
    import json

    try:
        data = json.loads(payload or "{}")
    except json.JSONDecodeError as exc:
        raise InstrumentIOError(
            f"iperf3 returned invalid JSON: {exc}") from exc
    if "error" in data:
        raise InstrumentIOError(f"iperf3 failed: {data['error']}")
    try:
        bits = float(data["end"]["sum_received"]["bits_per_second"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InstrumentIOError(
            f"iperf3 JSON misses end.sum_received.bits_per_second"
            f": {exc}") from exc
    return round(bits / 1e6, 2)
