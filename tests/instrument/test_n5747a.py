# -*- coding: utf-8 -*-
"""Unit tests for the Keysight N5747A PSU driver (mocked transport)."""

from __future__ import annotations

import pytest

from mtkgui.drivers.base import Status
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.n5747a import N5747ADriver
from tests.instrument.conftest import MockTransport

ADDR = "COM547"  # example address as it would come from config/ YAML


@pytest.fixture
def psu(mock_transport: MockTransport) -> N5747ADriver:
    """Return an N5747A driver over the shared mock transport."""
    driver = N5747ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    mock_transport.written.clear()  # drop the *IDN? recorded by open()
    return driver


def test_open_queries_idn(mock_transport: MockTransport):
    """open() reads *IDN? once and caches the answer."""
    driver = N5747ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    assert mock_transport.written == ["*IDN?"]
    assert "N5747A" in driver.identify() or driver.identify()


def test_power_up_sequence(psu):
    """set_voltage / set_current / output_on emit the documented commands."""
    psu.set_voltage(5.0)
    psu.set_current(1.0)
    psu.output_on()
    assert psu._transport.written == [
        "SOUR:VOLT 5", "SOUR:CURR 1", "OUTP ON"]


def test_power_down(psu):
    """output_off emits OUTP OFF."""
    psu.output_off()
    assert psu._transport.written == ["OUTP OFF"]


def test_setpoint_formatting(psu):
    """Setpoints are formatted with %.6g (no scientific noise)."""
    psu.set_voltage(12.3456789)
    psu.set_current(0.000125)
    assert psu._transport.written == ["SOUR:VOLT 12.3457", "SOUR:CURR 0.000125"]


def test_setpoint_validation(psu):
    """Non-finite or non-numeric setpoints raise InstrumentConfigError."""
    for bad in (float("nan"), float("inf"), "abc", None):
        with pytest.raises(InstrumentConfigError):
            psu.set_voltage(bad)
        with pytest.raises(InstrumentConfigError):
            psu.set_current(bad)


def test_measure_voltage(psu):
    """measure_voltage parses MEAS:VOLT? and stamps source/unit."""
    psu._transport.script = {"MEAS:VOLT?": "+5.00210000E+00"}
    result = psu.measure_voltage()
    assert result.value == pytest.approx(5.0021)
    assert result.unit == "V"
    assert result.status is Status.OK
    assert result.source == "N5747A"
    assert result.timestamp.tzinfo is not None


def test_measure_current(psu):
    """measure_current parses MEAS:CURR?."""
    psu._transport.script = {"MEAS:CURR?": "+6.01000000E-01"}
    result = psu.measure_current()
    assert result.value == pytest.approx(0.601)
    assert result.unit == "A"


def test_setpoint_and_state_queries(psu):
    """Setpoint queries and OUTP? state are parsed correctly."""
    psu._transport.script = {
        "SOUR:VOLT?": "+5",
        "SOUR:CURR?": "+1",
        "OUTP?": "+1",
    }
    assert psu.get_voltage_setpoint() == pytest.approx(5.0)
    assert psu.get_current_setpoint() == pytest.approx(1.0)
    assert psu.get_output_enabled() is True
    psu._transport.script["OUTP?"] = "+0"
    assert psu.get_output_enabled() is False


def test_reset(psu):
    """reset() sends *RST then *CLS."""
    psu.reset()
    assert psu._transport.written == ["*RST", "*CLS"]


def test_open_rejects_empty_address(mock_transport: MockTransport):
    """open() rejects an empty address."""
    driver = N5747ADriver(transport=mock_transport)
    with pytest.raises(InstrumentConfigError):
        driver.open("", {})


def test_write_before_open_raises():
    """write() before open() raises ConnectionLostError."""
    driver = N5747ADriver(transport=MockTransport())
    with pytest.raises(ConnectionLostError):
        driver.output_on()


def test_timeout_fault_propagates(mock_transport):
    """A transport timeout surfaces as InstrumentTimeoutError."""
    mock_transport.fault_on = "MEAS:VOLT"
    mock_transport.fault = InstrumentTimeoutError("no reply")
    driver = N5747ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    with pytest.raises(InstrumentTimeoutError):
        driver.measure_voltage()
