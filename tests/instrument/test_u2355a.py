# -*- coding: utf-8 -*-
"""Unit tests for the Keysight U2355A driver (mocked transport)."""

from __future__ import annotations

import pytest

from mtkgui.drivers.base import Status
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.u2355a import U2355ADriver
from tests.instrument.conftest import MockTransport

ADDR = "USB0"  # example address as it would come from config/ YAML


@pytest.fixture
def daq(mock_transport: MockTransport) -> U2355ADriver:
    """Return a U2355A driver over the shared mock transport."""
    driver = U2355ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    mock_transport.written.clear()  # drop the *IDN? recorded by open()
    return driver


def test_open_queries_idn(mock_transport: MockTransport):
    """open() reads *IDN? once."""
    driver = U2355ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    assert mock_transport.written == ["*IDN?"]
    assert driver.identify()


def test_measure_voltage(daq):
    """Single-shot AI measurement sends MEAS:VOLT:DC? and parses volts."""
    daq._transport.script = {
        "MEAS:VOLT:DC? AUTO,DEF,(@101)": "+3.29870000E+00",
    }
    result = daq.measure_voltage("101")
    assert result.value == pytest.approx(3.2987)
    assert result.unit == "V"
    assert result.source == "U2355A/101"
    assert result.status is Status.OK


def test_capture_ai_command_flow(daq):
    """capture_ai configures, triggers and fetches in order."""
    # 2 channels x 3 samples
    daq._transport.script = {"FETC:VOLT:DC?": "+1,+2,+3,+4,+5,+6"}
    data = daq.capture_ai(["101", "102"], rate_hz=1000.0, samples=3)
    assert data == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert daq._transport.written == [
        "CONF:VOLT:DC AUTO,DEF,(@101,102)",
        "SAMP:COUN 3",
        "TRIG:SOUR IMM",
        "*OPC?",
        "FETC:VOLT:DC?",
    ]


def test_capture_ai_validation(daq):
    """capture_ai rejects bad channels, rates and sample counts."""
    with pytest.raises(InstrumentConfigError):
        daq.capture_ai([], rate_hz=100, samples=10)
    with pytest.raises(InstrumentConfigError):
        daq.capture_ai(["101", " "], rate_hz=100, samples=10)
    with pytest.raises(InstrumentConfigError):
        daq.capture_ai(["101"], rate_hz=0, samples=10)
    with pytest.raises(InstrumentConfigError):
        daq.capture_ai(["101"], rate_hz=100, samples=0)
    with pytest.raises(InstrumentConfigError):
        daq.capture_ai(["101"], rate_hz=100, samples=10**7)


def test_capture_ai_uneven_reply(daq):
    """An incomplete fetch reply yields per-channel lists without error."""
    daq._transport.script = {"FETC:VOLT:DC?": "+1,+2,+3"}
    data = daq.capture_ai(["101", "102"], rate_hz=100, samples=2)
    # instrument returned only 3 samples; driver splits evenly (2 + 1)
    assert len(data) == 2
    assert all(isinstance(ch, list) for ch in data)


def test_measure_counter(daq):
    """Counter measurement sends MEAS:FREQ? with gate and parses Hz."""
    daq._transport.script = {"MEAS:FREQ? DEF,DEF,(@201)": "+5.99990000E+06"}
    result = daq.measure_counter("201")
    assert result.value == pytest.approx(5999900.0)
    assert result.unit == "Hz"
    assert result.source == "U2355A/201"

    daq._transport.written.clear()
    daq._transport.script = {"MEAS:FREQ? 0.1,DEF,(@202)": "+4.00000000E+06"}
    result = daq.measure_counter("202", gate_s=0.1)
    assert result.value == pytest.approx(4000000.0)
    assert daq._transport.written == ["MEAS:FREQ? 0.1,DEF,(@202)"]


def test_dio_write_and_read(daq):
    """DIO bank write/read use the documented DIG:DATA commands."""
    daq.dio_write("301", 0b1010)
    assert daq._transport.written == ["DIG:DATA 10,(@301)"]

    daq._transport.script = {"DIG:DATA? (@301)": "+10"}
    result = daq.dio_read("301")
    assert result.value == 10
    assert result.unit == ""
    assert result.status is Status.OK


def test_dio_write_rejects_out_of_range(daq):
    """DIO write rejects values beyond the 24-bit bank."""
    with pytest.raises(InstrumentConfigError):
        daq.dio_write("301", 0x1_00_0000)


def test_channel_validation(daq):
    """Empty channel strings are config errors."""
    for call in (
        lambda: daq.measure_voltage(""),
        lambda: daq.measure_counter("  "),
        lambda: daq.dio_read(None),
    ):
        with pytest.raises(InstrumentConfigError):
            call()


def test_reset(daq):
    """reset() sends *RST then *CLS."""
    daq.reset()
    assert daq._transport.written == ["*RST", "*CLS"]


def test_write_before_open_raises():
    """write() before open() raises ConnectionLostError."""
    driver = U2355ADriver(transport=MockTransport())
    with pytest.raises(ConnectionLostError):
        driver.reset()


def test_timeout_fault_propagates(mock_transport):
    """A transport timeout surfaces as InstrumentTimeoutError."""
    mock_transport.fault_on = "MEAS:VOLT"
    mock_transport.fault = InstrumentTimeoutError("no reply")
    driver = U2355ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    with pytest.raises(InstrumentTimeoutError):
        driver.measure_voltage("101")
