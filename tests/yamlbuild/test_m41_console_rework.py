# -*- coding: utf-8 -*-
"""M41: Console 5-submodule rework, network setup steps, SFTP auto-fill.

Covers the TASK5 spec:
* Console tab = Serial | SSH | CLI | SFTP Put | SFTP Pull (QGroupBox);
* Port combo refresh drops disappeared devices; mac / Windows lists;
* editable Tera Term baudrate table (BAUDRATES validation);
* Host PC / DUT wording (no "SSH Host");
* Test Connection = ping -> TCP 22 -> auth, each layer with guidance;
* QSettings ``console/*`` round-trip (isolated settings.ini);
* SFTP add / edit / runtime fallback auto-fill (step value wins);
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

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QGroupBox, QLabel  # noqa: E402

import mtkgui.gui.yamlbuild.FCTTestConfigWidget as widget_mod  # noqa: E402
from mtkgui.engine import host_platform  # noqa: E402
from mtkgui.engine.fct_test_config import (  # noqa: E402
    BAUDRATES,
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


# ------------------------------------------------------------ submodules
def test_console_tab_has_five_named_submodules(panel):
    boxes = [panel.console_serial_box, panel.console_ssh_box,
             panel.console_cli_box, panel.sftp_put_box,
             panel.sftp_pull_box]
    assert all(isinstance(b, QGroupBox) for b in boxes)
    assert panel.console_serial_box.title().startswith("Console Serial")
    assert panel.console_ssh_box.title() == "Console SSH (Host PC <-> DUT)"
    assert panel.console_cli_box.title().startswith("Console CLI")
    assert panel.sftp_put_box.title().startswith("SFTP Put")
    assert panel.sftp_pull_box.title().startswith("SFTP Pull")


def test_ssh_blocks_say_host_pc_and_dut_never_ssh_host(panel):
    labels = [w.text() for w in panel.console_ssh_box.findChildren(QLabel)]
    labels += [w.title() for w in panel.console_ssh_box.findChildren(
        QGroupBox)]
    assert any("SSH client runs on this PC" in t for t in labels)
    assert any(t.startswith("DUT (remote)") for t in labels)
    assert not any("SSH Host" in t for t in labels)
    # the Host PC IPv4 line is read-only (auto-detected)
    assert panel.console_host_pc_ip.isReadOnly()


def test_host_pc_ip_line_mirrors_wifi_tab(panel):
    panel.wifi_host_ip.setText("192.168.1.10")
    assert panel.console_host_pc_ip.text() == "192.168.1.10"
    panel.wifi_host_ip.setText("")
    assert panel.console_host_pc_ip.text() == ""


# ---------------------------------------------------------------- serial
def test_port_combo_refresh_removes_stale_entries(panel, monkeypatch):
    monkeypatch.setattr(widget_mod, "_serial_ports",
                        lambda: ["/dev/cu.A", "/dev/cu.B"])
    panel._refresh_serial_ports()
    texts = [panel.console_port.itemText(i)
             for i in range(panel.console_port.count())]
    assert texts == ["/dev/cu.A", "/dev/cu.B"]

    panel.console_port.setCurrentText("/dev/cu.A")
    monkeypatch.setattr(widget_mod, "_serial_ports", lambda: ["/dev/cu.C"])
    panel._refresh_serial_ports()
    texts = [panel.console_port.itemText(i)
             for i in range(panel.console_port.count())]
    assert texts == ["/dev/cu.C"]
    # the edited text is preserved (it may still disappear later)
    assert panel.console_port.currentText() == "/dev/cu.A"


def test_serial_port_platform_filter():
    devices = ["/dev/cu.usbmodem1", "/dev/tty.usbmodem1", "COM3"]
    assert host_platform.serial_port_devices(devices, "mac") == \
        ["/dev/cu.usbmodem1"]
    assert host_platform.serial_port_devices(devices, "windows") == ["COM3"]
    assert host_platform.serial_port_devices(devices, "linux") == devices


def test_baudrate_combo_has_tera_term_table_and_is_editable(panel):
    items = [panel.console_baud.itemText(i)
             for i in range(panel.console_baud.count())]
    assert items == [str(b) for b in BAUDRATES]
    assert panel.console_baud.isEditable()
    assert "115200" in items and "460800" in items and "921600" in items


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


# -------------------------------------------------------------- settings
def test_console_qsettings_round_trip(qapp, monkeypatch, tmp_path):
    store = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    monkeypatch.setattr(widget_mod, "_console_settings", lambda: store)
    first = FCTTestConfigPanel()
    first.console_port.setCurrentText("/dev/cu.TEST")
    first.console_baud.setCurrentText("460800")
    first.console_ssh_host.setText("10.1.1.5")
    first.console_ssh_user.setText("root")
    first.console_ssh_password.setText("pw-123")
    first.console_scripts_local.setText("C:/assets")
    first.console_pull_local.setText("C:/logs")
    store.sync()

    second = FCTTestConfigPanel()
    assert second.console_port.currentText() == "/dev/cu.TEST"
    assert second.console_baud.currentText() == "460800"
    assert second.console_ssh_host.text() == "10.1.1.5"
    assert second.console_ssh_user.text() == "root"
    assert second.console_ssh_password.text() == "pw-123"
    assert second.console_scripts_local.text() == "C:/assets"
    assert second.console_pull_local.text() == "C:/logs"


# ------------------------------------------------------------------ sftp
def test_sftp_rows_autofill_from_console_config(panel):
    panel.console_scripts_local.setText("C:/assets")
    panel.console_scripts_remote.setText("/root")
    panel.console_pull_remote.setText("/tmp/results")
    panel.console_pull_local.setText("C:/logs")

    put_row = panel.cmd_table.rowCount()
    panel._add_row_for_label(STEP_TYPE_SFTP_PUT)
    put = panel._get_row_cmd(put_row)
    assert put.kind == KIND_SFTP_PUT
    assert put.local == "C:/assets" and put.remote == "/root"

    get_row = panel.cmd_table.rowCount()
    panel._add_row_for_label(STEP_TYPE_SFTP_GET)
    get = panel._get_row_cmd(get_row)
    assert get.kind == KIND_SFTP_GET
    assert get.remote == "/tmp/results" and get.local == "C:/logs"

    # a console change never rewrites an already-added row
    panel.console_scripts_local.setText("D:/other")
    assert panel._get_row_cmd(put_row).local == "C:/assets"


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


def test_wifi_row_plugs_wifi_tab_ssid_and_password(panel):
    panel.wifi_ap_ssid.setText("MTK-AP")
    panel.wifi_ap_password.setText("ap-pw")
    panel._add_operation_row(WIFI_CONNECT_OP)
    cmd = _last_cmd(panel)
    assert cmd.kind == KIND_OP
    assert cmd.op_params["type"] == "wifi_connect"
    assert cmd.op_params["ssid"] == "MTK-AP"
    assert cmd.op_params["password"] == "ap-pw"


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
    wifi_act = panel._op_add_actions[f"Operation: {WIFI_CONNECT_OP}"]
    lan_act = panel._op_add_actions[f"Operation: {LAN_SETUP_OP}"]
    assert wifi_act.isEnabled() and lan_act.isEnabled()

    panel.dut_type.setCurrentText("bare_metal")
    assert not wifi_act.isEnabled() and not lan_act.isEnabled()
    assert "Linux DUT" in wifi_act.toolTip()

    panel.dut_type.setCurrentText("linux")
    assert wifi_act.isEnabled() and lan_act.isEnabled()


def test_network_ops_always_usable_without_resources(panel):
    panel.set_available_ops(set())
    for name in NETWORK_OPS:
        assert panel._op_add_actions[f"Operation: {name}"].isEnabled()
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


def test_lan_editor_shows_host_pc_subnet_hint(panel, monkeypatch):
    panel.wifi_host_ip.setText("192.168.1.10")
    panel._add_operation_row(LAN_SETUP_OP)
    row = panel.cmd_table.rowCount() - 1
    seen = {}

    def fake_exec(dialog):
        seen["labels"] = [lbl.text() for lbl in dialog.findChildren(QLabel)]
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_network_op_row(row)
    assert any("same subnet as the Host PC" in t for t in seen["labels"])
    assert any("192.168.1.10" in t for t in seen["labels"])


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
