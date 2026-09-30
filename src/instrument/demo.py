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

#: scripted SCPI replies for the simulated DAQ973A transport
_SIM_SCPI = {
    "*IDN?": "Keysight Technologies,DAQ973A,DEMO00000001,A.01.00",
    "MEAS:RES? AUTO,DEF,(@101)": "+2.47300000E+02",
    "MEAS:RES? AUTO,DEF,(@102)": "+3.54800000E+02",
    "MEAS:VOLT:DC? AUTO,DEF,(@103)": "+3.29890000E+00",
}


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
    driver = DAQ973ADriver(transport=DemoScriptTransport(_SIM_SCPI))
    driver.open(daq_cfg["address"], {})
    overall = Status.OK
    results: list[MeasurementResult] = []
    for point in config.get("ict_points", []):
        if point["method"] == "resistance":
            result = driver.measure_resistance_2w(point["channel"])
            passed = (isinstance(result.value, float)
                      and result.value >= point["min_ohm"]
                      and result.value < 9.9e37)
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
        with open(args.config, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    else:
        config = yaml.safe_load(DEFAULT_CONFIG_YAML)
    demo = config.get("demo", config)

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
