# -*- coding: utf-8 -*-
"""Keysight U2355A USB DAQ / counter / DIO driver.

Covers the three station capabilities:

* **AI capture** - the 12 analog inputs record the power-rails
  up-sequence (CSV + waveform) at a configured rate,
* **Counters** - the two counters (up to 6 MHz) measure CLK2 / CLK3,
* **DIO** - the 24 TTL channels walk the DUT GPIO through the level
  shifters.

Verification status: the U2355A remote programming model must be
confirmed against the official programming documentation during the
Windows bring-up; the command templates below therefore use the
standard SCPI measurement-model mnemonics (CONFigure / SAMPle:COUNt /
INITiate / FETCh / DIGital) and are all built in one place
(:data:`CMD`).  Until the on-site check, treat the exact spellings as
the single place to correct.

Channel / counter identifiers always come from the caller (``config/``
YAML) and are never hardcoded here.
"""

from __future__ import annotations

import logging

from mtkgui.drivers.base import InstrumentDriver, MeasurementResult, Transport, parse_float
from mtkgui.drivers.errors import InstrumentConfigError, InstrumentError

_LOG = logging.getLogger("mtkgui.drivers.u2355a")

#: SCPI command templates - VERIFY against the U2355A programming
#: documentation at Windows bring-up (see module docstring).
CMD = {
    "idn": "*IDN?",
    "rst": "*RST",
    "cls": "*CLS",
    "err": "SYST:ERR?",
    # AI capture configuration
    "conf_vdc": "CONF:VOLT:DC {range},DEF,(@{chans})",
    "samp_count": "SAMP:COUN {count}",
    "trig_imm": "TRIG:SOUR IMM",
    "init_imm": "INIT:IMM",
    "opc": "*OPC?",
    "fetch_vdc": "FETC:VOLT:DC?",
    "meas_vdc": "MEAS:VOLT:DC? AUTO,DEF,(@{chans})",
    # counters (CLK2 / CLK3)
    "meas_freq": "MEAS:FREQ? {gate},DEF,(@{chans})",
    # DIO bank
    "dio_write": "DIG:DATA {value},(@{chans})",
    "dio_read": "DIG:DATA? (@{chans})",
}

#: Maximum AI sample count accepted by :meth:`U2355ADriver.capture_ai`.
MAX_SAMPLES = 250_000


class U2355ADriver(InstrumentDriver):
    """Driver for the Keysight U2355A USB DAQ (12 AI / 2 counters /
    24 DIO)."""

    MODEL = "U2355A"

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
        """Open the connection and check device identity.

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

    # -- AI capture ------------------------------------------------------------

    def measure_voltage(self, channels: str) -> MeasurementResult:
        """Measure DC voltage on one AI channel (single shot).

        Args:
            channels: AI channel list string (from YAML).

        Returns:
            :class:`MeasurementResult` with the reading in volts.

        Raises:
            InstrumentConfigError: Empty channel list.
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query``.
        """
        chans = self._validate_channels(channels)
        reply = self.query(CMD["meas_vdc"].format(chans=chans))
        return MeasurementResult.ok(
            parse_float(reply), "V", f"{self.MODEL}/{chans}")

    def capture_ai(
        self, channels: list[str], rate_hz: float, samples: int,
    ) -> list[list[float]]:
        """Record one sample block on the given AI channels.

        Configures the channels for DCV, sets the sample count,
        triggers immediately and fetches the block.  Used by the
        engine for the power-rails up-sequence capture (start time and
        rate are engine/CSV concerns; the driver only records).

        Args:
            channels: AI channel list, e.g. ``["101", "102"]`` (from
                      YAML).  Order defines the output order.
            rate_hz:  Sample rate in Hz.  Validated to be positive.
            samples:  Number of samples per channel (1..
                      :data:`MAX_SAMPLES`).

        Returns:
            One list of voltage samples per channel, ordered like
            ``channels``.  The sample count follows the instrument
            reply, which the engine reconciles with the requested
            count.

        Raises:
            InstrumentConfigError: Empty channel list, non-positive
                                   rate, or sample count out of range.
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query`` / ``write``.
        """
        if not channels or not all(
                isinstance(c, str) and c.strip() for c in channels):
            raise InstrumentConfigError(
                "U2355A: channels must be a non-empty list of strings "
                "(from config/ YAML)")
        if rate_hz <= 0:
            raise InstrumentConfigError(
                f"U2355A: rate_hz must be positive, got {rate_hz}")
        if not 1 <= int(samples) <= MAX_SAMPLES:
            raise InstrumentConfigError(
                f"U2355A: samples must be 1..{MAX_SAMPLES}, got {samples}")
        chans = ",".join(c.strip() for c in channels)
        self.write(CMD["conf_vdc"].format(range="AUTO", chans=chans))
        self.write(CMD["samp_count"].format(count=int(samples)))
        self.write(CMD["trig_imm"])
        self.query(CMD["opc"])  # wait for capture completion
        reply = self.query(CMD["fetch_vdc"])
        flat = [float(tok) for tok in reply.split(",") if tok.strip()]
        per_ch = max(1, len(flat) // len(channels))
        result: list[list[float]] = []
        for idx in range(len(channels)):
            result.append(flat[idx * per_ch:(idx + 1) * per_ch])
        _LOG.info("U2355A capture: %d ch x %d samples @ %g Hz",
                  len(channels), per_ch, rate_hz)
        return result

    # -- counters ----------------------------------------------------------------

    def measure_counter(
        self, counter_channel: str, gate_s: float | None = None,
    ) -> MeasurementResult:
        """Measure frequency on one counter input (CLK2 / CLK3).

        Args:
            counter_channel: Counter channel string (from YAML).
            gate_s:          Optional gate time in seconds (``DEF``
                             when ``None``).

        Returns:
            :class:`MeasurementResult` with the frequency in Hz.

        Raises:
            InstrumentConfigError: Empty channel string.
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query``.
        """
        chans = self._validate_channels(counter_channel)
        gate = "DEF" if gate_s is None else f"{float(gate_s):.6g}"
        reply = self.query(CMD["meas_freq"].format(
            gate=gate, chans=chans))
        return MeasurementResult.ok(
            parse_float(reply), "Hz", f"{self.MODEL}/{chans}")

    # -- DIO ---------------------------------------------------------------------

    def dio_write(self, channels: str, value: int) -> None:
        """Write the DIO bank (DUT GPIO through level shifters).

        Args:
            channels: DIO port channel string (from YAML).
            value:    Bit pattern (decimal, 0..0xFFFFFF for 24 ch).

        Raises:
            InstrumentConfigError: Empty channel list or value out of
                                   range.
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        chans = self._validate_channels(channels)
        value = int(value)
        if not 0 <= value <= 0xFF_FFFF:
            raise InstrumentConfigError(
                f"dio_write: value {value} outside 0..16777215")
        self.write(CMD["dio_write"].format(value=value, chans=chans))

    def dio_read(self, channels: str) -> MeasurementResult:
        """Read the DIO bank (GPIO loopback test).

        Args:
            channels: DIO port channel string (from YAML).

        Returns:
            :class:`MeasurementResult` with the bit pattern (unit "").

        Raises:
            InstrumentConfigError: Empty channel list.
            ConnectionLostError / InstrumentTimeoutError /
            InstrumentIOError: See ``query``.
        """
        chans = self._validate_channels(channels)
        reply = self.query(CMD["dio_read"].format(chans=chans))
        value = int(parse_float(reply))
        return MeasurementResult.ok(value, "", f"{self.MODEL}/{chans}")

    # -- helpers -------------------------------------------------------------------

    def reset(self) -> None:
        """Send ``*RST`` then ``*CLS``.

        Raises:
            ConnectionLostError / InstrumentIOError: See ``write``.
        """
        self.write(CMD["rst"])
        self.write(CMD["cls"])

    @staticmethod
    def _validate_channels(channels: str) -> str:
        """Validate a caller-supplied channel string.

        Args:
            channels: Channel or port string.

        Returns:
            The stripped string.

        Raises:
            InstrumentConfigError: Empty or non-string input.
        """
        if not isinstance(channels, str) or not channels.strip():
            raise InstrumentConfigError(
                "U2355A: channel must be a non-empty string "
                "(from config/ YAML)")
        return channels.strip()
