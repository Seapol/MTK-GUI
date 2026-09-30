# -*- coding: utf-8 -*-
"""Keysight N5747A system power supply driver.

The N5747A (60 V / 12.5 A / 750 W, single output) feeds DUT VIN on the
station.  Its J1 RI/FLT inhibit input is hard-wired to the fixture
E-Stop loop: an open E-Stop loop keeps the output off in hardware, so
the driver models the same semantics as the virtual rack - there is no
software bypass and no inhibit query.  The engine verifies a power-up
by reading back the output voltage (:meth:`N5747ADriver.measure_voltage`).

Command set: Keysight N5700A-series system PSU programming guide
(N5747A shares the N5700A SCPI command set) plus IEEE-488.2 common
commands.  Every command string is built in one place (:data:`CMD`).
"""

from __future__ import annotations

import logging

from mtkgui.drivers.base import (
    InstrumentDriver,
    MeasurementResult,
    Transport,
    parse_float,
)
from mtkgui.drivers.errors import InstrumentConfigError, InstrumentError

_LOG = logging.getLogger("mtkgui.drivers.n5747a")

#: SCPI command templates (Keysight N5700A series).
CMD = {
    "idn": "*IDN?",
    "rst": "*RST",
    "cls": "*CLS",
    "err": "SYST:ERR?",
    "set_volt": "SOUR:VOLT {volts:.6g}",
    "get_volt": "SOUR:VOLT?",
    "set_curr": "SOUR:CURR {amps:.6g}",
    "get_curr": "SOUR:CURR?",
    "outp_on": "OUTP ON",
    "outp_off": "OUTP OFF",
    "outp_state": "OUTP?",
    "meas_volt": "MEAS:VOLT?",
    "meas_curr": "MEAS:CURR?",
    "meas_pow": "MEAS:POW?",
}


def _fmt_level(value: float, name: str) -> float:
    """Validate and coerce a setpoint level.

    Args:
        value: Requested setpoint.
        name:  Parameter name used in the error message.

    Returns:
        The value as a finite float.

    Raises:
        InstrumentConfigError: Non-finite or non-numeric value.
    """
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise InstrumentConfigError(
            f"N5747A: {name} must be a number, got {value!r}") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise InstrumentConfigError(f"N5747A: {name} must be finite")
    return value


class N5747ADriver(InstrumentDriver):
    """Driver for the Keysight N5747A system power supply."""

    MODEL = "N5747A"

    def __init__(self, transport: Transport | None = None) -> None:
        """Create the driver.

        Args:
            transport: Transport to use, or ``None`` to build a
                       :class:`SerialTransport` in ``open()``.
        """
        super().__init__(transport)
        self._idn: str = ""

    # -- lifecycle -----------------------------------------------------------

    def open(self, address: str, options: dict) -> None:
        """Open the connection and check instrument identity.

        Args:
            address: Instrument address from ``config/`` YAML.
            options: Transport options; may be empty.

        Raises:
            InstrumentConfigError: Empty address or bad options.
            InstrumentIOError:     Port could not be opened.
            InstrumentTimeoutError: No reply to ``*IDN?``.
        """
        address = self._validate_address(address)
        if self._transport is None:
            from mtkgui.drivers.transport_serial import SerialTransport
            self._transport = SerialTransport()
        self.address = address
        self.options = dict(options or {})
        self._transport.open(address, self.options)
        self._is_open = True
        self._idn = self.query(CMD["idn"]).strip()
        _LOG.info("%s opened: %s", self._log_prefix(), self._idn)

    def close(self) -> None:
        """Close the connection.  Safe to call more than once."""
        if self._transport is not None:
            try:
                self._transport.close()
            except InstrumentError as exc:
                _LOG.warning("%s close warning: %s", self._log_prefix(), exc)
        self._is_open = False

    def identify(self) -> str:
        """Return the cached ``*IDN?`` string from ``open()``.

        Returns:
            Identification string.

        Raises:
            ConnectionLostError: Not open.
        """
        self._require_open()
        return self._idn

    # -- setpoints -----------------------------------------------------------

    def set_voltage(self, volts: float) -> None:
        """Set the output voltage setpoint.

        Args:
            volts: Voltage setpoint (from YAML, e.g. DUT rail voltage).

        Raises:
            InstrumentConfigError: Non-finite value.
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        volts = _fmt_level(volts, "voltage")
        self.write(CMD["set_volt"].format(volts=volts))

    def set_current(self, amps: float) -> None:
        """Set the output current limit setpoint.

        Args:
            amps: Current limit in amperes (from YAML).

        Raises:
            InstrumentConfigError: Non-finite value.
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        amps = _fmt_level(amps, "current")
        self.write(CMD["set_curr"].format(amps=amps))

    def get_voltage_setpoint(self) -> float:
        """Query the programmed voltage setpoint.

        Returns:
            Setpoint in volts.

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query``.
        """
        return parse_float(self.query(CMD["get_volt"]))

    def get_current_setpoint(self) -> float:
        """Query the programmed current limit.

        Returns:
            Limit in amperes.

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query``.
        """
        return parse_float(self.query(CMD["get_curr"]))

    # -- output control --------------------------------------------------------

    def output_on(self) -> None:
        """Switch the output on.

        An open E-Stop loop (J1 inhibit) keeps the output off in
        hardware; verify with :meth:`measure_voltage`.

        Raises:
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        self.write(CMD["outp_on"])

    def output_off(self) -> None:
        """Switch the output off.

        Raises:
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        self.write(CMD["outp_off"])

    def get_output_enabled(self) -> bool:
        """Query the output relay state.

        Returns:
            ``True`` when the output is enabled.

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query``.
        """
        return parse_float(self.query(CMD["outp_state"])) != 0

    # -- readbacks ---------------------------------------------------------------

    def measure_voltage(self) -> MeasurementResult:
        """Measure the actual output voltage.

        Returns:
            :class:`MeasurementResult` with the reading in volts.

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query``.
        """
        value = parse_float(self.query(CMD["meas_volt"]))
        return MeasurementResult.ok(value, "V", self.MODEL)

    def measure_current(self) -> MeasurementResult:
        """Measure the actual output current.

        Returns:
            :class:`MeasurementResult` with the reading in amperes.

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query``.
        """
        value = parse_float(self.query(CMD["meas_curr"]))
        return MeasurementResult.ok(value, "A", self.MODEL)

    # -- helpers ------------------------------------------------------------

    def reset(self) -> None:
        """Send ``*RST`` then ``*CLS`` (output off, setpoints cleared).

        Raises:
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        self.write(CMD["rst"])
        self.write(CMD["cls"])
