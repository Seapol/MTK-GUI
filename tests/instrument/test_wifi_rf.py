# -*- coding: utf-8 -*-
"""Unit tests for the WiFi RF test wrapper (scripted executor mocks
the Windows netsh / ping / iperf3 tools)."""

from __future__ import annotations

import pytest

from mtkgui.drivers.base import Status
from mtkgui.drivers.errors import (
    ConnectionLostError,
    InstrumentConfigError,
    InstrumentIOError,
    InstrumentTimeoutError,
)
from mtkgui.drivers.rf_common import CommandOutcome, ScriptedExecutor
from mtkgui.drivers.wifi_rf import (
    WiFiRFTestDriver,
    netsh_signal_to_dbm,
    parse_netsh_interfaces,
    parse_netsh_networks,
    parse_ping_windows,
    parse_iperf_json,
)

ADDR = "wlan0"  # example address as it would come from config/ YAML

NETSH_FOUND = """\
Interface name : Wi-Fi
There are 3 networks currently visible.

SSID 1 : HOME_ROUTER
    Authentication : WPA2-Personal
    BSSID 1 : aa:bb:cc:dd:ee:01
        Signal : 60%

SSID 2 : MYDUT-AP
    Authentication : WPA2-Personal
    BSSID 1 : aa:bb:cc:dd:ee:02
        Signal : 82%
    BSSID 2 : aa:bb:cc:dd:ee:03
        Signal : 40%

SSID 3 : NEIGHBOR
    Authentication : Open
    Signal : 30%
"""

NETSH_EMPTY = "Interface name : Wi-Fi\nThere are 0 networks currently visible.\n"

NETSH_INTERFACES_CONNECTED = """\
    Name                   : Wi-Fi
    State                  : connected
    SSID                   : MYDUT-AP
"""

NETSH_INTERFACES_DISCONNECTED = """\
    Name                   : Wi-Fi
    State                  : disconnected
"""

PING_OK = """\
Pinging 192.168.4.1 with 32 bytes of data:
Reply from 192.168.4.1: bytes=32 time=10ms TTL=64
Reply from 192.168.4.1: bytes=32 time=12ms TTL=64
Reply from 192.168.4.1: bytes=32 time=14ms TTL=64
Reply from 192.168.4.1: bytes=32 time=12ms TTL=64

Ping statistics for 192.168.4.1:
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 10ms, Maximum = 14ms, Average = 12ms
"""

PING_LOSSY = """\
Reply from 192.168.4.1: bytes=32 time=20ms TTL=64
Reply from 192.168.4.1: bytes=32 time=24ms TTL=64
Request timed out.
Request timed out.

Ping statistics for 192.168.4.1:
    Packets: Sent = 4, Received = 2, Lost = 2 (50% loss),
"""

IPERF_JSON = '{"end": {"sum_received": {"bits_per_second": 25000000.0}}}'


def make_wifi(script: dict) -> WiFiRFTestDriver:
    """Return an open WiFi wrapper over a scripted executor."""
    driver = WiFiRFTestDriver(executor=ScriptedExecutor(script))
    driver.open(ADDR, {})
    return driver


def wifi_config(**overrides) -> dict:
    """Return a valid run_test config (as the engine would build from
    config/ YAML); overrides patch top-level keys."""
    cfg = {
        "ssid": "MYDUT-AP", "password": "secret", "target_ip": "192.168.4.1",
        "iperf_enabled": False, "timeout_s": 10.0,
        "limits": {"min_rssi_dbm": -70.0, "max_ping_ms": 50.0,
                   "max_packet_loss_pct": 5.0, "min_throughput_mbps": 10.0},
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# parser unit tests
# ---------------------------------------------------------------------------


def test_netsh_signal_to_dbm():
    """netsh percentage maps to the documented dBm estimate."""
    assert netsh_signal_to_dbm(82) == pytest.approx(-59.0)
    assert netsh_signal_to_dbm(100) == pytest.approx(-50.0)
    assert netsh_signal_to_dbm(0) == pytest.approx(-100.0)


def test_parse_netsh_networks_picks_best_bssid():
    """The best BSSID signal of the target SSID wins."""
    assert parse_netsh_networks(NETSH_FOUND, "MYDUT-AP") == 82
    assert parse_netsh_networks(NETSH_FOUND, "mydut-ap") == 82


def test_parse_netsh_networks_missing_ssid():
    """A missing SSID returns -1; garbage output is an error; an empty
    scan (0 networks) is a valid not-found outcome."""
    assert parse_netsh_networks(NETSH_FOUND, "NOPE") == -1
    assert parse_netsh_networks(NETSH_EMPTY, "MYDUT-AP") == -1
    with pytest.raises(InstrumentIOError):
        parse_netsh_networks("total garbage, not netsh", "MYDUT-AP")


def test_parse_netsh_interfaces():
    """State + SSID must both match for 'connected'."""
    assert parse_netsh_interfaces(NETSH_INTERFACES_CONNECTED, "MYDUT-AP")
    assert not parse_netsh_interfaces(
        NETSH_INTERFACES_CONNECTED, "OTHER")
    assert not parse_netsh_interfaces(
        NETSH_INTERFACES_DISCONNECTED, "MYDUT-AP")


def test_parse_ping_windows():
    """Latency average and loss percentage are parsed."""
    avg, loss = parse_ping_windows(PING_OK, 4)
    assert avg == pytest.approx(12.0)
    assert loss == pytest.approx(0.0)
    avg, loss = parse_ping_windows(PING_LOSSY, 4)
    assert avg == pytest.approx(22.0)
    assert loss == pytest.approx(50.0)


def test_parse_iperf_json():
    """bits_per_second converts to Mbit/s; errors raise."""
    assert parse_iperf_json(IPERF_JSON) == pytest.approx(25.0)
    with pytest.raises(InstrumentIOError):
        parse_iperf_json('{"error": "connection refused"}')
    with pytest.raises(InstrumentIOError):
        parse_iperf_json("not json")


# ---------------------------------------------------------------------------
# PASS / FAIL cases
# ---------------------------------------------------------------------------


def script_pass(iperf: bool) -> dict:
    """Executor script for a healthy test run (longest-prefix keys)."""
    script = {
        "netsh wlan show networks":
            CommandOutcome(["netsh"], 0, NETSH_FOUND, ""),
        "netsh wlan add": CommandOutcome(["netsh"], 0, "ok", ""),
        "netsh wlan connect": CommandOutcome(["netsh"], 0, "ok", ""),
        "netsh wlan show interfaces":
            CommandOutcome(["netsh"], 0, NETSH_INTERFACES_CONNECTED, ""),
        "netsh wlan delete": CommandOutcome(["netsh"], 0, "ok", ""),
        "ping": CommandOutcome(["ping"], 0, PING_OK, ""),
    }
    if iperf:
        script["iperf3"] = CommandOutcome(["iperf3"], 0, IPERF_JSON, "")
    return script


def test_run_test_pass_case():
    """Healthy DUT: all phases within limits -> verdict PASS."""
    driver = make_wifi(script_pass(iperf=True))
    report = driver.run_test(wifi_config(iperf_enabled=True))
    assert report.verdict is Status.OK
    units = [r.unit for r in report.results]
    assert units == ["dBm", "", "ms", "%", "Mbit/s"]
    assert report.results[0].value == pytest.approx(-59.0)
    assert report.results[2].value == pytest.approx(12.0)
    assert report.results[4].value == pytest.approx(25.0)
    assert "within limits" in report.summary


def test_run_test_fail_low_rssi():
    """An RSSI below the YAML limit -> verdict FAIL with a note."""
    weak = NETSH_FOUND.replace("Signal : 82%", "Signal : 22%")
    driver = make_wifi(
        {"netsh wlan show networks": CommandOutcome(["netsh"], 0, weak, ""),
         "netsh wlan add": CommandOutcome(["netsh"], 0, "ok", ""),
         "netsh wlan connect": CommandOutcome(["netsh"], 0, "ok", ""),
         "netsh wlan show interfaces":
             CommandOutcome(["netsh"], 0, NETSH_INTERFACES_CONNECTED, ""),
         "netsh wlan delete": CommandOutcome(["netsh"], 0, "ok", ""),
         "ping": CommandOutcome(["ping"], 0, PING_OK, "")})
    report = driver.run_test(wifi_config())
    assert report.verdict is Status.FAIL
    assert "RSSI" in report.summary


def test_run_test_fail_high_loss():
    """Packet loss above the limit -> verdict FAIL."""
    driver = make_wifi(
        {"netsh wlan show networks":
            CommandOutcome(["netsh"], 0, NETSH_FOUND, ""),
         "netsh wlan add": CommandOutcome(["netsh"], 0, "ok", ""),
         "netsh wlan connect": CommandOutcome(["netsh"], 0, "ok", ""),
         "netsh wlan show interfaces":
             CommandOutcome(["netsh"], 0, NETSH_INTERFACES_CONNECTED, ""),
         "netsh wlan delete": CommandOutcome(["netsh"], 0, "ok", ""),
         "ping": CommandOutcome(["ping"], 0, PING_LOSSY, "")})
    report = driver.run_test(wifi_config())
    assert report.verdict is Status.FAIL
    assert "loss" in report.summary


def test_run_test_fail_ssid_not_found():
    """An absent SSID is a FAIL (scan outcome with empty value)."""
    driver = make_wifi(
        {"netsh wlan show networks":
            CommandOutcome(["netsh"], 0, NETSH_EMPTY, "")})
    report = driver.run_test(wifi_config())
    assert report.verdict is Status.FAIL
    assert "not found" in report.summary


def test_run_test_fail_low_throughput():
    """Throughput below the limit -> verdict FAIL."""
    slow = '{"end": {"sum_received": {"bits_per_second": 5000000.0}}}'
    driver = make_wifi(
        {**script_pass(iperf=True),
         "iperf3": CommandOutcome(["iperf3"], 0, slow, "")})
    report = driver.run_test(wifi_config(iperf_enabled=True))
    assert report.verdict is Status.FAIL
    assert "throughput" in report.summary


def test_run_test_fail_connect_not_established():
    """A scan hit but failed association -> verdict FAIL."""
    driver = make_wifi(
        {"netsh wlan show networks":
            CommandOutcome(["netsh"], 0, NETSH_FOUND, ""),
         "netsh wlan add": CommandOutcome(["netsh"], 0, "ok", ""),
         "netsh wlan connect": CommandOutcome(["netsh"], 0, "ok", ""),
         "netsh wlan show interfaces":
             CommandOutcome(["netsh"], 0, NETSH_INTERFACES_DISCONNECTED, ""),
         "netsh wlan delete": CommandOutcome(["netsh"], 0, "ok", "")})
    report = driver.run_test(wifi_config())
    assert report.verdict is Status.FAIL
    assert "association" in report.summary


# ---------------------------------------------------------------------------
# timeout / exception cases
# ---------------------------------------------------------------------------


def test_run_test_scan_timeout():
    """A scan timeout becomes a recorded TIMEOUT phase and verdict
    FAIL (never raises)."""
    driver = make_wifi({"netsh": InstrumentTimeoutError("timed out")})
    report = driver.run_test(wifi_config())
    assert report.verdict is Status.FAIL
    assert report.results[-1].status is Status.ERROR
    assert "error" in report.summary.lower()


def test_measure_methods_propagate_timeout():
    """Measurement methods raise InstrumentTimeoutError (spec error
    mapping) so the engine can classify it."""
    driver = make_wifi({"ping": InstrumentTimeoutError("timed out")})
    with pytest.raises(InstrumentTimeoutError):
        driver.measure_ping("192.168.4.1")


def test_run_test_ping_io_error():
    """A missing/failed ping tool records an ERROR phase -> FAIL."""
    driver = make_wifi(
        {**script_pass(iperf=False),
         "ping": InstrumentIOError("no such tool")})
    report = driver.run_test(wifi_config())
    assert report.verdict is Status.FAIL
    assert "traffic phase error" in report.summary


def test_scan_tool_failure_raises():
    """A failing netsh invocation raises InstrumentIOError."""
    driver = make_wifi(
        {"netsh wlan show networks": CommandOutcome(["netsh"], 2, "", "boom")})
    with pytest.raises(InstrumentIOError):
        driver.scan("MYDUT-AP")


# ---------------------------------------------------------------------------
# invalid config cases
# ---------------------------------------------------------------------------


def test_run_test_rejects_missing_keys():
    """Missing YAML config keys raise InstrumentConfigError."""
    driver = make_wifi({})
    with pytest.raises(InstrumentConfigError):
        driver.run_test({"ssid": "x"})
    with pytest.raises(InstrumentConfigError):
        driver.run_test(wifi_config(limits={"min_rssi_dbm": -70}))


def test_scan_rejects_empty_ssid():
    """An empty SSID is a config error."""
    driver = make_wifi({})
    with pytest.raises(InstrumentConfigError):
        driver.scan("  ")


def test_ping_rejects_bad_count():
    """A ping count outside 1..100 is a config error."""
    driver = make_wifi({})
    with pytest.raises(InstrumentConfigError):
        driver.ping_stats("192.168.4.1", count=0)


def test_not_open_guard():
    """Operations before open() raise ConnectionLostError."""
    driver = WiFiRFTestDriver(executor=ScriptedExecutor({}))
    with pytest.raises(ConnectionLostError):
        driver.scan("MYDUT-AP")
    with pytest.raises(ConnectionLostError):
        driver.run_test(wifi_config())
