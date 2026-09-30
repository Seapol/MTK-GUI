# -*- coding: utf-8 -*-
"""Unit tests for the Keysight DAQ973A driver (mocked transport)."""

from __future__ import annotations

import pytest

from mtkgui.drivers.base import Status
from mtkgui.drivers.daq973a import DAQ973ADriver, OVERLOAD_HIGH
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentIOError,
    InstrumentTimeoutError,
)
from tests.instrument.conftest import MOCK_IDN, MockTransport

ADDR = "COM973"  # example address as it would come from config/ YAML


@pytest.fixture
def daq(mock_transport: MockTransport) -> DAQ973ADriver:
    """Return a DAQ973A driver over the shared mock transport."""
    driver = DAQ973ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    mock_transport.written.clear()  # drop the *IDN? recorded by open()
    return driver


def test_open_queries_idn(mock_transport: MockTransport):
    """open() validates the address and reads *IDN? once."""
    driver = DAQ973ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    assert mock_transport.written == ["*IDN?"]
    assert driver.identify() == MOCK_IDN
    assert driver.address == ADDR


def test_open_rejects_empty_address(mock_transport: MockTransport):
    """open() rejects an empty address as a config error."""
    driver = DAQ973ADriver(transport=mock_transport)
    with pytest.raises(InstrumentConfigError):
        driver.open("   ", {})


def test_identify_before_open_raises():
    """identify() before open() raises ConnectionLostError."""
    driver = DAQ973ADriver(transport=MockTransport({"*IDN?": MOCK_IDN}))
    with pytest.raises(ConnectionLostError):
        driver.identify()


def test_measure_resistance_2w_command_and_value(daq):
    """2-wire OHM measurement sends the documented MEAS:RES? form."""
    daq._transport.script = {
        "MEAS:RES? AUTO,DEF,(@101)": "+1.23456700E+01",
    }
    result = daq.measure_resistance_2w("101")
    assert result.value == pytest.approx(12.34567)
    assert result.unit == "Ohm"
    assert result.status is Status.OK
    assert result.source == "DAQ973A/101"
    assert result.timestamp.tzinfo is not None
    assert daq._transport.written == ["MEAS:RES? AUTO,DEF,(@101)"]


def test_measure_resistance_2w_fixed_range(daq):
    """A fixed range is formatted into the MEAS:RES? command."""
    daq._transport.script = {"MEAS:RES? 1000,DEF,(@101)": "+5.0"}
    result = daq.measure_resistance_2w("101", range_ohm=1000)
    assert result.value == pytest.approx(5.0)


def test_measure_resistance_2w_explicit_resolution(daq):
    """An explicit resolution (engine-derived from YAML limits) is
    formatted into the MEAS:RES? command."""
    daq._transport.script = {"MEAS:RES? 1000,0.001,(@101)": "+5.0"}
    result = daq.measure_resistance_2w("101", range_ohm=1000,
                                       resolution=0.001)
    assert result.value == pytest.approx(5.0)
    assert result.unit == "Ohm"


def test_measure_resistance_2w_overload_passes_through(daq):
    """An open input reports the documented overload reading (9.9e37)."""
    daq._transport.script = {
        "MEAS:RES? AUTO,DEF,(@240)": "+9.90000000E+37",
    }
    result = daq.measure_resistance_2w("240")
    assert result.value == pytest.approx(OVERLOAD_HIGH)
    assert result.status is Status.OK  # limit decision is the engine's


def test_measure_dcv_command_and_value(daq):
    """DCV measurement sends the documented MEAS:VOLT:DC? form."""
    daq._transport.script = {
        "MEAS:VOLT:DC? AUTO,DEF,(@101)": "+3.30000000E+00",
    }
    result = daq.measure_dcv("101")
    assert result.value == pytest.approx(3.3)
    assert result.unit == "V"
    assert result.source == "DAQ973A/101"


def test_measure_dcv_explicit_resolution(daq):
    """An explicit resolution (engine-derived for the +/-0.1 % voltage
    tolerance) is formatted into the MEAS:VOLT:DC? command."""
    daq._transport.script = {
        "MEAS:VOLT:DC? 10,0.0001,(@101)": "+3.30000000E+00",
    }
    result = daq.measure_dcv("101", range_v=10, resolution=0.0001)
    assert result.value == pytest.approx(3.3)


def test_measure_frequency(daq):
    """DMM frequency measurement sends MEAS:FREQ? and parses Hz."""
    daq._transport.script = {
        "MEAS:FREQ? DEF,DEF,(@103)": "+3.27680000E+04",
    }
    result = daq.measure_frequency("103")
    assert result.value == pytest.approx(32768.0)
    assert result.unit == "Hz"


def test_measure_totalizer(daq):
    """DAQM907A totalizer measurement sends MEAS:TOT? with the gate."""
    daq._transport.script = {
        "MEAS:TOT? DEF,(@1301)": "+9.98900000E+04",
    }
    result = daq.measure_totalizer("1301")
    assert result.value == pytest.approx(99890.0)
    assert result.unit == "Hz"

    daq._transport.written.clear()
    daq._transport.script = {"MEAS:TOT? 1,(@1301)": "+1.00000000E+05"}
    result = daq.measure_totalizer("1301", gate_s=1.0)
    assert result.value == pytest.approx(100000.0)
    assert daq._transport.written == ["MEAS:TOT? 1,(@1301)"]


def test_set_ao_voltage(daq):
    """AO stimulus sends the SOUR:VOLT command."""
    daq.set_ao_voltage("1303", -5.5)
    assert daq._transport.written == ["SOUR:VOLT -5.5,(@1303)"]


def test_set_ao_voltage_rejects_bad_input(daq):
    """AO stimulus rejects NaN / infinity levels."""
    with pytest.raises(InstrumentConfigError):
        daq.set_ao_voltage("1303", float("nan"))
    with pytest.raises(InstrumentConfigError):
        daq.set_ao_voltage("1303", float("inf"))


def test_dio_write_and_read(daq):
    """DIO port write/read use the documented DIG:DATA commands."""
    daq.write_dio("1310", 0b0101)
    assert daq._transport.written == ["DIG:DATA 5,(@1310)"]

    daq._transport.script = {"DIG:DATA? (@1310)": "+2"}
    result = daq.read_dio("1310")
    assert result.value == 2
    assert result.unit == ""
    assert result.status is Status.OK


def test_dio_write_rejects_out_of_range(daq):
    """DIO write rejects values beyond the 16-bit port."""
    with pytest.raises(InstrumentConfigError):
        daq.write_dio("1310", 0x1FFFF)


def test_channel_validation(daq):
    """Empty channel lists are config errors."""
    with pytest.raises(InstrumentConfigError):
        daq.measure_resistance_2w("  ")
    with pytest.raises(InstrumentConfigError):
        daq.measure_dcv("")
    with pytest.raises(InstrumentConfigError):
        daq.set_ao_voltage(None, 1.0)


def test_routing_commands(daq):
    """close_channels/open_channels emit ROUT:CLOS / ROUT:OPEN."""
    daq.close_channels("101,102")
    daq.open_channels("101,102")
    assert daq._transport.written == [
        "ROUT:CLOS (@101,102)", "ROUT:OPEN (@101,102)"]


def test_reset_sends_rst_cls(daq):
    """reset() sends *RST then *CLS."""
    daq.reset()
    assert daq._transport.written == ["*RST", "*CLS"]


def test_unscripted_query_raises_ioerror(daq):
    """A non-numeric reply raises InstrumentIOError via parse_float."""
    daq._transport.script = {"MEAS:VOLT:DC? AUTO,DEF,(@101)": "NAn"}
    with pytest.raises(InstrumentIOError):
        daq.measure_dcv("101")


def test_timeout_fault_propagates(mock_transport):
    """A transport timeout surfaces as InstrumentTimeoutError."""
    mock_transport.fault_on = "MEAS:RES?"
    mock_transport.fault = InstrumentTimeoutError("no reply")
    driver = DAQ973ADriver(transport=mock_transport)
    driver.open(ADDR, {})
    with pytest.raises(InstrumentTimeoutError):
        driver.measure_resistance_2w("101")


def test_close_is_idempotent(daq):
    """close() can be called twice safely."""
    daq.close()
    assert not daq.is_open
    daq.close()
