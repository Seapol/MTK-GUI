# -*- coding: utf-8 -*-
"""Instrument gateway - one call shape for Real and Virtual modes.

The engine never talks to hardware directly (interface_spec.md §4.3):

  * Virtual mode -> mtkgui.virtual_hardware.VirtualRack (T4-owned,
    wrapped by the runner as-is; this module does not touch it).
  * Real mode    -> the mtkgui.drivers package (T1).  RealGateway
    adapts the T1 driver API (open/write/query + typed
    MeasurementResult results) to the SAME call shapes the runner
    already uses against the virtual rack:

        execute_op(name, params)                 -> GatewayOutcome
        measure_row(kind, name, unit, lo, hi)    -> GatewayOutcome
        capture_rails(rails, start_s, end_s, hz) -> (frac, volts, anomaly)
        rf_test(kind, name, config)              -> GatewayOutcome

    The driver reports measurement facts only; limit decisions
    (PASS/FAIL) are made HERE in the engine from the YAML limits.

The mtkgui.drivers package lives on the feature/instrument-driver
branch and may not be merged yet: the import is lazy, and a missing
module degrades every call into an ERROR outcome ("driver module not
available") instead of breaking the import of the engine.

Addresses / channels / firmware images / RF parameters all come from
the config YAML (equipment section, op_params) - nothing is hardcoded
(.traerules §4).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .steps import (dio_channel_index, dio_name, dio_pattern_value,
                    fixture_level, op_status_lines)

# equipment YAML key -> instrument abbreviation used by the op catalog
_INSTRUMENT_KEYS = {
    "DAQM": "daq973a",   # DAQ973A mainframe + DAQM908A/907A modules
    "DAQ": "u2355a",     # U2355A USB DAQ / counter / DIO
    "PSU": "psu",        # N5747A power supply
    "JLINK": "jlink",    # J-Link flash probe
}


class DriverUnavailable(RuntimeError):
    """mtkgui.drivers is not importable (T1 branch not merged yet)."""


@dataclass
class GatewayOutcome:
    """Rack-shaped step outcome (mirrors virtual_hardware.Measurement).

    verdict: "Done" (op ok) / "PASS" / "FAIL" (out of limit) /
             "Error" (instrument fault).
    value:   raw measured value (float) or matched text.
    text:    display string for the Measured column.
    lines:   Event Log sub-action lines.
    """

    verdict: str
    value: float | str | None = None
    text: str = ""
    lines: list[str] = field(default_factory=list)


def _fmt_value(value, unit: str) -> str:
    """Measured column text: 12.34 + "Ω" -> "12.34 Ω"."""
    if isinstance(value, float):
        return f"{value:g} {unit}".strip()
    return f"{value} {unit}".strip() if value not in (None, "") else ""


def _parse_limit(text: str) -> float | None:
    """YAML threshold string -> float ("—", "" or junk -> None)."""
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def judge_limits(value: float, lo_s: str, hi_s: str) -> str | None:
    """Engine-side limit decision (the drivers never decide PASS/FAIL).

    Returns "FAIL" when the value is outside [lo, hi] (a missing
    threshold bound is open), None when inside / nothing to judge."""
    lo = _parse_limit(lo_s)
    hi = _parse_limit(hi_s)
    if lo is not None and value < lo:
        return "FAIL"
    if hi is not None and value > hi:
        return "FAIL"
    return None


class RealGateway:
    """Real-mode instrument backend backed by mtkgui.drivers (T1)."""

    def __init__(self, equipment: dict | None = None,
                 fixture_type: str = "ATE"):
        self._equipment = dict(equipment or {})
        self._drivers: dict[str, object] = {}
        self._module = None
        # M38: fixture type from the MainWindow login global ("ATE" |
        # "Manual"); a Manual fixture never touches the DAQM907A DIO
        self._fixture_type = ("Manual"
                              if str(fixture_type or "").strip().lower()
                              == "manual" else "ATE")
        # last instrument-fault reason (rail capture; surfaced in the
        # runner's event log / row detail)
        self.last_error = ""
        try:
            from .. import drivers as drivers_module

            self._module = drivers_module
        except ImportError:
            self._module = None

    # ------------------------------------------------------------ state
    @property
    def fixture_type(self) -> str:
        """M38: "ATE" (drive / compare the DAQM907A DIO) or "Manual"
        (never touch fixture hardware)."""
        return self._fixture_type

    @fixture_type.setter
    def fixture_type(self, value) -> None:
        self._fixture_type = ("Manual"
                              if str(value or "").strip().lower()
                              == "manual" else "ATE")

    @property
    def available(self) -> bool:
        """True when the T1 driver package is importable."""
        return self._module is not None

    def _require_module(self):
        if self._module is None:
            raise DriverUnavailable(
                "mtkgui.drivers is not available "
                "(feature/instrument-driver not merged yet)")
        return self._module

    def _instrument_cfg(self, key: str) -> dict:
        """equipment.<key>.fields from the project YAML ({} if absent)."""
        entry = self._equipment.get(key) or {}
        return dict(entry.get("fields") or {})

    def _address(self, key: str) -> str:
        """Instrument address from the YAML equipment section.

        Convention: every instrument entry carries an "Address" field
        (the Equipment page connection panel saves it there)."""
        fields = self._instrument_cfg(key)
        for label in ("Address", "address", "VISA Address"):
            if fields.get(label):
                return str(fields[label])
        raise self._module.InstrumentConfigError(
            f"equipment.{key}: no 'Address' field in the project YAML")

    def _driver(self, abbr: str):
        """Open (and cache) one driver by instrument abbreviation."""
        if abbr in self._drivers:
            return self._drivers[abbr]
        mod = self._require_module()
        key = _INSTRUMENT_KEYS[abbr]
        if abbr == "DAQM":
            drv = mod.DAQ973ADriver()
        elif abbr == "DAQ":
            drv = mod.U2355ADriver()
        elif abbr == "PSU":
            drv = mod.N5747ADriver()
        else:  # JLINK
            drv = mod.JLinkDriver()
        drv.open(self._address(key), self._instrument_cfg(key))
        self._drivers[abbr] = drv
        return drv

    def close(self) -> None:
        """Close every opened driver connection."""
        for drv in self._drivers.values():
            try:
                drv.close()
            except Exception:  # noqa: BLE001 - best effort on teardown
                pass
        self._drivers.clear()

    # ------------------------------------------------- per-instrument
    def connect_instrument(self, abbr: str) -> tuple[bool, str]:
        """Open ONE instrument driver (per-instrument Connect).

        Returns:
            (ok, line) - the line is a human-readable result for the
            Event Log.
        """
        try:
            key = _INSTRUMENT_KEYS.get(abbr, abbr)
            self._driver(abbr)
            return True, f"{abbr} connected ({self._address(key)})"
        except Exception as exc:  # noqa: BLE001 - outcome, not crash
            return False, f"{abbr} init failed: {exc}"

    def disconnect_instrument(self, abbr: str) -> tuple[bool, str]:
        """Close ONE instrument driver (per-instrument Disconnect).

        Returns:
            (ok, line) - the line is a human-readable result for the
            Event Log.
        """
        drv = self._drivers.pop(abbr, None)
        if drv is None:
            return True, f"{abbr} was not connected"
        try:
            drv.close()
            return True, f"{abbr} disconnected"
        except Exception as exc:  # noqa: BLE001 - keep the session
            self._drivers[abbr] = drv
            return False, f"{abbr} close failed: {exc}"

    # ------------------------------------------------------- op steps
    KNOWN_OP_TYPES = ("instruments", "reset", "fixture", "power",
                      "generic", "dio_read", "dio_out")

    def execute_op(self, name: str, params: dict | None) -> GatewayOutcome:
        """Standard operation step against the real rack."""
        import time as _time
        from .protocol import (CommandValidator, ProtocolAdapter,
                               ProtocolError, ReplyParser,
                               TimeoutPolicy)
        if getattr(self, "_proto", None) is None:
            self.proto = ProtocolAdapter(
                policy=TimeoutPolicy(execute_s=120.0),
                parser=ReplyParser(),
                log_fn=lambda line: None)
        p = dict(params) if params else {}
        t = p.get("type") or "generic"
        t0 = _time.monotonic()
        try:
            # P1 Task9: command pre-validation (unknown op types are
            # rejected before touching any instrument)
            self.proto.validate_command(t, CommandValidator(
                set(self.KNOWN_OP_TYPES)))
        except ProtocolError as exc:
            return GatewayOutcome("Error", lines=[f"{name}: {exc}"])
        try:
            out = self._execute_op_by_type(name, t, p)
        except DriverUnavailable as exc:
            out = GatewayOutcome("Error", lines=[str(exc)])
        except self._err_base() as exc:
            out = GatewayOutcome("Error", lines=[f"{name}: {exc}"])
        duration = _time.monotonic() - t0
        out.lines.append(f"[INSTR_PROTO] op={t} duration="
                         f"{duration:.3f}s verdict={out.verdict}")
        return out

    def _execute_op_by_type(self, name: str, t: str,
                            p: dict) -> GatewayOutcome:
        try:
            if t in ("instruments", "reset"):
                return self._op_instruments(p, reset=(t == "reset"))
            if t == "fixture":
                return self._op_fixture(p)
            if t == "power":
                return self._op_power(p)
            if t == "dio_out":
                return self._op_dio_out(p)
            if t == "dio_read":
                return self._op_dio_read(p)
        except DriverUnavailable as exc:
            return GatewayOutcome("Error", lines=[str(exc)])
        except self._err_base() as exc:
            return GatewayOutcome("Error", lines=[f"{name}: {exc}"])
        # generic op: no instrument interaction defined
        return GatewayOutcome("Done", lines=op_status_lines(name, p))

    def _err_base(self):
        mod = self._module
        return mod.InstrumentError if mod is not None else RuntimeError

    def _op_instruments(self, p: dict, reset: bool) -> GatewayOutcome:
        mod = self._require_module()
        lines = []
        for abbr in p.get("instruments", []):
            key = _INSTRUMENT_KEYS.get(abbr)
            if key is None:
                lines.append(f"{abbr}: unknown instrument key")
                continue
            try:
                drv = self._driver(abbr)
                idn = drv.identify()
                if reset and abbr == "PSU":
                    drv.reset()
                lines.append(f"{abbr} {'reset' if reset else 'init'} OK: "
                             f"{idn}")
            except mod.InstrumentError as exc:
                lines.append(f"{abbr} {'reset' if reset else 'init'} "
                             f"failed: {exc}")
                return GatewayOutcome("Error", lines=lines)
        return GatewayOutcome("Done", lines=lines or ["init OK"])

    def _fixture_channel(self, p: dict) -> str:
        """Fixture DIO channel from op_params or the equipment section."""
        channel = (p.get("channel")
                   or self._instrument_cfg("fixture").get("Channel"))
        if not channel:
            raise self._require_module().InstrumentConfigError(
                "fixture DIO channel not configured "
                "(op_params.channel or equipment.fixture.fields)")
        return str(channel)

    def _op_fixture(self, p: dict) -> GatewayOutcome:
        """M38: DAQM907A fixture operation.

        Write-style (no expectation) drives the fixture DIO -> Done.
        Read-style (``expect`` / ``unexpected`` in op_params) reads the
        DIO level and compares it with the step's cmd / params
        expectation: match -> Done, mismatch / unexpected present -> Fail.
        A Manual fixture never touches hardware (-> Done).
        """
        sig = p.get("signal", "press")
        expect = fixture_level(p.get("expect"))
        unexpected = fixture_level(p.get("unexpected"))
        if self._fixture_type == "Manual":
            return GatewayOutcome(
                "Done",
                lines=[f"fixture {sig}: Manual fixture -> no hardware "
                       f"action"])
        if expect or unexpected:
            return self._read_fixture(p, sig, expect, unexpected)
        mod = self._require_module()
        drv = self._driver("DAQM")
        channel = self._fixture_channel(p)
        level = p.get("level", "H")
        drv.write_dio(channel, 1 if level == "H" else 0)
        return GatewayOutcome(
            "Done",
            lines=[f"drive {sig}={level} -> DIO {channel} written"])

    def _read_fixture(self, p: dict, sig: str, expect: str,
                      unexpected: str) -> GatewayOutcome:
        """M38: compare the read fixture level with the expectation."""
        drv = self._driver("DAQM")
        channel = self._fixture_channel(p)
        result = drv.read_dio(channel)
        raw = int(getattr(result, "value", 0) or 0)
        level = "High" if raw else "Low"
        lines = [f"fixture {sig}: read DIO {channel} = {level}"]
        text = ""
        verdict = "Done"
        if expect:
            text = f"Expect {expect}"
            if level == expect:
                lines.append(f"Expect {expect} -> matched")
            else:
                text = f"Expect {expect} / read {level}"
                lines.append(f"Expect {expect} but read {level} -> FAIL")
                verdict = "Fail"
        if unexpected and level == unexpected:
            text = f"Unexpected {unexpected} / read {level}"
            lines.append(f"Unexpected {unexpected} present -> FAIL")
            verdict = "Fail"
        return GatewayOutcome(verdict, value=level, text=text, lines=lines)

    def _op_dio_out(self, p: dict) -> GatewayOutcome:
        """M7: drive the U2355A DIO bank (digital output)."""
        channels = str(p.get("channels") or "DIO01-DIO08")
        pattern = str(p.get("pattern") or "0x00")
        value = dio_pattern_value(pattern, channels)
        drv = self._driver("DAQ")
        drv.dio_write(channels, value)
        return GatewayOutcome(
            "Done",
            lines=[f"U2355A DIO write {channels} = {pattern} "
                   f"(0x{value:02X}) -> written"])

    def _op_dio_read(self, p: dict) -> GatewayOutcome:
        """M38: read the U2355A DIO bank and PRESENT the value (no
        pass/fail judgement - the operator reads the levels)."""
        rows = list(p.get("control_io") or [])
        channels = ",".join(sorted({
            dio_name(str(row.get("dio"))) for row in rows
            if dio_name(str(row.get("dio")))}))
        if not channels:
            channels = "DIO01-DIO24"
        drv = self._driver("DAQ")
        result = drv.dio_read(channels)
        value = int(getattr(result, "value", 0) or 0)
        levels = []
        lines = []
        for row in rows:
            net = str(row.get("net") or "")
            dio = str(row.get("dio") or "")
            index = dio_channel_index(dio)
            if not net or not dio or index is None:
                continue
            level = "HIGH" if (value >> index) & 1 else "LOW"
            levels.append(f"{dio}={'H' if level == 'HIGH' else 'L'}")
            lines.append(f"Control IO {net}: {dio} = {level}")
        if not lines:
            lines.append("Control IO: no allocated control net (read "
                         "the full bank)")
        value_line = f"DIO Read = 0x{value:02X}"
        if levels:
            value_line += " / " + " ".join(levels)
        return GatewayOutcome("Done", value=value, text=value_line,
                              lines=[value_line] + lines)

    def _op_power(self, p: dict) -> GatewayOutcome:
        mod = self._require_module()
        drv = self._driver("PSU")
        if "voltage" in p:
            drv.set_voltage(float(p["voltage"]))
            drv.set_current(float(p.get("current", 0.0)))
            drv.output_on()
            readback = drv.measure_voltage()
            return GatewayOutcome(
                "Done", value=readback.value,
                lines=[f"N5747A set {p['voltage']:.2f} V / "
                       f"{p.get('current', 0.0):.2f} A -> output ON, "
                       f"readback {readback.value:g} V"])
        drv.output_off()
        return GatewayOutcome("Done", lines=["N5747A output OFF"])

    # ------------------------------------------------- measurement rows
    def measure_row(self, kind: str, name: str, unit: str, lo_s: str,
                    hi_s: str, force: str | None = None) -> GatewayOutcome:
        """One measurement row: driver reading -> engine limit decision."""
        try:
            mod = self._require_module()
            value = self._measure(kind, name, unit, mod)
        except DriverUnavailable as exc:
            return GatewayOutcome("Error", lines=[str(exc)])
        except mod.InstrumentError as exc:
            return GatewayOutcome("Error", lines=[f"{name}: {exc}"])
        if force == "FAIL" and lo_s not in ("—", ""):
            # test hook: pretend an out-of-limit reading (mirrors the
            # virtual rack behaviour for the sim-fail context menu)
            lo = _parse_limit(lo_s)
            value = (lo - abs(lo) * 0.5) if lo else 0.0
        text = _fmt_value(value, unit)
        verdict = judge_limits(float(value), lo_s, hi_s) or "PASS"
        line = (f"{name}: {text} (threshold {lo_s}..{hi_s}) "
                f"-> {verdict}")
        if verdict == "FAIL":
            line = f"{name}: {text} out of limit ({lo_s}..{hi_s}) -> FAIL"
        return GatewayOutcome(verdict, value=value, text=text,
                              lines=[line])

    def _measure(self, kind: str, name: str, unit: str, mod) -> float:
        """Dispatch one reading to the matching driver method."""
        channel_map = (self._equipment.get("measure_channels") or {})
        channel = channel_map.get(name)
        if not channel:
            raise mod.InstrumentConfigError(
                f"no measurement channel mapped for '{name}' "
                f"(add equipment.measure_channels['{name}'] to YAML)")
        if unit == "Ω":
            return float(self._driver("DAQM")
                         .measure_resistance_2w(str(channel)).value)
        if unit == "V":
            if kind == "DAQ AI":
                raise mod.InstrumentConfigError(
                    "rail capture goes through capture_rails")
            return float(self._driver("DAQM")
                         .measure_dcv(str(channel)).value)
        if unit == "Hz":
            drv = self._driver("DAQ")
            tp = str(channel)
            if "CLK2" in tp or "CLK3" in tp:  # U2355A counters CLK2/CLK3
                return float(drv.measure_counter(tp).value)
            return float(self._driver("DAQM")
                         .measure_frequency(str(channel)).value)
        if unit == "ch":
            # digital channel rows: read back the U2355A DIO port
            return float(self._driver("DAQ")
                         .dio_read(str(channel)).value)
        raise mod.InstrumentConfigError(
            f"real driver does not implement measurement kind "
            f"'{kind}' (unit '{unit}') yet")

    # ----------------------------------------------------- rail capture
    def capture_rails(self, rails: list, start_s: float, end_s: float,
                      rate_hz: float,
                      force: str | None = None) -> tuple:
        """Power-rails up-sequence capture via the U2355A.

        Returns (fractions, volts, anomaly) in the virtual rack shape:
        anomaly is None (healthy / judged record-only), a rail name
        (forced test FAIL) or "error" (instrument fault)."""
        mod = None
        try:
            mod = self._require_module()
            channels = list(self._equipment.get("rail_channels") or [])
            if not channels:
                raise mod.InstrumentConfigError(
                    "no rail channels configured "
                    "(power_rails_up_sequence.channels)")
            n = max(1, int((end_s - start_s) * rate_hz))
            drv = self._driver("DAQ")
            data = drv.capture_ai(channels, float(rate_hz), n)
            volts = []
            frac = []
            for (_label, _color, vnom, _off), series in zip(rails, data):
                row = [float(v) for v in series[:n]]
                volts.append(row)
                frac.append([min(1.06, max(0.0, v / vnom))
                             for v in row])
            anomaly = None
            if force == "FAIL" and rails:
                anomaly = rails[0][0]  # test hook: flag the first rail
            return frac, volts, anomaly
        except DriverUnavailable as exc:
            # keep the reason for the runner's event-log / row detail
            self.last_error = str(exc)
            return None, None, "error"
        except mod.InstrumentError as exc:
            self.last_error = f"rail capture: {exc}"
            return None, None, "error"

    # ---------------------------------------------------------- RF tests
    def rf_test(self, kind: str, name: str,
                config: dict | None) -> GatewayOutcome:
        """FCT WIFI / Bluetooth step against the RF test drivers.

        config carries the RF test parameters from the project YAML
        (ssid / password / mac / target_ip / limits); missing keys are
        an engine-side config error, never a guessed default."""
        mod = None
        try:
            mod = self._require_module()
            cfg = dict(config or {})
            if kind == "WIFI":
                drv = self._rf_driver(mod, "wifi")
                report = drv.run_test(cfg)
            elif kind == "Bluetooth":
                drv = self._rf_driver(mod, "bluetooth")
                report = drv.run_test(cfg)
            else:
                raise mod.InstrumentConfigError(
                    f"RF test kind '{kind}' not supported")
        except DriverUnavailable as exc:
            return GatewayOutcome("Error", lines=[str(exc)])
        except self._err_base() as exc:
            return GatewayOutcome("Error", lines=[f"{name}: {exc}"])
        verdict = {mod.Status.OK: "PASS",
                   mod.Status.FAIL: "FAIL"}.get(report.verdict, "Error")
        lines = [f"{name}: {report.summary}"]
        lines += [f"  {r.source}: {r.value} {r.unit}".rstrip()
                  for r in report.results]
        return GatewayOutcome(verdict,
                              value=report.summary, text=report.summary,
                              lines=lines)

    def _rf_driver(self, mod, which: str):
        """Build the RF test driver with a subprocess executor."""
        executor = mod.SubprocessExecutor()
        if which == "wifi":
            drv = mod.WiFiRFTestDriver(executor=executor)
        else:
            drv = mod.BluetoothRFTestDriver(executor=executor)
        # RF drivers need no open() round (CLI based); register for close
        self._drivers[which.upper()] = drv
        return drv
