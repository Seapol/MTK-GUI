# -*- coding: utf-8 -*-
"""Shared fixtures for the engine tests (headless - no GUI required)."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest

from mtkgui.engine.demo import HeadlessConsole, HeadlessEnv
from mtkgui.engine.sequence import load_sequence


def make_config() -> dict:
    """Minimal project config covering every engine feature: op steps,
    impedance screening, a measurement row, the rail capture, a console
    step, a WIFI RF row and a J-Link flash row."""
    return {
        "product": {"part_number": "TEST-0001", "core_id": "M33",
                    "batch": "B1"},
        "test_workflow": {
            "overall_flow": [
                {"stage": "ICT", "description": "", "enable": True},
                {"stage": "FCT", "description": "", "enable": True},
            ],
            "stop_if_failure": False,
            "stop_if_any_short": True,
            "ict_test_cases": [
                {"name": "Init Instruments", "kind": "op",
                 "op_params": {"type": "instruments",
                               "instruments": ["DAQM", "DAQ", "PSU"]}},
                {"name": "Impedance Shorts (80 pts)",
                 "kind": "Static Impedance", "unit": "Ω",
                 "threshold_min": "1.5", "threshold_max": "—"},
                {"name": "Power On DUT", "kind": "op",
                 "op_params": {"type": "power", "voltage": 5.0,
                               "current": 1.0}},
                {"name": "Power Voltage (80 pts)", "kind": "Power Voltage",
                 "unit": "V", "threshold_min": "3.201",
                 "threshold_max": "3.399"},
                {"name": "CLKOUT1 - 4 MHz (U2355A CTR0)", "kind": "Clock Hz",
                 "unit": "Hz", "threshold_min": "3996000",
                 "threshold_max": "4004000"},
                {"name": "Power Rails Up Sequence", "kind": "DAQ AI"},
            ],
            "power_rails_up_sequence": {
                "instrument": "U2355A", "channels": ["AI1"],
                "duration_s": 1.0, "sample_rate_hz": 100,
                "rails": [{"name": "VDD_3V3", "nominal_v": 3.3,
                           "ramp_offset_s": 0.0, "color": "#c00"}],
            },
            "fct_test_cases": [
                {"name": "SendtoCLI: \"wifi_test --scan\", "
                         "'Pass' (expected)",
                 "kind": "SendtoCLI", "timeout_ms": 2000},
                {"name": "WIFI: scan and associate", "kind": "WIFI",
                 "op_params": {"ssid": "TESTNET", "password": "",
                               "target_ip": "192.168.1.1",
                               "limits": {"min_rssi_dbm": -70,
                                          "max_ping_ms": 50,
                                          "max_packet_loss_pct": 0,
                                          "min_throughput_mbps": 10}}},
                {"name": "Flash FAT Firmware", "kind": "op",
                 "op_params": {"type": "flash", "slot": "fat",
                               "image": "firmware/fat.bin",
                               "device": "MIMXRT700xxxxx"}},
            ],
        },
        "equipment": {
            "daq973a": {"fields": {"Address": "GPIB0::9::INSTR"}},
            "u2355a": {"fields": {"Address": "USB0::U2355A::INSTR"}},
            "psu": {"fields": {"Address": "TCPIP0::192.168.1.20::inst0"}},
            "jlink": {"fields": {"Address": "/usr/bin/JLinkExe"}},
            "fixture": {"fields": {"Channel": "DIO16"}},
        },
    }


def make_env(config: dict | None = None, mode: str = "virtual",
             tmp_path=None, stop_on_fail: bool = True):
    """Headless environment over the demo bridge (the same interface
    the Qt workflow page implements for the TestRunner)."""
    config = config or make_config()
    stages = load_sequence(config)
    env = HeadlessEnv(stages, mode=mode, config=config,
                      logs_dir=tmp_path or "logs",
                      stop_on_fail=stop_on_fail, fast=True)
    # capture engine log lines for assertions (additive test hook)
    env._captured_log: list[str] = []
    _orig_log = env._log

    def _spying_log(line: str) -> None:
        env._captured_log.append(line)
        _orig_log(line)

    def _log_lines() -> list[str]:
        return list(env._captured_log)

    env._log = _spying_log
    env._log_lines = _log_lines
    return env, stages


@pytest.fixture
def env(tmp_path):
    """Default virtual-mode headless environment."""
    e, stages = make_env(tmp_path=tmp_path)
    yield e


@pytest.fixture
def scripted_drivers():
    """Install a mtkgui.drivers stub (T1 API shape) and remove it after
    the test - lets RealGateway run without the T1 branch merged."""
    mod = ModuleType("mtkgui.drivers")

    class Status:
        OK = "OK"
        FAIL = "FAIL"
        ERROR = "ERROR"
        TIMEOUT = "TIMEOUT"

    class InstrumentError(Exception):
        pass

    class InstrumentConfigError(InstrumentError):
        pass

    class InstrumentIOError(InstrumentError):
        pass

    class InstrumentTimeoutError(InstrumentError):
        pass

    class ConnectionLostError(InstrumentError):
        pass

    from datetime import datetime, timezone

    class MeasurementResult:
        def __init__(self, value, unit, status=Status.OK, source="STUB"):
            self.value = value
            self.unit = unit
            self.status = status
            self.source = source
            self.timestamp = datetime.now(timezone.utc)

    class Record:
        def __init__(self):
            self.calls: list[tuple] = []

    rec = Record()

    class DAQ973ADriver:
        def __init__(self, transport=None):
            rec.calls.append(("ctor", "DAQ973A"))

        def open(self, address, options):
            rec.calls.append(("open", "DAQ973A", address))

        def close(self):
            pass

        def identify(self):
            return "STUB DAQ973A"

        def measure_resistance_2w(self, channels, **kw):
            rec.calls.append(("ohm", channels))
            return MeasurementResult(12.34, "Ohm")

        def measure_dcv(self, channels, **kw):
            rec.calls.append(("dcv", channels))
            return MeasurementResult(3.301, "V")

        def measure_frequency(self, channels, **kw):
            rec.calls.append(("freq", channels))
            return MeasurementResult(4000200.0, "Hz")

        def write_dio(self, channels, value):
            rec.calls.append(("dio", channels, value))
            return None

        def reset(self):
            rec.calls.append(("reset", "DAQ973A"))
            return None

    class U2355ADriver:
        def __init__(self, transport=None):
            pass

        def open(self, address, options):
            pass

        def close(self):
            pass

        def identify(self):
            return "STUB U2355A"

        def measure_counter(self, channel, gate_s=None):
            return MeasurementResult(4000200.0, "Hz")

        def dio_read(self, channels):
            return MeasurementResult(24, "")

        def capture_ai(self, channels, rate_hz, samples):
            n = int(samples)
            return [[3.3 if i > n // 4 else 0.0 for i in range(n)]
                    for _ in channels]

    class N5747ADriver:
        def __init__(self, transport=None):
            self.on = False

        def open(self, address, options):
            pass

        def close(self):
            pass

        def identify(self):
            return "STUB N5747A"

        def set_voltage(self, volts):
            rec.calls.append(("set_v", volts))

        def set_current(self, amps):
            rec.calls.append(("set_i", amps))

        def output_on(self):
            self.on = True
            rec.calls.append(("out_on",))

        def output_off(self):
            self.on = False
            rec.calls.append(("out_off",))

        def measure_voltage(self):
            return MeasurementResult(5.0, "V")

        def reset(self):
            rec.calls.append(("reset", "PSU"))

    class JLinkDriver:
        def __init__(self, transport=None):
            pass

        def open(self, address, options):
            rec.calls.append(("open", "JLINK", address,
                              options.get("device")))

        def close(self):
            pass

        def identify(self):
            return "STUB JLINK"

        def flash_firmware(self, path, verify=True, reset_and_run=True,
                           erase=False):
            rec.calls.append(("flash", path, verify))
            return MeasurementResult(524288, "")

    class SubprocessExecutor:
        pass

    class RFTestReport:
        def __init__(self, verdict=Status.OK):
            self.verdict = verdict
            self.results = []
            self.summary = "stub RF report"

    class WiFiRFTestDriver:
        def __init__(self, executor=None, transport=None):
            pass

        def open(self, address, options):
            pass

        def close(self):
            pass

        def identify(self):
            return "STUB WIFI"

        def run_test(self, config):
            missing = {"ssid", "target_ip"} - set(config or {})
            if missing:
                raise InstrumentConfigError(f"missing {missing}")
            rec.calls.append(("wifi", config.get("ssid")))
            ok = config.get("limits", {}).get("min_rssi_dbm") is not None
            return RFTestReport(Status.OK if ok else Status.FAIL)

    class BluetoothRFTestDriver(WiFiRFTestDriver):
        def run_test(self, config):
            if not config.get("mac"):
                raise InstrumentConfigError("missing mac")
            return RFTestReport(Status.OK)

    for name, obj in (
            ("Status", Status), ("InstrumentError", InstrumentError),
            ("InstrumentConfigError", InstrumentConfigError),
            ("InstrumentIOError", InstrumentIOError),
            ("InstrumentTimeoutError", InstrumentTimeoutError),
            ("ConnectionLostError", ConnectionLostError),
            ("MeasurementResult", MeasurementResult),
            ("DAQ973ADriver", DAQ973ADriver),
            ("U2355ADriver", U2355ADriver),
            ("N5747ADriver", N5747ADriver),
            ("JLinkDriver", JLinkDriver),
            ("SubprocessExecutor", SubprocessExecutor),
            ("RFTestReport", RFTestReport),
            ("WiFiRFTestDriver", WiFiRFTestDriver),
            ("BluetoothRFTestDriver", BluetoothRFTestDriver)):
        setattr(mod, name, obj)
    mod._record = rec

    saved = sys.modules.get("mtkgui.drivers")
    saved_attr = getattr(__import__("mtkgui"), "drivers", None)
    import mtkgui as _pkg

    sys.modules["mtkgui.drivers"] = mod
    _pkg.drivers = mod  # required by `from .. import drivers`
    yield mod
    # restore both the module cache and the package attribute (the
    # import machinery resolves `from .. import drivers` via either)
    if saved is not None:
        sys.modules["mtkgui.drivers"] = saved
    else:
        sys.modules.pop("mtkgui.drivers", None)
    if saved_attr is not None:
        _pkg.drivers = saved_attr
    elif getattr(_pkg, "drivers", None) is mod:
        del _pkg.drivers


__all__ = ["HeadlessConsole", "HeadlessEnv", "make_config", "make_env",
           "load_sequence", "pytest"]
