# -*- coding: utf-8 -*-
"""P3-B5: FCTTestConfigPanel headless tests (set_values / values)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QPushButton

import yaml

from mtkgui.engine.fct_test_config import ConsoleCommand, FctTestConfig
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


FRDM_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.usbmodem53930099631"
    baudrate: 115200
    login_sequence:
      - {wait_for: "login:", send: root}
      - {wait_for: "Password:", send: ""}
      - {wait_for: root@imx93frdm}
    test_commands:
      - {name: Kernel check, send: "uname -a",
         expect_pass: "Linux imx93frdm", timeout: 5}
  wifi:
    enabled: true
    interface: mlan0
    scan_enabled: true
    ap_ssid: FRDM-IMX93-DUT
    scan_via: dut_console
    rssi_min: -70
    ping_enabled: false
    iperf_enabled: false
  bluetooth:
    enabled: true
    rssi_enabled: true
    expected_name: FRDM-IMX93-DUT
    expected_addr: B8:F4:4F:59:51:A0
    scan_retries: 2
    rssi_min: -70
    pair_enabled: false
    tone_enabled: false
    audio_confirm: true
"""


def test_roundtrip_preserves_config(qapp):
    panel = FCTTestConfigPanel()
    params = {"legacy_key": "kept",
              "fct_test_config_yaml": FRDM_YAML}
    panel.set_values(params)
    out = panel.values()
    assert out["legacy_key"] == "kept"
    node = yaml.safe_load(out["fct_test_config_yaml"])
    cfg = FctTestConfig.from_dict(node["fct_test_config"])
    assert cfg.dut_type == "linux"
    assert cfg.console.enabled and cfg.console.baudrate == 115200
    # legacy expect_pass of a send command migrates to the Capture
    # positive keyword (WaitFor uses expect_pass; Capture uses expect_fail)
    kernel = next(c for c in cfg.console.test_commands
                  if c.name == "Kernel check")
    assert kernel.capture_enabled and kernel.capture_is_expected
    assert kernel.expect_fail == "Linux imx93frdm"
    assert cfg.wifi.scan_enabled and cfg.wifi.ap_ssid == "FRDM-IMX93-DUT"
    assert cfg.bluetooth.rssi_enabled
    assert cfg.bluetooth.expected_name == "FRDM-IMX93-DUT"
    assert cfg.bluetooth.expected_addr == "b8:f4:4f:59:51:a0"
    assert cfg.bluetooth.scan_retries == 2


def test_ui_edits_reach_values(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.console_enabled.setChecked(True)
    panel.console_port.setCurrentText("/dev/cu.test")
    panel.wifi_enabled.setChecked(True)
    panel.wifi_ap_ssid.setText("DUT-AP")
    panel.wifi_ping_box.setChecked(True)
    panel.bt_enabled.setChecked(True)
    panel.bt_name.setText("DUT-BT")
    panel.bt_expected_addr.setText("AA:BB:CC:DD:EE:FF")
    panel.bt_scan_retries.setValue(4)
    panel.bt_tone_box.setChecked(True)
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    cfg = FctTestConfig.from_dict(node["fct_test_config"])
    assert cfg.console.port == "/dev/cu.test"
    assert cfg.wifi.scan_enabled and cfg.wifi.ap_ssid == "DUT-AP"
    assert cfg.wifi.ping_enabled
    assert cfg.bluetooth.rssi_enabled and cfg.bluetooth.tone_enabled
    assert cfg.bluetooth.expected_addr == "aa:bb:cc:dd:ee:ff"
    assert cfg.bluetooth.scan_retries == 4


def test_invalid_config_logged_not_lost(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.bt_enabled.setChecked(True)
    panel.bt_name.setText("")                 # required -> invalid
    logs = []
    panel.task_log.connect(lambda lvl, msg: logs.append(msg))
    out = panel.values()
    assert out["fct_test_config_yaml"]        # text preserved
    node = yaml.safe_load(out["fct_test_config_yaml"])
    assert FctTestConfig.from_dict(
        node["fct_test_config"]).validate()   # and still invalid
    assert any("expected_name" in m for m in logs)


def test_dut_type_grey_out_and_hint(qapp):
    panel = FCTTestConfigPanel()
    # turn the master switches on so sub-test groups are live
    panel.wifi_enabled.setChecked(True)
    panel.bt_enabled.setChecked(True)
    panel.dut_type.setCurrentText("bare_metal")
    # no Linux shell: driver cmd, Connect&Ping, iPerf, Pair, Tone greyed;
    # the Scan/RSSI discovery tests (both DUT kinds) stay available
    assert not panel.wifi_driver_cmd.isEnabled()
    assert not panel.wifi_ping_box.isEnabled()
    assert not panel.wifi_iperf_box.isEnabled()
    assert not panel.bt_pair_box.isEnabled()
    assert not panel.bt_tone_box.isEnabled()
    assert panel.wifi_scan_box.isEnabled()
    assert panel.bt_rssi_box.isEnabled()
    assert "Bare Metal" in panel.dut_hint.text()
    # back to linux: Linux-only sub-tests re-enable
    panel.dut_type.setCurrentText("linux")
    assert panel.wifi_driver_cmd.isEnabled()
    assert panel.wifi_ping_box.isEnabled()
    assert panel.wifi_iperf_box.isEnabled()
    assert panel.bt_pair_box.isEnabled()
    assert panel.bt_tone_box.isEnabled()


def test_set_values_restores_dut_type_grey(qapp):
    panel = FCTTestConfigPanel()
    node = yaml.safe_load(FRDM_YAML)
    node["fct_test_config"]["dut_type"] = "bare_metal"
    panel.set_values({"fct_test_config_yaml": yaml.safe_dump(node)})
    assert panel.dut_type.currentText() == "bare_metal"
    assert "Bare Metal" in panel.dut_hint.text()


def test_bare_metal_console_transport_serial_only(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.dut_type.setCurrentText("linux")
    add_btn = next(b for b in panel.findChildren(QPushButton)
                   if b.text() == "Add row")
    add_btn.click()
    cb = panel.cmd_table.cellWidget(0, 1)
    assert cb.count() == 3  # linux: serial + ssh + "(message)"
    cb.setCurrentText("ssh")
    # switch to bare metal: ssh is removed and the row falls back
    panel.dut_type.setCurrentText("bare_metal")
    assert cb.count() == 2 and cb.itemText(0) == "serial"
    assert cb.currentText() == "serial"
    assert panel._get_row_cmd(0).transport == "serial"
    # a row added under bare metal is serial-only (+ "(message)") too
    add_btn.click()
    assert panel.cmd_table.cellWidget(1, 1).count() == 2
    # back to linux restores both transports
    panel.dut_type.setCurrentText("linux")
    assert cb.count() == 3


THREE_STAGE_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.test"
    baudrate: 115200
    test_commands:
      - name: "Boot capture"
        kind: capture
        wait_enabled: false
        send_enabled: false
        capture_enabled: true
        expect_fail: "FW ready"
        capture_is_expected: true
        timeout: 6
      - name: "Login"
        kind: send
        send: "root"
        wait_enabled: true
        send_enabled: true
        capture_enabled: true
        expect_pass: "login:"
        expect_fail: "Password:"
        capture_is_expected: true
        wait_timeout: 10
        send_timeout: 4
        timeout: 6
  wifi: {enabled: false, mode: rssi_only, interface: mlan0, ssid: x, rssi_min: -70}
  bluetooth: {enabled: false, mode: rssi_only, expected_name: x, rssi_min: -70}
"""


def test_three_stage_off_cells_rendered(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": THREE_STAGE_YAML})
    t = panel.cmd_table
    assert t.rowCount() == 2
    # row 0: capture-only -> WaitFor / SendTo show (off), Capture populated
    assert t.item(0, 2).text() == "(off)"
    assert t.item(0, 3).text() == "(off)"
    assert t.item(0, 4).text() == "FW ready"
    assert t.item(0, 5).text() == "C:6s"      # only capture timeout
    # row 1: full Wait -> Send -> Capture chain
    assert t.item(1, 2).text() == "login:"
    assert t.item(1, 3).text() == "root"
    assert t.item(1, 4).text() == "Password:"
    assert t.item(1, 5).text() == "W:10s S:4s C:6s"


def test_three_stage_off_roundtrip(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": THREE_STAGE_YAML})
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    cfg = FctTestConfig.from_dict(node["fct_test_config"])
    cap, login = cfg.console.test_commands
    # capture-only row keeps its stage flags through the table roundtrip
    assert cap.wait_enabled is False
    assert cap.send_enabled is False
    assert cap.capture_enabled is True
    assert cap.expect_fail == "FW ready"
    # full chain row keeps all three stages
    assert login.wait_enabled and login.send_enabled and login.capture_enabled
    assert login.expect_pass == "login:"
    assert login.expect_fail == "Password:"


def test_timeout_column_read_only(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": THREE_STAGE_YAML})
    from PySide6.QtCore import Qt
    item = panel.cmd_table.item(1, 5)
    assert not (item.flags() & Qt.ItemIsEditable)


def test_advanced_capture_attrs_survive_roundtrip(qapp):
    # expected=no + ignore-case + end line + custom timeout must not be
    # lost when the row goes table -> values() -> YAML -> model
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.console_enabled.setChecked(True)
    cmd = ConsoleCommand(
        name="No error window", kind="send", send="run",
        wait_enabled=False, send_enabled=True, capture_enabled=True,
        expect_fail="ERROR", expect_fail_is_regex=False,
        case_sensitive=False, capture_is_expected=False,
        capture_end_line="DONE", timeout=8.0)
    r = panel.cmd_table.rowCount()
    panel.cmd_table.insertRow(r)
    panel._save_row_cmd(r, cmd)
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    restored = FctTestConfig.from_dict(
        node["fct_test_config"]).console.test_commands[0]
    assert restored.capture_enabled and not restored.capture_is_expected
    assert restored.expect_fail == "ERROR"
    assert restored.case_sensitive is False
    assert restored.capture_end_line == "DONE"
    assert restored.timeout == 8.0


def test_sftp_row_clears_wait_and_capture(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.console_enabled.setChecked(True)
    cmd = ConsoleCommand(
        name="Deploy", kind="sftp_put", transport="ssh",
        wait_enabled=False, send_enabled=True, capture_enabled=False,
        local="load.sh", remote="/root/load.sh", send_timeout=30.0)
    r = panel.cmd_table.rowCount()
    panel.cmd_table.insertRow(r)
    panel._save_row_cmd(r, cmd)
    # unified model: an SSH transfer is an ACTION row - the action name
    # and its params replace the dead Wait/Send/Capture stage cells
    assert panel.cmd_table.item(r, 2).text() == "action: sftp_put"
    assert panel.cmd_table.item(r, 3).text() == "load.sh -> /root/load.sh"
    assert panel.cmd_table.item(r, 4).text() == "(n/a)"
    assert panel.cmd_table.item(r, 5).text() == "S:30s"
    assert panel.cmd_table.item(r, 7).text() == "action"
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    restored = FctTestConfig.from_dict(
        node["fct_test_config"]).console.test_commands[0]
    assert restored.kind == "sftp_put"
    assert restored.local == "load.sh" and restored.remote == "/root/load.sh"
    assert not restored.wait_enabled and not restored.capture_enabled




def test_setup_fields_round_trip_without_editor_tab(qapp):
    """M22g: the Setup tab is gone (4 tabs left). The `setup:` node is
    still parsed and re-emitted verbatim, so an old YAML keeps its
    power / fixture spine (MessageGoStop prompts, U2355A fixture ops)."""
    panel = FCTTestConfigPanel()
    labels = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert labels == ["Console", "Wi-Fi", "Bluetooth", "Sequence"]
    assert not hasattr(panel, "setup_power")
    text = yaml.safe_dump({"fct_test_config": {
        "dut_type": "linux",
        "setup": {"power_mode": "psu", "use_fixture": True,
                  "manual_on_message": "plug it",
                  "manual_off_message": "unplug it"}}}, sort_keys=False)
    panel.set_values({"fct_test_config_yaml": text})

    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    assert node["fct_test_config"]["setup"] == {
        "power_mode": "psu", "use_fixture": True,
        "manual_on_message": "plug it",
        "manual_off_message": "unplug it"}


def test_setup_defaults_when_yaml_has_no_setup_node(qapp):
    """A YAML without a `setup:` node still gets the engine defaults
    (manual power + default prompts), so nothing goes silently missing."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml":
                      "fct_test_config:\n  dut_type: linux\n"})
    out = panel.values()
    setup = yaml.safe_load(out["fct_test_config_yaml"])["fct_test_config"][
        "setup"]
    assert setup["power_mode"] == "manual"
    assert setup["use_fixture"] is False
    assert setup["manual_on_message"]


# --------------------------------------------------- message rows (P3-B7)
MESSAGE_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.test"
    baudrate: 115200
    test_commands:
      - {name: Kernel check, kind: send, send: "uname -a", timeout: 5}
      - {name: Swap DUT fixture, kind: message, dialog_style: yesno,
         timeout: 30}
      - {name: Ready check, kind: message, dialog_style: ok, timeout: 10}
  wifi: {enabled: false}
  bluetooth: {enabled: false}
"""


def test_message_rows_render_and_round_trip(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": MESSAGE_YAML})
    t = panel.cmd_table
    # message rows: combo "(message)", style in the Capture column,
    # answer stage timeout (legacy rows carry no wait stage)
    assert t.cellWidget(1, 1).currentText() == "(message)"
    assert t.item(1, 4).text() == "Yes-No dialog"
    assert t.item(1, 5).text() == "S:30s"
    assert t.item(2, 4).text() == "OK dialog"
    assert t.item(2, 5).text() == "T:10s"
    # the row model is explicit: a message row IS a dialog step
    assert t.item(1, 7).text() == "dialog"
    assert t.item(0, 7).text() == "interact"
    cmd = panel._row_cmd(1)
    assert cmd.kind == "message" and cmd.dialog_style == "yesno"
    # values() keeps the message rows (no data loss on OK)
    out = panel.values()
    cfg = FctTestConfig.from_dict(yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"])
    cmds = cfg.console.test_commands
    assert [c.kind for c in cmds] == ["send", "message", "message"]
    assert [c.dialog_style for c in cmds] == ["yesno", "yesno", "ok"]


def test_console_choice_switches_row_kind(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": MESSAGE_YAML})
    # switch the send row to a message row via the Console column
    combo0 = panel.cmd_table.cellWidget(0, 1)
    combo0.setCurrentText("(message)")
    cmd0 = panel._get_row_cmd(0)
    assert cmd0.kind == "message"
    assert not cmd0.send_enabled and not cmd0.wait_enabled
    assert panel.cmd_table.item(0, 4).text() == "Yes-No dialog"
    # ...and back to a transport: the row returns to a Send row
    combo0.setCurrentText("serial")
    cmd0 = panel._get_row_cmd(0)
    assert cmd0.kind == "send" and cmd0.send_enabled


def test_message_row_survives_bare_metal_switch(qapp):
    """"(message)" stays selectable on bare-metal DUTs and a restored
    message row is never reset by the transport refresh."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": MESSAGE_YAML})
    panel.dut_type.setCurrentText("bare_metal")
    combo = panel.cmd_table.cellWidget(1, 1)
    assert combo.currentText() == "(message)"
    cmd = panel._get_row_cmd(1)
    assert cmd.kind == "message" and cmd.transport == "serial"
    out = panel.values()
    cfg = FctTestConfig.from_dict(yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"])
    assert cfg.console.test_commands[1].kind == "message"
    assert cfg.validate() == []


# ----------------------------------------- Console/Sequence split (M22c)
def test_console_tab_is_connection_config_only(qapp):
    """The Console tab carries ONLY the Host PC Serial/SSH connection
    fields; the test-commands table + row buttons moved to Sequence."""
    from PySide6.QtWidgets import QLineEdit, QTableWidget

    panel = FCTTestConfigPanel()
    labels = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert labels == ["Console", "Wi-Fi", "Bluetooth", "Sequence"]
    console = panel.tabs.widget(labels.index("Console"))
    seq = panel.tabs.widget(labels.index("Sequence"))
    # no data table left on the Console page
    assert console.findChildren(QTableWidget) == []
    assert panel.cmd_table in seq.findChildren(QTableWidget)
    # connection config lives on the Console page (serial + ssh)
    console_edits = console.findChildren(QLineEdit)
    assert panel.console_ssh_host in console_edits
    assert panel.console_ssh_user in console_edits
    # the row buttons moved with the table
    seq_buttons = {b.text() for b in seq.findChildren(QPushButton)}
    assert {"Add row", "Remove selected", "Duplicate", "Edit",
            "Move Up", "Move Down"} <= seq_buttons


CONSOLE_EXTRAS_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.test"
    baudrate: 115200
    newline: crlf
    inter_cmd_delay_ms: 250
    ssh_host: 192.168.1.20
    ssh_username: root
    deploy_scripts: true
    scripts_local_dir: assets
    scripts_remote_dir: /root
    test_commands:
      - {name: Pull report, transport: ssh, kind: sftp_get,
         wait_enabled: false, send_enabled: true, capture_enabled: false,
         remote: "/root/fat_result.json",
         local: "{{dut_report}}/fat_result.json"}
    post_rf_commands:
      - {name: Stop iperf3, transport: serial, kind: host,
         wait_enabled: false, send_enabled: true, capture_enabled: false,
         host_cmd: "pkill -f iperf3"}
  wifi: {enabled: false}
  bluetooth: {enabled: false}
"""


def test_ssh_endpoint_and_console_extras_round_trip(qapp):
    """Console connection fields are editable; every other console key
    (newline / delay / deploy / post_rf teardown rows) round-trips
    untouched - the page split must not lose data."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": CONSOLE_EXTRAS_YAML})
    assert panel.console_ssh_host.text() == "192.168.1.20"
    assert panel.console_ssh_user.text() == "root"
    panel.console_ssh_host.setText("192.168.1.21")
    out = panel.values()
    console = yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"]["console"]
    assert console["ssh_host"] == "192.168.1.21"
    assert console["ssh_username"] == "root"
    assert console["newline"] == "crlf"
    assert console["inter_cmd_delay_ms"] == 250
    assert console["deploy_scripts"] is True
    assert console["scripts_local_dir"] == "assets"
    assert console["scripts_remote_dir"] == "/root"
    assert console["test_commands"][0]["kind"] == "sftp_get"
    assert console["test_commands"][0]["remote"] == "/root/fat_result.json"
    assert console["post_rf_commands"][0]["host_cmd"] == "pkill -f iperf3"


# ------------------------------------------- unified row types (M26)
HOST_ROW_YAML = """
fct_test_config:
  dut_type: linux
  console:
    enabled: true
    port: "/dev/cu.test"
    baudrate: 115200
    test_commands:
      - {name: Start iperf3, transport: serial, kind: host,
         wait_enabled: false, send_enabled: true, capture_enabled: false,
         timeout: 20, host_cmd: "iperf3 -s -1"}
  wifi: {enabled: false}
  bluetooth: {enabled: false}
"""


def test_sftp_row_is_an_action_with_editable_params(qapp):
    """ONE row = ONE step with an explicit type: an SSH transfer row is
    an ACTION showing its action name + params (not dead stage cells)."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": CONSOLE_EXTRAS_YAML})
    t = panel.cmd_table
    assert t.item(0, 7).text() == "action"
    assert t.item(0, 2).text() == "action: sftp_get"
    assert t.item(0, 3).text() == ("/root/fat_result.json -> "
                                   "{{dut_report}}/fat_result.json")
    assert t.item(0, 4).text() == "remove_after=yes"
    out = panel.values()
    cmd = FctTestConfig.from_dict(yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"]
    ).console.test_commands[0]
    assert cmd.kind == "sftp_get"
    assert cmd.local == "{{dut_report}}/fat_result.json"
    assert cmd.remote == "/root/fat_result.json"


def test_host_cli_row_is_an_action_and_round_trips(qapp):
    """A 'host' row is an ACTION with its command visible/editable and
    kept as a host row on save (never converted to a console send)."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": HOST_ROW_YAML})
    t = panel.cmd_table
    assert t.item(0, 7).text() == "action"
    assert t.item(0, 2).text() == "action: host_cli"
    assert t.item(0, 3).text() == "iperf3 -s -1"
    out = panel.values()
    cmd = FctTestConfig.from_dict(yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"]
    ).console.test_commands[0]
    assert cmd.kind == "host"
    assert cmd.host_cmd == "iperf3 -s -1"
    assert cmd.timeout == 20

