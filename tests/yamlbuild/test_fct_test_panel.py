# -*- coding: utf-8 -*-
"""P3-B5: FCTTestConfigPanel headless tests (set_values / values)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QPushButton

import yaml

from mtkgui.engine.fct_test_config import (
    ConsoleCommand,
    FctTestConfig,
    STEP_TYPE_BT_TONE,
    STEP_TYPE_CONSOLE_CLI,
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_CONSOLE_SSH,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_SFTP_PUT,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (
    FCTTestConfigPanel,
    _COL_CAPTURE,
    _COL_CMD,
    _COL_SEND,
    _COL_STEP,
    _COL_TIMEOUT,
    _COL_TYPE,
    _COL_WAIT,
)


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
    assert cfg.console.port and cfg.console.baudrate == 115200
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
    panel.console_port.setCurrentText("/dev/cu.test")
    panel.wifi_scan_box.setChecked(True)
    panel.wifi_ap_ssid.setText("DUT-AP")
    panel.wifi_ping_box.setChecked(True)
    panel.bt_rssi_box.setChecked(True)
    panel.bt_name.setText("DUT-BT")
    panel.bt_expected_addr.setText("AA:BB:CC:DD:EE:FF")
    panel.bt_scan_retries.setValue(4)
    panel.bt_tone_file.setText("resources/tones/tone_2khz_6s.wav")
    panel.bt_tone_duration.setValue(8)
    panel.bt_pair_script.setText("/root/bt_conn.sh")
    panel._add_row_for_label(STEP_TYPE_BT_TONE)
    out = panel.values()
    node = yaml.safe_load(out["fct_test_config_yaml"])
    cfg = FctTestConfig.from_dict(node["fct_test_config"])
    assert cfg.console.port == "/dev/cu.test"
    assert cfg.wifi.scan_enabled and cfg.wifi.ap_ssid == "DUT-AP"
    assert cfg.wifi.ping_enabled
    assert cfg.bluetooth.rssi_enabled and cfg.bluetooth.tone_enabled
    assert cfg.bluetooth.expected_addr == "aa:bb:cc:dd:ee:ff"
    assert cfg.bluetooth.scan_retries == 4
    assert cfg.bluetooth.test_tone == "resources/tones/tone_2khz_6s.wav"
    assert cfg.bluetooth.tone_duration_s == 8
    assert cfg.bluetooth.bt_pair_script == "/root/bt_conn.sh"


def test_invalid_config_logged_not_lost(qapp):
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.bt_rssi_box.setChecked(True)
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
    # M36: no master switch - only the DUT kind gates the Linux-only
    # sub-tests; the BT tab is always enabled (M32).
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


def test_bare_metal_add_menu_hides_ssh_and_sftp(qapp):
    """m30: bare-metal DUTs hide Console_ssh / SFTP_put / SFTP_get in the
    Add dropdown; Console_serial and Console_cli stay available."""
    panel = FCTTestConfigPanel()
    panel.set_values({})
    panel.dut_type.setCurrentText("linux")
    assert panel._add_actions[STEP_TYPE_CONSOLE_SSH].isVisible()
    assert panel._add_actions[STEP_TYPE_SFTP_PUT].isVisible()
    assert panel._add_actions[STEP_TYPE_SFTP_GET].isVisible()
    panel.dut_type.setCurrentText("bare_metal")
    assert not panel._add_actions[STEP_TYPE_CONSOLE_SSH].isVisible()
    assert not panel._add_actions[STEP_TYPE_SFTP_PUT].isVisible()
    assert not panel._add_actions[STEP_TYPE_SFTP_GET].isVisible()
    assert panel._add_actions[STEP_TYPE_CONSOLE_SERIAL].isVisible()
    assert panel._add_actions[STEP_TYPE_CONSOLE_CLI].isVisible()


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
    # row 0: capture-only -> WaitFor / SendTo show (off), Capture shows
    # the unified Expected; Timeout shows only the capture window
    assert t.item(0, _COL_TYPE).text() == "Console_serial"
    assert t.item(0, _COL_WAIT).text() == "(off)"
    assert t.item(0, _COL_SEND).text() == "(off)"
    assert t.item(0, _COL_CAPTURE).text() == '+ "FW ready"'
    assert t.item(0, _COL_TIMEOUT).text() == "C:6s"
    # row 1: full Wait -> Send -> Capture chain
    assert t.item(1, _COL_WAIT).text() == "login:"
    assert t.item(1, _COL_SEND).text() == "root"
    assert t.item(1, _COL_CAPTURE).text() == '+ "Password:"'
    assert t.item(1, _COL_TIMEOUT).text() == "W:10s S:4s C:6s"


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
    item = panel.cmd_table.item(1, _COL_TIMEOUT)
    assert not (item.flags() & Qt.ItemIsEditable)


def test_advanced_capture_attrs_survive_roundtrip(qapp):
    # expected=no + ignore-case + end line + custom timeout must not be
    # lost when the row goes table -> values() -> YAML -> model
    panel = FCTTestConfigPanel()
    panel.set_values({})
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
    cmd = ConsoleCommand(
        name="Deploy", kind="sftp_put", transport="ssh",
        wait_enabled=False, send_enabled=True, capture_enabled=False,
        local="load.sh", remote="/root/load.sh", send_timeout=30.0)
    r = panel.cmd_table.rowCount()
    panel.cmd_table.insertRow(r)
    panel._save_row_cmd(r, cmd)
    # m30: an SSH transfer is an SFTP_put row - the Type column names it
    # and the cmd/params column shows the transfer paths (WaitFor /
    # SendTo stage cells stay empty)
    assert panel.cmd_table.item(r, _COL_TYPE).text() == "SFTP_put"
    assert panel.cmd_table.item(r, _COL_CMD).text() == \
        "load.sh -> /root/load.sh"
    assert panel.cmd_table.item(r, _COL_CAPTURE).text() == "(off)"
    assert panel.cmd_table.item(r, _COL_TIMEOUT).text() == "S:30s"
    assert panel.cmd_table.item(r, _COL_WAIT).text() == ""
    assert panel.cmd_table.item(r, _COL_SEND).text() == ""
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
    # m30: a message row shows its Message* Type label; the Yes/No rows
    # render the answer payloads, the OK row shows (off) send
    assert t.item(1, _COL_TYPE).text() == "MessageYesNo"
    assert t.item(1, _COL_SEND).text() == "YES='y' / NO='n'"
    assert t.item(1, _COL_TIMEOUT).text() == "S:30s"
    assert t.item(2, _COL_TYPE).text() == "MessageOK"
    assert t.item(2, _COL_SEND).text() == "(off)"
    assert t.item(2, _COL_TIMEOUT).text() == "T:10s"
    assert t.item(0, _COL_TYPE).text() == "Console_serial"
    cmd = panel._row_cmd(1)
    assert cmd.kind == "message" and cmd.dialog_style == "yesno"
    # values() keeps the message rows (no data loss on OK)
    out = panel.values()
    cfg = FctTestConfig.from_dict(yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"])
    cmds = cfg.console.test_commands
    assert [c.kind for c in cmds] == ["send", "message", "message"]
    assert [c.dialog_style for c in cmds] == ["yesno", "yesno", "ok"]


def test_add_menu_covers_all_twelve_types(qapp):
    """m30: the Add dropdown offers exactly the 12 Type labels and each
    added row renders that label in its Type column."""
    from mtkgui.engine.fct_test_config import (
        STEP_TYPE_LABELS,
        step_type_label,
    )
    panel = FCTTestConfigPanel()
    panel.set_values({})
    assert set(panel._add_actions) == set(STEP_TYPE_LABELS)
    for label in STEP_TYPE_LABELS:
        panel._add_row_for_label(label)
        r = panel.cmd_table.rowCount() - 1
        cmd = panel._row_cmd(r)
        assert step_type_label(cmd) == label
        assert panel.cmd_table.item(r, _COL_TYPE).text() == label


def test_message_row_survives_bare_metal_switch(qapp):
    """A restored message row is untouched by the bare-metal switch and
    still round-trips as a message row (Console_ssh/SFTP are only hidden
    from the Add menu, not from already-loaded rows)."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": MESSAGE_YAML})
    panel.dut_type.setCurrentText("bare_metal")
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
    assert {"Add", "Remove selected", "Duplicate", "Edit",
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
    (newline / delay / SFTP paths / post_rf teardown rows) round-trips
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
    # M42: the deploy_scripts switch is retired - never re-emitted
    assert "deploy_scripts" not in console
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
    """m30: an SSH transfer row is an SFTP_get Type with its transfer
    paths in the cmd/params column (not dead Wait/Send/Capture cells)."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": CONSOLE_EXTRAS_YAML})
    t = panel.cmd_table
    assert t.item(0, _COL_TYPE).text() == "SFTP_get"
    assert t.item(0, _COL_CMD).text() == ("/root/fat_result.json -> "
                                          "{{dut_report}}/fat_result.json")
    assert t.item(0, _COL_WAIT).text() == ""
    assert t.item(0, _COL_SEND).text() == ""
    out = panel.values()
    cmd = FctTestConfig.from_dict(yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"]
    ).console.test_commands[0]
    assert cmd.kind == "sftp_get"
    assert cmd.local == "{{dut_report}}/fat_result.json"
    assert cmd.remote == "/root/fat_result.json"


def test_host_cli_row_is_an_action_and_round_trips(qapp):
    """m30: a 'host' row is a Console_cli Type (Windows command in the
    cmd/params cell) and stays a host row on save."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": HOST_ROW_YAML})
    t = panel.cmd_table
    assert t.item(0, _COL_TYPE).text() == "Console_cli"
    assert t.item(0, _COL_CMD).text() == "iperf3 -s -1"
    out = panel.values()
    cmd = FctTestConfig.from_dict(yaml.safe_load(
        out["fct_test_config_yaml"])["fct_test_config"]
    ).console.test_commands[0]
    assert cmd.kind == "host"
    assert cmd.host_cmd == "iperf3 -s -1"
    assert cmd.timeout == 20



def test_wifi_tab_three_column_rows(qapp):
    """m31: the Wi-Fi tab body is a scrollable three-column grid - the
    DUT / Hotspot AP / Host PC boxes sit in ONE row (columns 0/1/2) and
    the Scan / RSSI, Ping and iPerf boxes sit in ONE row (columns
    0/1/2)."""
    from PySide6.QtWidgets import QGridLayout, QScrollArea
    panel = FCTTestConfigPanel()
    assert isinstance(panel.wifi_tab, QScrollArea), \
        "Wi-Fi tab body must be wrapped in a QScrollArea"
    grid = panel.wifi_tab.widget().layout()
    assert isinstance(grid, QGridLayout), \
        "Wi-Fi tab body must be a QGridLayout"

    def pos(widget):
        return grid.getItemPosition(grid.indexOf(widget))[:2]

    cfg = [pos(w) for w in (panel.wifi_base, panel.wifi_ap_box,
                           panel.wifi_host_box)]
    assert {r for r, _c in cfg} == {1}, "DUT/AP/Host must share row 1"
    assert [c for _r, c in cfg] == [0, 1, 2], \
        "DUT/AP/Host must occupy columns 0/1/2"

    tests = [pos(w) for w in (panel.wifi_scan_box, panel.wifi_ping_box,
                              panel.wifi_iperf_box)]
    assert {r for r, _c in tests} == {2}, "Scan/Ping/iPerf must share row 2"
    assert [c for _r, c in tests] == [0, 1, 2], \
        "Scan/Ping/iPerf must occupy columns 0/1/2"


def test_bt_tab_one_row(qapp):
    """m32: the Bluetooth tab body is a scrollable ONE-row three-column
    grid - Host PC BT / Pair / Tone boxes sit side by side."""
    from PySide6.QtWidgets import QGridLayout, QScrollArea
    panel = FCTTestConfigPanel()
    assert isinstance(panel.bt_tab, QScrollArea), \
        "Bluetooth tab body must be wrapped in a QScrollArea"
    grid = panel.bt_tab.widget().layout()
    assert isinstance(grid, QGridLayout), \
        "Bluetooth tab body must be a QGridLayout"

    def pos(widget):
        return grid.getItemPosition(grid.indexOf(widget))[:2]

    boxes = [pos(w) for w in (panel.bt_rssi_box, panel.bt_pair_box,
                              panel.bt_tone_box)]
    assert {r for r, _c in boxes} == {0}, "the three modules must share row 0"
    assert [c for _r, c in boxes] == [0, 1, 2], \
        "Host/Pair/Tone must occupy columns 0/1/2"
    # M32: the enable checkbox is gone, tone is NOT checkable
    assert not hasattr(panel, "bt_enabled")
    assert not panel.bt_tone_box.isCheckable()


def test_fct_panel_minimum_height_is_bounded(qapp):
    """m28: the two-column reflow keeps the panel minimum height <= 700
    px so the block-07 dialog still fits an offscreen-height screen
    (single-column stacking measured ~891 px)."""
    panel = FCTTestConfigPanel()
    assert panel.minimumSizeHint().height() <= 700
