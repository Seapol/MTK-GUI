# -*- coding: utf-8 -*-
"""Keysight DAQ973A data acquisition mainframe driver.

Covers the two module families used on the station:

* **DAQM908A** multiplexer modules (slots 1/2, channels 101-140 and
  201-240) routed into the built-in 6.5-digit DMM for 2-wire resistance
  (ICT short screening) and DC voltage (rail measurements).
* **DAQM907A** multifunction module (totalizer inputs for CLK1 <= 100
  kHz, two analog outputs for the TP_ADC0/1 stimulus, and the
  open-drain DIO port that drives the fixture control signals).

Command set: Keysight DAQ973A / 34980A-family SCPI programming manual
plus IEEE-488.2 common commands.  Every command string is built in one
place (:data:`CMD`) so any correction from the on-site manual check is
a single-line change.

Channel lists (e.g. ``"101"``, ``"201,202"``, ``"1301"``) always come
from the caller, which reads them from ``config/`` YAML - they are
never constructed from hardcoded slot maps here.
"""

from __future__ import annotations

import logging

from mtkgui.drivers.base import (
    InstrumentDriver,
    MeasurementResult,
    Transport,
    parse_float,
)
from mtkgui.drivers.errors import (
    InstrumentConfigError,
    InstrumentError,
    InstrumentIOError,
)

_LOG = logging.getLogger("mtkgui.drivers.daq973a")

#: SCPI command templates (Keysight DAQ973A / 34980A family).
CMD = {
    "idn": "*IDN?",
    "rst": "*RST",
    "cls": "*CLS",
    "err": "SYST:ERR?",
    # channel routing (multiplexer modules)
    "route_close": "ROUT:CLOS (@{chans})",
    "route_open": "ROUT:OPEN (@{chans})",
    # measurement functions (DMM via multiplexer)
    "func": 'FUNC "{func}", (@{chans})',
    "meas_vdc": "MEAS:VOLT:DC? {range},{res},(@{chans})",
    "meas_res": "MEAS:RES? {range},{res},(@{chans})",
    "meas_freq": "MEAS:FREQ? DEF,DEF,(@{chans})",
    # DAQM907A multifunction module
    "meas_tot": "MEAS:TOT? {gate},(@{chans})",
    "ao_volt": "SOUR:VOLT {volts},(@{chans})",
    "dio_write": "DIG:DATA {value},(@{chans})",
    "dio_read": "DIG:DATA? (@{chans})",
}

#: Reading returned by Keysight DMMs when a measurement is out of the
#: selected range / open input (documented 34980A-family behaviour).
OVERLOAD_HIGH = 9.9e37


def _fmt_range(value: float | None) -> str:
    """Format a measurement range argument.

    Args:
        value: Fixed range value, or ``None`` for AUTO ranging.

    Returns:
        ``"AUTO"`` or the formatted number.
    """
    if value is None:
        return "AUTO"
    return f"{value:.6g}"


def _fmt_res(value: float | None) -> str:
    """Format a measurement resolution argument.

    Args:
        value: Absolute resolution, or ``None`` for the instrument
               default.  The engine derives it from the YAML limits so
               readings stay fine enough for the production tolerances
               (e.g. +/-0.1 % on voltage measurements); the tolerance
               values themselves live in the YAML, never here.

    Returns:
        ``"DEF"`` or the formatted number.
    """
    if value is None:
        return "DEF"
    return f"{value:.6g}"


def _fmt_gate(value: float | None) -> str:
    """Format a totalizer gate time argument.

    Args:
        value: Gate time in seconds, or ``None`` for the instrument
               default.

    Returns:
        ``"DEF"`` or the formatted number.
    """
    if value is None:
        return "DEF"
    return f"{value:.6g}"


class DAQ973ADriver(InstrumentDriver):
    """Driver for the Keysight DAQ973A mainframe (DAQM908A + DAQM907A).

    The transport is injectable: pass a mocked transport for tests, a
    :class:`~mtkgui.drivers.transport_serial.SerialTransport` (or any
    future VISA transport) for the real rack.
    """

    MODEL = "DAQ973A"

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
            address: Instrument address from ``config/`` YAML (serial
                     port for the shipped transport; any other address
                     type requires an injected transport).
            options: Transport options (baudrate, timeout_s, ...); may
                     be empty.

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
            Identification string, e.g.
            ``"Keysight Technologies,DAQ973A,..."``.

        Raises:
            ConnectionLostError: Not open.
        """
        self._require_open()
        return self._idn

    # -- DAQM908A: DMM measurements via multiplexer --------------------------

    def measure_resistance_2w(
        self, channels: str, range_ohm: float | None = None,
        resolution: float | None = None,
    ) -> MeasurementResult:
        """Measure 2-wire resistance on one multiplexer channel.

        Used for the ICT impedance short screening before power-up.
        The 1.5 ohm class threshold is a YAML limit evaluated by the
        engine; this method only delivers a reading fine enough for
        that decision (optionally with an explicit resolution).

        Args:
            channels:   Channel list string, e.g. ``"101"`` (from
                        YAML).
            range_ohm:  Fixed ohms range, ``None`` for AUTO.
            resolution: Absolute resolution in ohms, ``None`` for the
                        instrument default.

        Returns:
            :class:`MeasurementResult` with the reading in ohms.  An
            open input reports the instrument overload value
            (``9.9e37``) with ``Status.OK`` - the limit decision is the
            engine's.

        Raises:
            ConnectionLostError:    Not open.
            InstrumentTimeoutError: No reply.
            InstrumentIOError:      Communication or parsing failure.
        """
        chans = self._validate_channels(channels)
        reply = self.query(CMD["meas_res"].format(
            range=_fmt_range(range_ohm), res=_fmt_res(resolution),
            chans=chans))
        value = parse_float(reply)
        return MeasurementResult.ok(
            value, "Ohm", f"{self.MODEL}/{chans}")

    def measure_dcv(
        self, channels: str, range_v: float | None = None,
        resolution: float | None = None,
    ) -> MeasurementResult:
        """Measure DC voltage on one multiplexer channel.

        Args:
            channels:   Channel list string, e.g. ``"101"`` (from
                        YAML).
            range_v:    Fixed volts range, ``None`` for AUTO.
            resolution: Absolute resolution in volts, ``None`` for the
                        instrument default (the +/-0.1 % production
                        tolerance on rail voltages is a YAML limit
                        checked by the engine).

        Returns:
            :class:`MeasurementResult` with the reading in volts.

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See :meth:`measure_resistance_2w`.
        """
        chans = self._validate_channels(channels)
        reply = self.query(CMD["meas_vdc"].format(
            range=_fmt_range(range_v), res=_fmt_res(resolution),
            chans=chans))
        value = parse_float(reply)
        return MeasurementResult.ok(value, "V", f"{self.MODEL}/{chans}")

    def measure_frequency(self, channels: str) -> MeasurementResult:
        """Measure frequency on one multiplexer channel (DMM counter).

        Args:
            channels: Channel list string (from YAML).

        Returns:
            :class:`MeasurementResult` with the reading in Hz.

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See :meth:`measure_resistance_2w`.
        """
        chans = self._validate_channels(channels)
        reply = self.query(CMD["meas_freq"].format(chans=chans))
        value = parse_float(reply)
        return MeasurementResult.ok(value, "Hz", f"{self.MODEL}/{chans}")

    # -- DAQM907A: totalizer / AO / DIO --------------------------------------

    def measure_totalizer(
        self, channels: str, gate_s: float | None = None,
    ) -> MeasurementResult:
        """Count events on a DAQM907A totalizer input (CLK1 <= 100 kHz).

        Args:
            channels: Totalizer channel list string (from YAML).
            gate_s:   Gate time in seconds, ``None`` for the
                      instrument default.

        Returns:
            :class:`MeasurementResult` with the frequency in Hz.

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See :meth:`measure_resistance_2w`.
        """
        chans = self._validate_channels(channels)
        reply = self.query(CMD["meas_tot"].format(
            gate=_fmt_gate(gate_s), chans=chans))
        value = parse_float(reply)
        return MeasurementResult.ok(value, "Hz", f"{self.MODEL}/{chans}")

    def set_ao_voltage(self, channels: str, volts: float) -> None:
        """Drive a DAQM907A analog output (TP_ADC stimulus).

        Args:
            channels: AO channel list string (from YAML).
            volts:    Output level within the module range (-12..+12 V
                      on the station wiring).

        Raises:
            InstrumentConfigError: Empty channel list or non-finite
                                   voltage.
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        chans = self._validate_channels(channels)
        volts = float(volts)
        if volts != volts or volts in (float("inf"), float("-inf")):
            raise InstrumentConfigError(
                f"set_ao_voltage: invalid level {volts!r}")
        self.write(CMD["ao_volt"].format(volts=f"{volts:.6g}", chans=chans))

    def write_dio(self, channels: str, value: int) -> None:
        """Write the DAQM907A open-drain DIO port (fixture control).

        Args:
            channels: DIO port channel string (from YAML).
            value:    Bit pattern to drive (decimal, 0..65535).

        Raises:
            InstrumentConfigError: Empty channel list or value out of
                                   range.
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        chans = self._validate_channels(channels)
        value = int(value)
        if not 0 <= value <= 0xFFFF:
            raise InstrumentConfigError(
                f"write_dio: value {value} outside 0..65535")
        self.write(CMD["dio_write"].format(value=value, chans=chans))

    def read_dio(self, channels: str) -> MeasurementResult:
        """Read the DAQM907A DIO port (presence / inpos / E-Stop inputs).

        Args:
            channels: DIO port channel string (from YAML).

        Returns:
            :class:`MeasurementResult` with the bit pattern (unit "").

        Raises:
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See :meth:`measure_resistance_2w`.
        """
        chans = self._validate_channels(channels)
        reply = self.query(CMD["dio_read"].format(chans=chans))
        value = int(parse_float(reply))
        return MeasurementResult.ok(value, "", f"{self.MODEL}/{chans}")

    # -- routing helpers -------------------------------------------------------

    def close_channels(self, channels: str) -> None:
        """Close (connect) multiplexer channels.

        Args:
            channels: Channel list string, e.g. ``"101,102"``.

        Raises:
            InstrumentConfigError: Empty channel list.
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        chans = self._validate_channels(channels)
        self.write(CMD["route_close"].format(chans=chans))

    def open_channels(self, channels: str) -> None:
        """Open (disconnect) multiplexer channels.

        Args:
            channels: Channel list string.

        Raises:
            InstrumentConfigError: Empty channel list.
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        chans = self._validate_channels(channels)
        self.write(CMD["route_open"].format(chans=chans))

    def reset(self) -> None:
        """Send ``*RST`` then ``*CLS`` to return the mainframe to its
        power-on state.

        Raises:
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        self.write(CMD["rst"])
        self.write(CMD["cls"])

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _validate_channels(channels: str) -> str:
        """Validate a caller-supplied channel list string.

        Args:
            channels: Channel list like ``"101"`` or ``"201,202"``.

        Returns:
            The stripped channel list.

        Raises:
            InstrumentConfigError: Empty or non-string input.
        """
        if not isinstance(channels, str) or not channels.strip():
            raise InstrumentConfigError(
                "DAQ973A: channel list must be a non-empty string "
                "(from config/ YAML)")
        return channels.strip()
