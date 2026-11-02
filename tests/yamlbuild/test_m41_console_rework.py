# -*- coding: utf-8 -*-
"""M41: console / network setup / SFTP engine behaviour.

M50 removed the Console tab (its connection fields became Equipment
DUT group references); the engine-level behaviour below keeps its
coverage:
* serial port platform filter + baudrate validation;
* Test Connection diagnosis layers (ping -> TCP 22 -> auth);
* SFTP add / runtime fallback auto-fill (step value wins);
* Wi-Fi / LAN setup steps: command plans, SSID/password plug-in,
  driver-missing, emitted IP, bare-metal gating;
* DUT-IP mismatch warning is a warning, never a hard fail.

All Qt tests run offscreen; no real serial / network / SSH is touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

import yaml  # noqa: E402

from mtkgui.engine import host_platform  # noqa: E402
from mtkgui.engine.fct_test_config import (  # noqa: E402
    ConsoleCfg,
    ConsoleCommand,
    FctTestConfig,
    KIND_OP,
    KIND_SFTP_GET,
    KIND_SFTP_PUT,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_SFTP_PUT,
    _console_row_steps,
)
from mtkgui.engine.steps import (  # noqa: E402
    LAN_SETUP_OP,
    NETWORK_OPS,
    WIFI_CONNECT_OP,
    wpa_conf_text,
)
from mtkgui.engine.runner import TestRunner as OpTestRunner  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _SshProbeWorker,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    return FCTTestConfigPanel()


def _last_cmd(panel) -> ConsoleCommand:
    return panel._get_row_cmd(panel.cmd_table.rowCount() - 1)


# ---------------------------------------------------------------- serial
def test_serial_port_platform_filter():
    devices = ["/dev/cu.usbmodem1", "/dev/tty.usbmodem1", "COM3"]
    assert host_platform.serial_port_devices(devices, "mac") == \
        ["/dev/cu.usbmodem1"]
    assert host_platform.serial_port_devices(devices, "windows") == ["COM3"]
    assert host_platform.serial_port_devices(devices, "linux") == devices


def test_baudrate_validation_accepts_positive_integers():
    cfg = FctTestConfig(console=ConsoleCfg(port="/dev/cu.X",
                                           baudrate=460800))
    assert cfg.validate() == []
    cfg.console.baudrate = 500000            # arbitrary positive int OK
    assert cfg.validate() == []
    cfg.console.baudrate = 0
    assert any("baudrate" in e for e in cfg.validate())


# ------------------------------------------------------- test connection
def test_diagnosis_layer1_ping_failure(monkeypatch):
    monkeypatch.setattr(host_platform, "ping_host", lambda *a, **k: False)
    worker = _SshProbeWorker("192.168.1.20", "root", "")
    seen = {}
    worker.fail.connect(lambda msg: seen.setdefault("msg", msg))
    worker.run()
    msg = seen["msg"]
    assert "network unreachable" in msg
    assert "Wi-Fi/LAN network setup step first" in msg
    assert "LAN cable" in msg


def test_diagnosis_layer2_tcp22_failure(monkeypatch):
    monkeypatch.setattr(host_platform, "ping_host", lambda *a, **k: True)
    monkeypatch.setattr(host_platform, "tcp_port_open", lambda *a, **k: False)
    worker = _SshProbeWorker("192.168.1.20", "root", "")
    seen = {}
    worker.fail.connect(lambda msg: seen.setdefault("msg", msg))
    worker.run()
    assert "TCP port 22 closed" in seen["msg"]
    assert "check DUT sshd is running" in seen["msg"]


def test_diagnosis_layer3_auth_failure(monkeypatch):
    import types

    monkeypatch.setattr(host_platform, "ping_host", lambda *a, **k: True)
    monkeypatch.setattr(host_platform, "tcp_port_open", lambda *a, **k: True)

    class _Client:
        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, **kw):
            raise RuntimeError("Authentication failed.")

        def close(self):
            pass

    fake = types.ModuleType("paramiko")
    fake.AutoAddPolicy = object
    fake.SSHClient = _Client
    monkeypatch.setitem(sys.modules, "paramiko", fake)

    worker = _SshProbeWorker("192.168.1.20", "root", "")
    seen = {}
    worker.fail.connect(lambda msg: seen.setdefault("msg", msg))
    worker.run()
    assert "authentication failed" in seen["msg"].lower()
    assert "check username, password or key" in seen["msg"]


# ------------------------------------------------------------------ sftp
SFTP_DIRS_YAML = """
fct_test_config:
  dut_type: linux
  console:
    scripts_local_dir: assets/dut
    scripts_remote_dir: /root
    pull_remote_dir: /tmp/results
    pull_local_dir: logs/results
"""


def test_sftp_rows_autofill_from_the_loaded_console_config(qapp):
    """M50: a project loaded from the legacy schema keeps its console
    dirs; an ADDED SFTP row starts from them (never rewrites an
    already-added row)."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": SFTP_DIRS_YAML})
    put_row = panel.cmd_table.rowCount()
    panel._add_row_for_label(STEP_TYPE_SFTP_PUT)
    put = panel._get_row_cmd(put_row)
    assert put.kind == KIND_SFTP_PUT
    assert put.local == "assets/dut" and put.remote == "/root"

    get_row = panel.cmd_table.rowCount()
    panel._add_row_for_label(STEP_TYPE_SFTP_GET)
    get = panel._get_row_cmd(get_row)
    assert get.kind == KIND_SFTP_GET
    assert get.remote == "/tmp/results" and get.local == "logs/results"


def test_sftp_runtime_falls_back_to_console_dirs():
    put = ConsoleCommand(kind=KIND_SFTP_PUT, name="put",
                         local="", remote="", send_timeout=30.0)
    steps = _console_row_steps(put, "ser1", "1.2.3.4", "root",
                               "C:/assets", "/root", "/tmp/results",
                               "C:/logs")
    assert steps[0].params["local"] == "C:/assets"
    assert steps[0].params["remote"] == "/root"

    # a non-empty step value wins over the console fallback
    put.local = "D:/override"
    steps = _console_row_steps(put, "ser1", "1.2.3.4", "root",
                               "C:/assets", "/root", "/tmp/results",
                               "C:/logs")
    assert steps[0].params["local"] == "D:/override"
    assert steps[0].params["remote"] == "/root"


# ------------------------------------------------------------ wifi setup
def test_wpa_conf_template_uses_ssid_and_password():
    text = wpa_conf_text("MTK-AP", "s3cret")
    assert 'ssid="MTK-AP"' in text
    assert 'psk="s3cret"' in text


def test_wifi_connect_plan_builds_conf_and_commands():
    plan = host_platform.wifi_connect_plan(
        {"iface": "wlan0", "ssid": "MTK-AP", "password": "pw",
         "dhcp": True})
    assert plan["probe"] == "iw dev wlan0 info"
    assert plan["prepare"] == ["ip link set wlan0 up"]
    assert 'ssid="MTK-AP"' in plan["conf_write"]
    assert 'psk="pw"' in plan["conf_write"]
    assert plan["connect"] == ("wpa_supplicant -B -i wlan0 -c "
                              "/tmp/wpa_supplicant.conf")
    assert plan["net_commands"] == ["dhclient wlan0", "udhcpc -i wlan0"]
    assert plan["confirm"] == "ip -4 addr show wlan0"


def test_wifi_row_plugs_the_equipment_ap_values(qapp):
    """M50: the Wi-Fi connect row references the Equipment PC Wi-Fi
    config instead of a deleted Wi-Fi tab."""
    node = {"equipment": {"peripherals": {
        "wifi": {"ap_ssid": "MTK-AP", "ap_password": "ap-pw"}}}}
    panel = FCTTestConfigPanel(equipment_provider=lambda: node)
    panel._add_operation_row(WIFI_CONNECT_OP)
    cmd = _last_cmd(panel)
    assert cmd.kind == KIND_OP
    assert cmd.op_params["type"] == "wifi_connect"
    assert cmd.op_params["ssid"] == "MTK-AP"
    assert cmd.op_params["password"] == "ap-pw"
    assert cmd.refs["ssid"] == "equipment.peripherals.wifi.ap_ssid"


def test_wifi_driver_missing_is_detected():
    assert host_platform.wifi_driver_ready("No such device", "wlan0") is False
    assert host_platform.wifi_driver_ready("", "wlan0") is False
    assert host_platform.wifi_driver_ready(
        "Interface wlan0\n\ttype managed", "wlan0") is True


def test_parse_dut_ip_skips_loopback_and_link_local():
    text = ("3: wlan0: <BROADCAST,MULTICAST,UP> mtu 1500\n"
            "    inet 169.254.1.2/16 scope link\n"
            "    inet 192.168.1.55/24 brd 192.168.1.255 scope global")
    assert host_platform.parse_dut_ip(text, "wlan0") == "192.168.1.55"
    assert host_platform.parse_dut_ip("inet 127.0.0.1/8", "wlan0") == ""


def test_network_ops_bare_metal_gating(panel):
    """M48: the network-setup ops live in the FCT-only Network submenu
    (tracked in _network_add_actions)."""
    wifi_act = panel._network_add_actions[WIFI_CONNECT_OP]
    lan_act = panel._network_add_actions[LAN_SETUP_OP]
    assert wifi_act.isEnabled() and lan_act.isEnabled()

    panel.dut_type.setCurrentText("bare_metal")
    assert not wifi_act.isEnabled() and not lan_act.isEnabled()
    assert "Linux DUT" in wifi_act.toolTip()

    panel.dut_type.setCurrentText("linux")
    assert wifi_act.isEnabled() and lan_act.isEnabled()


def test_network_ops_always_usable_without_resources(panel):
    panel.set_available_ops(set())
    for name in NETWORK_OPS:
        assert panel._network_add_actions[name].isEnabled()
    assert not panel._op_add_actions["Operation: Power On DUT"] \
        .isEnabled()


# ------------------------------------------------------------- lan setup
def test_lan_setup_dhcp_and_static_commands():
    dhcp = host_platform.lan_setup_plan({"iface": "eth0", "mode": "dhcp"})
    assert dhcp["net_commands"] == ["dhclient eth0", "udhcpc -i eth0"]

    static = host_platform.lan_setup_plan(
        {"iface": "eth0", "mode": "static", "dut_ip": "192.168.1.100",
         "netmask": "255.255.255.0", "gateway": "192.168.1.1"})
    assert "ip addr add 192.168.1.100/24 dev eth0" in static["net_commands"]
    assert "ip link set eth0 up" in static["net_commands"]
    assert "ip route add default via 192.168.1.1" in static["net_commands"]


# ---------------------------------------------------- IP mismatch warning
class _Env:
    """Minimal run environment: the mismatch warning only needs _log."""

    def __init__(self):
        self.lines: list = []

    def _log(self, msg):
        self.lines.append(msg)


def test_dut_ip_mismatch_only_warns():
    env = _Env()
    runner = OpTestRunner(env)
    runner._warn_dut_ip_mismatch("SFTP upload", "192.168.1.99",
                                 "192.168.1.20", "Emitted DUT IP")
    assert len(env.lines) == 1 and env.lines[0].startswith("[WARN]")
    assert "differs from the configured console SSH DUT IP" in env.lines[0]

    env.lines.clear()
    runner._warn_dut_ip_mismatch("SFTP upload", "192.168.1.20",
                                 "192.168.1.20", "Emitted DUT IP")
    assert env.lines == []                # same IP -> silent
