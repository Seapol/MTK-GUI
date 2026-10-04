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

from .steps import op_status_lines

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
                 config: dict | None = None):
        self._equipment = dict(equipment or {})
        # full project config (optional): the flash parameter layer
        # resolves firmware-section defaults against it (P1 Task6)
        self._flash_config = config or {}
        self._drivers: dict[str, object] = {}
        self._module = None
        try:
            from .. import drivers as drivers_module

            self._module = drivers_module
        except ImportError:
            self._module = None

    # ------------------------------------------------------------ state
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

    # ------------------------------------------------------- op steps
    def execute_op(self, name: str, params: dict | None) -> GatewayOutcome:
        """Standard operation step against the real rack."""
        p = dict(params) if params else {}
        t = p.get("type") or "generic"
        try:
            if t in ("instruments", "reset"):
                return self._op_instruments(p, reset=(t == "reset"))
            if t == "fixture":
                return self._op_fixture(p)
            if t == "power":
                return self._op_power(p)
            if t == "flash":
                return self._op_flash(p)
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

    def _op_fixture(self, p: dict) -> GatewayOutcome:
        mod = self._require_module()
        drv = self._driver("DAQM")
        channel = (p.get("channel")
                   or self._instrument_cfg("fixture").get("Channel"))
        if not channel:
            raise mod.InstrumentConfigError(
                "fixture DIO channel not configured "
                "(op_params.channel or equipment.fixture.fields)")
        level = p.get("level", "H")
        drv.write_dio(str(channel), 1 if level == "H" else 0)
        sig = p.get("signal", "press")
        return GatewayOutcome(
            "Done",
            lines=[f"drive {sig}={level} -> DIO {channel} written"])

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

    def _op_flash(self, p: dict) -> GatewayOutcome:
        mod = self._require_module()
        drv = self._driver("JLINK")
        # P1 Task6: structured parameter resolution + full validation
        # BEFORE any driver call (illegal params never reach the flash)
        from .flash_params import (flash_param_log_lines,
                                   resolve_flash_params,
                                   validate_flash_params)
        params = resolve_flash_params(p, config=self._flash_config)
        if not params.image:
            slot = p.get("slot", "")
            raise mod.InstrumentConfigError(
                f"flash image for slot '{slot}' not configured "
                f"(set firmware.{slot}_image in the project YAML)")
        errors = validate_flash_params(params)
        log_lines = flash_param_log_lines(params, errors)
        if errors:
            raise mod.InstrumentConfigError(
                f"flash parameters rejected: {errors[0]}")
        # P1 Task7: slot image registry - integrity/tamper/reuse gate
        # before the driver call (bad or illegal images never flash)
        from .slot_images import SlotImageRegistry
        if getattr(self, "_slot_registry", None) is None:
            cfg_fw = self._flash_config.get("firmware") or {}
            self._slot_registry = SlotImageRegistry(
                skip_if_same_hash=bool(cfg_fw.get("skip_if_same_hash",
                                                  False)))
        rec = self._slot_registry.inspect(params.resolved_image(),
                                          params.slot)
        log_lines.extend(rec.log_lines())
        if rec.state.value != "VALID":
            raise mod.InstrumentConfigError(
                f"slot image rejected: {rec.reason}")
        if not self._slot_registry.should_flash(params.slot,
                                                rec.sha256):
            self._slot_registry.mark_flashed(params.slot, rec.sha256)
            return GatewayOutcome(
                "Done", value="reused",
                lines=log_lines + ["[SLOT_IMG] identical image "
                                   "already flashed -> write skipped"])
        # P1 Task8: fault-tolerant execution - segmented timeouts,
        # transient-disconnect retry, rollback on write/verify failure,
        # forced driver release
        from .flash_ft import (FlashVerifyFailed, FlashWriteFailed,
                               FlashTolerance)
        ft = FlashTolerance(
            retries=params.retries,
            log_fn=lambda line: log_lines.append(line))
        try:
            write = ft.execute_write(
                lambda: drv.flash_firmware(
                    params.resolved_image(), verify=params.verify,
                    reset_and_run=params.reset_run,
                    erase=params.erase).value,
                self._slot_registry, params.slot)
            verify = ft.execute_verify(
                getattr(drv, "verify_firmware", None),
                self._slot_registry, params.slot)
        except (FlashWriteFailed, FlashVerifyFailed) as exc:
            raise mod.InstrumentConfigError(str(exc))
        finally:
            ft.release(drv)
        slot = params.slot
        self._slot_registry.mark_flashed(slot, rec.sha256)
        detail = write.detail or write.phase
        return GatewayOutcome(
            "Done", value=int(detail) if detail.isdigit() else detail,
            lines=log_lines[:1]
            + [f"J-Link flash {slot} {params.image}: "
               f"{write.detail} bytes OK",
               "J-Link reset & run"]
            + log_lines[1:])

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
            return None, None, "error"
        except mod.InstrumentError:
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
