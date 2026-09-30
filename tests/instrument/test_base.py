# -*- coding: utf-8 -*-
"""Unit tests for the driver base module (interface_spec.md section 2)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mtkgui.drivers.base import (
    InstrumentDriver,
    MeasurementResult,
    Status,
    Transport,
    parse_float,
    utc_now,
)
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentError,
    InstrumentIOError,
    InstrumentTimeoutError,
)


class _MinimalDriver(InstrumentDriver):
    """Concrete driver stub implementing the abstract lifecycle."""

    def open(self, address: str, options: dict) -> None:
        self.address = address
        self.options = dict(options or {})
        self._transport.open(address, self.options)
        self._is_open = True

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
        self._is_open = False

    def identify(self) -> str:
        self._require_open()
        return self.query("*IDN?")


# ---------------------------------------------------------------------------
# shared exceptions (interface_spec.md section 1.3)
# ---------------------------------------------------------------------------


def test_exception_hierarchy():
    """All shared exceptions derive from InstrumentError."""
    assert issubclass(InstrumentTimeoutError, InstrumentError)
    assert issubclass(InstrumentIOError, InstrumentError)
    assert issubclass(InstrumentConfigError, InstrumentError)
    assert issubclass(ConnectionLostError, InstrumentError)
    assert issubclass(InstrumentError, Exception)


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


def test_status_values():
    """Status defines exactly the four spec'd codes."""
    assert [s.value for s in Status] == ["OK", "FAIL", "ERROR", "TIMEOUT"]


# ---------------------------------------------------------------------------
# MeasurementResult
# ---------------------------------------------------------------------------


def test_measurement_result_fields():
    """MeasurementResult carries the five spec'd fields."""
    ts = utc_now()
    result = MeasurementResult(
        value=1.5, unit="Ohm", status=Status.OK, timestamp=ts,
        source="DAQ973A/CH101")
    assert result.value == 1.5
    assert result.unit == "Ohm"
    assert result.status is Status.OK
    assert result.timestamp is ts
    assert result.source == "DAQ973A/CH101"


def test_measurement_result_ok_factory():
    """ok() stamps Status.OK with a timezone-aware UTC timestamp."""
    before = datetime.now(timezone.utc)
    result = MeasurementResult.ok(3.3, "V", "N5747A")
    after = datetime.now(timezone.utc)
    assert result.status is Status.OK
    assert result.value == 3.3
    assert result.unit == "V"
    assert before <= result.timestamp <= after
    assert result.timestamp.tzinfo is timezone.utc


def test_measurement_result_failed_factory():
    """failed() carries ERROR / TIMEOUT status."""
    err = MeasurementResult.failed("", "V", "N5747A", Status.ERROR)
    tmo = MeasurementResult.failed("", "V", "N5747A", Status.TIMEOUT)
    assert err.status is Status.ERROR
    assert tmo.status is Status.TIMEOUT


# ---------------------------------------------------------------------------
# parse_float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("+1.23456700E+01", 12.34567),
        ("-0.001", -0.001),
        ("+9.90000000E+37", 9.9e37),
        ("123", 123.0),
        (" +5 V", 5.0),
        ("+0,\"No error\"", 0.0),
    ],
)
def test_parse_float_valid(reply, expected):
    """parse_float extracts the leading SCPI number."""
    assert parse_float(reply) == pytest.approx(expected)


def test_parse_float_invalid():
    """parse_float raises InstrumentIOError on non-numeric replies."""
    with pytest.raises(InstrumentIOError):
        parse_float("NAn")


# ---------------------------------------------------------------------------
# driver lifecycle guards
# ---------------------------------------------------------------------------


def test_write_query_before_open_raise():
    """write/query/identify before open() raise ConnectionLostError."""
    from tests.instrument.conftest import MockTransport
    driver = _MinimalDriver(transport=MockTransport())  # never opened
    with pytest.raises(ConnectionLostError):
        driver.write("*RST")
    with pytest.raises(ConnectionLostError):
        driver.query("*IDN?")
    with pytest.raises(ConnectionLostError):
        driver.identify()


def test_transport_property_without_open():
    """transport property raises ConnectionLostError when absent."""
    driver = _MinimalDriver()
    with pytest.raises(ConnectionLostError):
        _ = driver.transport


def test_is_open_flag():
    """is_open reflects the lifecycle."""
    from tests.instrument.conftest import MockTransport
    transport = MockTransport()
    driver = _MinimalDriver(transport=transport)
    assert not driver.is_open
    driver.open("MOCK0", {})
    assert driver.is_open
    driver.close()
    assert not driver.is_open


def test_address_validation():
    """Empty or non-string addresses are rejected as config errors."""
    driver = _MinimalDriver()
    for bad in ("", "   ", None, 42):
        with pytest.raises(InstrumentConfigError):
            driver._validate_address(bad)
    assert driver._validate_address(" GPIB0::10 ") == "GPIB0::10"


# ---------------------------------------------------------------------------
# check_errors
# ---------------------------------------------------------------------------


def test_check_errors_drains_queue():
    """check_errors() stops at the +0 reply and returns no errors."""
    from tests.instrument.conftest import MockTransport
    transport = MockTransport(default_reply='+0,"No error"')
    driver = _MinimalDriver(transport=transport)
    driver.open("MOCK0", {})
    assert driver.check_errors() == []
    assert transport.written == ["SYST:ERR?"]


def test_check_errors_collects_errors():
    """check_errors() returns the error strings before the +0 reply."""
    from tests.instrument.conftest import MockTransport

    class QueueTransport(MockTransport):
        """Replies with queued errors then the empty marker."""

        def __init__(self, replies: list[str]) -> None:
            super().__init__()
            self.replies = list(replies)

        def query(self, command: str) -> str:
            self.write(command)
            if command == "SYST:ERR?":
                if self.replies:
                    item = self.replies.pop(0)
                    return item
                return '+0,"No error"'
            return ""

    transport = QueueTransport(['-113,"Undefined header"'])
    driver = _MinimalDriver(transport=transport)
    driver.open("MOCK0", {})
    assert driver.check_errors() == ['-113,"Undefined header"']
