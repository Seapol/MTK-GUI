# -*- coding: utf-8 -*-
"""Unit tests for the pyserial transport over pyserial's loop:// URL.

``loop://`` is a pyserial built-in test device (no OS port needed):
bytes written to the port are immediately available on the read side,
so the write path, read path and timeout mapping of SerialTransport
are exercised end-to-end without hardware.
"""

from __future__ import annotations

import pytest

from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentIOError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.transport_serial import SerialTransport


@pytest.fixture
def transport() -> SerialTransport:
    """Return a SerialTransport opened on pyserial's loop:// device."""
    transport = SerialTransport()
    transport.open("loop://", {"timeout_s": 0.5})
    return transport


def test_open_close_lifecycle(transport):
    """open()/close() toggle the flag; close is idempotent."""
    assert transport._is_open
    transport.close()
    assert not transport._is_open
    transport.close()  # idempotent


def test_open_rejects_empty_address():
    """open() without an address raises InstrumentConfigError."""
    transport = SerialTransport()
    with pytest.raises(InstrumentConfigError):
        transport.open("  ", {})


def test_open_rejects_bad_options():
    """open() with non-numeric options raises InstrumentConfigError."""
    transport = SerialTransport()
    with pytest.raises(InstrumentConfigError):
        transport.open("loop://", {"baudrate": "fast"})


def test_write_before_open_raises():
    """write() before open() raises ConnectionLostError."""
    transport = SerialTransport()
    with pytest.raises(ConnectionLostError):
        transport.write("*IDN?")


def test_query_before_open_raises():
    """query() before open() raises ConnectionLostError."""
    transport = SerialTransport()
    with pytest.raises(ConnectionLostError):
        transport.query("*IDN?")


def test_write_appends_terminator(transport):
    """write() appends the LF terminator; loop:// echoes it back."""
    transport.write("*RST")
    raw = transport._port.read(5)
    assert raw == b"*RST\n"


def test_query_reads_echoed_reply(transport):
    """query() reads until the terminator and strips it."""
    # loop:// echoes the written command back, so the reply is the
    # command itself - this validates framing + decoding + stripping
    reply = transport.query("*IDN?")
    assert reply == "*IDN?"


def test_query_timeout_maps_to_instrument_timeout(transport):
    """A silent instrument (no terminator reply) raises
    InstrumentTimeoutError."""
    # simulate an instrument that never answers: read() returns empty
    transport._port.read = lambda *args, **kwargs: b""  # type: ignore[method-assign]
    with pytest.raises(InstrumentTimeoutError):
        transport.query("*IDN?")


def test_unopenable_port_maps_to_io_error():
    """An invalid OS port name maps to InstrumentIOError."""
    transport = SerialTransport()
    with pytest.raises(InstrumentIOError):
        # port numbers above the OS limit cannot be opened
        transport.open("/dev/does-not-exist-mtk-gui", {})
