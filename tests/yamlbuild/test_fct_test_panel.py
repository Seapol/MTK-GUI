# -*- coding: utf-8 -*-
"""P3-B5: FCTTestConfigPanel headless tests (set_values / values).

M50: the panel is ONE page (the FCT step sequence).  The former
Console / Wi-Fi / Bluetooth tabs are gone; shared values are runtime
references into the Equipment page, and an OLD ``fct_test_config_yaml``
project is imported best effort.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QPushButton

import yaml

from mtkgui.engine.fct_test_config import (
    ConsoleCommand,
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_BT_TONE,
    STEP_TYPE_CONSOLE_CLI,
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_CONSOLE_SSH,
    STEP_TYPE_DELAY,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_SFTP_PUT,
    STEP_TYPE_WIFI_SCAN,
    console_command_for_label,
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


def _steps(panel) -> list:
    """The rows as the saved ``fct.steps`` list."""
    node = yaml.safe_load(panel.values()["fct_steps_yaml"]) or {}
    return (node.get("fct") or {}).get("steps") or []


def _fct(panel) -> dict:
    return (yaml.safe_load(panel.values()["fct_steps_yaml"]) or {}).get("fct") \
        or {}


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


def test_legacy_config_imports_into_single_page_rows(qapp):
    """M50: the OLD config imports into rows (console body first, then
    the enabled Wi-Fi/Bluetooth sub-tests) and saves the new schema."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": FRDM_YAML,
                      "legacy_key": "kept"})
    assert hasattr(panel, "legacy_key") is False
    out = panel.values()
    assert out["legacy_key"] == "kept"
    steps = _steps(panel)
    assert [s["type"] for s in steps] == [STEP_TYPE_CONSOLE_SERIAL,
                                          STEP_TYPE_WIFI_SCAN,
                                          STEP_TYPE_BT_RSSI]
    kernel = steps[0]
    assert kernel["name"] == "Kernel check"
    # legacy expect_pass of a send command migrates to the Capture
    # positive keyword (WaitFor uses expect_pass; Capture uses expect_fail)
    assert kernel["capture_enabled"] is True
    assert kernel["capture_is_expected"] is True
    assert kernel["expect_fail"] == "Linux imx93frdm"
    # shared values now travel as Equipment references + step overrides
    assert steps[1]["ref"]["ap_ssid"] == \
        "equipment.peripherals.wifi.ap_ssid"
    assert steps[1]["override"]["ap_ssid"] == "FRDM-IMX93-DUT"
    assert steps[1]["rssi_min"] == -70
    assert steps[2]["ref"]["bt_name"] == "equipment.dut.bluetooth.name"
    assert steps[2]["override"]["addr"] == "b8:f4:4f:59:51:a0"


def test_ui_edits_reach_values(qapp):
    """Every Add entry lands as one step entry in the saved schema."""
    panel = FCTTestConfigPanel()
    panel.set_values({})
    labels = [STEP_TYPE_CONSOLE_SERIAL, STEP_TYPE_CONSOLE_SSH,
              STEP_TYPE_SFTP_PUT, STEP_TYPE_SFTP_GET,
              STEP_TYPE_CONSOLE_CLI, STEP_TYPE_BT_TONE, STEP_TYPE_DELAY]
    for label in labels:
        panel._add_row_for_label(label)
    assert [s["type"] for s in _steps(panel)] == labels


def test_unresolvable_reference_is_logged_with_the_step_name(qapp):
    """M50 §6: an unknown reference is reported (step name + path) at
    save time - the row itself is never rewritten."""
    panel = FCTTestConfigPanel(equipment_provider=lambda: {"equipment": {}})
    cmd = console_command_for_label(STEP_TYPE_CONSOLE_SERIAL)
    cmd.name = "bad row"
    cmd.refs = {"port": "equipment.not.a.real.path"}
    panel._insert_row(cmd)
    logs = []
    panel.task_log.connect(lambda _lvl, msg: logs.append(msg))
    panel.values()
    errors = [m for m in logs if "FCT step references" in m]
    assert errors, logs
    assert "bad row" in errors[0]
    assert "equipment.not.a.real.path" in errors[0]
    assert panel.cmd_table.item(0, _COL_STEP).text() == "bad row"


def test_dut_type_gates_the_add_menu_and_hint(qapp):
    """M36: no master switch - only the DUT kind gates the Linux-only
    sub-tests; discovery tests stay available on both kinds."""
    panel = FCTTestConfigPanel()
    panel.dut_type.setCurrentText("bare_metal")
    assert not panel._add_actions[STEP_TYPE_CONSOLE_SSH].isVisible()
    assert not panel._add_actions[STEP_TYPE_SFTP_PUT].isVisible()
    assert not panel._add_actions[STEP_TYPE_SFTP_GET].isVisible()
    assert panel._add_actions[STEP_TYPE_CONSOLE_SERIAL].isVisible()
    assert panel._add_actions[STEP_TYPE_BT_RSSI].isVisible()
    assert panel._add_actions[STEP_TYPE_WIFI_SCAN].isVisible()
    assert "Bare Metal" in panel.dut_hint.text()
    # back to linux: the SSH-only items re-enable
    panel.dut_type.setCurrentText("linux")
    assert panel._add_actions[STEP_TYPE_CONSOLE_SSH].isVisible()
    assert panel._add_actions[STEP_TYPE_SFTP_PUT].isVisible()
    assert panel._add_actions[STEP_TYPE_SFTP_GET].isVisible()


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
  wifi: {enabled: false, scan_enabled: false, ping_enabled: false,
         iperf_enabled: false}
  bluetooth: {enabled: false, rssi_enabled: false, pair_enabled: false,
              tone_enabled: false}
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
    cap, login = _steps(panel)
    # capture-only row keeps its stage flags through the table roundtrip
    assert cap["wait_enabled"] is False
    assert cap["send_enabled"] is False
    assert cap["capture_enabled"] is True
    assert cap["expect_fail"] == "FW ready"
    # full chain row keeps all three stages
    assert login["wait_enabled"] and login["send_enabled"] \
        and login["capture_enabled"]
    assert login["expect_pass"] == "login:"
    assert login["expect_fail"] == "Password:"


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
    restored = _steps(panel)[0]
    assert restored["capture_enabled"] and not restored["capture_is_expected"]
    assert restored["expect_fail"] == "ERROR"
    assert restored["case_sensitive"] is False
    assert restored["capture_end_line"] == "DONE"
    assert restored["timeout"] == 8.0


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
    # m30: an SSH transfer is an SSH SFTP Push row - the Type column
    # names it and the cmd/params column shows the transfer paths
    # (WaitFor / SendTo stage cells stay empty)
    assert panel.cmd_table.item(r, _COL_TYPE).text() == STEP_TYPE_SFTP_PUT
    assert panel.cmd_table.item(r, _COL_CMD).text() == \
        "load.sh -> /root/load.sh"
    assert panel.cmd_table.item(r, _COL_CAPTURE).text() == "(off)"
    assert panel.cmd_table.item(r, _COL_TIMEOUT).text() == "S:30s"
    assert panel.cmd_table.item(r, _COL_WAIT).text() == ""
    assert panel.cmd_table.item(r, _COL_SEND).text() == ""
    restored = _steps(panel)[0]
    assert restored["type"] == STEP_TYPE_SFTP_PUT
    assert restored["local"] == "load.sh"
    assert restored["remote"] == "/root/load.sh"
    assert not restored["wait_enabled"] and not restored["capture_enabled"]


def test_setup_fields_round_trip_without_editor_tab(qapp):
    """M50: only the Sequence page exists. The `setup:` node is still
    parsed and re-emitted in ``fct.runtime``, so an old YAML keeps its
    power / fixture spine (MessageGoStop prompts, U2355A fixture ops)."""
    panel = FCTTestConfigPanel()
    labels = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert labels == ["Sequence"]
    assert not hasattr(panel, "setup_power")
    assert not hasattr(panel, "wifi_tab") and not hasattr(panel, "bt_tab")
    text = yaml.safe_dump({"fct_test_config": {
        "dut_type": "linux",
        "setup": {"power_mode": "psu", "use_fixture": True,
                  "manual_on_message": "plug it",
                  "manual_off_message": "unplug it"}}}, sort_keys=False)
    panel.set_values({"fct_test_config_yaml": text})

    setup = ((_fct(panel).get("runtime") or {}).get("setup") or {})
    assert setup["power_mode"] == "psu"
    assert setup["use_fixture"] is True
    assert setup["manual_on_message"] == "plug it"
    assert setup["manual_off_message"] == "unplug it"


def test_setup_defaults_when_yaml_has_no_setup_node(qapp):
    """A YAML without a `setup:` node still gets the engine defaults
    (manual power + default prompts), so nothing goes silently missing."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml":
                      "fct_test_config:\n  dut_type: linux\n"})
    setup = ((_fct(panel).get("runtime") or {}).get("setup") or {})
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
  wifi: {enabled: false, scan_enabled: false, ping_enabled: false,
         iperf_enabled: false}
  bluetooth: {enabled: false, rssi_enabled: false, pair_enabled: false,
              tone_enabled: false}
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
    steps = _steps(panel)
    assert [s["type"] for s in steps] == ["Console_serial", "MessageYesNo",
                                          "MessageOK"]
    assert [s["dialog_style"] for s in steps] == ["yesno", "yesno", "ok"]


def test_add_menu_covers_all_twelve_types(qapp):
    """m30/M43/M45d: the Add dropdown offers every Type label (Operation
    is the M43 submenu, not a direct item; the M46 serial transfers are
    File Transfer submenu items) and each added row renders that label
    in its Type column."""
    from mtkgui.engine.fct_test_config import (
        STEP_TYPE_LABELS,
        STEP_TYPE_OPERATION,
        STEP_TYPE_SERIAL_PULL,
        STEP_TYPE_SERIAL_PUT,
        step_type_label,
    )
    panel = FCTTestConfigPanel()
    panel.set_values({})
    # M48: the menu entries are the standard ops + messages + delay
    # (Operation group) + the FCT-only step types
    from mtkgui.engine.steps import DIO_OPS, OP_STEPS
    standard = [n for n in OP_STEPS if n not in DIO_OPS]
    direct = ((set(STEP_TYPE_LABELS) - {STEP_TYPE_OPERATION})
              | {STEP_TYPE_SERIAL_PUT, STEP_TYPE_SERIAL_PULL,
                 "Delay — plain wait (ms)"}
              | {f"Operation: {n}" for n in standard})
    assert set(panel._add_actions) == direct
    for label in direct:
        if label.startswith("Operation: ") or label in (
                "Delay — plain wait (ms)"):
            continue        # added via _add_operation_row (tested above)
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
    steps = _steps(panel)
    assert steps[1]["type"] == "MessageYesNo"
    assert steps[1]["transport"] == "serial"


# ----------------------------------------- single-page contract (M50)
def test_single_sequence_page_has_no_console_wifi_bt_tabs(qapp):
    """M50 §1: the Console / Wi-Fi / Bluetooth tabs are gone - the panel
    keeps ONE page and nothing hidden remains."""
    from PySide6.QtWidgets import QTableWidget

    panel = FCTTestConfigPanel()
    labels = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
    assert labels == ["Sequence"]
    assert not hasattr(panel, "wifi_tab")
    assert not hasattr(panel, "bt_tab")
    assert not hasattr(panel, "console_ssh_host")
    seq = panel.tabs.widget(0)
    assert panel.cmd_table in seq.findChildren(QTableWidget)
    seq_buttons = {b.text() for b in seq.findChildren(QPushButton)}
    assert {"Add", "Load Template", "Clean up", "Remove", "Duplicate",
            "Edit", "Move Up", "Move Down"} <= seq_buttons


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
  wifi: {enabled: false, scan_enabled: false, ping_enabled: false,
         iperf_enabled: false}
  bluetooth: {enabled: false, rssi_enabled: false, pair_enabled: false,
              tone_enabled: false}
"""


def test_ssh_endpoint_and_console_extras_round_trip(qapp):
    """M50 §5: an SSH step references Equipment ``dut.ssh`` (IP/username/
    password) instead of a Console page; the remaining console keys
    (newline / delay / SFTP paths) ride in ``fct.runtime``; post-RF rows
    stay teardown rows."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": CONSOLE_EXTRAS_YAML})
    steps = _steps(panel)
    sftp = next(s for s in steps
                if s["type"] == STEP_TYPE_SFTP_GET)
    assert sftp["ref"]["host"] == "equipment.dut.ssh.ip"
    assert sftp["ref"]["username"] == "equipment.dut.ssh.username"
    assert sftp["ref"]["password"] == "equipment.dut.ssh.password"
    assert sftp["remote"] == "/root/fat_result.json"
    teardown = [s for s in steps if s.get("teardown")]
    assert [s["host_cmd"] for s in teardown] == ["pkill -f iperf3"]
    console = (_fct(panel).get("runtime") or {}).get("console") or {}
    assert console["newline"] == "crlf"
    assert console["inter_cmd_delay_ms"] == 250
    assert console["scripts_local_dir"] == "assets"
    assert console["scripts_remote_dir"] == "/root"
    # M42: the deploy_scripts switch is retired - never re-emitted
    assert "deploy_scripts" not in console


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
  wifi: {enabled: false, scan_enabled: false, ping_enabled: false,
         iperf_enabled: false}
  bluetooth: {enabled: false, rssi_enabled: false, pair_enabled: false,
              tone_enabled: false}
"""


def test_sftp_row_is_an_action_with_editable_params(qapp):
    """m30: an SSH transfer row is an SSH SFTP Pull Type with its
    transfer paths in the cmd/params column (not dead Wait/Send/Capture
    cells)."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": CONSOLE_EXTRAS_YAML})
    t = panel.cmd_table
    assert t.item(0, _COL_TYPE).text() == STEP_TYPE_SFTP_GET
    assert t.item(0, _COL_CMD).text() == ("/root/fat_result.json -> "
                                          "{{dut_report}}/fat_result.json")
    assert t.item(0, _COL_WAIT).text() == ""
    assert t.item(0, _COL_SEND).text() == ""
    sftp = _steps(panel)[0]
    assert sftp["type"] == STEP_TYPE_SFTP_GET
    assert sftp["local"] == "{{dut_report}}/fat_result.json"
    assert sftp["remote"] == "/root/fat_result.json"


def test_host_cli_row_is_an_action_and_round_trips(qapp):
    """m30: a 'host' row is a Console_cli Type (Windows command in the
    cmd/params cell) and stays a host row on save."""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": HOST_ROW_YAML})
    t = panel.cmd_table
    assert t.item(0, _COL_TYPE).text() == "Console_cli"
    assert t.item(0, _COL_CMD).text() == "iperf3 -s -1"
    step = _steps(panel)[0]
    assert step["type"] == "Console_cli"
    assert step["host_cmd"] == "iperf3 -s -1"
    assert step["timeout"] == 20


def test_fct_panel_minimum_height_is_bounded(qapp):
    """m28: the two-column reflow keeps the panel minimum height <= 700
    px so the block-07 dialog still fits an offscreen-height screen
    (single-column stacking measured ~891 px)."""
    panel = FCTTestConfigPanel()
    assert panel.minimumSizeHint().height() <= 700
