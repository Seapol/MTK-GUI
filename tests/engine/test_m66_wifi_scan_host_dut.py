# -*- coding: utf-8 -*-
"""M66: Wifi_Scan is a REAL Host <-> DUT test.

Covers the operator-selected 4-step preset (driver load -> credentials
-> join AP/hotspot -> link verdict), the DUT-side RSSI verdict with the
Host -> DUT reachability gate, and the lswifi RSSI source fix."""
from __future__ import annotations

import pytest

import mtkgui.engine.fct_exec as fe
import mtkgui.engine.host_platform as hp
from mtkgui.engine.fct_templates import (
    TEMPLATE_LABELS,
    TEMPLATE_WIFI_SCAN,
    apply_prefill,
    load_template_commands,
    template_path,
)
from mtkgui.engine.fct_test_config import (
    FctTestConfig,
    WifiCfg,
    build_fct_steps,
)


class _Channel:
    """Console channel stub: one canned output batch, then silence."""

    def __init__(self, lines):
        self._lines = list(lines)
        self.written: list = []

    def write(self, data):
        self.written.append(str(data))

    def read_lines(self, max_lines=200, timeout_s=0.1):
        if self._lines:
            out, self._lines = self._lines, []
            return out
        return []


def _rf_step(cfg, timeout_s=0.5, channel="console"):
    return fe.FctStep(
        name="Wi-Fi Scan", step_type="EXTERNAL_TOOL", channel=channel,
        timeout_s=timeout_s,
        params={"tool_family": "wifi", "rssi_via": "dut_console",
                "fct_rf": dict(cfg)})


# ------------------------------------------------- template preset (4 steps)
def test_wifi_scan_template_is_registered_and_operator_only():
    assert TEMPLATE_WIFI_SCAN in TEMPLATE_LABELS
    assert template_path(TEMPLATE_WIFI_SCAN).endswith("fct_wifi_scan.yaml")
    # loading is an explicit call - nothing loads it at import time
    cmds = load_template_commands(TEMPLATE_WIFI_SCAN, {})
    assert len(cmds) == 4
    assert [c.name for c in cmds] == [
        "Wi-Fi driver load & ready", "Wi-Fi: Connect DUT to AP",
        "DUT Wi-Fi address", "Wi-Fi Scan / RSSI (Host <-> DUT)"]
    assert [c.kind for c in cmds] == ["send", "op", "send", "wifi_test"]


def test_template_row1_gets_the_project_driver_load_command():
    cmds = load_template_commands(TEMPLATE_WIFI_SCAN, {
        "wifi_driver_load_cmd": "modprobe moal",
        "wifi_interface": "wlan0"})
    assert cmds[0].send == "modprobe moal; iw dev wlan0 info"
    plain = load_template_commands(TEMPLATE_WIFI_SCAN, {})
    assert "iw dev wlan0 info" in plain[0].send


def test_template_row2_prefills_plan_a_and_plan_b_credentials():
    cmds = load_template_commands(TEMPLATE_WIFI_SCAN, {
        "wifi_ssid": "Factory-AP", "wifi_password": "secret",
        "wifi_interface": "wlan0"})
    op = cmds[1].op_params
    assert op["type"] == "wifi_connect"
    assert op["ssid"] == "Factory-AP"
    assert op["password"] == "secret"
    assert op["iface"] == "wlan0"
    # plan B: the same row with the Host hotspot values (operator edit)
    plan_b = apply_prefill(cmds[1], {"wifi_ssid": "MTK-HOTSPOT",
                                     "wifi_password": "hotspot-pw"})
    assert plan_b.op_params["ssid"] == "MTK-HOTSPOT"
    assert plan_b.op_params["password"] == "hotspot-pw"


def test_template_row4_defaults_to_the_dut_side_verdict():
    cmds = load_template_commands(TEMPLATE_WIFI_SCAN, {})
    assert cmds[3].rf_subtest == "scan"
    assert cmds[3].step_params["scan_via"] == "dut_console"
    assert cmds[3].step_params["rssi_min"] == -70


# ----------------------------------------- Wifi_Scan default = DUT link
def test_scan_via_defaults_to_the_dut_console():
    assert WifiCfg().scan_via == "dut_console"
    cfg = FctTestConfig.from_dict({"dut_type": "linux", "wifi": {
        "scan_enabled": True, "ap_ssid": "AP"}})
    assert cfg.wifi.scan_via == "dut_console"
    assert cfg.wifi.dut_ip == ""


def test_linux_scan_builds_the_dut_console_verdict():
    cfg = FctTestConfig(dut_type="linux", wifi=WifiCfg(
        scan_enabled=True, ap_ssid="Factory-AP", interface="wlan0",
        dut_ip="192.168.1.50"))
    step = build_fct_steps(cfg)[0]
    assert step.name == "Wi-Fi Scan / RSSI (DUT console)"
    assert step.params["rssi_via"] == "dut_console"
    assert step.params["fct_rf"]["dut_ip"] == "192.168.1.50"
    assert step.params["fct_rf"]["mode"] == "rssi_only"


def test_explicit_host_scan_stays_available_as_peripheral_check():
    cfg = FctTestConfig(dut_type="linux", wifi=WifiCfg(
        scan_enabled=True, ap_ssid="Factory-AP", scan_via="host"))
    step = build_fct_steps(cfg)[0]
    assert step.name == "Wi-Fi Scan / RSSI"
    assert "rssi_via" not in step.params
    assert step.params["fct_rf"]["mode"] == "rssi_only"


# ------------------------------------------------------ DUT-side verdict
def _dut_link_output(signal_dbm):
    return [
        "Connected to 11:22:33:44:55:66 (on wlan0)",
        "\tSSID: Factory-AP",
        f"\tsignal: {signal_dbm} dBm",
        "\ttx bitrate: 72.2 MBit/s",
    ]


def test_dut_signal_above_threshold_passes():
    ctx = fe.FctContext(channels={"console": _Channel(
        _dut_link_output(-76))})
    out = fe._run_rf_tool(_rf_step({"mode": "rssi_only", "rssi_min": -80,
                                    "interface": "wlan0"}), "wifi", ctx)
    assert out.verdict == fe.VERDICT_PASS
    assert "-76" in out.reason and "min -80" in out.reason
    # the DUT was asked for its own link - never the host-side AP scan
    assert ctx.channels["console"].written == ["iw dev wlan0 link\n"]


def test_dut_signal_below_threshold_fails():
    ctx = fe.FctContext(channels={"console": _Channel(
        _dut_link_output(-76))})
    out = fe._run_rf_tool(_rf_step({"mode": "rssi_only", "rssi_min": -70,
                                    "interface": "wlan0"}), "wifi", ctx)
    assert out.verdict == fe.VERDICT_FAIL


def test_host_reaches_the_dut_ip(monkeypatch):
    monkeypatch.setattr(hp, "ping_host", lambda ip, timeout_s=4.0: True)
    ctx = fe.FctContext(channels={"console": _Channel(
        _dut_link_output(-60))})
    out = fe._run_rf_tool(_rf_step({"mode": "rssi_only", "rssi_min": -80,
                                    "interface": "wlan0",
                                    "dut_ip": "192.168.1.50"}),
                          "wifi", ctx)
    assert out.verdict == fe.VERDICT_PASS
    assert "Host -> DUT 192.168.1.50: reachable" in out.reason


def test_unreachable_dut_ip_fails_the_link(monkeypatch):
    monkeypatch.setattr(hp, "ping_host", lambda ip, timeout_s=4.0: False)
    ctx = fe.FctContext(channels={"console": _Channel(
        _dut_link_output(-60))})
    out = fe._run_rf_tool(_rf_step({"mode": "rssi_only", "rssi_min": -80,
                                    "interface": "wlan0",
                                    "dut_ip": "192.168.1.50"}),
                          "wifi", ctx)
    assert out.verdict == fe.VERDICT_FAIL
    assert "NO REPLY" in out.reason


def test_dut_without_bound_channel_is_error():
    out = fe._run_rf_tool(_rf_step({"mode": "rssi_only",
                                    "rssi_min": -70}), "wifi",
                          fe.FctContext())
    assert out.verdict == fe.VERDICT_ERROR
    assert "not bound" in out.reason


def test_lswifi_rssi_source_is_dbm_strict():
    """M66 root cause: dBm values are taken as-is; only percentage fields
    convert.  (Real 26-AP regression lives in test_m49b_host_rf.)"""
    import mtkgui.engine.host_rf as hr
    assert hr._rssi_value(-76) == -76
    assert hr._rssi_value(76) is None
    assert hr._rssi_value(76, percent=True) == -62
    assert "signal" not in hr._RSSI_KEYS
    assert "Signal" not in hr._RSSI_KEYS
