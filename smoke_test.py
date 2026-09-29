# -*- coding: utf-8 -*-
"""Headless smoke test for MTK GUI (no display, no real serial ports).

Run:  QT_QPA_PLATFORM=offscreen python smoke_test.py
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from mtkgui.main_window import MainWindow
from mtkgui.style import QSS
from mtkgui.theme import THEMES

app = QApplication(sys.argv)
app.setStyleSheet(QSS)
w = MainWindow()
w.show()

# 1. Multi-console: no YAML loaded -> 0 channels; 1-4 serial + 0-1 SSH.
from serial.tools import list_ports
list(list_ports.comports())  # enumeration must not crash

mc = w.workflow_page.multi_console
assert len(mc.channels) == 0  # no YAML loaded -> console starts empty
assert w.workflow_page.rail_samples is None  # waveform starts empty
mc.add_serial()
assert mc.current_key() == "ser1"
assert list(mc.channels)[0] == "ser1"
mc.add_serial()
mc.add_serial()
mc.add_serial()
keys = list(mc.channels)
assert keys == ["ser1", "ser2", "ser3", "ser4"], keys
assert mc.btn_add_serial.isEnabled() is False  # 4-serial cap
assert mc.add_serial() is None
ssh_key = mc.add_ssh()
assert ssh_key == "ssh1"
assert mc.btn_add_ssh.isEnabled() is False     # single SSH channel
assert mc.add_ssh() is None
# each channel keeps its own identifying accent color
accent_colors = {ch["accent"].lower() for ch in mc.channels.values()}
assert len(accent_colors) == 5
# remove SSH, then SER4; SER1..SER3 remain
mc.remove_channel("ssh1")
assert "ssh1" not in mc.channels and mc.btn_add_ssh.isEnabled()
mc.remove_channel("ser4")
assert list(mc.channels) == ["ser1", "ser2", "ser3"]
assert mc.btn_remove.isEnabled()  # can still remove
print("channel add/remove limits ok")

# 1b. Double-click the console opens the config dialog (auto-cancelled).
def close_modal_cfg():
    dlg = app.activeModalWidget()
    if dlg:
        dlg.done(0)
QTimer.singleShot(80, close_modal_cfg)
mc.channels["ser3"]["row"].btn_config.click()
# programmatic parameter set updates the row's endpoint display
mc.set_channel_params("ser1", {"port": "/dev/ttyFAKE99", "baudrate": 9600})
assert mc.channels["ser1"]["row"].combo_port.currentText() == "/dev/ttyFAKE99"
print("channel configuration ok")

# 2. Simulate incoming data on two channels; per-channel RX counters.
rx1 = b"\r\nboot complete\r\n"
rx2 = b"companion ready\r\n"
mc.on_data("ser1", rx1)
mc.on_data("ser2", rx2)
assert "boot complete" in mc.console("ser1").view.toPlainText()
assert "companion ready" in mc.console("ser2").view.toPlainText()
assert mc.channels["ser1"]["stats"][1] == len(rx1)
assert mc.channels["ser2"]["stats"][1] == len(rx2)
# read_buffer accumulates raw bytes
assert mc.get_read_buffer("ser1") == rx1
assert mc.get_read_buffer("ser2") == rx2
# row counts updated
assert "RX:" in mc.channels["ser1"]["row"].label_counts.text()
assert f"{len(rx1)}" in mc.channels["ser1"]["row"].label_counts.text()
print("text RX + per-channel counters ok")

# 3. HEX display on SER2.
mc.console("ser2").check_hex.setChecked(True)
mc.on_data("ser2", b"\x41\x54\x0d\x0a")
assert "41 54 0D 0A" in mc.console("ser2").view.toPlainText()
mc.console("ser2").check_hex.setChecked(False)
print("HEX display ok")

# 4. Sending while disconnected only adds a SYS message.
mc.handle_send("ser1", "AT", False, True)
assert "not connected" in mc.console("ser1").view.toPlainText()
print("send-while-disconnected ok")

# 5. Quick commands: picking an entry copies it to the Send line.
#    Quick commands live in ConsoleWindow (popup), not the compact row.
cw = mc.channels["ser1"]["console_window"]
entry = cw.combo_quick.itemData(1)
assert entry and entry["command"]
cw._on_quick_picked(1)
assert cw.send_panel.edit.text() == entry["command"]
assert cw.combo_quick.currentIndex() == 0  # combo resets for re-pick
assert cw.send_panel.check_crlf.isChecked() == bool(entry.get("crlf", True))
# saving the current line adds a persisted snippet (cap = 15)
from mtkgui.quick_commands import (
    MAX_QUICK_COMMANDS, load_commands, save_commands,
    user_commands_path)
cmd_file = user_commands_path()
cmd_existed = cmd_file.exists()
cw.send_panel.edit.setText("smoke_cmd_xyz")
cw.save_current_quick()
saved = load_commands()
assert any(c["command"] == "smoke_cmd_xyz" for c in saved)
assert any(cw.combo_quick.itemData(i)
           and cw.combo_quick.itemData(i)["command"] == "smoke_cmd_xyz"
           for i in range(cw.combo_quick.count()))
# cap: 15 entries disables Save Cmd
cw.quick_entries = [
    {"label": str(i), "command": str(i), "crlf": True}
    for i in range(MAX_QUICK_COMMANDS)]
cw._reload_quick_combo()
assert cw.btn_save_cmd.isEnabled() is False
# Clear Cmd empties all quick commands
assert cw.combo_quick.count() > 1  # has entries beyond the placeholder
cw.clear_all_quick()
assert cw.combo_quick.count() == 1  # only placeholder left
assert cw.quick_entries == []
assert load_commands() == []
if not cmd_existed and cmd_file.exists():
    cmd_file.unlink()
print("quick commands ok")

# 6. Payload encoding, including invalid HEX raising ValueError.
from mtkgui.widgets.multi_console import MultiConsoleWidget
assert MultiConsoleWidget.encode_payload("AT", False, True) == b"AT\r\n"
assert MultiConsoleWidget.encode_payload("41 54", True, False) == b"AT"
try:
    MultiConsoleWidget.encode_payload("ZZ", True, False)
    raise AssertionError("ValueError expected")
except ValueError:
    pass

def close_modal():
    dlg = app.activeModalWidget()
    if dlg:
        dlg.close()

QTimer.singleShot(100, close_modal)
mc.handle_send("ser1", "ZZ", True, False)  # invalid HEX -> warning box
print("invalid HEX handled ok")

# 7. Clear consoles.
for key in ("ser1", "ser2"):
    mc.console(key).clear_all()
    assert mc.console(key).view.toPlainText() == ""
print("clear ok")

# 8. ANSI SGR colors are rendered and stripped from plain text.
def has_colored_text(console, hex_color):
    doc = console.view.document()
    block = doc.firstBlock()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            color = fragment.charFormat().foreground().color()
            if (color.isValid()
                    and color.name().lower() == hex_color.lower()):
                return True
            it += 1
        block = block.next()
    return False

mc.on_data("ser1", b"\x1b[31mRED_TEXT\x1b[0m plain\r\n")
plain = mc.console("ser1").view.toPlainText()
assert "RED_TEXT" in plain and "plain" in plain
assert "\x1b" not in plain
assert has_colored_text(mc.console("ser1"), "#cd0000")
print("ANSI color ok")

# 9. An escape sequence split across two reads is buffered & completed.
mc.on_data("ser2", b"\x1b[3")
mc.on_data("ser2", b"2mGREEN_TEXT\x1b[0m\r\n")
assert "GREEN_TEXT" in mc.console("ser2").view.toPlainText()
assert has_colored_text(mc.console("ser2"), "#00cd00")
print("split ANSI sequence ok")

# 10. Adjustable background: black (dark) -> white (light) -> reset.
w.apply_background(QColor("#000000"))
assert w.theme is THEMES["dark"]
assert "#000000" in mc.console("ser1").view.styleSheet()
w.apply_background(QColor("#ffffff"))
assert w.theme is THEMES["light"]
assert "#ffffff" in mc.console("ser1").view.styleSheet()
w.apply_background(QColor("#000000"))
assert w.theme is THEMES["dark"]
print("background color switch ok")

# 11. Up/Down command history on the Send line (in ConsoleWindow).
send = cw.send_panel
send.commit_sent("AT")
QTest.keyClick(send.edit, Qt.Key_Up)
assert send.edit.text() == "AT"
QTest.keyClick(send.edit, Qt.Key_Down)
assert send.edit.text() == ""
send.edit.setText("draft")
QTest.keyClick(send.edit, Qt.Key_Up)
QTest.keyClick(send.edit, Qt.Key_Down)
assert send.edit.text() == "draft"
print("command history ok")

# 12. Two tabs exist: Test Work Flow, Equipment (console is embedded).
assert w.tabs.count() == 2
assert w.tabs.tabText(0) == "Test Work Flow"
assert w.tabs.tabText(1) == "Equipment"
print("tabs ok")

# 12b. FCT keeps a 12-row viewport and shares its row 60/40 with console.
fct = w.workflow_page.fct
assert fct.minimumHeight() >= 300
fct_split = mc.parent()
from PySide6.QtWidgets import QSplitter as _QS
assert isinstance(fct_split, _QS)
assert fct_split.orientation() == Qt.Orientation.Horizontal
QApplication.processEvents()
sizes = fct_split.sizes()
assert sizes[0] > 0 and sizes[1] > 0
ratio = sizes[0] / sizes[1]
assert 0.8 < ratio < 1.25, (sizes, ratio)  # FCT 50% vs console 50%
print("fct/console 50:50 layout ok")

# 13. Equipment page: 26 blocks; a real mouse click on a block opens
# the configuration dialog (hit-testing through the view).
ep = w.equipment_page
expected_keys = {
    # layer 1
    "host", "probes", "peripherals",
    # layer 2 containers + children
    "daq973a", "u2355a", "psu",
    "m908a_1", "m908a_2", "m907a",
    "u_ai", "u_ctr", "psu_detail",
    # layer 3
    "fixture", "control_board",
    "cell_press", "cell_inpos", "cell_presence", "cell_estop",
    # layer 4
    "dut", "grp_power", "grp_clocks", "grp_adc",
    "grp_vin", "grp_gnd", "grp_gpio",
}
assert set(ep.blocks) == expected_keys
for key in expected_keys:
    assert ep.blocks[key].rect().width() > 0

clicked = {"dialog": False}

def close_modal_2():
    dlg = app.activeModalWidget()
    if dlg:
        clicked["dialog"] = True
        dlg.close()

block = ep.blocks["m907a"]
view_pos = ep.view.mapFromScene(block.sceneBoundingRect().center())
QTimer.singleShot(80, close_modal_2)
QTest.mouseClick(ep.view.viewport(), Qt.LeftButton, Qt.NoModifier, view_pos)
assert clicked["dialog"], "clicking a block must open its config dialog"
print("equipment block click ok")

# 14. Test Work Flow: tables and demo run.
wf = w.workflow_page
# tables are empty until a YAML is loaded
assert wf.ict.rowCount() == 1 and wf.fct.rowCount() == 1

# Run is blocked until a YAML project file is loaded: a warning popup
# appears, the run does not start and the buttons stay in idle state.
def close_no_yaml_dlg():
    dlg = QApplication.activeModalWidget()
    if dlg is not None:
        dlg.close()
    else:
        QTimer.singleShot(50, close_no_yaml_dlg)
QTimer.singleShot(120, close_no_yaml_dlg)
wf.start_run()
assert wf.run_state == "idle"          # run never started
assert wf.btn_run.isEnabled()          # Run stays available
assert wf.btn_stop.isEnabled() is False
print("run gate (no yaml) ok")

from mtkgui.project_config import load_config, apply_config
cfg = load_config(str(Path("config/FRDM-IMX93_12345_Dev_rev1.1.yaml")))
apply_config(cfg, wf, w.equipment_page)
assert wf.overall.rowCount() == 2
assert wf.ict.rowCount() == 172
assert wf.fct.rowCount() == 21
# FCT Test Method (kind) loaded from the YAML per case: message tests,
# console/CLI steps and the Power On/Off DUT + fixture teardown ops
assert wf.fct_kinds[0] == "MessageYesNo"
assert wf.fct_kinds[1] == "MessageGoStop"
assert wf.fct_kinds[2] == "op"
assert wf.fct_kinds[3] == "MessageOK"
assert wf.fct_kinds[5] == "CapturefromConsole"
assert wf.fct_kinds[7] == "SendtoCLI"
assert wf.fct_kinds[12] == "MessageGoStop"
assert wf.fct_kinds[16] == "WaitforConsole"
assert wf.fct_kinds[18] == "op"
assert wf.fct_kinds[20] == "op"
assert wf.fct_op_params[4] == {"type": "power", "voltage": 5.0,
                               "current": 1.0}
wf.run_demo()
assert wf.overall.item(0, 3).text() == "PASS"
assert wf.ict.item(0, 7).text() == "Done"
# Row 4 = first impedance test (per-net), Row 84 = Power On DUT
assert "Impedance Shorts" in wf.ict_steps[4][1]
assert wf.ict_steps[84][1] == "Power On DUT"
assert wf.ict.item(4, 7).text() == "PASS"
assert wf.ict.item(84, 7).text() == "Done"
# FCT row 0 = LED test -> PASS, row 1 = Flash FAT dialog -> PASS,
# row 2 = Power Off DUT standard step -> Done
assert wf.fct.item(0, 4).text() == "PASS"
assert wf.fct.item(1, 4).text() == "PASS"
assert wf.fct.item(2, 4).text() == "Done"
assert wf.rail_csv_path is not None and wf.rail_csv_path.exists()
with open(wf.rail_csv_path) as fh:
    header = fh.readline().strip()
assert header.startswith("time_ms") and "VDD_SNVS_3V3" in header
assert "VDD_PCIE_1V8" in header
# DAQ AI capture is ICT row 85 (right after Power On DUT, before the
# voltage tests): samples + CSV, but NO waveform drawn
daq = next(i for i, s in enumerate(wf.ict_steps) if s[0] == "DAQ AI")
assert daq == 85
assert "Power Rails Up Sequence" in wf.ict_steps[daq][1]
assert wf.ict.item(daq, 7).text() == "PASS"
assert wf.rail_samples is not None and len(wf.rail_samples) == 12
assert wf.rail_widget.data == []  # waveform display off
# disable the DAQ AI row -> skipped as Ignore, no capture
daq_wait, wf.ict_enables[daq] = wf.ict_enables[daq], False
wf.clear_results()
wf.run_demo()
assert wf.ict.item(daq, 7).text() == "Ignore"
wf.ict_enables[daq] = daq_wait
wf.clear_results()
assert wf.overall.item(0, 3).text() == "Pending"
assert wf.overall.item(0, 4).text() == "--"
print("test workflow demo ok")

# 12b. Overall Flow EN: skip stages; refuse all-disabled runs.
wf.set_overall_en([False, True])
assert wf.overall.item(0, 2).checkState() == Qt.CheckState.Unchecked
steps = wf._steps_template(len(wf.ict_steps), wf.fct.rowCount())
assert not any(s[0] in ("ict", "rails") or s == ("stage", 0)
               for s in steps), steps[:3]
assert any(s[0] == "fct" for s in steps)
wf.set_overall_en([True, False])
steps = wf._steps_template(len(wf.ict_steps), wf.fct.rowCount())
assert not any(s[0] in ("fct", "fctconn") or s == ("stage", 1)
               for s in steps), steps[:3]
assert any(s[0] == "ict" for s in steps)
# both stages disabled -> Run blocked with a warning popup
wf.set_overall_en([False, False])
wf.project_path = "smoke-dummy.yaml"  # pass the no-yaml gate
QTimer.singleShot(150, close_modal)
wf.start_run()
QTest.qWait(400)
assert wf.run_state == "idle"
wf.set_overall_en([True, True])
steps = wf._steps_template(len(wf.ict_steps), wf.fct.rowCount())
assert steps[0] == ("ict", 0) and ("stage", 0) in steps
print("overall flow EN ok")

# 15. Overall Flow stop policies: defaults + abort decisions.
assert wf.stop_if_fail_cb.isChecked() is False
assert wf.stop_if_short_cb.isChecked() is True
# row 4 = impedance (Ω unit), row 85 = power voltage (V unit)
assert wf._is_impedance_short_row(4)
assert not wf._is_impedance_short_row(85)
# simulated short at the Impedance Shorts row
wf.ict_sim_fail.add(4)
wf._exec_ict_row(4)
assert wf.ict.item(4, 7).text() == "FAIL"
assert wf._policy_abort_reason("ict", (4,))  # stop-on-short default ON
wf.stop_if_short_cb.setChecked(False)
assert wf._policy_abort_reason("ict", (4,)) is None  # stop-on-fail OFF
wf.stop_if_fail_cb.setChecked(True)
assert wf._policy_abort_reason("ict", (4,))
# non-short ICT failure only reacts to stop-on-fail
wf.ict_sim_fail.discard(4)
wf.ict_sim_fail.add(86)  # Power Voltage
wf._exec_ict_row(86)
assert wf.ict.item(86, 7).text() == "FAIL"
assert wf._policy_abort_reason("ict", (86,))
wf.stop_if_fail_cb.setChecked(False)
assert wf._policy_abort_reason("ict", (86,)) is None
# FCT failure follows stop-on-fail only (rows 0/1 are message tests:
# LED test, then the Flash FAT dialog)
wf.fct_sim_fail.add(1)
wf._exec_fct_row(1)
assert wf.fct.item(1, 4).text() == "FAIL"
assert wf._policy_abort_reason("fct", (1,)) is None
wf.stop_if_fail_cb.setChecked(True)
assert wf._policy_abort_reason("fct", (1,))
# restore defaults
wf.stop_if_fail_cb.setChecked(False)
wf.stop_if_short_cb.setChecked(True)
wf.ict_sim_fail.clear()
wf.fct_sim_fail.clear()
wf.clear_results()
print("stop policies ok")

# 13b. FCT message tests (MessageOK / MessageYesNo / MessageGoStop) pop
# a modal operator dialog on a real run; the answer judges the row
# (OK / Yes / GO -> PASS, No / STOP -> FAIL). The run timer must not
# re-enter _run_step while the dialog is open.
answers = iter(["Yes", "GO", "OK"])
msg_timer = QTimer(w)
msg_timer.setInterval(120)


def answer_popup():
    dlg = app.activeModalWidget()
    if isinstance(dlg, QMessageBox):
        want = next(answers, "OK")
        for b in dlg.buttons():
            if b.text().replace("&", "") == want:
                b.click()
                break


msg_timer.timeout.connect(answer_popup)
msg_timer.start()
for r in (0, 1, 3):  # MessageYesNo, MessageGoStop, MessageOK rows
    wf._exec_fct_row(r)
msg_timer.stop()
assert wf.fct.item(0, 4).text() == "PASS"
assert wf.fct.item(1, 4).text() == "PASS"
assert wf.fct.item(3, 4).text() == "PASS"
# operator answers No / STOP -> the rows FAIL
answers = iter(["No", "STOP"])
msg_timer.start()
for r in (0, 1):
    wf._exec_fct_row(r)
msg_timer.stop()
assert wf.fct.item(0, 4).text() == "FAIL"
assert wf.fct.item(1, 4).text() == "FAIL"
wf.clear_results()
print("FCT message dialogs ok")

# 14. Operator account: default-deny permissions (supervisor keeps all).
from mtkgui.permissions import (
    DEFAULT_PERMISSIONS, ROLE_OPERATOR, ROLE_SUPERVISOR)
w2 = MainWindow(role=ROLE_OPERATOR)
w2.permissions = dict(DEFAULT_PERMISSIONS)  # deterministic defaults
w2.apply_permissions()
w2.show()
assert w2.role == ROLE_OPERATOR
# File menu: no save, supervisor-only settings hidden
assert w2.act_save_yaml.isEnabled() is False
assert w2.act_save_yaml_as.isEnabled() is False
assert w2.act_serial_check.isEnabled() is False
assert w2.act_permissions.isVisible() is False
# Product Information read-only; Run Control locked
wf2 = w2.workflow_page
assert wf2._can_edit_ict is False and wf2._can_edit_fct is False
assert wf2.part_edit.isReadOnly() and wf2.core_edit.isReadOnly()
assert wf2.batch_edit.isReadOnly() and wf2.serial_edit.isReadOnly()
assert wf2.auto_sn.isEnabled() is False
assert wf2.longrun_spin.isEnabled() is False
assert wf2.interval_spin.isEnabled() is False
# Overall Flow EN: grayed out for operator without the toggle right
assert not (wf2.overall.item(0, 2).flags() & Qt.ItemFlag.ItemIsEnabled)
assert (w.workflow_page.overall.item(0, 2).flags()
        & Qt.ItemFlag.ItemIsEnabled)
# Serial console: no channel add/remove, no parameter config dialogs
mc2 = wf2.multi_console
assert mc2.btn_add_serial.isEnabled() is False
assert mc2.btn_add_ssh.isEnabled() is False
# Equipment page: block-configuration windows are denied
assert w2.equipment_page._config_allowed is False
# the original supervisor window keeps everything enabled
assert w.act_save_yaml.isEnabled()
assert w.act_permissions.isVisible()
w2.close()
print("operator permission limits ok")

# 15. Virtual mode: supervisor-only, simulated HW + fault injection.
w3 = MainWindow(role=ROLE_SUPERVISOR, mode="Virtual")
w3.show()
assert w3.mode == "Virtual"
assert w3.act_fault_inject.isEnabled()
wf3 = w3.workflow_page
assert wf3.virtual_mode is True
assert wf3.multi_console.virtual_mode is True
# load YAML so tables are populated for the virtual demo run
cfg3 = load_config(str(Path("config/FRDM-IMX93_12345_Dev_rev1.1.yaml")))
apply_config(cfg3, wf3, w3.equipment_page)
# fault injection ratios support 0.01 % precision (dialog + roundtrip)
from mtkgui.virtual_mode import VirtualFaultDialog, load_fault_config, \
    save_fault_config
fd = VirtualFaultDialog({"test_fail_ratio": 12.34,
                         "equipment_error_ratio": 0.05})
assert abs(fd.get_config()["test_fail_ratio"] - 12.34) < 1e-9
assert abs(fd.get_config()["equipment_error_ratio"] - 0.05) < 1e-9
save_fault_config({"test_fail_ratio": 0.01, "equipment_error_ratio": 99.99})
cfg_rt = load_fault_config()
assert abs(cfg_rt["test_fail_ratio"] - 0.01) < 1e-9, cfg_rt
assert abs(cfg_rt["equipment_error_ratio"] - 99.99) < 1e-9, cfg_rt
save_fault_config({"test_fail_ratio": 0, "equipment_error_ratio": 0})
# 100% injected fail ratio -> every test row FAILs, "Virtual " prefix
wf3.set_virtual_fault({"test_fail_ratio": 100, "equipment_error_ratio": 0})
wf3.run_demo()
assert wf3.ict.item(4, 7).text() == "Virtual FAIL"
# 100 % injected fail ratio -> every test row FAILs (message tests
# included), "Virtual " prefix; the Power Off DUT op row reports Done
assert wf3.fct.item(0, 4).text() == "Virtual FAIL"
assert wf3.fct.item(1, 4).text() == "Virtual FAIL"
assert wf3.fct.item(2, 4).text() == "Virtual Done"
assert wf3.result_label.text() == "Virtual FAIL"
wf3.clear_results()
wf3.set_virtual_fault({"test_fail_ratio": 0, "equipment_error_ratio": 0})
wf3.run_demo()
assert wf3.ict.item(4, 7).text() == "Virtual PASS"
assert wf3.result_label.text() == "Virtual PASS"
# DAQ waveform: virtual badge, virtual CSV name, realistic overshoot
assert wf3.rail_widget.virtual is True
assert wf3.rail_csv_path.name.startswith("power_rails_virtual_")
assert max(max(s) for s in wf3.rail_samples) > 1.0  # post-ramp overshoot
assert w.workflow_page.rail_widget.virtual is False  # Real mode unchanged
# AI waveform review: written next to the CSV, every rail graded
rpath = wf3.rail_csv_path.with_name(
    wf3.rail_csv_path.stem + "_ai_review.txt")
assert rpath.exists(), rpath
rtext = rpath.read_text()
assert "AI Waveform Review" in rtext and "OVERALL:" in rtext, rtext[:200]
assert "VDD_SNVS_3V3" in rtext and "overshoot" in rtext, rtext[:300]
assert "12/12 rails pass" in rtext, rtext[-200:]
w3.close()
# operator account is always forced back to Real mode
w4 = MainWindow(role=ROLE_OPERATOR, mode="Virtual")
w4.show()
assert w4.mode == "Real"
assert w4.act_fault_inject.isEnabled() is False
assert w4.workflow_page.virtual_mode is False
w4.close()
print("virtual mode ok")

# 16. Virtual console connection works without real hardware.
mc3 = w3.workflow_page.multi_console
mc3.add_serial()  # no YAML loaded -> w3's console starts empty
mc3.open_channel("ser1")  # fake port: real mode would fail, virtual connects
for _ in range(20):  # queued thread signals may need a few loop passes
    QTest.qWait(100)
    if "Virtual DUT" in mc3.console("ser1").view.toPlainText():
        break
assert "Virtual DUT" in mc3.console("ser1").view.toPlainText()
assert mc3.channels["ser1"]["worker"].isRunning()
mc3.close_channel("ser1")
QTest.qWait(600)
assert not mc3.channels["ser1"]["worker"].isRunning()
print("virtual console connect ok")

# 17. every dialog window shows centered on the primary screen
from PySide6.QtWidgets import QDialog
probe = QDialog()
probe.resize(400, 200)
probe.show()
scr = probe.screen().availableGeometry()
c = probe.frameGeometry().center()
assert abs(c.x() - scr.center().x()) <= 1, (c, scr.center())
assert abs(c.y() - scr.center().y()) <= 1, (c, scr.center())
probe.close()
print("dialog centering ok")

# 18. Console channels live in the YAML and are auto-connected before FCT.
from mtkgui.project_config import build_config, save_config
wf.clear_results()
mcw = wf.multi_console
# the project YAML has console: [] -> the reset left one default serial
# channel; add the two more serials this round-trip test relies on
if "ser2" not in mcw.channels:
    mcw.add_serial()
if "ser3" not in mcw.channels:
    mcw.add_serial()
mcw.set_channel_params("ser1", {"port": "/dev/ttySMOKE1", "baudrate": 9600})
mcw.set_channel_params("ser2", {"port": "/dev/ttySMOKE2", "baudrate": 115200})
ssh18 = mcw.add_ssh()
mcw.set_channel_params(ssh18, {"host": "10.1.2.3", "port": 22,
                               "username": "root", "password": "pw"})
cfg18 = build_config(wf, w.equipment_page)
cons = cfg18["console"]
assert [c["kind"] for c in cons] == ["serial", "serial", "serial", "ssh"], cons
assert cons[0]["params"]["port"] == "/dev/ttySMOKE1"
assert cons[1]["params"]["baudrate"] == 115200
assert cons[3]["params"]["host"] == "10.1.2.3"
p18 = Path("/tmp/mtk_smoke_console.yaml")
save_config(cfg18, p18)
cfg18b = load_config(str(p18))
assert cfg18b["console"][3]["params"]["username"] == "root"
# round-trip into a fresh window (one serial tab by default): serial
# channels are reused in order, missing ones are created
w5 = MainWindow(role=ROLE_SUPERVISOR)
w5.show()
apply_config(cfg18, w5.workflow_page, w5.equipment_page)
mc5 = w5.workflow_page.multi_console
assert mc5.yaml_channel_keys() == ["ser1", "ser2", "ser3", "ssh1"]
assert mc5.channels["ser1"]["params"]["port"] == "/dev/ttySMOKE1"
assert mc5.channels["ser2"]["params"]["baudrate"] == 115200
assert mc5.channels["ssh1"]["params"]["host"] == "10.1.2.3"
cfg_rt = build_config(w5.workflow_page, w5.equipment_page)
assert cfg_rt["console"][1]["params"]["port"] == "/dev/ttySMOKE2"
w5.close()
print("console YAML round-trip ok")

# 18b. Pre-FCT auto connect, failure path (Real mode): the run stops,
# a popup reports the error, Overall Result FAIL, first FCT row Error.
mcw.apply_yaml_channels(
    [{"kind": "serial", "params": {"port": "/dev/ttySMOKE_MISSING"}}])
assert mcw.yaml_channel_keys() == ["ser1"]

def close_modal_18():
    dlg = app.activeModalWidget()
    if dlg:
        dlg.done(0)
    else:
        QTimer.singleShot(50, close_modal_18)

wf.fct_connect_timeout = 0.5
wf.clear_results()
steps18 = wf._steps_template(len(wf.ict_steps), wf.fct.rowCount())
idx18 = [i for i, s in enumerate(steps18) if s[0] == "fctconn"][0]
wf._run_steps = steps18
wf._run_index = idx18
wf._run_start = time.monotonic()
wf._stage_start = wf._run_start
wf.run_state = "running"
wf.btn_run.setEnabled(False)
wf.btn_stop.setEnabled(True)
wf.product_group.setEnabled(False)
QTimer.singleShot(150, close_modal_18)
wf._run_step()  # enters the fctconn step -> background connect + polling
for _ in range(60):  # up to ~6 s for the abort to finish
    QTest.qWait(100)
    if wf.run_state == "idle":
        break
assert wf.run_state == "idle"
assert wf.fct.item(0, 4).text() == "Error"
assert wf.fct.item(1, 4).text() == ""  # remaining FCT rows stay blank
assert wf.result_label.text() == "FAIL"
assert wf._judge_verdict() == "FAIL"
wf.fct_connect_timeout = 10.0
mcw.set_channel_params("ser1", {"port": None})
mcw._yaml_channel_keys = None
mcw.close_channel(ssh18)
print("pre-FCT connect failure ok")

# 18c. Pre-FCT auto connect, success path (Virtual mode): the missing
# channel is opened automatically and the run continues to FCT.
mc3.apply_yaml_channels([{"kind": "serial", "params": {"port": "vport0"}}])
wf3.fct_connect_timeout = 2.0
wf3.clear_results()
steps3 = wf3._steps_template(len(wf3.ict_steps), wf3.fct.rowCount())
idx3 = [i for i, s in enumerate(steps3) if s[0] == "fctconn"][0]
wf3._run_steps = steps3
wf3._run_index = idx3
wf3._run_start = time.monotonic()
wf3._stage_start = wf3._run_start
wf3.run_state = "running"
wf3.btn_run.setEnabled(False)
wf3.btn_stop.setEnabled(True)
wf3.product_group.setEnabled(False)
# FCT message tests pop operator dialogs during the real run; an
# auto-clicker answers them (OK / Yes / GO -> PASS)
click_timer = QTimer(w3)
click_timer.setInterval(120)


def click_fct_popup():
    dlg = app.activeModalWidget()
    if isinstance(dlg, QMessageBox):
        for b in dlg.buttons():
            if b.text().replace("&", "") in ("OK", "Yes", "GO"):
                b.click()
                break


click_timer.timeout.connect(click_fct_popup)
click_timer.start()
wf3._run_step()  # opens the virtual channel, then the run continues
for _ in range(150):  # wait for the whole (virtual) run to finish
    QTest.qWait(100)
    if wf3.run_state == "idle":
        break
click_timer.stop()
assert wf3.run_state == "idle"
assert mc3.channel_connected("ser1")  # opened automatically
assert wf3.fct.item(0, 4).text() == "Virtual PASS"
assert wf3.fct.item(2, 4).text() == "Virtual Done"
assert wf3.fct.item(20, 4).text() == "Virtual Done"  # Reset Instruments
assert wf3.result_label.text() == "Virtual PASS"
mc3.close_channel("ser1")
wf3.fct_connect_timeout = 10.0
mc3._yaml_channel_keys = None
print("pre-FCT connect success (virtual) ok")

# 19. GUI Theme switching: View > GUI Theme applies a new stylesheet and
# persists the choice in QSettings.
from PySide6.QtCore import QSettings
from mtkgui.style import APP_NAME, APP_ORG

w.apply_gui_theme("Dark")
qss_dark = QApplication.instance().styleSheet()
assert "#1e242c" in qss_dark
assert QSettings(APP_ORG, APP_NAME).value("gui_theme") == "Dark"
w.apply_gui_theme("Ocean")
assert "#eaf1f7" in QApplication.instance().styleSheet()
w.apply_gui_theme("Light")  # restore default for the remainder of the run
qss_light = QApplication.instance().styleSheet()
assert "#f3f5f8" in qss_light
assert QSettings(APP_ORG, APP_NAME).value("gui_theme") == "Light"
print("gui theme switching ok")

QTimer.singleShot(300, app.quit)
app.exec()
print("ALL SMOKE TESTS PASSED")
