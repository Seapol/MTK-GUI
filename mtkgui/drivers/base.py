# -*- coding: utf-8 -*-
"""Abstract base driver and result model for instrument drivers.

Implements the Instrument Driver Module contract of
docs/interface_spec.md (section 2):

* ``Transport``       - injectable message/response link (serial today;
                        VISA / LAN / process transports can be injected
                        without touching the drivers),
* ``InstrumentDriver``- abstract base class with the open / close /
                        write / query / identify lifecycle,
* ``Status``          - OK / FAIL / ERROR / TIMEOUT status codes,
* ``MeasurementResult``- the typed result every measurement returns.

Design rules enforced here:

* Drivers never decide PASS/FAIL.  FAIL is a limit decision made by the
  test flow engine; drivers report OK / ERROR / TIMEOUT only.
* Instrument addresses come from the caller (engine), which reads them
  from ``config/`` YAML.  No address is hardcoded in this package.
* Transport-specific exceptions never leak: they are mapped to the
  shared error types of :mod:`mtkgui.drivers.errors`.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentError,
    InstrumentIOError,
)

_LOG = logging.getLogger("mtkgui.drivers")

_FLOAT_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_float(reply: str) -> float:
    """Parse the leading number of a SCPI reply.

    Args:
        reply: Raw instrument reply, e.g. ``"+1.23456700E+01"``.

    Returns:
        The parsed float.

    Raises:
        InstrumentIOError: The reply contains no parsable number.
    """
    match = _FLOAT_RE.search(reply or "")
    if match is None:
        raise InstrumentIOError(f"cannot parse SCPI number from {reply!r}")
    return float(match.group(0))


def utc_now() -> datetime:
    """Return the current UTC time with timezone info attached.

    Returns:
        Timezone-aware ``datetime`` in UTC, used to timestamp
        measurements.
    """
    return datetime.now(timezone.utc)


class Status(str, Enum):
    """Status code of a measurement result.

    OK      - the instrument delivered a valid reading; the limit
              (PASS/FAIL) decision belongs to the engine.
    FAIL    - out of limits (reserved for engine-side construction,
              drivers do not emit it).
    ERROR   - instrument fault (the driver raises an
              :class:`InstrumentError` subclass instead in most paths).
    TIMEOUT - the instrument did not answer in time.
    """

    OK = "OK"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


@dataclass
class MeasurementResult:
    """One executed measurement or instrument operation.

    Attributes:
        value:     Measured value (numeric) or matched/returned text.
        unit:      Engineering unit of the value, e.g. "Ohm", "V", "Hz",
                   or "" when the value carries no unit.
        status:    :class:`Status` of the operation.
        timestamp: UTC timestamp of the reading.
        source:    Instrument model + channel, e.g. "DAQ973A/CH101".
    """

    value: float | str
    unit: str
    status: Status
    timestamp: datetime
    source: str

    @classmethod
    def ok(cls, value: float | str, unit: str, source: str) -> "MeasurementResult":
        """Build a successful result stamped with the current UTC time.

        Args:
            value:  Measured value (numeric) or returned text.
            unit:   Engineering unit, "" when unitless.
            source: Instrument model + channel label.

        Returns:
            A :class:`MeasurementResult` with ``Status.OK``.
        """
        return cls(
            value=value, unit=unit, status=Status.OK,
            timestamp=utc_now(), source=source,
        )

    @classmethod
    def failed(
        cls, value: float | str, unit: str, source: str,
        status: Status = Status.ERROR,
    ) -> "MeasurementResult":
        """Build an unsuccessful result stamped with the current time.

        Args:
            value:  Value or text observed when the operation failed.
            unit:   Engineering unit, "" when unitless.
            source: Instrument model + channel label.
            status: Failure status, ``Status.ERROR`` or
                    ``Status.TIMEOUT``.

        Returns:
            A :class:`MeasurementResult` with the requested status.
        """
        return cls(
            value=value, unit=unit, status=status,
            timestamp=utc_now(), source=source,
        )


class Transport(ABC):
    """Abstract message/response link between a driver and an
    instrument.

    A transport owns the physical (or virtual) connection: opening the
    port, framing commands with the line terminator, applying the I/O
    timeout, and decoding replies.  Transports raise the shared error
    types of :mod:`mtkgui.drivers.errors` on failure.

    Subclasses must keep ``open()`` idempotent-safe: calling ``open()``
    on an already open transport, or ``close()`` on a closed one, must
    not raise.
    """

    @abstractmethod
    def open(self, address: str, options: dict) -> None:
        """Open the connection to the instrument.

        Args:
            address: Transport-specific instrument address (e.g. a
                     pyserial port name or URL, a VISA resource string).
                     Supplied by the engine from ``config/`` YAML.
            options: Transport options dict (terminator, timeout_s,
                     baudrate, ...).  Unknown options are ignored.

        Raises:
            InstrumentConfigError: Bad or missing options.
            InstrumentIOError:     The port could not be opened.
        """

    @abstractmethod
    def close(self) -> None:
        """Close the connection.  Must be safe to call twice."""

    @abstractmethod
    def write(self, command: str) -> None:
        """Send one command line to the instrument.

        Args:
            command: Command string without terminator; the transport
                     appends the configured line terminator.

        Raises:
            ConnectionLostError:    The transport is not open.
            InstrumentIOError:      Writing failed.
            InstrumentTimeoutError: Write timed out.
        """

    @abstractmethod
    def query(self, command: str) -> str:
        """Send one command and return the instrument reply line.

        Args:
            command: Command string without terminator.

        Returns:
            The decoded reply string with the terminator stripped.

        Raises:
            ConnectionLostError:    The transport is not open.
            InstrumentIOError:      Writing failed.
            InstrumentTimeoutError: No (complete) reply within the
                                    configured timeout.
        """


class InstrumentDriver(ABC):
    """Abstract base class for all station instrument drivers.

    The lifecycle is ``open() -> (write() / query() / measure...) ->
    close()``.  A transport can be injected via the constructor; when
    omitted, a concrete driver creates its default transport inside
    ``open()``.  The constructor parameter is the mocked-transport
    injection point used by the unit tests.

    Attributes:
        address: Instrument address used in the last ``open()`` call.
        options: Options dict used in the last ``open()`` call.
    """

    def __init__(self, transport: Transport | None = None) -> None:
        """Create the driver.

        Args:
            transport: Transport to use, or ``None`` to let the
                       concrete driver build its default transport in
                       ``open()``.  Tests inject a mocked transport
                       here.
        """
        self._transport = transport
        self.address: str | None = None
        self.options: dict = {}
        self._is_open: bool = False

    # -- lifecycle ---------------------------------------------------------

    @abstractmethod
    def open(self, address: str, options: dict) -> None:
        """Open the instrument connection.

        Args:
            address: Instrument address from ``config/`` YAML.
            options: Driver options dict (may be empty).

        Raises:
            InstrumentConfigError: Bad or missing parameters.
            InstrumentIOError:     The instrument could not be reached.
            ConnectionLostError:   Connection dropped during opening.
        """

    @abstractmethod
    def close(self) -> None:
        """Close the instrument connection.  Safe to call twice."""

    @abstractmethod
    def identify(self) -> str:
        """Identify the instrument.

        Returns:
            Identification string, typically the ``*IDN?`` reply for
            SCPI instruments or the tool banner for subprocess tools.

        Raises:
            ConnectionLostError:    Not connected.
            InstrumentTimeoutError: No reply.
            InstrumentIOError:      Communication failure.
        """

    # -- message exchange ----------------------------------------------------

    def write(self, command: str) -> None:
        """Send one command to the instrument.

        Args:
            command: Command string without terminator.

        Raises:
            ConnectionLostError: Not connected.
            InstrumentIOError:   Writing failed.
            InstrumentTimeoutError: Write timed out.
        """
        self._require_open()
        try:
            self._transport.write(command)
        except InstrumentError:
            raise
        except Exception as exc:  # map foreign transport errors
            raise InstrumentIOError(
                f"write failed on {self.address!r}: {exc}") from exc
        _LOG.debug("%s write: %s", self._log_prefix(), command)

    def query(self, command: str) -> str:
        """Send one command and return the instrument reply.

        Args:
            command: Command string without terminator.

        Returns:
            The decoded reply string with the terminator stripped.

        Raises:
            ConnectionLostError: Not connected.
            InstrumentIOError:   Communication failure.
            InstrumentTimeoutError: No reply in time.
        """
        self._require_open()
        try:
            reply = self._transport.query(command)
        except InstrumentError:
            raise
        except Exception as exc:  # map foreign transport errors
            raise InstrumentIOError(
                f"query failed on {self.address!r}: {exc}") from exc
        _LOG.debug("%s query: %s -> %r", self._log_prefix(), command, reply)
        return reply

    # -- helpers -------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Return ``True`` when the driver is currently open."""
        return self._is_open

    @property
    def transport(self) -> Transport:
        """Return the transport in use (exposed for tests and engine).

        Raises:
            ConnectionLostError: The driver was never opened and has no
                                 injected transport.
        """
        if self._transport is None:
            raise ConnectionLostError(
                f"{type(self).__name__}: no transport (not open)")
        return self._transport

    def check_errors(self) -> list[str]:
        """Drain the SCPI status/error register queue.

        Sends ``SYST:ERR?`` until the queue reports empty (``+0``) or a
        safety cap of 100 entries is reached.

        Returns:
            List of raw error strings; empty when the queue was clear.
        """
        errors: list[str] = []
        for _ in range(100):
            reply = self.query("SYST:ERR?")
            code = reply.split(",", 1)[0].strip()
            if code in ("+0", "0", "+0,\"No error\""):
                break
            errors.append(reply)
        return errors

    def _require_open(self) -> None:
        """Guard every message exchange behind an open connection.

        Raises:
            ConnectionLostError: The driver is not open.
        """
        if not self._is_open:
            raise ConnectionLostError(
                f"{type(self).__name__}: not open "
                f"(call open(address, options) first)")

    def _log_prefix(self) -> str:
        """Return a stable log prefix like ``DAQ973ADriver@GPIB0::10``.

        Returns:
            Short string combining driver class and address.
        """
        return f"{type(self).__name__}@{self.address}"

    @staticmethod
    def _validate_address(address: str) -> str:
        """Validate a caller-supplied instrument address.

        Args:
            address: Address string from the YAML equipment section.

        Returns:
            The stripped, non-empty address.

        Raises:
            InstrumentConfigError: The address is empty or not a
                                   string.
        """
        if not isinstance(address, str) or not address.strip():
            raise InstrumentConfigError(
                "instrument address must be a non-empty string "
                "(read from config/ YAML, never hardcoded)")
        return address.strip()
