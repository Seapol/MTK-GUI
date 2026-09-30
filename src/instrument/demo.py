#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless console demo for the instrument driver module.

Runs the station test sequence without any GUI and without hardware:

  1. loads the test config from a YAML file (SSID, password, BT MAC,
     iperf flag, RF limits, ICT channels/limits),
  2. instantiates the instrument drivers (DAQ973A for ICT, the WiFi RF
     wrapper and the Bluetooth RF wrapper),
  3. executes the ICT -> WiFi RF -> Bluetooth RF sequence,
  4. prints every structured MeasurementResult / RFTestReport and the
     overall PASS/FAIL verdict.

By default the demo runs fully simulated (scripted executor + mock
instrument transport), so it works on any machine - this is the same
mock-injection architecture the unit tests use.  Pass ``--real`` on
the Windows station to run the real command line tools (netsh / ping /
iperf3 / PowerShell probes); the SCPI transport still needs a real
serial/VISA link, so ICT stays simulated unless the transport is
replaced.

Usage:
    python src/instrument/demo.py [--config path/to/config.yaml] [--real]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# make the repo root importable (src/instrument/demo.py -> repo root)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml  # noqa: E402

from mtkgui.drivers.base import MeasurementResult, Status, Transport  # noqa: E402
from mtkgui.drivers.daq973a import CMD as DAQ_CMD  # noqa: E402
from mtkgui.drivers.daq973a import DAQ973ADriver  # noqa: E402
from mtkgui.drivers.bluetooth_rf import BluetoothRFTestDriver  # noqa: E402
from mtkgui.drivers.rf_common import (  # noqa: E402
    CommandExecutor,
    CommandOutcome,
    ScriptedExecutor,
    SubprocessExecutor,
)
from mtkgui.drivers.wifi_rf import WiFiRFTestDriver  # noqa: E402

#: default demo configuration (per-unit config lives in config/ YAML)
DEFAULT_CONFIG_YAML = """\
demo:
  daq973a:
    address: "COM973"          # instrument address from equipment YAML
  wifi:
    address: "wlan0"
    ssid: "MYDUT-AP"
    password: "dut-secret"
    target_ip: "192.168.4.1"
    iperf_enabled: true
    iperf_seconds: 10
    timeout_s: 15
    limits:
      min_rssi_dbm: -70
      max_ping_ms: 50
      max_packet_loss_pct: 5
      min_throughput_mbps: 10
  bluetooth:
    address: "bt-host"
    bt_type: "ble"             # "ble" or "classic"
    mac: "AA:BB:CC:DD:EE:FF"
    per_attempts: 20
    timeout_s: 15
    limits:
      min_rssi_dbm: -80
      max_per_pct: 10
  ict_points:                  # ICT sequence: 2-wire OHM then DCV
    - {name: "TP_P1",  method: "resistance", channel: "101", min_ohm: 1.5}
    - {name: "TP_P2",  method: "resistance", channel: "102", min_ohm: 1.5}
    - {name: "VDD_3V3", method: "dcv",       channel: "103",
       min_v: 3.267, max_v: 3.333}
"""

#: scripted netsh / ping / iperf3 outputs for the simulated run
_SIM_NETSH = """\
SSID 1 : MYDUT-AP
    BSSID 1 : aa:bb:cc:dd:ee:02
        Signal : 82%
"""
_SIM_INTERFACES = "    State : connected\n    SSID : MYDUT-AP\n"
_SIM_PING = """\
Reply from 192.168.4.1: bytes=32 time=11ms TTL=64
Reply from 192.168.4.1: bytes=32 time=13ms TTL=64
Reply from 192.168.4.1: bytes=32 time=12ms TTL=64
Reply from 192.168.4.1: bytes=32 time=12ms TTL=64
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
"""
_SIM_IPERF = '{"end": {"sum_received": {"bits_per_second": 25300000.0}}}'
_SIM_BT_WATCH = "AABBCCDDEEFF -55\n"
_SIM_BT_CONNECT = "CONNECT=Connected"
_SIM_BT_PER = "ATTEMPTS=20\nFAILURES=1\n"

#: base scripted SCPI replies for the simulated DAQ973A transport
#: (per-point replies are generated from the ICT point list, see
#: :func:`build_sim_scpi`)
_SIM_SCPI = {
    "*IDN?": "Keysight Technologies,DAQ973A,DEMO00000001,A.01.00",
    "MEAS:RES? AUTO,DEF,(@101)": "+2.47300000E+02",
    "MEAS:RES? AUTO,DEF,(@102)": "+3.54800000E+02",
    "MEAS:VOLT:DC? AUTO,DEF,(@103)": "+3.29890000E+00",
}

#: SCPI templates imported from the driver so generated replies match
#: the exact command strings it emits (single source of truth).
_CMD = DAQ_CMD

#: DAQM907A totalizer channels used by the demo for clock points
#: (CLK1/CLK2/CLK3 -> 1201/1202/1203, per equipment YAML slot 3).
_CLOCK_CHANNELS = ["1201", "1202", "1203"]


def _num(value) -> float | None:
    """Parse a YAML threshold string, returning ``None`` for the
    ``"-"`` / ``"—"`` placeholders used in the station YAML.

    Args:
        value: Raw threshold value.

    Returns:
        The float value, or ``None`` when not numeric.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tp_to_channel(tp: str) -> str:
    """Map a test point name to the DAQM908A multiplexer channel.

    Mapping per the equipment YAML: TP_P01-40 -> CH101-140 (slot 1),
    TP_P41-80 -> CH201-240 (slot 2).

    Args:
        tp: Test point name like ``"TP_P07"``.

    Returns:
        Channel string such as ``"107"``.
    """
    n = int(tp.replace("TP_P", ""))
    return str(100 + n if n <= 40 else 200 + (n - 40))


def load_station_config(path: str) -> dict:
    """Derive the demo ``demo`` section from a station YAML file.

    Parses ``test_workflow.ict_test_cases`` of the station config
    (Impedance Shorts / Power Voltages / Clock entries) into the
    flat ``ict_points`` list the demo ICT runner consumes.  FCT
    (WiFi / Bluetooth) parameters keep the embedded demo defaults
    when the station YAML does not define them.

    Args:
        path: Path to the station YAML (e.g. ``config/*.yaml``).

    Returns:
        A ``demo`` config dict with ``ict_points`` filled in.

    Raises:
        OSError / yaml.YAMLError: on unreadable / invalid YAML.
    """
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    points: list[dict] = []
    clock_index = 0
    for case in raw.get("test_workflow", {}).get("ict_test_cases", []):
        if not case.get("enable", True):
            continue
        name = case.get("name", "")
        if name.startswith("Impedance Shorts") and "(TP_" in name:
            min_ohm = _num(case.get("threshold_min"))
            if min_ohm is None:
                continue
            tp = "TP_" + name.rsplit("(TP_", 1)[-1].rstrip(")")
            points.append({
                "name": tp,
                "method": "resistance",
                "channel": _tp_to_channel(tp),
                "min_ohm": min_ohm,
            })
        elif name.startswith("Power Voltages") and "(TP_" in name:
            min_v = _num(case.get("threshold_min"))
            max_v = _num(case.get("threshold_max"))
            if min_v is None or max_v is None:
                continue
            tp = "TP_" + name.rsplit("(TP_", 1)[-1].rstrip(")")
            points.append({
                "name": tp,
                "method": "dcv",
                "channel": _tp_to_channel(tp),
                "min_v": min_v,
                "max_v": max_v,
            })
        elif name.startswith("Clock"):
            min_hz = _num(case.get("threshold_min"))
            max_hz = _num(case.get("threshold_max"))
            if min_hz is None or max_hz is None:
                continue
            points.append({
                "name": name,
                "method": "freq",
                "channel": _CLOCK_CHANNELS[clock_index % len(_CLOCK_CHANNELS)],
                "min_hz": float(case["threshold_min"]),
                "max_hz": float(case["threshold_max"]),
            })
            clock_index += 1

    demo = dict(yaml.safe_load(DEFAULT_CONFIG_YAML)["demo"])
    demo["ict_points"] = points
    demo["station"] = {
        "product": raw.get("product", {}),
        "config_path": str(path),
    }
    return demo


def build_sim_scpi(points: list[dict]) -> dict[str, str]:
    """Generate scripted SCPI replies for the demo ICT point list.

    Every point gets a passing reading at (or near) the middle of its
    limit window, so the simulated run exercises the full judging
    logic without hardware.

    Args:
        points: ICT point list (resistance / dcv / freq entries).

    Returns:
        Command -> reply mapping for :class:`DemoScriptTransport`.
    """
    script = dict(_SIM_SCPI)
    for point in points:
        chans = point["channel"]
        if point["method"] == "resistance":
            cmd = _CMD["meas_res"].format(range="AUTO", res="DEF", chans=chans)
            script[cmd] = "+2.47300000E+02"
        elif point["method"] == "dcv":
            cmd = _CMD["meas_vdc"].format(range="AUTO", res="DEF", chans=chans)
            mid = (point["min_v"] + point["max_v"]) / 2.0
            script[cmd] = f"{mid:.8E}"
        elif point["method"] == "freq":
            cmd = _CMD["meas_freq"].format(chans=chans)
            mid = (point["min_hz"] + point["max_hz"]) / 2.0
            script[cmd] = f"{mid:.8E}"
    return script


class DemoScriptTransport(Transport):
    """Minimal mock transport replaying the scripted SCPI replies."""

    def __init__(self, script: dict[str, str]) -> None:
        self.script = dict(script)
        self._open = False

    def open(self, address: str, options: dict) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, command: str) -> None:
        if not self._open:
            from mtkgui.drivers.errors import ConnectionLostError
            raise ConnectionLostError("demo transport not open")

    def query(self, command: str) -> str:
        self.write(command)
        return self.script.get(command, '+0,"No error"')


class DemoBTExecutor(CommandExecutor):
    """Simulated executor for the Bluetooth probes (content-based
    selection, mirroring the unit-test ContentExecutor pattern)."""

    def __init__(self) -> None:
        self.script = {
            "AdvertisementWatcher":
                CommandOutcome(["powershell"], 0, _SIM_BT_WATCH, ""),
            "BluetoothLEDevice":
                CommandOutcome(["powershell"], 0, _SIM_BT_CONNECT, ""),
            "BluetoothDevice]::FromBluetoothAddressAsync":
                CommandOutcome(["powershell"], 0, _SIM_BT_CONNECT, ""),
            "FAILURES=": CommandOutcome(["powershell"], 0, _SIM_BT_PER, ""),
        }

    def run(self, command: list[str], timeout_s: float) -> CommandOutcome:
        joined = " ".join(command)
        for needle, outcome in self.script.items():
            if needle in joined:
                return outcome
        return CommandOutcome(command, 0, "", "")


def build_wifi_executor(real: bool) -> CommandExecutor:
    """Return the real or the simulated WiFi command executor.

    Args:
        real: ``True`` runs the actual Windows tools.

    Returns:
        A :class:`CommandExecutor` instance.
    """
    if real:
        return SubprocessExecutor()
    return ScriptedExecutor({
        "netsh wlan show networks":
            CommandOutcome(["netsh"], 0, _SIM_NETSH, ""),
        "netsh wlan add": CommandOutcome(["netsh"], 0, "ok", ""),
        "netsh wlan connect": CommandOutcome(["netsh"], 0, "ok", ""),
        "netsh wlan show interfaces":
            CommandOutcome(["netsh"], 0, _SIM_INTERFACES, ""),
        "netsh wlan delete": CommandOutcome(["netsh"], 0, "ok", ""),
        "ping": CommandOutcome(["ping"], 0, _SIM_PING, ""),
        "iperf3": CommandOutcome(["iperf3"], 0, _SIM_IPERF, ""),
    })


def run_ict(config: dict) -> tuple[Status, list[MeasurementResult]]:
    """Run the ICT sequence and judge it against the YAML limits.

    NOTE: the limit evaluation here is demo/engine logic (the driver
    only measures); in the full station the test flow engine owns it.

    Args:
        config: ``demo`` section of the YAML config.

    Returns:
        ``(overall_status, results)`` tuple.
    """
    daq_cfg = config["daq973a"]
    points = config.get("ict_points", [])
    driver = DAQ973ADriver(transport=DemoScriptTransport(build_sim_scpi(points)))
    driver.open(daq_cfg["address"], {})
    overall = Status.OK
    results: list[MeasurementResult] = []
    for point in points:
        if point["method"] == "resistance":
            result = driver.measure_resistance_2w(point["channel"])
            passed = (isinstance(result.value, float)
                      and result.value >= point["min_ohm"]
                      and result.value < 9.9e37)
        elif point["method"] == "freq":
            result = driver.measure_frequency(point["channel"])
            passed = (isinstance(result.value, float)
                      and point["min_hz"] <= result.value <= point["max_hz"])
        else:
            result = driver.measure_dcv(point["channel"])
            passed = (isinstance(result.value, float)
                      and point["min_v"] <= result.value <= point["max_v"])
        results.append(result)
        if not passed and overall is Status.OK:
            overall = Status.FAIL
    driver.close()
    return overall, results


def print_result(result: MeasurementResult) -> None:
    """Print one structured measurement result line.

    Args:
        result: The measurement to print.
    """
    print(f"    [{result.source}] {result.value} {result.unit}"
          f"  ->  {result.status.value}  "
          f"({result.timestamp.isoformat(timespec='seconds')})")


def verdict_text(status: Status) -> str:
    """Render a spec Status as the station's PASS/FAIL wording.

    Args:
        status: Verdict status (``Status.OK`` or ``Status.FAIL``).

    Returns:
        ``"PASS"`` for OK, ``"FAIL"`` otherwise.
    """
    return "PASS" if status is Status.OK else "FAIL"


def main() -> int:
    """Entry point.

    Returns:
        Process exit code: 0 = PASS, 1 = FAIL, 2 = config error.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=None,
                        help="path to the demo YAML config "
                             "(default: embedded demo config)")
    parser.add_argument("--real", action="store_true",
                        help="use the real Windows tools (netsh, ping, "
                             "iperf3, PowerShell) instead of the "
                             "simulated executor")
    args = parser.parse_args()

    if args.config:
        demo = load_station_config(args.config)
        product = demo.get("station", {}).get("product", {})
        if product:
            print(f"config: {product.get('part_number', '?')} "
                  f"(core {product.get('core_id', '?')}, "
                  f"batch {product.get('batch', '?')})")
    else:
        demo = yaml.safe_load(DEFAULT_CONFIG_YAML)["demo"]

    print("=" * 72)
    print("MTK-GUI instrument driver demo (headless)")
    print("=" * 72)

    # -- 1. ICT ------------------------------------------------------------
    print("\n[1/3] ICT - DAQ973A impedance / DCV")
    ict_status, ict_results = run_ict(demo)
    for result in ict_results:
        print_result(result)
    print(f"  ICT verdict: {verdict_text(ict_status)}")

    # -- 2. WiFi RF ----------------------------------------------------------
    print("\n[2/3] WiFi RF test (host adapter)")
    wifi = WiFiRFTestDriver(executor=build_wifi_executor(args.real))
    wifi.open(demo["wifi"]["address"], {})
    wifi_report = wifi.run_test(demo["wifi"])
    for result in wifi_report.results:
        print_result(result)
    print(f"  WiFi verdict: {verdict_text(wifi_report.verdict)} "
          f"({wifi_report.summary})")
    wifi.close()

    # -- 3. Bluetooth RF -------------------------------------------------------
    print("\n[3/3] Bluetooth RF test - "
          f"{demo['bluetooth']['bt_type'].upper()} (host adapter)")
    bt = BluetoothRFTestDriver(
        executor=SubprocessExecutor() if args.real else DemoBTExecutor())
    bt.open(demo["bluetooth"]["address"], {})
    bt_report = bt.run_test(demo["bluetooth"])
    for result in bt_report.results:
        print_result(result)
    print(f"  Bluetooth verdict: {verdict_text(bt_report.verdict)} "
          f"({bt_report.summary})")
    bt.close()

    # -- overall rollup -------------------------------------------------------
    verdicts = [ict_status, wifi_report.verdict, bt_report.verdict]
    overall = Status.OK if all(v is Status.OK for v in verdicts) \
        else Status.FAIL
    print("\n" + "=" * 72)
    print(f"OVERALL VERDICT: {verdict_text(overall)}")
    print("=" * 72)
    return 0 if overall is Status.OK else 1


if __name__ == "__main__":
    sys.exit(main())
