# -*- coding: utf-8 -*-
"""Headless demo - execute the full test sequence without a GUI.

Runs the production TestRunner (mtkgui.engine.runner) against a
lightweight console environment instead of the Qt workflow page:

    python -m mtkgui.engine.demo                        # virtual DUT
    python -m mtkgui.engine.demo --mode real            # scripted drivers
    python -m mtkgui.engine.demo --config my.yaml --inject fail=20

Sequence: the stages come from the project YAML via the Common loader
(mtkgui.project_config.load_config) and mtkgui.engine.sequence -
ICT -> Flash FAT Firmware -> FCT (WiFi / BT RF) -> Flash OOBE Firmware
(flash stages are inserted when the YAML does not define them).

Modes (.traerules §3 run_modes):
  * virtual: simulated rack (mtkgui.virtual_hardware.VirtualRack) with
    fault injection and a scripted virtual serial DUT.
  * real:    the engine routes through mtkgui.engine.instruments.
    RealGateway exactly as with real hardware; the demo injects a
    scripted mtkgui.drivers stub so the full flow runs offline without
    instruments (hardware runs use the GUI).

The power-rails waveform capture is written to a CSV log (+ AI review
text file) in --logs-dir.  Exit code: 0 PASS, 1 FAIL.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from .rails import ai_wave_review, capture_samples, rail_plot_data, \
    write_csv
from .results import StepStatus
from .runner import TestRunner
from .sequence import load_sequence
from .steps import display_text


# ------------------------------------------------------------- console
class _ScriptedDutWorker:
    """Virtual serial DUT: replies to console commands with the
    standard pass markers; one-shot fault injection
    ("no_response" / "wrong_reply") like mtkgui.virtual_dut."""

    _REPLIES = {
        "wifi_test": "wifi_test --scan\nRSSI -42 dBm\nPass\nSuccess\n",
        "bt_test": "bt_test --scan\nRSSI -55 dBm\nPass\n",
    }

    def __init__(self):
        self.buffer = bytearray()
        self._fault = None
        self.boot_log = ("U-Boot 2023.10\n"
                         "Booting FRDM-IMX93 ...\n"
                         "Linux version 6.6.52 (demo build)\n"
                         "App firmware 1.1.0.0\n"
                         "Boot log OK, Pass\n")

    def inject_fault(self, kind) -> None:
        self._fault = kind  # "no_response" | "wrong_reply" | None

    def receive(self, payload: bytes) -> None:
        fault, self._fault = self._fault, None
        if fault == "no_response":
            return
        cmd = payload.decode("utf-8", "replace").strip()
        reply = "OK\nPass\n"
        for prefix, scripted in self._REPLIES.items():
            if cmd.startswith(prefix):
                reply = scripted
                break
        if fault == "wrong_reply":
            reply = "ERROR retry exhausted\n"
        self.buffer += f"{cmd}\n{reply}".encode("utf-8")

    def isRunning(self) -> bool:  # duck-typed for _poll_fct_connect
        return True


class HeadlessConsole:
    """MultiConsoleWidget stand-in (documented subset, spec §4.2)."""

    def __init__(self):
        self.virtual_mode = True
        self._worker = _ScriptedDutWorker()
        self.channels = {"VCOM0": {"kind": "serial", "label": "VCOM0 "
                                   "(virtual DUT)",
                                   "worker": self._worker}}
        self._connected = set()

    # documented MultiConsoleWidget API subset
    def yaml_channel_keys(self):
        return list(self.channels)

    def channel_endpoint(self, key: str):
        return "virtual"

    def channel_connected(self, key: str) -> bool:
        return key in self._connected

    def open_channel(self, key: str) -> None:
        self._connected.add(key)  # scripted DUT connects instantly
        self._worker.buffer += self._worker.boot_log.encode("utf-8")

    def close_channel(self, key: str) -> None:
        self._connected.discard(key)

    def write_to_channel(self, key: str, payload: bytes) -> None:
        self._worker.receive(payload)

    def get_read_buffer(self, key: str) -> bytearray:
        return self._worker.buffer

    def clear_read_buffer(self, key: str) -> None:
        self._worker.buffer.clear()


# ------------------------------------------------------ scripted drivers
# unit -> scripted reading for rows whose YAML limits are open
_UNIT_FALLBACK = {"V": 3.3, "Ω": 12.34, "Hz": 4000200.0, "ch": 24.0}


def _mid_limit(lo_s: str, hi_s: str, fallback: float) -> float:
    """Healthy scripted value: the middle of the YAML limit window."""
    try:
        lo = float(str(lo_s))
    except (TypeError, ValueError):
        lo = None
    try:
        hi = float(str(hi_s))
    except (TypeError, ValueError):
        hi = None
    if lo is not None and hi is not None:
        return (lo + hi) / 2.0
    if lo is not None:
        return lo + abs(lo) * 0.01
    if hi is not None:
        return hi - abs(hi) * 0.01
    return fallback


def _scripted_value(key, fallback: float) -> float:
    """Scripted reading for one measurement row: the demo derives
    healthy values from the YAML limits (engine.demo carries them in
    mtkgui.drivers._scripted_values); rows without an entry fall back
    to the unit default."""
    module = sys.modules.get("mtkgui.drivers")
    values = getattr(module, "_scripted_values", None) or {}
    return float(values.get(key, fallback))


def _install_scripted_drivers(force: bool = True):
    """Inject a mtkgui.drivers stub (scripted T1 API) so the demo can
    exercise the RealGateway path offline, without instruments.  The
    demo is an offline simulation tool by design - it never touches
    real hardware (hardware runs use the GUI).

    Returns a cleanup callable that removes the stub again."""
    if "mtkgui.drivers" in sys.modules and not force:
        return None  # real drivers already importable - use them

    from types import ModuleType
    from datetime import datetime, timezone

    class Status:
        OK = "OK"
        FAIL = "FAIL"
        ERROR = "ERROR"
        TIMEOUT = "TIMEOUT"

    class InstrumentError(Exception):
        pass

    class InstrumentConfigError(InstrumentError):
        pass

    class MeasurementResult:
        def __init__(self, value, unit, status=Status.OK,
                     source="SCRIPTED"):
            self.value = value
            self.unit = unit
            self.status = status
            self.timestamp = datetime.now(timezone.utc)
            self.source = source

    class _ScriptedDriver:
        def __init__(self, *args, **kwargs):
            self.is_open = False

        def open(self, address, options):
            self.is_open = True   # scripted: no hardware behind it

        def close(self):
            self.is_open = False

        def identify(self):
            return "SCRIPTED-DRIVER (offline demo)"

    class DAQ973ADriver(_ScriptedDriver):
        def measure_resistance_2w(self, channels, **kw):
            return MeasurementResult(
                _scripted_value(channels, 12.34), "Ohm")

        def measure_dcv(self, channels, **kw):
            return MeasurementResult(_scripted_value(channels, 3.3), "V")

        def measure_frequency(self, channels, **kw):
            return MeasurementResult(
                _scripted_value(channels, 4000200.0), "Hz")

        def write_dio(self, channels, value):
            return None

        def reset(self):
            return None

    class U2355ADriver(_ScriptedDriver):
        def measure_counter(self, channel, gate_s=None):
            return MeasurementResult(_scripted_value(channel, 4000200.0),
                                     "Hz")

        def dio_read(self, channels):
            return MeasurementResult(24, "")

        def capture_ai(self, channels, rate_hz, samples):
            n = int(samples)
            rows = []
            for idx, _ch in enumerate(channels):
                vnom = [3.3, 1.8, 1.1, 5.0][idx % 4]
                rows.append([vnom * (1.0 if i > n // 4 else 0.0)
                             for i in range(n)])
            return rows

    class N5747ADriver(_ScriptedDriver):
        def set_voltage(self, volts):
            self._v = volts

        def set_current(self, amps):
            self._i = amps

        def output_on(self):
            pass

        def output_off(self):
            pass

        def measure_voltage(self):
            return MeasurementResult(getattr(self, "_v", 5.0), "V")

        def reset(self):
            pass

    class RFResult(MeasurementResult):
        pass

    class RFTestReport:
        def __init__(self):
            self.verdict = Status.OK
            self.results = []
            self.summary = "scripted RF pass"

    class WiFiRFTestDriver(_ScriptedDriver):
        def run_test(self, config):
            return RFTestReport()

    class BluetoothRFTestDriver(_ScriptedDriver):
        def run_test(self, config):
            return RFTestReport()

    class JLinkDriver(_ScriptedDriver):
        def flash_firmware(self, firmware_path, verify=True,
                           reset_and_run=True, erase=False):
            return MeasurementResult(524288, "")

    module = ModuleType("mtkgui.drivers")
    for name, obj in (
            ("Status", Status), ("InstrumentError", InstrumentError),
            ("InstrumentConfigError", InstrumentConfigError),
            ("InstrumentIOError", InstrumentError),
            ("InstrumentTimeoutError", InstrumentError),
            ("ConnectionLostError", InstrumentError),
            ("MeasurementResult", MeasurementResult),
            ("DAQ973ADriver", DAQ973ADriver), ("U2355ADriver",
                                               U2355ADriver),
            ("N5747ADriver", N5747ADriver), ("JLinkDriver", JLinkDriver),
            ("WiFiRFTestDriver", WiFiRFTestDriver),
            ("BluetoothRFTestDriver", BluetoothRFTestDriver),
            ("SubprocessExecutor", _ScriptedDriver)):
        setattr(module, name, obj)
    import mtkgui as _pkg

    sys.modules["mtkgui.drivers"] = module
    _pkg.drivers = module  # required by `from .. import drivers`

    def cleanup() -> None:
        sys.modules.pop("mtkgui.drivers", None)
        if getattr(_pkg, "drivers", None) is module:
            del _pkg.drivers

    return cleanup


# ------------------------------------------------------------ headless env
class HeadlessEnv:
    """RunnerEnv bridge for headless runs: stdout log, in-memory result
    rows, scripted console / rails - the same interface the Qt workflow
    page implements for the TestRunner."""

    def __init__(self, stages, *, mode: str = "virtual",
                 config: dict | None = None, logs_dir: Path | None = None,
                 stop_on_fail: bool = True, fast: bool = True):
        self.stages = stages
        self.mode = mode
        self.virtual_mode = mode == "virtual"
        cfg = config or {}
        wf = cfg.get("test_workflow") or {}
        # rows: stage 0 = ICT rows, everything else = FCT rows
        self.ict_steps = [s.as_ict_tuple() for s in stages[0].steps]
        self.ict_enables = [s.enable for s in stages[0].steps]
        self.ict_waits = [0 if fast else s.wait_ms
                          for s in stages[0].steps]
        fct = [s for stage in stages[1:] for s in stage.steps]
        # the offline demo runs flash steps with scripted images when
        # the project YAML defines no firmware section (the engine
        # itself never guesses an image path)
        for s in stages[0].steps + fct:
            p = s.op_params or {}
            if p.get("type") == "flash" and not p.get("image"):
                p["image"] = f"demo/{p.get('slot', 'fw')}_firmware.bin"
                s.op_params = p
                # the scripted demo image must pass the flash parameter
                # existence check (P1 Task6) - create it on demand
                if not os.path.isfile(p["image"]):
                    os.makedirs(os.path.dirname(p["image"]) or ".",
                                exist_ok=True)
                    with open(p["image"], "wb") as fh:
                        fh.write(b"\xde\xad\xbe\xef")
        self.fct_rows = [s.name for s in fct]
        self.fct_kinds = [s.kind for s in fct]
        self.fct_op_params = [s.op_params for s in fct]
        self.fct_enables = [s.enable for s in fct]
        self.fct_waits = [0 if fast else s.wait_ms for s in fct]
        self.fct_timeouts = [s.timeout_ms for s in fct]
        self._overall_en = [s.enable for s in stages]
        # stop strategies: the headless demo defaults to "Stop if
        # failure" (production requirement); override via --no-stop-on-fail
        self.stop_if_failure = stop_on_fail
        self.stop_if_any_short = bool(wf.get("stop_if_any_short", True))
        # power rails capture settings from the YAML (defaults like page)
        rails_cfg = wf.get("power_rails_up_sequence") or {}
        self.rails = [(r["name"], r.get("color", "#000"),
                       float(r.get("nominal_v", 1.0)),
                       float(r.get("ramp_offset_s", 0.0)))
                      for r in rails_cfg.get("rails", [])]
        self.cap_start = -0.5
        self.cap_end = float(rails_cfg.get("duration_s", 6.0))
        self.cap_rate = int(rails_cfg.get("sample_rate_hz", 200))
        self.csv_export = True
        self.logs_dir = Path(logs_dir or "logs")
        # instrument backends
        self.rack = None
        self.gateway = None
        if self.virtual_mode:
            from ..virtual_hardware import VirtualRack

            # fixed seed: the headless demo and the pytest suite must be
            # deterministic (P0 acceptance: zero flaky runs); fault
            # injection ratios are still set via set_fault_ratios()
            self.rack = VirtualRack(seed=42)
        else:
            from .instruments import RealGateway

            self.gateway = RealGateway(self._scripted_equipment(cfg))
        self.multi_console = HeadlessConsole()
        # run bookkeeping
        self.cycle_times: list[float] = []
        self.products_passed = 0
        self.products_failed = 0
        self._sn = 0
        # context-menu sim-fail hooks (the page owns these in the GUI)
        self.ict_sim_fail: set[int] = set()
        self.fct_sim_fail: set[int] = set()
        self.rows: dict[tuple, str] = {}
        self.measured: dict[tuple, object] = {}
        self.rail_samples = None
        self.rail_volts = None
        self.rail_csv_path = None
        self.ai_review_text = None
        self.runner: TestRunner | None = None

    def _scripted_equipment(self, cfg: dict) -> dict:
        """Equipment section for the offline real-mode demo: keep every
        YAML value, fill the missing instrument addresses and the
        measurement-channel mappings with scripted placeholders (the
        gateway stays config-driven; the stub drivers ignore them)."""
        equipment = dict(cfg.get("equipment") or {})
        for key in ("daq973a", "u2355a", "psu", "jlink", "fixture"):
            entry = dict(equipment.get(key) or {})
            fields = dict(entry.get("fields") or {})
            if key == "fixture":
                fields.setdefault("Channel", "SCRIPTED_DIO")
            else:
                fields.setdefault("Address", "SCRIPTED")
            entry["fields"] = fields
            equipment[key] = entry
        if not equipment.get("measure_channels"):
            equipment["measure_channels"] = {
                step.name: step.name
                for stage in self.stages for step in stage.steps
                if step.kind not in ("op", "DAQ AI")}
        if not equipment.get("rail_channels"):
            equipment["rail_channels"] = [
                f"AI{i + 1}" for i in range(len(self.rails))]
        # scripted readings: healthy values derived from the YAML
        # limits (mid of min..max) so the offline demo passes without
        # any hardcoded product parameter
        sys.modules.get("mtkgui.drivers", None)  # ensure attribute safe
        values: dict[str, float] = {}
        for stage in self.stages:
            for step in stage.steps:
                if step.kind in ("op", "DAQ AI"):
                    continue
                values[step.name] = _mid_limit(
                    step.lo, step.hi,
                    _UNIT_FALLBACK.get(step.unit, 0.0))
        module = sys.modules.get("mtkgui.drivers")
        if module is not None:
            module._scripted_values = values
        return equipment

    # ------------------------------------------------- RunnerEnv bridge
    def overall_en(self) -> list:
        return self._overall_en

    def _stop_flags(self) -> tuple:
        return (self.stop_if_failure, self.stop_if_any_short)

    def _interval_s(self) -> float:
        return 0.0

    def _stage_name(self, r: int) -> str:
        return self.stages[r].name if r < len(self.stages) else "?"

    def _fct_row_count(self) -> int:
        return len(self.fct_rows)

    def _steps_template(self, ict_count: int, fct_count: int) -> list:
        """Run steps for the staged sequence: ICT rows, then every
        non-ICT stage's rows with stage markers between (the production
        flow needs flash stages the 2-stage GUI template cannot express)."""
        steps: list[tuple] = []
        if self._overall_en[0]:
            steps += [("ict", r) for r in range(ict_count)]
            steps.append(("stage", 0))
        fct_index = 0
        for i in range(1, len(self.stages)):
            if not self._overall_en[i]:
                continue
            stage = self.stages[i]
            if stage.steps and fct_index == 0:
                steps.append(("fctconn",))
            for _s in stage.steps:
                steps.append(("fct", fct_index))
                fct_index += 1
            steps.append(("stage", i))
        return steps

    def _virtual_fault_roll(self, allow_fail=True, allow_error=True):
        if not self.virtual_mode:
            return None
        if self.rack is not None:
            return self.rack.policy.roll(allow_fail=allow_fail,
                                         allow_error=allow_error)
        return None

    # rendering hooks (engine -> env)
    def _render_step(self, kind, row, status, measured, duration):
        key = (kind, row)
        text = display_text(status, self._kind_hint(kind, row)) \
            if isinstance(status, StepStatus) else status
        self.rows[key] = text
        if measured is not None:
            self.measured[key] = measured

    def _kind_hint(self, kind, row):
        if kind == "ict":
            return "op" if self.ict_steps[row][0] == "op" else ""
        if kind == "fct":
            k = self.fct_kinds[row] if row < len(self.fct_kinds) else ""
            return "op" if k == "op" else ""
        return ""

    def _store_rail_capture(self, samples, volts, plot_cache, csv_path,
                            review):
        self.rail_samples = samples
        self.rail_volts = volts
        self.rail_csv_path = csv_path
        self.ai_review_text = review

    def _emit_progress(self, done, total):
        pass  # headless: no status bar

    def _highlight_step(self, kind, row):
        pass

    def _mark_stage_skipped(self, r, text):
        self._log(text)

    def _instrument_error(self, abbr):
        self._log(f"[equipment fault] {abbr}")

    def _connect_failed_popup(self, labels):
        self._log(f"[popup] Console Connect Failed: {labels}")

    # data service delegates (engine -> env)
    def _generate_rail_samples(self, inject_faults=True):
        return capture_samples(self.rack, self.rails, self.cap_start,
                               self.cap_end, self.cap_rate,
                               inject_faults=inject_faults)

    def _rail_plot_data(self, samples):
        return rail_plot_data(self.rails, samples)

    def _write_csv(self, samples, volts=None):
        self.logs_dir.mkdir(exist_ok=True)
        return write_csv(self.logs_dir, self.rails, samples, volts,
                         self.cap_start, self.cap_rate, self.virtual_mode)

    def _ai_wave_review(self):
        return ai_wave_review(self.rails, self.rail_samples,
                              self.cap_start, self.cap_end, self.cap_rate,
                              self.virtual_mode)

    # run-control rendering
    def _log(self, line: str) -> None:
        print(f"  {line}")

    def _set_phase(self, text):
        pass

    def _clear_highlight(self):
        pass

    def _fill_ict_row(self, r, placeholder=False):
        pass

    def _update_result(self):
        pass

    def _count_product(self):
        verdict = (self.runner.verdict() if self.runner is not None
                   else None)
        if verdict == "FAIL":
            self.products_failed += 1
        else:
            self.products_passed += 1

    def _next_serial(self):
        self._sn += 1

    def _fct_message_dialog(self, kind, name):
        return "PASS"  # headless: operator confirms

    # ---------------------------------------------------------- report
    def print_report(self) -> None:
        print()
        print("=" * 62)
        print("TEST SEQUENCE REPORT (headless)")
        print("=" * 62)
        fct_index = 0
        for i, stage in enumerate(self.stages):
            print(f"\nStage {i + 1}: {stage.name}  "
                  f"[{self.rows.get(('stage', i), '—')}]")
            if i == 0:
                for r, step in enumerate(stage.steps):
                    self._print_row("ict", r, step.name,
                                    self.ict_steps[r][2])
            else:
                for step in stage.steps:
                    self._print_row("fct", fct_index, step.name,
                                    step.unit)
                    fct_index += 1
        verdict = (self.runner.verdict() if self.runner is not None
                   else None)
        print("\n" + "-" * 62)
        cycle = (f"{sum(self.cycle_times) / len(self.cycle_times):.2f} s"
                 if self.cycle_times else "—")
        print(f"Overall Result : {verdict or '—'}   "
              f"(cycle {cycle})")
        if self.rail_csv_path is not None:
            print(f"Rail CSV log   : {self.rail_csv_path}")
        print(f"Products       : passed {self.products_passed}, "
              f"failed {self.products_failed}")

    def _print_row(self, kind, row, name, unit):
        status = self.rows.get((kind, row), "—")
        measured = self.measured.get((kind, row))
        extra = f"  = {measured}" if measured not in (None, "") else ""
        print(f"  [{status:>7}] {name}{extra}")


# ----------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mtkgui.engine.demo",
        description="Headless full-sequence test run (no GUI).")
    parser.add_argument(
        "--config",
        default="projects/96317/A-96317_96317_EVT-(Proto-1)_rev1.1.yaml",
        help="project YAML (loaded via the Common loader)")
    parser.add_argument("--mode", choices=("virtual", "real"),
                        default="virtual",
                        help="virtual DUT or scripted real-mode drivers")
    parser.add_argument("--inject", default="",
                        metavar="fail=P,err=P",
                        help="virtual fault injection percentages")
    parser.add_argument("--no-stop-on-fail", action="store_true",
                        help="keep running after a FAIL step")
    parser.add_argument("--realtime", action="store_true",
                        help="honor the YAML per-step wait times")
    parser.add_argument("--retry", type=int, default=None, metavar="N",
                        help="retry a FAIL/ERROR step up to N times "
                        "(default: YAML test_workflow.retry, else 0)")
    parser.add_argument("--logs-dir", default="logs",
                        help="CSV / AI review output directory")
    args = parser.parse_args(argv)

    # Common loader: the engine never parses YAML itself (spec §1.1)
    from ..project_config import load_config

    config = load_config(args.config) if Path(args.config).exists() else {}
    if not config:
        print(f"ERROR: project YAML not found: {args.config}",
              file=sys.stderr)
        return 2

    # a QCoreApplication must exist exactly once per process (demo may
    # run multiple times in-process, e.g. under pytest)
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(argv or ["mtkgui-engine-demo"])

    if args.mode == "real":
        cleanup_drivers = _install_scripted_drivers()
    else:
        cleanup_drivers = None
    fail_pct = err_pct = 0.0
    if args.inject:
        for part in args.inject.split(","):
            key, _, val = part.partition("=")
            try:
                if key.strip() == "fail":
                    fail_pct = float(val)
                elif key.strip() == "err":
                    err_pct = float(val)
            except ValueError:
                print(f"WARNING: bad --inject part '{part}'",
                      file=sys.stderr)

    stages = load_sequence(config)
    env = HeadlessEnv(stages, mode=args.mode, config=config,
                      logs_dir=Path(args.logs_dir),
                      stop_on_fail=not args.no_stop_on_fail,
                      fast=not args.realtime)
    runner = TestRunner(env)
    # basic fault-policy retry: CLI > YAML test_workflow.retry > 0 (off);
    # the source is recorded and logged at run start for traceability
    if args.retry is not None:
        runner.set_retry(args.retry, source="cli")
    else:
        runner.set_retry((config.get("test_workflow") or {}).get("retry"),
                         source="yaml")
    if runner.retry_count:
        print(f"Step retry: {runner.retry_count} attempt(s) on FAIL/ERROR "
              f"(source: {runner.retry_source})")
    env.runner = runner
    if env.rack is not None:
        env.rack.set_fault_ratios(fail_pct, err_pct)
    runner.cycle_reset.connect(lambda: env.rows.clear())
    runner.stage_skipped.connect(env._mark_stage_skipped)

    def on_finished(summary: dict) -> None:
        env.cycle_times.append(summary.get("cycle_s", 0.0))
        if summary.get("counted"):
            env._count_product()
        app.quit()

    runner.run_finished.connect(on_finished)

    print(f"mtk-gui test flow engine - headless demo "
          f"(mode: {args.mode}, config: {args.config})")
    runner.start(1)   # one cycle
    app.exec()
    env.print_report()
    if cleanup_drivers is not None:
        cleanup_drivers()
    verdict = runner.verdict()
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
