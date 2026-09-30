# -*- coding: utf-8 -*-
"""Shared fixtures for the drivers unit tests.

The mocked transport is the injection point of the driver design: it
records every command written and replays scripted replies, so every
driver is exercised without hardware.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# make the repo root importable regardless of how pytest is invoked
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mtkgui.drivers.base import Transport  # noqa: E402
from mtkgui.drivers.errors import (  # noqa: E402
    ConnectionLostError,
    InstrumentError,
    InstrumentIOError,
    InstrumentTimeoutError,
)

#: Default ``*IDN?`` reply reused by most driver tests.
MOCK_IDN = "Keysight Technologies,DAQ973A,MY00000001,1.2.3"


class MockTransport(Transport):
    """Scriptable in-memory transport for driver unit tests.

    The ``script`` dict maps the exact command string to the reply
    string.  Commands missing from the script answer with ``default_reply``
    (or raise, see ``on_unknown``).  Every written command is appended
    to ``written`` so tests assert on the exact SCPI strings produced
    by the drivers (locking the command set against accidental edits).

    Attributes:
        script:        Command -> reply mapping.
        default_reply: Reply used for commands not in ``script``.
        on_unknown:    ``None`` or an exception instance to raise for
                       unknown commands.
        written:       Ordered list of commands passed to ``write``.
        fault_on:      Optional substring; when a command contains it,
                       ``fault`` is raised instead of replying.
        fault:         Exception to raise for faulting commands.
    """

    def __init__(
        self,
        script: dict[str, str] | None = None,
        default_reply: str = "",
        on_unknown: Exception | None = None,
    ) -> None:
        self.script: dict[str, str] = dict(script or {})
        self.default_reply = default_reply
        self.on_unknown = on_unknown
        self.written: list[str] = []
        self.fault_on: str | None = None
        self.fault: Exception | None = None
        self._is_open = False

    # -- Transport interface ---------------------------------------------------

    def open(self, address: str, options: dict) -> None:
        """Mark the transport open and record the call."""
        if not address:
            raise InstrumentIOError("MockTransport: empty address")
        self.address = address
        self.options = dict(options or {})
        self._is_open = True

    def close(self) -> None:
        """Mark the transport closed.  Safe to call twice."""
        self._is_open = False

    def write(self, command: str) -> None:
        """Record one command.

        Args:
            command: Command string from the driver.

        Raises:
            ConnectionLostError:    Transport not open.
            InstrumentTimeoutError: ``fault`` configured and matches.
        """
        if not self._is_open:
            raise ConnectionLostError("MockTransport: not open")
        self.written.append(command)
        if self.fault_on and self.fault_on in command and self.fault:
            raise self.fault

    def query(self, command: str) -> str:
        """Record one command and return the scripted reply.

        Args:
            command: Command string from the driver.

        Returns:
            The scripted reply for this command, else
            ``default_reply``.

        Raises:
            ConnectionLostError:    Transport not open.
            InstrumentTimeoutError: Timeout fault configured.
            InstrumentIOError:      I/O fault configured or unknown
                                    command with ``on_unknown`` set.
        """
        self.write(command)
        if self.fault_on and self.fault_on in command:
            if isinstance(self.fault, InstrumentTimeoutError):
                raise self.fault
            if isinstance(self.fault, InstrumentIOError):
                raise self.fault
        if command in self.script:
            return self.script[command]
        if self.on_unknown is not None:
            raise self.on_unknown
        return self.default_reply


@pytest.fixture
def mock_transport() -> MockTransport:
    """Return an open mock transport with the standard ``*IDN?`` script."""
    transport = MockTransport({"*IDN?": MOCK_IDN})
    transport.open("MOCK0", {})
    return transport
