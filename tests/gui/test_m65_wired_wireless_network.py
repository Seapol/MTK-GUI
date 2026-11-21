# -*- coding: utf-8 -*-
"""M65 / M100: the Equipment page splits the legacy "Wired & Wireless
Network" peripheral into a Host PC group (serial / SSH / RJ45 / Wi-Fi /
Bluetooth) and a Router group (RJ45 Ethernet / Wi-Fi AP) with an Enable
toggle.  Legacy ``peripherals.*`` project YAML migrates to the new
``host_pc`` / ``router`` keys on load and the old keys are never written
back."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui import project_config  # noqa: E402
from mtkgui.engine import host_platform  # noqa: E402
from mtkgui.equipment_page import (  # noqa: E402
    GROUP_FIELDS,
    LEFT_ENTRIES,
    EquipmentPage,
    _HostBluetoothDialog,
    _SerialChannelsDialog,
    _SshChannelDialog,
    _default_group,
    _default_serial_channels,
    _default_ssh_channel,
    _migrate_peripherals,
    _mock_configs,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _entries():
    return {key: (label, kind, source)
            for _group, entries in LEFT_ENTRIES
            for key, label, kind, source in entries}


# ------------------------------------------------------ left-column structure
def test_host_pc_router_left_entries():
    entries = _entries()
    assert entries["host_pc"] == ("Host PC", "group", None)
    assert entries["serial_console"][1] == "sub"
    assert entries["serial_console"][2] == ("host_pc", "serial")
    assert entries["ssh_console"][2] == ("host_pc", "ssh")
    assert entries["rj45_wired"][2] == ("host_pc", "rj45")
    assert entries["wifi_wireless"][2] == ("host_pc", "wifi")
    assert entries["host_bt"][2] == ("host_pc", "bluetooth")
    assert entries["router"][1] == "group_toggle"
    assert entries["router_ethernet"][2] == ("router", "ethernet")
    assert entries["router_ap"][2] == ("router", "ap")
    # the combined network entry is gone from the left column
    labels = [label for _group, es in LEFT_ENTRIES
              for _key, label, _kind, _src in es]
    assert "Wired & Wireless Network" not in labels


def test_group_field_defaults_match_the_yaml_contract():
    assert _default_group("host_pc", "rj45") == {
        "host_ip": "", "lan_port": "", "gateway": ""}
    assert _default_group("host_pc", "wifi") == {
        "host_ip": "", "hotspot_ssid": "", "hotspot_password": ""}
    assert _default_group("host_pc", "bluetooth") == {
        "adapter": "", "scan_targets": ""}
    assert _default_group("router", "ethernet") == {
        "router_ip": "", "gateway": ""}
    assert _default_group("router", "ap") == {"ssid": "", "password": ""}
    assert _default_group("router", "enabled") == {"enabled": True}


def test_serial_and_ssh_channel_defaults():
    serial = _default_serial_channels()
    assert list(serial) == [f"ser{i}" for i in range(1, 5)]
    for channel in serial.values():
        assert channel == {"port": "", "baud": "115200", "data": "8",
                           "parity": None, "stop": "1", "flow": None}
    assert _default_ssh_channel() == {
        "ssh1": {"host": "", "port": "22", "user": "", "password": ""}}


def test_mock_configs_own_host_pc_and_router_groups():
    configs = _mock_configs()
    assert set(configs["host_pc"]["groups"]) == {
        "serial", "ssh", "rj45", "wifi", "bluetooth"}
    assert set(configs["router"]["groups"]) == {"enabled", "ethernet", "ap"}
    assert "groups" not in configs["peripherals"]


# ----------------------------------------------------- enable toggle gating
def test_router_enable_disables_children(qapp):
    page = EquipmentPage()
    try:
        toggle = page.group_toggles["router"]
        assert toggle.isChecked() is True
        for key in ("router_ethernet", "router_ap"):
            assert page.entry_buttons[key]["config"].isEnabled() is True
        toggle.setChecked(False)
        qapp.processEvents()
        assert page.configs["router"]["groups"]["enabled"]["enabled"] is False
        for key in ("router_ethernet", "router_ap"):
            assert page.entry_labels[key].isEnabled() is False
            assert page.entry_buttons[key]["config"].isEnabled() is False
        # Host PC subs are not gated by the Router toggle
        assert page.entry_buttons["rj45_wired"]["config"].isEnabled() is True
    finally:
        page.deleteLater()


# -------------------------------------------------------------- sub dialogs
def test_serial_dialog_round_trips_channels(qapp):
    dlg = _SerialChannelsDialog(None, _default_serial_channels())
    try:
        dlg._edits["ser1"]["port"].setText("/dev/ttyUSB0")
        dlg._edits["ser2"]["baud"].setText("9600")
        values = dlg.values()
        assert values["ser1"]["port"] == "/dev/ttyUSB0"
        assert values["ser2"]["baud"] == "9600"
        assert values["ser3"]["parity"] == ""
    finally:
        dlg.deleteLater()


def test_ssh_dialog_round_trips_single_channel(qapp):
    dlg = _SshChannelDialog(None, _default_ssh_channel())
    try:
        dlg._edits["host"].setText("192.168.1.60")
        dlg._edits["user"].setText("root")
        values = dlg.values()
        assert values["ssh1"]["host"] == "192.168.1.60"
        assert values["ssh1"]["user"] == "root"
    finally:
        dlg.deleteLater()


def test_bluetooth_dialog_read_only_adapter(qapp, monkeypatch):
    monkeypatch.setattr(host_platform, "host_bt_identity",
                        lambda: ("PC-BT", "AA:BB:CC:DD:EE:FF"))
    dlg = _HostBluetoothDialog(None, {"adapter": "", "scan_targets": ""})
    try:
        assert dlg.edit_adapter.isReadOnly() is True
        assert dlg.edit_adapter.text() == "PC-BT"
        dlg.edit_scan.setText("DUT-BT")
        values = dlg.values()
        assert values["adapter"] == "PC-BT"
        assert values["scan_targets"] == "DUT-BT"
    finally:
        dlg.deleteLater()


# ------------------------------------------------------------------ migration
def test_legacy_peripherals_yaml_migrates_to_host_pc_router():
    configs = {"peripherals": {"title": "Test Peripherals", "groups": {
        "wifi": {"ap_ssid": "AP", "ap_ip": "", "host_ip": "",
                 "ap_password": ""},
        "bluetooth": {"adapter": "PC-BT", "scan_targets": "DUT-BT"},
        "router": {
            "router_ip": "10.0.0.1", "gateway": "10.0.0.1",
            "router_ap_ssid": "Factory-AP", "router_ap_password": "pw",
            "wired_host_ip": "10.0.0.5", "wired_host_port": "en5",
            "wired_gateway": "10.0.0.1", "wifi_host_ip": "10.0.0.6",
            "hotspot_ssid": "AP", "hotspot_password": "pw",
            "wired_enabled": False,
        },
    }}}
    _migrate_peripherals(configs)
    host = configs["host_pc"]["groups"]
    assert host["rj45"]["host_ip"] == "10.0.0.5"
    assert host["rj45"]["lan_port"] == "en5"
    assert host["rj45"]["gateway"] == "10.0.0.1"
    assert host["wifi"]["host_ip"] == "10.0.0.6"
    assert host["wifi"]["hotspot_ssid"] == "AP"
    assert host["bluetooth"]["adapter"] == "PC-BT"
    assert host["bluetooth"]["scan_targets"] == "DUT-BT"
    router = configs["router"]["groups"]
    assert router["ethernet"]["router_ip"] == "10.0.0.1"
    assert router["ethernet"]["gateway"] == "10.0.0.1"
    assert router["ap"]["ssid"] == "Factory-AP"
    assert router["ap"]["password"] == "pw"
    assert router["enabled"]["enabled"] is False
    assert "groups" not in configs["peripherals"]


def test_legacy_keys_not_written_back():
    legacy_yaml = {"equipment": {"peripherals": {"router": {
        "router_ip": "10.0.0.1", "gateway": "10.0.0.1",
        "router_ap_ssid": "AP", "wired_host_ip": "10.0.0.5",
        "wired_enabled": True, "setup_mode": "via_ap",
    }}}}
    configs = project_config._equipment_from_yaml(legacy_yaml["equipment"])
    _migrate_peripherals(configs)
    out = project_config._equipment_to_yaml(configs)
    for legacy_key in ("router", "wifi", "bluetooth"):
        assert legacy_key not in out["peripherals"]
    assert out["host_pc"]["rj45"]["host_ip"] == "10.0.0.5"
    assert out["router"]["ethernet"]["router_ip"] == "10.0.0.1"
    assert out["router"]["ap"]["ssid"] == "AP"


def test_group_round_trips_through_yaml(qapp):
    cfg = {
        "host_pc": {"title": "Host PC", "groups": {
            "rj45": _default_group("host_pc", "rj45"),
            "wifi": _default_group("host_pc", "wifi")}},
        "router": {"title": "Router", "groups": {
            "enabled": _default_group("router", "enabled"),
            "ethernet": _default_group("router", "ethernet"),
            "ap": _default_group("router", "ap")}},
    }
    cfg["host_pc"]["groups"]["rj45"]["host_ip"] = "10.0.0.5"
    cfg["router"]["groups"]["ap"]["ssid"] = "MTK-AP"
    equipment = project_config._equipment_to_yaml(cfg)
    assert equipment["host_pc"]["rj45"]["host_ip"] == "10.0.0.5"
    assert equipment["router"]["ap"]["ssid"] == "MTK-AP"
    restored = project_config._equipment_from_yaml(equipment)
    assert restored["host_pc"]["groups"]["rj45"]["host_ip"] == "10.0.0.5"
    assert restored["router"]["groups"]["ap"]["ssid"] == "MTK-AP"


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
