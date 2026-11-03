# -*- coding: utf-8 -*-
"""M65: "Ethernet Router" -> "Wired & Wireless Network" (RJ45 + AP
modules, per-mode topology cards, Auto Detect, Test Connection, netsh
Hosted Network)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from mtkgui import project_config  # noqa: E402
from mtkgui.engine import host_platform  # noqa: E402
from mtkgui.engine.ref_resolver import describe, resolve  # noqa: E402
from mtkgui.equipment_page import (  # noqa: E402
    LEFT_ENTRIES,
    NETWORK_FIELDS,
    NETWORK_MODES,
    NETWORK_TITLE,
    RouterNetworkDialog,
    _RouterModeDialog,
    _default_group,
    _mock_configs,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _entry(key):
    for _group, entries in LEFT_ENTRIES:
        for ekey, label, _kind, _source in entries:
            if ekey == key:
                return label
    return None


def _values(**kw):
    data = _default_group("peripherals", "router")
    data.update(kw)
    return data


def _pump(app, predicate, timeout_ms=3000):
    """Wait for an async dialog worker without blocking the UI thread."""
    deadline = 0
    while deadline < timeout_ms:
        app.processEvents()
        if predicate():
            return True
        QThread.msleep(10)
        deadline += 10
    app.processEvents()
    return predicate()


# ------------------------------------------------------------- naming
def test_peripheral_is_relabelled():
    assert _entry("router") == NETWORK_TITLE
    table = dict((row[0], row[1])
                 for row in _mock_configs()["peripherals"]["table"])
    assert "Wired & Wireless Network" in table
    assert table["Wired & Wireless Network"] == "Wired / Wi-Fi connectivity"


def test_ref_descriptions_use_the_new_name():
    assert describe("equipment.peripherals.router.dut_ip").startswith(
        NETWORK_TITLE)
    assert describe("equipment.peripherals.router.gateway").startswith(
        NETWORK_TITLE)


def test_legacy_router_refs_still_resolve():
    equipment = {"equipment": {"peripherals": {"router": {
        "setup_mode": "via_ap", "dut_ip": "10.0.0.2",
        "router_ip": "10.0.0.1", "netmask": "255.255.255.0",
        "gateway": "10.0.0.1"}}}}
    assert resolve("equipment.peripherals.router.setup_mode",
                   equipment) == "via_ap"
    assert resolve("equipment.peripherals.router.dut_ip",
                   equipment) == "10.0.0.2"


def test_new_fields_are_in_the_yaml_group():
    keys = [key for key, _label, _default in NETWORK_FIELDS]
    assert "wired_enabled" in keys and "wifi_enabled" in keys
    assert "wired_mode" in keys and "wifi_mode" in keys
    assert "hotspot_ssid" in keys and "router_ap_ssid" in keys
    defaults = _default_group("peripherals", "router")
    assert defaults["wired_enabled"] is True
    assert defaults["wifi_enabled"] is True
    assert defaults["wired_mode"] == "direct"
    assert defaults["wifi_mode"] == "hotspot"
    assert defaults["wifi_dut_iface"] == "wlan0"


# -------------------------------------------------- mode-selection page
def test_default_selection_and_hints(qapp):
    dlg = RouterNetworkDialog(None, _values())
    try:
        assert dlg._cards["wired"]["direct"]._selected
        assert not dlg._cards["wired"]["lan"]._selected
        assert dlg._cards["wifi"]["hotspot"]._selected
        assert not dlg._cards["wifi"]["router"]._selected
        assert dlg._hints["wired"].text() == \
            "Current selection: Direct (no router)"
        assert dlg._hints["wifi"].text() == \
            "Current selection: Host PC hotspot (no router)"
    finally:
        dlg.deleteLater()


def test_modes_are_mutually_exclusive(qapp, monkeypatch):
    monkeypatch.setattr(_RouterModeDialog, "exec", lambda self: 0)
    dlg = RouterNetworkDialog(None, _values())
    try:
        dlg._cards["wired"]["lan"].clicked.emit("lan")
        assert dlg.values()["wired_mode"] == "lan"
        assert dlg._cards["wired"]["lan"]._selected
        assert not dlg._cards["wired"]["direct"]._selected
        assert dlg._hints["wired"].text() == \
            "Current selection: LAN via router"
        # the wireless module keeps its own independent selection
        assert dlg.values()["wifi_mode"] == "hotspot"
        dlg._cards["wifi"]["router"].clicked.emit("router")
        assert dlg.values()["wifi_mode"] == "router"
        assert dlg._cards["wifi"]["hotspot"]._selected is False
    finally:
        dlg.deleteLater()


def test_yaml_values_prefill_the_page(qapp):
    values = _values(wired_mode="lan", wifi_mode="router",
                     wired_gateway="192.168.1.1")
    dlg = RouterNetworkDialog(None, values)
    try:
        assert dlg._cards["wired"]["lan"]._selected
        assert dlg._cards["wifi"]["router"]._selected
        assert dlg.values()["wired_gateway"] == "192.168.1.1"
    finally:
        dlg.deleteLater()


def test_old_project_values_get_the_new_defaults(qapp):
    """Only legacy fields saved: the new module fields default (saved
    values still win)."""
    legacy = {"setup_mode": "via_ap", "router_ip": "10.0.0.1",
              "dut_ip": "10.0.0.2", "netmask": "255.255.255.0",
              "gateway": "10.0.0.1"}
    values = dict(_default_group("peripherals", "router"))
    values.pop("wired_mode", None)
    values.update(legacy)
    dlg = RouterNetworkDialog(None, values)
    try:
        assert dlg.values()["wifi_dut_iface"] == "wlan0"
        # legacy via_ap maps onto the LAN mode (not silently "direct")
        assert dlg.values()["wired_mode"] == "lan"
        assert dlg._cards["wired"]["lan"]._selected
        assert dlg.values()["dut_ip"] == "10.0.0.2"
        assert dlg.values()["router_ip"] == "10.0.0.1"
        assert dlg.values()["setup_mode"] == "via_ap"
    finally:
        dlg.deleteLater()


def test_values_keep_the_legacy_fct_fields(qapp):
    dlg = RouterNetworkDialog(None, _values(
        wired_mode="lan", wired_gateway="10.0.0.1"))
    try:
        data = dlg.values()
        assert data["setup_mode"] == "via_ap"
        assert data["router_ip"] == "10.0.0.1"
        assert data["gateway"] == "10.0.0.1"
    finally:
        dlg.deleteLater()
    dlg = RouterNetworkDialog(None, _values(router_ip="10.9.9.9"))
    try:
        # direct mode: the legacy value is never clobbered
        assert dlg.values()["setup_mode"] == "direct"
        assert dlg.values()["router_ip"] == "10.9.9.9"
    finally:
        dlg.deleteLater()


def test_group_round_trips_through_yaml(qapp):
    values = _values(wired_mode="lan", wifi_mode="router",
                     wired_dut_ports="eth0, eth1",
                     hotspot_ssid="MTK-HOTSPOT", wifi_gateway="10.1.1.1")
    cfg = {"peripherals": {"title": "Test Peripherals",
                           "groups": {"router": values}}}
    equipment = project_config._equipment_to_yaml(cfg)
    assert equipment["peripherals"]["router"]["wired_mode"] == "lan"
    assert equipment["peripherals"]["router"]["wifi_mode"] == "router"
    assert equipment["peripherals"]["router"]["hotspot_ssid"] == \
        "MTK-HOTSPOT"
    restored = project_config._equipment_from_yaml(equipment)
    router = restored["peripherals"]["groups"]["router"]
    assert router["wired_dut_ports"] == "eth0, eth1"
    assert router["wifi_gateway"] == "10.1.1.1"


# ------------------------------------------------------ per-mode dialogs
def test_direct_mode_has_no_test_connection(qapp):
    dlg = _RouterModeDialog(None, "direct", _values(
        wired_dut_ports="eth0"))
    try:
        assert dlg.btn_test is None
        assert "wired_dut_ports" in dlg._edits
        assert dlg._edits["wired_dut_ports"].text() == "eth0"
        readonly = [e.text() for e in dlg.findChildren(QLineEdit)
                    if e.isReadOnly()]
        assert "— not applicable" in readonly
    finally:
        dlg.deleteLater()


def test_router_modes_expose_test_connection(qapp):
    for mode in ("lan", "router"):
        dlg = _RouterModeDialog(None, mode, _values())
        try:
            assert dlg.btn_test is not None
            assert dlg.btn_test.text() == "Test Connection"
        finally:
            dlg.deleteLater()


def test_hotspot_mode_has_start_stop_control(qapp):
    dlg = _RouterModeDialog(None, "hotspot", _values())
    try:
        assert dlg.btn_hotspot_start.text() == "Start Hotspot"
        assert dlg.btn_hotspot_stop.text() == "Stop Hotspot"
        assert dlg.btn_test is None
        assert "hotspot_ssid" in dlg._edits
        assert "hotspot_password" in dlg._edits
        assert dlg._edits["wifi_dut_iface"].text() == "wlan0"
    finally:
        dlg.deleteLater()


def test_apply_and_save_writes_the_mode_fields(qapp):
    seen = []
    dlg = _RouterModeDialog(None, "lan", _values(),
                            on_save=lambda data: seen.append(dict(data)))
    try:
        dlg._edits["wired_dut_ports"].setText("eth0, eth1")
        dlg._edits["wired_gateway"].setText("192.168.1.1")
        dlg.btn_apply.click()
        assert dlg.result() == dlg.DialogCode.Accepted
        assert seen and seen[0]["wired_dut_ports"] == "eth0, eth1"
        assert seen[0]["wired_gateway"] == "192.168.1.1"
    finally:
        dlg.deleteLater()


def test_auto_detect_fills_the_host_fields(qapp, monkeypatch):
    monkeypatch.setattr(host_platform, "detect_host_network", lambda: {
        "wired_ip": "192.168.1.10", "wifi_ip": "192.168.137.1",
        "wired_port": "Ethernet", "wifi_port": "Wi-Fi",
        "gateway": "192.168.1.1"})
    app = qapp
    dlg = _RouterModeDialog(None, "lan", _values())
    try:
        dlg._detect()
        assert _pump(app, lambda: "Auto Detect:" in dlg.result_label.text())
        assert dlg._edits["wired_host_port"].text() == "Ethernet"
        assert dlg._edits["wired_host_ip"].text() == "192.168.1.10"
        assert dlg._edits["wifi_host_ip"].text() == "192.168.137.1"
        assert dlg._edits["wired_gateway"].text() == "192.168.1.1"
    finally:
        dlg.deleteLater()


# ------------------------------------------------------- host detection
def test_parse_ipconfig_reads_both_adapters():
    text = """
Ethernet adapter Ethernet:

    IPv4 Address. . . . . . . . . . . : 192.168.1.10
    Default Gateway . . . . . . . . . : 192.168.1.1

Wireless LAN adapter Wi-Fi:

    IPv4 Address. . . . . . . . . . . : 192.168.137.1
    Default Gateway . . . . . . . . . :
"""
    info = host_platform.parse_ipconfig(text)
    assert info["wired_ip"] == "192.168.1.10"
    assert info["wifi_ip"] == "192.168.137.1"
    assert info["wired_port"] == "Ethernet"
    assert info["wifi_port"] == "Wi-Fi"
    assert info["gateway"] == "192.168.1.1"


def test_detect_host_network_on_mac(monkeypatch):
    outputs = {
        "networksetup -listallhardwareports": (
            "Hardware Port: Ethernet\nDevice: en0\n\n"
            "Hardware Port: Wi-Fi\nDevice: en1\n"),
        "ifconfig": "en0: flags=8863\n\tinet 10.0.0.5 netmask 0xffffff00\n"
                    "en1: flags=8863\n\tinet 10.0.0.6 netmask 0xffffff00\n",
        "route -n get default": "route to: default\ngateway: 10.0.0.1\n",
    }
    monkeypatch.setattr(host_platform, "platform_key", lambda: "mac")
    monkeypatch.setattr(host_platform, "run_link_cmd",
                        lambda cmd, timeout_s=15: outputs.get(cmd, ""))
    info = host_platform.detect_host_network()
    assert info["wired_port"] == "en0"
    assert info["wifi_port"] == "en1"
    assert info["wired_ip"] == "10.0.0.5"
    assert info["wifi_ip"] == "10.0.0.6"
    assert info["gateway"] == "10.0.0.1"


def test_detect_host_network_never_fabricates(monkeypatch):
    monkeypatch.setattr(host_platform, "platform_key", lambda: "linux")
    info = host_platform.detect_host_network()
    assert set(info.values()) == {""}


# ------------------------------------------------------ Test Connection
def test_test_connection_pass_and_fail(monkeypatch):
    monkeypatch.setattr(host_platform, "platform_key", lambda: "mac")
    calls = []

    def fake_run(cmd, timeout_s=15):
        calls.append(cmd)
        return ("2 packets transmitted, 2 packets received"
                if "10.0.0.1" in cmd else
                "2 packets transmitted, 0 packets received")

    monkeypatch.setattr(host_platform, "run_link_cmd", fake_run)
    ok, message = host_platform.test_router_gateway("10.0.0.1")
    assert ok and "PASSED" in message
    ok, message = host_platform.test_router_gateway("10.0.0.9")
    assert not ok and "FAILED" in message
    assert calls[0] == "ping -c 2 10.0.0.1"
    ok, message = host_platform.test_router_gateway("")
    assert not ok and "No router gateway" in message


# ----------------------------------------------------- netsh Hotspot
def test_netsh_command_construction():
    cmds = host_platform.hotspot_start_commands("MTK-HOTSPOT", "pass1234")
    assert cmds[0] == ('netsh wlan set hostednetwork mode=allow '
                       'ssid="MTK-HOTSPOT" key="pass1234"')
    assert cmds[1] == "netsh wlan start hostednetwork"
    assert host_platform.hotspot_stop_command() == \
        "netsh wlan stop hostednetwork"


def test_netsh_parsing():
    status = host_platform.parse_hostednetwork_status(
        "Hosted network settings\n\n    Status : Started")
    assert status == "Started"
    supported = host_platform.parse_hostednetwork_supported(
        "Hosted network supported : Yes")
    assert supported
    assert not host_platform.parse_hostednetwork_supported(
        "Hosted network supported : No")


def test_start_and_stop_hotspot(monkeypatch):
    monkeypatch.setattr(host_platform, "platform_key", lambda: "windows")
    calls = []

    def fake_run(cmd, timeout_s=15):
        calls.append(cmd)
        if cmd == "netsh wlan show drivers":
            return "Hosted network supported : Yes"
        return "The hosted network started."

    monkeypatch.setattr(host_platform, "run_link_cmd", fake_run)
    ok, message = host_platform.start_hotspot("MTK-HOTSPOT", "pass1234")
    assert ok and "PASSED" in message
    assert calls[1] == ('netsh wlan set hostednetwork mode=allow '
                        'ssid="MTK-HOTSPOT" key="pass1234"')
    assert calls[2] == "netsh wlan start hostednetwork"
    ok, message = host_platform.stop_hotspot()
    assert ok and "stopped" in message
    assert calls[-1] == "netsh wlan stop hostednetwork"


def test_start_hotspot_requires_a_key(monkeypatch):
    monkeypatch.setattr(host_platform, "platform_key", lambda: "windows")
    launched = []
    monkeypatch.setattr(host_platform, "run_link_cmd",
                        lambda cmd, timeout_s=15: launched.append(cmd) or "")
    ok, message = host_platform.start_hotspot("MTK-HOTSPOT", "")
    assert not ok and "password" in message
    assert launched == []           # no netsh command with an empty key


def test_hotspot_control_is_windows_only(monkeypatch):
    monkeypatch.setattr(host_platform, "platform_key", lambda: "mac")
    ok, message = host_platform.start_hotspot("MTK-HOTSPOT", "pass1234")
    assert not ok and "Windows" in message
    assert host_platform.hostednetwork_status() == ""
