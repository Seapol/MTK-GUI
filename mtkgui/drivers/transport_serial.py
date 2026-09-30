# -*- coding: utf-8 -*-
"""pyserial-backed SCPI transport.

The default real transport shipped with the drivers package.  It uses
pyserial (already a project dependency) via ``serial_for_url`` so both
plain OS ports (``COM3``, ``/dev/ttyUSB0``) and pyserial URL schemes
(``loop://``, ``socket://``, ``alt://``) work with the same code path.

VISA / LAN transports for GPIB-attached instruments are injected by the
engine later; they only need to satisfy :class:`mtkgui.drivers.base.Transport`.
"""

from __future__ import annotations

import logging

import serial

from mtkgui.drivers.base import Transport
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentIOError,
    InstrumentTimeoutError,
)

_LOG = logging.getLogger("mtkgui.drivers.serial")

_DEFAULT_TERMINATOR = "\n"
_DEFAULT_TIMEOUT_S = 5.0
_DEFAULT_BAUDRATE = 9600


class SerialTransport(Transport):
    """Message/response transport over a pyserial port.

    Options understood by ``open()``:

    * ``baudrate`` (int, default 9600)
    * ``bytesize`` (int, default 8)
    * ``parity``   (str, default "N")
    * ``stopbits`` (int, default 1)
    * ``terminator`` (str, default "\\n") - appended to writes, used to
      frame replies
    * ``timeout_s`` (float, default 5.0) - I/O timeout
    """

    def __init__(self) -> None:
        """Create a closed transport."""
        self._port = None
        self._terminator = _DEFAULT_TERMINATOR
        self._timeout_s = _DEFAULT_TIMEOUT_S
        self._is_open = False

    def open(self, address: str, options: dict) -> None:
        """Open the serial port.

        Args:
            address: pyserial port name or URL (from ``config/`` YAML).
            options: See class docstring.  May be empty.

        Raises:
            InstrumentConfigError: Bad option value or empty address.
            InstrumentIOError:     The port could not be opened.
        """
        if self._is_open:
            return
        opts = options or {}
        address = (address or "").strip()
        if not address:
            raise InstrumentConfigError(
                "SerialTransport.open: empty address")
        try:
            self._timeout_s = float(opts.get("timeout_s", _DEFAULT_TIMEOUT_S))
            self._terminator = str(opts.get("terminator", _DEFAULT_TERMINATOR))
            kwargs = dict(
                baudrate=int(opts.get("baudrate", _DEFAULT_BAUDRATE)),
                bytesize=int(opts.get("bytesize", 8)),
                parity=str(opts.get("parity", "N")),
                stopbits=int(opts.get("stopbits", 1)),
                timeout=self._timeout_s,
                write_timeout=self._timeout_s,
            )
        except (TypeError, ValueError) as exc:
            raise InstrumentConfigError(
                f"SerialTransport.open: bad option - {exc}") from exc
        try:
            self._port = serial.serial_for_url(address, **kwargs)
        except serial.SerialException as exc:
            raise InstrumentIOError(
                f"SerialTransport.open: cannot open {address!r}: {exc}"
            ) from exc
        self._is_open = True
        _LOG.info("serial transport open: %s (%r)", address, kwargs)

    def close(self) -> None:
        """Close the serial port.  Safe to call more than once."""
        if self._port is not None:
            try:
                if self._port.is_open:
                    self._port.close()
            except serial.SerialException as exc:
                _LOG.warning("error while closing serial port: %s", exc)
        self._port = None
        self._is_open = False

    def write(self, command: str) -> None:
        """Send one command line (terminator appended).

        Args:
            command: Command string without terminator.

        Raises:
            ConnectionLostError:    Transport not open.
            InstrumentIOError:      Write failed.
            InstrumentTimeoutError: Write timed out.
        """
        port = self._require_open()
        payload = (command + self._terminator).encode("latin-1")
        try:
            written = port.write(payload)
            port.flush()
        except serial.SerialTimeoutException as exc:
            raise InstrumentTimeoutError(
                f"SerialTransport.write timed out: {exc}") from exc
        except serial.SerialException as exc:
            raise InstrumentIOError(
                f"SerialTransport.write failed: {exc}") from exc
        if written is not None and written != len(payload):
            raise InstrumentIOError(
                f"SerialTransport.write short write: "
                f"{written}/{len(payload)} bytes")

    def query(self, command: str) -> str:
        """Send one command and read the reply line.

        Args:
            command: Command string without terminator.

        Returns:
            Decoded reply with the terminator stripped.

        Raises:
            ConnectionLostError:    Transport not open.
            InstrumentIOError:      Write failed.
            InstrumentTimeoutError: No complete reply within the
                                    configured timeout.
        """
        self.write(command)
        port = self._require_open()
        try:
            # the port read timeout configured in open() governs
            raw = port.read_until(self._terminator.encode("latin-1"))
        except serial.SerialException as exc:
            raise InstrumentIOError(
                f"SerialTransport.query read failed: {exc}") from exc
        if not raw or not raw.endswith(self._terminator.encode("latin-1")):
            raise InstrumentTimeoutError(
                f"SerialTransport.query: no complete reply within "
                f"{self._timeout_s}s for {command!r}")
        return raw.decode("latin-1").rstrip("\r\n")

    # -- helpers -------------------------------------------------------------

    def _require_open(self):
        """Return the open serial port or raise ConnectionLostError.

        Returns:
            The underlying ``serial.SerialBase`` instance.

        Raises:
            ConnectionLostError: The transport is not open.
        """
        if not self._is_open or self._port is None:
            raise ConnectionLostError("SerialTransport: not open")
        return self._port
