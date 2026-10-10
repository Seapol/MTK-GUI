# -*- coding: utf-8 -*-
"""FCTTestConfigWidget — P3-B5 block 07 panel (three tabs).

Edits the `fct_test_config` product-YAML node (Console / Wi-Fi /
Bluetooth) for the "Build FCT Test Work Flow Sequence" module:

* Console tab   — port (serial device dropdown) + baudrate and the
  test_commands table (one row = one test: Name / Console transport /
  WaitFor / SendTo / Capture / Retry, each with its own timeout); rows
  are add/remove/duplicate/reorder;
* Wi-Fi tab     — base parameters (interface / driver load command)
  plus three independently enabled sub-tests, each with its own
  timeout (default 15 s): 1. Scan/RSSI (both DUT kinds), 2. Connect &
  Ping (Linux only, PASS on >=1 reply), 3. iPerf throughput (Linux
  only, Host server -> DUT client, iperf2/iperf3);
* Bluetooth tab — three independently enabled sub-tests, each with
  its own timeout: 1. RSSI discovery (both DUT kinds), 2. Pair &
  connect with optional L2CAP ping (Linux only), 3. Tone/music over
  A2DP with GUI confirm (Linux only, Host source -> DUT sink);
* Setup tab     — FCT power source (manual prompts / PSU / none) and
  ATE fixture DIO usage.

`values()` returns the legacy module params preserved plus
``fct_test_config_yaml`` — the full node as YAML text — so the
Preview & Export shows the complete configuration (spec §3.4).
"""
from __future__ import annotations

import copy

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.engine.fct_test_config import (
    BAUDRATES,
    BT_MODES,
    BW_TOOLS,
    WIFI_MODES,
    WIFI_SCAN_VIA,
    ConsoleCommand,
    FctTestConfig,
)

# Each cmd_table row carries its full ConsoleCommand on the Name cell's
# UserRole so that advanced attributes (regex/case/expected/end line/
# per-stage timeouts) survive the table -> YAML round-trip; the visible
# cells are only a rendered summary.
_CMD_ROLE = Qt.UserRole + 1


def _serial_ports() -> list:
    """Available serial devices (pyserial list_ports; tolerant)."""
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:                        # noqa: BLE001 - optional
        return []


class FCTTestConfigPanel(QWidget):
    """Block 07 config panel: Console / Wi-Fi / Bluetooth tabs."""

    #: (level, message) Event-Log mirror (T6 panel convention)
    task_log = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(1100)
        self._legacy: dict = {}             # preserved module params
        self._guard = False
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)
        self.tabs.addTab(self._build_console_tab(), "Console")
        self.tabs.addTab(self._build_wifi_tab(), "Wi-Fi")
        self.tabs.addTab(self._build_bt_tab(), "Bluetooth")
        self.tabs.addTab(self._build_setup_tab(), "Setup")
        self.dut_type = QComboBox()
        self.dut_type.addItems(["linux", "bare_metal"])
        self.dut_type.currentTextChanged.connect(self._on_dut_type_changed)
        self.dut_hint = QLabel("")
        self.dut_hint.setWordWrap(True)
        self.dut_hint.setStyleSheet("color: #6b7280;")
        head = QHBoxLayout()
        head.addWidget(QLabel("DUT OS Firmware:"))
        head.addWidget(self.dut_type)
        head.addStretch(1)
        lay.insertLayout(0, head)
        lay.insertWidget(1, self.dut_hint)
        self._on_dut_type_changed(self.dut_type.currentText())

    # ---------------------------------------------------------- DUT type
    def _on_dut_type_changed(self, dut: str) -> None:
        """DUT OS/firmware gates the available FCT items.

        Linux BSP DUT - full console set (Serial/SSH Wait->Send->Capture;
        SSH sftp_put/sftp_get); Wi-Fi host server -> DUT client, full-stack
        RSSI->Ping->iPerf or RSSI only; Bluetooth host source -> DUT A2DP
        sink (RSSI->Pair/Connect->Tone over BT).

        Bare Metal/RTOS DUT - serial-only console but the SAME
        Wait->Send->Capture flow (firmware prompts can be answered, e.g.
        Button/LED yes/no), no SSH/SFTP; Wi-Fi and Bluetooth are host ->
        DUT RSSI-only discovery scans."""
        is_linux = dut == "linux"
        self._sync_wifi_groups()
        self._sync_bt_groups()
        self.dut_hint.setText(
            "Linux BSP DUT - Console: full set (Serial/SSH "
            "Wait->Send->Capture; SSH sftp_put/sftp_get). Wi-Fi: host "
            "server -> DUT client, full-stack RSSI->Ping->iPerf or RSSI "
            "only. Bluetooth: host source -> DUT A2DP sink, "
            "RSSI->Pair/Connect->Tone over BT."
            if is_linux else
            "Bare Metal/RTOS DUT - Console: serial only but the same "
            "Wait->Send->Capture flow (e.g. Button/LED: wait prompt -> "
            "send yes/no -> capture result); no SSH/SFTP. Wi-Fi: host -> "
            "DUT RSSI only. Bluetooth: host -> DUT RSSI only.")
        self._refresh_console_transport_options()

    def _refresh_console_transport_options(self) -> None:
        """Bare-metal rows may only use serial; Linux rows may choose
        serial or ssh. An existing ssh/sftp row falls back to serial when
        the selected DUT has no OS."""
        if not hasattr(self, "cmd_table"):
            return
        is_linux = self.dut_type.currentText() == "linux"
        options = ["serial", "ssh"] if is_linux else ["serial"]
        for r in range(self.cmd_table.rowCount()):
            cb = self.cmd_table.cellWidget(r, 1)
            if not isinstance(cb, QComboBox):
                continue
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(options)
            if cur in options:
                cb.setCurrentText(cur)
            else:
                cb.setCurrentText("serial")
                cmd = self._get_row_cmd(r)
                if cmd is not None and cmd.transport != "serial":
                    cmd.transport = "serial"
                    if cmd.kind in ("sftp_put", "sftp_get"):
                        cmd.kind = "send"
                        cmd.local = cmd.remote = ""
                    self._save_row_cmd(r, cmd)
            cb.blockSignals(False)

    # ------------------------------------------------------------ setup
    def _build_setup_tab(self) -> QWidget:
        """FCT fixture / power wrapper. FCT uses NO DAQ; the DUT is
        powered by the rack PSU (Power On/Off ops) or a wall adapter /
        USB cable the operator connects when prompted (MessageGoStop);
        the optional ATE fixture is driven through U2355A DIO."""
        from mtkgui.engine.fct_test_config import (
            DEFAULT_MANUAL_OFF_MSG,
            DEFAULT_MANUAL_ON_MSG,
            POWER_MANUAL,
            POWER_NONE,
            POWER_PSU,
        )
        w = QWidget()
        form = QFormLayout(w)
        self.setup_power = QComboBox()
        self._POWER_MANUAL = POWER_MANUAL
        self.setup_power.addItem(
            "Manual adapter/USB (operator prompt)", POWER_MANUAL)
        self.setup_power.addItem("Rack PSU (N5747A Power On/Off)", POWER_PSU)
        self.setup_power.addItem("Already powered (no power action)",
                                 POWER_NONE)
        self.setup_power.currentIndexChanged.connect(
            self._on_setup_power_changed)
        form.addRow("DUT power:", self.setup_power)

        self.setup_fixture = QCheckBox(
            "Use ATE fixture (clamp/lock, driven by U2355A DIO)")
        form.addRow("Fixture:", self.setup_fixture)

        self.setup_on_msg = QLineEdit(DEFAULT_MANUAL_ON_MSG)
        form.addRow("Power-on prompt:", self.setup_on_msg)
        self.setup_off_msg = QLineEdit(DEFAULT_MANUAL_OFF_MSG)
        form.addRow("Power-off prompt:", self.setup_off_msg)

        hint = QLabel(
            "FCT needs no DAQ. With manual power a MessageGoStop asks the "
            "operator to connect/remove the adapter or USB cable. The rack "
            "PSU choice adds the same Power On/Off operations as ICT.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6b7280;")
        form.addRow(hint)
        form.addRow(QLabel(""))
        return w

    def _on_setup_power_changed(self, _idx: int) -> None:
        """The manual prompt texts are editable only in manual mode."""
        manual = self.setup_power.currentData() == self._POWER_MANUAL
        self.setup_on_msg.setEnabled(manual)
        self.setup_off_msg.setEnabled(manual)

    # ------------------------------------------------------------ console
    def _build_console_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.console_enabled = QCheckBox("Enable Console FCT")
        lay.addWidget(self.console_enabled)
        form = QFormLayout()
        self.console_port = QComboBox()
        self.console_port.setEditable(True)
        ports = _serial_ports()
        if ports:
            self.console_port.addItems(ports)
        form.addRow("Port:", self.console_port)
        self.console_baud = QComboBox()
        self.console_baud.addItems([str(b) for b in BAUDRATES])
        form.addRow("Baudrate:", self.console_baud)
        lay.addLayout(form)

        lay.addWidget(QLabel("Test commands:"))
        self.cmd_table = QTableWidget(0, 7)
        self.cmd_table.setHorizontalHeaderLabels(
            ["Name", "Console", "WaitFor", "SendTo",
             "Capture", "Timeout(s)", "Retry"])
        self.cmd_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.cmd_table.setColumnWidth(0, 120)  # Name
        self.cmd_table.setColumnWidth(1, 80)   # Console
        self.cmd_table.setColumnWidth(5, 70)   # Timeout (capture)
        self.cmd_table.setColumnWidth(6, 60)   # Retry
        lay.addWidget(self.cmd_table)
        self.cmd_table.cellDoubleClicked.connect(self._on_cmd_double_click)
        lay.addLayout(self._cmd_row_buttons())
        return w

    def _cmd_row_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        add = QPushButton("Add row")

        def _add():
            r = self.cmd_table.rowCount()
            self.cmd_table.insertRow(r)
            # text columns: Name / WaitFor / SendTo / Capture
            for col in (0, 2, 3, 4):
                self.cmd_table.setItem(r, col, QTableWidgetItem(""))
            # Timeout column = read-only
            from PySide6.QtCore import Qt as _Qt
            timeout_item = QTableWidgetItem("W:10s S:4s C:6s")
            timeout_item.setFlags(timeout_item.flags() & ~_Qt.ItemIsEditable)
            self.cmd_table.setItem(r, 5, timeout_item)
            # Console column = dropdown
            cb = QComboBox()
            cb.addItems(["serial", "ssh"])
            self.cmd_table.setCellWidget(r, 1, cb)
            # Retry column = dropdown
            rb = QComboBox()
            rb.addItems(["no", "yes"])
            self.cmd_table.setCellWidget(r, 6, rb)
            # default command: Send enabled, Wait/Capture off
            self._save_row_cmd(r, ConsoleCommand(
                kind="send", wait_enabled=False, send_enabled=True,
                capture_enabled=False))
            # bare-metal DUT: the new row's Console combo is serial only
            self._refresh_console_transport_options()

        add.clicked.connect(_add)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(
            lambda: self.cmd_table.removeRow(self.cmd_table.currentRow()))
        duplicate = QPushButton("Duplicate")
        def _duplicate():
            r = self.cmd_table.currentRow()
            if r < 0:
                return
            self.cmd_table.insertRow(r + 1)
            # copy text cells (except Timeout which is read-only)
            for col in (0, 2, 3, 4):
                src = self.cmd_table.item(r, col)
                if src:
                    self.cmd_table.setItem(r + 1, col,
                                           QTableWidgetItem(src.text()))
            # copy Timeout as read-only
            from PySide6.QtCore import Qt as _Qt
            src_to = self.cmd_table.item(r, 5)
            new_to = QTableWidgetItem(src_to.text() if src_to else "W:10s S:4s C:6s")
            new_to.setFlags(new_to.flags() & ~_Qt.ItemIsEditable)
            self.cmd_table.setItem(r + 1, 5, new_to)
            # copy Console dropdown
            src_cb = self.cmd_table.cellWidget(r, 1)
            new_cb = QComboBox()
            new_cb.addItems(["serial", "ssh"])
            new_cb.setCurrentText(src_cb.currentText())
            self.cmd_table.setCellWidget(r + 1, 1, new_cb)
            # copy Retry dropdown
            src_rb = self.cmd_table.cellWidget(r, 6)
            new_rb = QComboBox()
            new_rb.addItems(["no", "yes"])
            new_rb.setCurrentText(src_rb.currentText())
            self.cmd_table.setCellWidget(r + 1, 6, new_rb)
            # deep-copy the full source command (advanced attrs included)
            src_cmd = self._row_cmd(r)
            if src_cmd is not None:
                self._save_row_cmd(r + 1, copy.deepcopy(src_cmd))
        duplicate.clicked.connect(_duplicate)
        edit = QPushButton("Edit")
        edit.clicked.connect(
            lambda: self._edit_sendto_cell(
                self.cmd_table.currentRow(), 3))
        move_up = QPushButton("Move Up")
        def _move_up():
            r = self.cmd_table.currentRow()
            if r <= 0:
                return
            self._swap_rows(r, r - 1)
            self.cmd_table.setCurrentCell(r - 1, 0)
        move_up.clicked.connect(_move_up)
        move_down = QPushButton("Move Down")
        def _move_down():
            r = self.cmd_table.currentRow()
            if r < 0 or r >= self.cmd_table.rowCount() - 1:
                return
            self._swap_rows(r, r + 1)
            self.cmd_table.setCurrentCell(r + 1, 0)
        move_down.clicked.connect(_move_down)
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(duplicate)
        row.addWidget(edit)
        row.addWidget(move_up)
        row.addWidget(move_down)
        row.addStretch(1)
        return row

    def _swap_rows(self, r1: int, r2: int) -> None:
        """Swap two rows in cmd_table (full command + rendered cells)."""
        c1, c2 = self._row_cmd(r1), self._row_cmd(r2)
        if c1 is not None and c2 is not None:
            self._save_row_cmd(r1, copy.deepcopy(c2))
            self._save_row_cmd(r2, copy.deepcopy(c1))
            return
        # fallback: swap text cells
        for col in (0, 2, 3, 4, 5):
            item1 = self.cmd_table.item(r1, col)
            item2 = self.cmd_table.item(r2, col)
            text1 = item1.text() if item1 else ""
            text2 = item2.text() if item2 else ""
            self.cmd_table.setItem(r1, col, QTableWidgetItem(text2))
            self.cmd_table.setItem(r2, col, QTableWidgetItem(text1))
        # swap Console dropdown
        cb1 = self.cmd_table.cellWidget(r1, 1)
        cb2 = self.cmd_table.cellWidget(r2, 1)
        text_cb1 = cb1.currentText()
        text_cb2 = cb2.currentText()
        cb1.setCurrentText(text_cb2)
        cb2.setCurrentText(text_cb1)
        # swap Retry dropdown
        rb1 = self.cmd_table.cellWidget(r1, 6)
        rb2 = self.cmd_table.cellWidget(r2, 6)
        text_rb1 = rb1.currentText()
        text_rb2 = rb2.currentText()
        rb1.setCurrentText(text_rb2)
        rb2.setCurrentText(text_rb1)

    def _on_cmd_double_click(self, row: int, col: int) -> None:
        """Double-click on WaitFor/SendTo/Capture opens an editor dialog."""
        if col == 2:    # WaitFor
            self._edit_regex_cell(row, col, "WaitFor")
        elif col == 3:  # SendTo
            self._edit_sendto_cell(row, col)
        elif col == 4:  # Capture
            self._edit_regex_cell(row, col, "Capture")

    def _edit_regex_cell(self, row: int, col: int, title: str) -> None:
        """Exact / Regex editor dialog with live match test."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                        QTextEdit, QPushButton, QLabel,
                                        QCheckBox)
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(750)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        lay = QVBoxLayout(dlg)
        # load current state from the row's full ConsoleCommand
        cmd = self._row_cmd(row)
        cell_text = self.cmd_table.item(row, col).text() if self.cmd_table.item(row, col) else ""
        if cmd is not None:
            if title == "WaitFor":
                cur_pattern = cmd.expect_pass
                cur_regex = cmd.expect_pass_is_regex
                cur_enabled = cmd.wait_enabled
                cur_timeout = int(cmd.wait_timeout)
            else:
                cur_pattern = cmd.expect_fail
                cur_regex = cmd.expect_fail_is_regex
                cur_enabled = cmd.capture_enabled
                cur_timeout = int(cmd.timeout)
            cur_case = cmd.case_sensitive
            cur_expected = cmd.capture_is_expected
            cur_endline = cmd.capture_end_line
        else:
            is_off0 = cell_text.strip() == "(off)"
            cur_pattern = "" if is_off0 else cell_text
            cur_regex = False
            cur_enabled = not is_off0
            cur_case = True
            cur_expected = False
            cur_endline = ""
            cur_timeout = 10 if title == "WaitFor" else 6
        # Enable this step checkbox
        enable_cb = QCheckBox(f"Enable {title} step")
        enable_cb.setChecked(cur_enabled)
        lay.addWidget(enable_cb)
        # Use Regex checkbox (default off = exact match)
        regex_cb = QCheckBox("Use Regex (default off = exact substring match)")
        regex_cb.setChecked(cur_regex)
        lay.addWidget(regex_cb)
        # Case sensitive checkbox (default on)
        case_cb = QCheckBox("Case Sensitive (uncheck = ignore case, e.g. PASS=pass)")
        case_cb.setChecked(cur_case)
        lay.addWidget(case_cb)
        # Capture expected checkbox (only for Capture column)
        expect_cb = QCheckBox(
            "Expect to capture this message (yes = found is PASS; "
            "no = found is FAIL, use End line to bound the clean window)")
        if title == "Capture":
            expect_cb.setChecked(cur_expected)
            lay.addWidget(expect_cb)
        # End line input (always visible for Capture column)
        # Regex / Case Sensitive reuse the same checkboxes above
        end_line_label = QLabel("End line (marks end of range, same Regex/Case settings):")
        end_line_edit = QLineEdit()
        end_line_edit.setPlaceholderText("e.g. # TEST COMPLETE")
        end_line_edit.setText(cur_endline)
        if title == "Capture":
            lay.addWidget(end_line_label)
            lay.addWidget(end_line_edit)
        else:
            end_line_label.setVisible(False)
            end_line_edit.setVisible(False)
        # Timeout input
        from PySide6.QtWidgets import QSpinBox
        timeout_label = QLabel("Timeout (seconds, min 1):")
        lay.addWidget(timeout_label)
        timeout_spin = QSpinBox()
        timeout_spin.setRange(1, 3600)
        timeout_spin.setValue(cur_timeout)
        lay.addWidget(timeout_spin)
        # pattern text (3 lines)
        lay.addWidget(QLabel("Pattern text:"))
        pattern_edit = QTextEdit()
        pattern_edit.setPlainText(cur_pattern)
        pattern_edit.setMaximumHeight(70)
        lay.addWidget(pattern_edit)
        # test input (10 lines, disabled when not regex)
        lay.addWidget(QLabel("Regex match test (sample output per pattern):"))
        test_edit = QTextEdit()
        test_edit.setMinimumHeight(220)
        test_edit.setEnabled(False)
        lay.addWidget(test_edit)
        # Load sample from file button
        load_btn = QPushButton("Load sample from file...")
        load_btn.setEnabled(False)
        def _load_sample():
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                dlg, "Open log file", "",
                "Log files (*.log *.txt);;All files (*)")
            if path:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        test_edit.setPlainText(f.read())
                except Exception as e:
                    result_label.setText(f"Load error: {e}")
        load_btn.clicked.connect(_load_sample)
        lay.addWidget(load_btn)
        test_btn = QPushButton("Test match")
        test_btn.setEnabled(False)
        lay.addWidget(test_btn)
        # result
        result_label = QLabel("")
        lay.addWidget(result_label)
        def _on_regex_changed(state):
            test_edit.setEnabled(state)
            test_btn.setEnabled(state)
            load_btn.setEnabled(state)
        regex_cb.toggled.connect(_on_regex_changed)
        _on_regex_changed(regex_cb.isChecked())
        def _test():
            import re
            pattern = pattern_edit.toPlainText()
            sample = test_edit.toPlainText()
            flags = 0 if case_cb.isChecked() else re.IGNORECASE
            try:
                if regex_cb.isChecked():
                    # regex mode
                    if re.search(pattern, sample, flags):
                        result_label.setText("✓ REGEX MATCH")
                        result_label.setStyleSheet("color: green")
                    else:
                        result_label.setText("✗ no regex match")
                        result_label.setStyleSheet("color: red")
                else:
                    # exact substring mode
                    if case_cb.isChecked():
                        hit = pattern in sample
                    else:
                        hit = pattern.lower() in sample.lower()
                    if hit:
                        result_label.setText("✓ EXACT MATCH")
                        result_label.setStyleSheet("color: green")
                    else:
                        result_label.setText("✗ no exact match")
                        result_label.setStyleSheet("color: red")
            except re.error as e:
                result_label.setText(f"Regex error: {e}")
                result_label.setStyleSheet("color: red")
        # common patterns hint
        lay.addWidget(QLabel("Regex common:  root@.*  |  login:  |  ERROR|FAIL  |  \\d+\\.\\d+"))
        # buttons
        btn_row = QHBoxLayout()
        ok = QPushButton("OK")
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)
        if dlg.exec() == QDialog.Accepted:
            if cmd is None:
                cmd = self._get_row_cmd(row)
            pat = pattern_edit.toPlainText()
            enabled = enable_cb.isChecked()
            cmd.case_sensitive = case_cb.isChecked()
            if title == "WaitFor":
                cmd.wait_enabled = enabled
                cmd.expect_pass = pat if enabled else ""
                cmd.expect_pass_is_regex = regex_cb.isChecked()
                cmd.wait_timeout = float(timeout_spin.value())
            else:
                cmd.capture_enabled = enabled
                cmd.expect_fail = pat if enabled else ""
                cmd.expect_fail_is_regex = regex_cb.isChecked()
                cmd.capture_is_expected = expect_cb.isChecked()
                cmd.capture_end_line = end_line_edit.text()
                cmd.timeout = float(timeout_spin.value())
            # keep kind consistent for a wait-only row
            if cmd.wait_enabled and not cmd.send_enabled:
                cmd.kind = "wait"
            elif cmd.kind == "wait" and cmd.send_enabled:
                cmd.kind = "send"
            self._save_row_cmd(row, cmd)

    def _edit_sendto_cell(self, row: int, col: int) -> None:
        """SendTo editor: shell command (serial/ssh) or SFTP transfer (ssh only)."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                        QTextEdit, QLineEdit, QPushButton,
                                        QLabel, QComboBox, QFileDialog,
                                        QStackedWidget, QCheckBox,
                                        QSpinBox, QWidget, QFormLayout)
        transport = self.cmd_table.cellWidget(row, 1).currentText()
        current_text = self.cmd_table.item(row, col).text() if self.cmd_table.item(row, col) else ""
        cmd = self._row_cmd(row)
        if cmd is not None:
            send_is_off = not cmd.send_enabled
        else:
            send_is_off = current_text.strip() == "(off)"

        dlg = QDialog(self)
        dlg.setWindowTitle("SendTo editor")
        dlg.setMinimumWidth(750)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        lay = QVBoxLayout(dlg)

        # Enable Send step checkbox
        send_enable_cb = QCheckBox("Enable Send step")
        send_enable_cb.setChecked(not send_is_off)
        lay.addWidget(send_enable_cb)

        # operation type (only for ssh)
        op_label = QLabel("Operation:")
        op_type = QComboBox()
        op_type.addItems(["shell_command", "sftp_put", "sftp_get"])
        lay.addWidget(op_label)
        lay.addWidget(op_type)

        # stacked widget for different operation types
        stack = QStackedWidget()

        # page 0: shell command
        page_cmd = QWidget()
        lay_cmd = QVBoxLayout(page_cmd)
        lay_cmd.addWidget(QLabel(
            "One line = one command. Multiple lines = multiple commands,\n"
            "sent in order. Newline auto-appended to each command (no need to type \\n)."))
        cmd_edit = QTextEdit()
        cmd_edit.setMinimumHeight(150)
        lay_cmd.addWidget(cmd_edit)
        # send timeout
        from PySide6.QtWidgets import QSpinBox
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("Send timeout (seconds, min 1):"))
        send_timeout_spin = QSpinBox()
        send_timeout_spin.setRange(1, 3600)
        send_timeout_spin.setValue(
            int(cmd.send_timeout) if cmd is not None else 4)
        timeout_row.addWidget(send_timeout_spin)
        timeout_row.addStretch(1)
        lay_cmd.addLayout(timeout_row)
        stack.addWidget(page_cmd)

        # page 1: sftp_put
        page_put = QWidget()
        lay_put = QFormLayout(page_put)
        put_local = QLineEdit()
        put_remote = QLineEdit()
        browse_put_local = QPushButton("Browse...")
        def _browse_put():
            path, _ = QFileDialog.getOpenFileName(dlg, "Select file to upload")
            if path:
                put_local.setText(path)
        browse_put_local.clicked.connect(_browse_put)
        lay_put.addRow("Local file:", put_local)
        lay_put.addRow("", browse_put_local)
        lay_put.addRow("Remote path:", put_remote)
        put_timeout = QSpinBox()
        put_timeout.setRange(1, 3600)
        put_timeout.setValue(30)
        lay_put.addRow("Timeout (seconds):", put_timeout)
        stack.addWidget(page_put)

        # page 2: sftp_get
        page_get = QWidget()
        lay_get = QFormLayout(page_get)
        get_remote = QLineEdit()
        get_local = QLineEdit()
        browse_get_local = QPushButton("Browse...")
        def _browse_get():
            path, _ = QFileDialog.getSaveFileName(dlg, "Save file as")
            if path:
                get_local.setText(path)
        browse_get_local.clicked.connect(_browse_get)
        lay_get.addRow("Remote file:", get_remote)
        lay_get.addRow("Local save:", get_local)
        lay_get.addRow("", browse_get_local)
        get_timeout = QSpinBox()
        get_timeout.setRange(1, 3600)
        get_timeout.setValue(30)
        lay_get.addRow("Timeout (seconds):", get_timeout)
        stack.addWidget(page_get)

        lay.addWidget(stack)

        # show/hide op type based on transport
        if transport == "serial":
            op_type.setVisible(False)
            stack.setCurrentIndex(0)
        else:
            op_type.setVisible(True)

        def _on_op_changed(idx):
            stack.setCurrentIndex(idx)
        op_type.currentIndexChanged.connect(_on_op_changed)

        # restore from the row's full command, fall back to cell text
        if cmd is not None and cmd.kind in ("sftp_put", "sftp_get"):
            if cmd.kind == "sftp_put":
                op_type.setCurrentIndex(1)
                put_local.setText(cmd.local)
                put_remote.setText(cmd.remote)
                put_timeout.setValue(int(cmd.send_timeout))
            else:
                op_type.setCurrentIndex(2)
                get_remote.setText(cmd.remote)
                get_local.setText(cmd.local)
                get_timeout.setValue(int(cmd.send_timeout))
        elif current_text.startswith("[PUT] "):
            op_type.setCurrentIndex(1)
            rest = current_text[6:]  # after "[PUT] "
            if " -> " in rest:
                put_local.setText(rest.split(" -> ")[0])
                put_remote.setText(rest.split(" -> ")[1])
        elif current_text.startswith("[GET] "):
            op_type.setCurrentIndex(2)
            rest = current_text[6:]  # after "[GET] "
            if " -> " in rest:
                get_remote.setText(rest.split(" -> ")[0])
                get_local.setText(rest.split(" -> ")[1])
        else:
            op_type.setCurrentIndex(0)
            cmd_edit.setPlainText(cmd.send if cmd is not None
                                  else current_text)

        # buttons
        btn_row = QHBoxLayout()
        ok = QPushButton("OK")
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        if dlg.exec() == QDialog.Accepted:
            idx = op_type.currentIndex()
            if cmd is None:
                cmd = self._get_row_cmd(row)
            if not send_enable_cb.isChecked():
                # Send disabled
                cmd.send_enabled = False
                cmd.send = ""
                self._save_row_cmd(row, cmd)
                return
            cmd.send_enabled = True
            if idx == 0:
                # shell command (one or many lines; newline auto-appended)
                cmd.kind = "send"
                cmd.send = cmd_edit.toPlainText()
                cmd.send_timeout = float(send_timeout_spin.value())
                cmd.local = ""
                cmd.remote = ""
            elif idx == 1:
                # sftp_put: Wait/Capture are not used for a file transfer
                cmd.kind = "sftp_put"
                cmd.local = put_local.text()
                cmd.remote = put_remote.text()
                cmd.send_timeout = float(put_timeout.value())
                cmd.wait_enabled = False
                cmd.expect_pass = ""
                cmd.capture_enabled = False
                cmd.expect_fail = ""
            else:
                # sftp_get
                cmd.kind = "sftp_get"
                cmd.remote = get_remote.text()
                cmd.local = get_local.text()
                cmd.send_timeout = float(get_timeout.value())
                cmd.wait_enabled = False
                cmd.expect_pass = ""
                cmd.capture_enabled = False
                cmd.expect_fail = ""
            self._save_row_cmd(row, cmd)

    # --------------------------------------------------------------- wifi
    @staticmethod
    def _tspin(value: int = 15) -> QSpinBox:
        """A per-sub-test timeout spin box (seconds, 1..600, default 15)."""
        s = QSpinBox()
        s.setRange(1, 600)
        s.setValue(int(value))
        s.setSuffix(" s")
        return s

    def _build_wifi_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.wifi_enabled = QCheckBox(
            "Enable Wi-Fi FCT  (DUT advertises the Wi-Fi endpoint; "
            "Host PC is the initiator)")
        lay.addWidget(self.wifi_enabled)
        self.wifi_enabled.toggled.connect(self._sync_wifi_groups)

        # ---- base parameters ------------------------------------------------
        self.wifi_base = QGroupBox("Base parameters")
        base = QFormLayout(self.wifi_base)
        self.wifi_interface = QLineEdit("mlan0")
        base.addRow("Interface (DUT):", self.wifi_interface)
        self.wifi_driver_cmd = QLineEdit()
        self.wifi_driver_cmd.setPlaceholderText("/root/load_rf_drivers.sh")
        self.wifi_driver_cmd.setToolTip(
            "Linux DUT only. Editable command sent over the console to "
            "load the Wi-Fi/BT drivers; the driver script itself is a "
            "BSP deliverable.")
        base.addRow("Driver load cmd (DUT):", self.wifi_driver_cmd)
        lay.addWidget(self.wifi_base)

        # ---- 1) scan / RSSI (both DUT kinds) --------------------------------
        self.wifi_scan_box = QGroupBox("1. Scan / RSSI test  (Linux + "
                                      "Bare-metal/RTOS)")
        self.wifi_scan_box.setCheckable(True)
        self.wifi_scan_box.setChecked(True)
        sc = QFormLayout(self.wifi_scan_box)
        self.wifi_scan_ssid = QLineEdit()
        self.wifi_scan_ssid.setPlaceholderText("DUT Wi-Fi SSID to scan")
        sc.addRow("DUT SSID:", self.wifi_scan_ssid)
        self.wifi_rssi_min = QSpinBox()
        self.wifi_rssi_min.setRange(-100, 0)
        self.wifi_rssi_min.setValue(-70)
        sc.addRow("RSSI min (dBm):", self.wifi_rssi_min)
        self.wifi_scan_via = QComboBox()
        self.wifi_scan_via.addItems(list(WIFI_SCAN_VIA))
        self.wifi_scan_via.setToolTip(
            "host: Host PC scans the DUT AP/hotspot (default, works for "
            "AP-mode & bare-metal). dut_console: read the station-mode "
            "Linux DUT's own link RSSI over the console (iw dev).")
        sc.addRow("RSSI via:", self.wifi_scan_via)
        self.wifi_scan_timeout = self._tspin(15)
        sc.addRow("Timeout:", self.wifi_scan_timeout)
        lay.addWidget(self.wifi_scan_box)

        # ---- 2) connect & ping (Linux only) --------------------------------
        self.wifi_ping_box = QGroupBox("2. Connect & Ping test  (Linux only; "
                                      "PASS on >=1 reply)")
        self.wifi_ping_box.setCheckable(True)
        self.wifi_ping_box.setChecked(False)
        pg = QFormLayout(self.wifi_ping_box)
        self.wifi_ping_ssid = QLineEdit()
        pg.addRow("DUT AP SSID:", self.wifi_ping_ssid)
        self.wifi_ping_password = QLineEdit()
        self.wifi_ping_password.setEchoMode(QLineEdit.Password)
        pg.addRow("Password:", self.wifi_ping_password)
        self.wifi_ping_count = QSpinBox()
        self.wifi_ping_count.setRange(1, 200)
        self.wifi_ping_count.setValue(20)
        pg.addRow("Ping count:", self.wifi_ping_count)
        self.wifi_ping_timeout = self._tspin(15)
        pg.addRow("Timeout:", self.wifi_ping_timeout)
        lay.addWidget(self.wifi_ping_box)

        # ---- 3) iperf throughput (Linux only) ------------------------------
        self.wifi_iperf_box = QGroupBox("3. iPerf throughput test  (Linux "
                                        "only; Host server / DUT client)")
        self.wifi_iperf_box.setCheckable(True)
        self.wifi_iperf_box.setChecked(False)
        ip = QFormLayout(self.wifi_iperf_box)
        self.wifi_iperf_tool = QComboBox()
        self.wifi_iperf_tool.addItems(list(BW_TOOLS)[::-1])  # iperf3 first
        ip.addRow("Tool:", self.wifi_iperf_tool)
        self.wifi_iperf_min = QDoubleSpinBox()
        self.wifi_iperf_min.setRange(0.0, 10000.0)
        self.wifi_iperf_min.setValue(10.0)
        ip.addRow("Min throughput (Mbps):", self.wifi_iperf_min)
        self.wifi_iperf_server = QLineEdit()
        self.wifi_iperf_server.setPlaceholderText(
            "Host PC server IP - leave empty to auto-detect")
        ip.addRow("Server IP (host):", self.wifi_iperf_server)
        self.wifi_iperf_duration = QSpinBox()
        self.wifi_iperf_duration.setRange(1, 600)
        self.wifi_iperf_duration.setValue(10)
        self.wifi_iperf_duration.setSuffix(" s")
        ip.addRow("Duration:", self.wifi_iperf_duration)
        self.wifi_iperf_timeout = self._tspin(15)
        ip.addRow("Timeout:", self.wifi_iperf_timeout)
        lay.addWidget(self.wifi_iperf_box)
        lay.addStretch(1)
        self._sync_wifi_groups()
        return w

    def _sync_wifi_groups(self) -> None:
        """Enable state = master Wi-Fi switch AND (for Linux-only
        sub-tests) the DUT OS/firmware kind."""
        if not hasattr(self, "wifi_scan_box") or not hasattr(
                self, "dut_type"):
            return
        is_linux = self.dut_type.currentText() == "linux"
        on = self.wifi_enabled.isChecked()
        self.wifi_base.setEnabled(on)
        self.wifi_driver_cmd.setEnabled(on and is_linux)
        self.wifi_scan_box.setEnabled(on)
        self.wifi_ping_box.setEnabled(on and is_linux)
        self.wifi_iperf_box.setEnabled(on and is_linux)
        # dut_console RSSI read needs a Linux shell; bare-metal = host scan
        if not is_linux and self.wifi_scan_via.currentText() != "host":
            self.wifi_scan_via.blockSignals(True)
            self.wifi_scan_via.setCurrentText("host")
            self.wifi_scan_via.blockSignals(False)
        self.wifi_scan_via.setEnabled(on and is_linux)

    # ---------------------------------------------------------- bluetooth
    def _build_bt_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.bt_enabled = QCheckBox(
            "Enable Bluetooth FCT  (Host PC is the initiator / A2DP "
            "source; DUT is the sink / advertiser)")
        lay.addWidget(self.bt_enabled)
        self.bt_enabled.toggled.connect(self._sync_bt_groups)

        # ---- 1) RSSI / discovery (both DUT kinds) --------------------------
        self.bt_rssi_box = QGroupBox("1. RSSI / discovery test  (Linux + "
                                     "Bare-metal/RTOS)")
        self.bt_rssi_box.setCheckable(True)
        self.bt_rssi_box.setChecked(True)
        rs = QFormLayout(self.bt_rssi_box)
        self.bt_name = QLineEdit()
        self.bt_name.setPlaceholderText("DUT Bluetooth advertised name")
        rs.addRow("DUT BT name:", self.bt_name)
        self.bt_rssi_min = QSpinBox()
        self.bt_rssi_min.setRange(-100, 0)
        self.bt_rssi_min.setValue(-70)
        rs.addRow("RSSI min (dBm):", self.bt_rssi_min)
        self.bt_rssi_timeout = self._tspin(15)
        rs.addRow("Timeout:", self.bt_rssi_timeout)
        lay.addWidget(self.bt_rssi_box)

        # ---- 2) pair & connect (Linux only) --------------------------------
        self.bt_pair_box = QGroupBox("2. Pair & Connect test  (Linux only)")
        self.bt_pair_box.setCheckable(True)
        self.bt_pair_box.setChecked(False)
        pr = QFormLayout(self.bt_pair_box)
        self.bt_pair_timeout = self._tspin(15)
        pr.addRow("Timeout:", self.bt_pair_timeout)
        self.bt_l2ping = QSpinBox()
        self.bt_l2ping.setRange(0, 100)
        self.bt_l2ping.setValue(0)
        self.bt_l2ping.setToolTip(
            "Optional L2CAP ping DUT -> host PC (data-transfer proof, "
            "real echo both ways); 0 = off.")
        pr.addRow("L2CAP ping count (0=off):", self.bt_l2ping)
        lay.addWidget(self.bt_pair_box)

        # ---- 3) tone / music over A2DP (Linux only) ------------------------
        self.bt_tone_box = QGroupBox("3. Tone / Music over A2DP  (Linux "
                                    "only; Host source -> DUT sink)")
        self.bt_tone_box.setCheckable(True)
        self.bt_tone_box.setChecked(False)
        tn = QFormLayout(self.bt_tone_box)
        self.bt_audio_confirm = QCheckBox(
            "GUI_CONFIRM: operator confirms the tone is heard on the DUT")
        self.bt_audio_confirm.setChecked(True)
        tn.addRow(self.bt_audio_confirm)
        self.bt_tone_timeout = self._tspin(15)
        tn.addRow("Timeout:", self.bt_tone_timeout)
        lay.addWidget(self.bt_tone_box)
        lay.addStretch(1)
        self._sync_bt_groups()
        return w

    def _sync_bt_groups(self) -> None:
        if not hasattr(self, "bt_rssi_box") or not hasattr(
                self, "dut_type"):
            return
        is_linux = self.dut_type.currentText() == "linux"
        on = self.bt_enabled.isChecked()
        self.bt_rssi_box.setEnabled(on)
        self.bt_pair_box.setEnabled(on and is_linux)
        self.bt_tone_box.setEnabled(on and is_linux)

    # ------------------------------------------------------- helpers
    # ------------------------------------------------- row model (UserRole)
    def _row_cmd(self, r: int):
        """The raw ConsoleCommand stored on the row (or None)."""
        item = self.cmd_table.item(r, 0)
        return item.data(_CMD_ROLE) if item is not None else None

    def _set_cell(self, r: int, col: int, text: str,
                  editable: bool = True) -> None:
        item = self.cmd_table.item(r, col)
        if item is None:
            item = QTableWidgetItem()
            self.cmd_table.setItem(r, col, item)
        item.setText(text)
        if editable:
            item.setFlags(item.flags() | Qt.ItemIsEditable)
        else:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)

    def _render_row_cmd(self, r: int, cmd: ConsoleCommand) -> None:
        """Refresh the visible summary cells/dropdowns from cmd."""
        self._set_cell(r, 0, cmd.name)
        self._set_cell(r, 2, cmd.expect_pass if cmd.wait_enabled
                       else "(off)")
        if not cmd.send_enabled:
            send_text = "(off)"
        elif cmd.kind == "sftp_put":
            send_text = f"[PUT] {cmd.local} -> {cmd.remote}"
        elif cmd.kind == "sftp_get":
            send_text = f"[GET] {cmd.remote} -> {cmd.local}"
        else:
            send_text = cmd.send
        self._set_cell(r, 3, send_text)
        self._set_cell(r, 4, cmd.expect_fail if cmd.capture_enabled
                       else "(off)")
        parts = []
        if cmd.wait_enabled:
            parts.append(f"W:{int(cmd.wait_timeout)}s")
        if cmd.send_enabled:
            parts.append(f"S:{int(cmd.send_timeout)}s")
        if cmd.capture_enabled:
            parts.append(f"C:{int(cmd.timeout)}s")
        self._set_cell(r, 5, " ".join(parts) if parts else "-",
                       editable=False)
        cb = self.cmd_table.cellWidget(r, 1)
        if cb is not None:
            cb.setCurrentText(cmd.transport)
        rb = self.cmd_table.cellWidget(r, 6)
        if rb is not None:
            rb.setCurrentText("yes" if cmd.retries > 0 else "no")

    def _save_row_cmd(self, r: int, cmd: ConsoleCommand) -> None:
        """Persist the full command on the row and re-render."""
        item = self.cmd_table.item(r, 0)
        if item is None:
            item = QTableWidgetItem()
            self.cmd_table.setItem(r, 0, item)
        item.setData(_CMD_ROLE, cmd)
        self._render_row_cmd(r, cmd)

    def _get_row_cmd(self, r: int) -> ConsoleCommand:
        """Return the row's command; overlay the directly-editable
        Name / Console / Retry columns."""
        item = self.cmd_table.item(r, 0)
        cmd = item.data(_CMD_ROLE) if item is not None else None
        if cmd is None:
            return self._row_to_console_command(r)
        if item is not None:
            cmd.name = item.text()
        cb = self.cmd_table.cellWidget(r, 1)
        if cb is not None:
            cmd.transport = cb.currentText()
        rb = self.cmd_table.cellWidget(r, 6)
        if rb is not None:
            cmd.retries = 1 if rb.currentText() == "yes" else 0
        return cmd

    def _row_to_console_command(self, r: int) -> ConsoleCommand:
        """Convert one cmd_table row to a ConsoleCommand.
        SendTo column encodes sftp ops as '[PUT] local -> remote' /
        '[GET] remote -> local'. '(off)' means that stage is disabled."""
        name = self.cmd_table.item(r, 0).text() if self.cmd_table.item(r, 0) else ""
        transport = self.cmd_table.cellWidget(r, 1).currentText()
        waitfor = self.cmd_table.item(r, 2).text() if self.cmd_table.item(r, 2) else ""
        sendto = self.cmd_table.item(r, 3).text() if self.cmd_table.item(r, 3) else ""
        capture = self.cmd_table.item(r, 4).text() if self.cmd_table.item(r, 4) else ""
        retries = 1 if self.cmd_table.cellWidget(r, 6).currentText() == "yes" else 0

        wait_enabled = waitfor.strip() not in ("", "(off)")
        capture_enabled = capture.strip() not in ("", "(off)")
        send_enabled = sendto.strip() not in ("", "(off)")
        if not wait_enabled:
            waitfor = ""
        if not capture_enabled:
            capture = ""

        kind = "send"
        send = sendto
        local = ""
        remote = ""

        if sendto.startswith("[PUT] "):
            kind = "sftp_put"
            send = ""
            rest = sendto[6:]
            if " -> " in rest:
                local, remote = rest.split(" -> ", 1)
        elif sendto.startswith("[GET] "):
            kind = "sftp_get"
            send = ""
            rest = sendto[6:]
            if " -> " in rest:
                remote, local = rest.split(" -> ", 1)

        return ConsoleCommand(
            kind=kind, name=name, transport=transport,
            wait_enabled=wait_enabled, send_enabled=send_enabled,
            capture_enabled=capture_enabled,
            send=send, expect_pass=waitfor, expect_fail=capture,
            retries=retries, local=local, remote=remote)

    # ------------------------------------------------------- state in/out
    def set_values(self, params: dict) -> None:
        """Restore from the module params (round-trip safe)."""
        self._legacy = {k: v for k, v in (params or {}).items()
                        if k != "fct_test_config_yaml"}
        text = str((params or {}).get("fct_test_config_yaml", "") or "")
        data = {}
        if text.strip():
            try:
                node = yaml.safe_load(text) or {}
                data = node.get("fct_test_config") or {}
            except yaml.YAMLError:
                self.task_log.emit("ERROR",
                                   "fct_test_config_yaml: invalid YAML "
                                   "- defaults loaded")
        cfg = FctTestConfig.from_dict(data)
        self._guard = True
        try:
            self.dut_type.setCurrentText(cfg.dut_type)
            c = cfg.console
            self.console_enabled.setChecked(c.enabled)
            if c.port:
                if self.console_port.findText(c.port) < 0:
                    self.console_port.addItem(c.port)
                self.console_port.setCurrentText(c.port)
            self.console_baud.setCurrentText(str(c.baudrate))
            self.cmd_table.setRowCount(0)
            for cmd in c.test_commands:
                r = self.cmd_table.rowCount()
                self.cmd_table.insertRow(r)
                # Name
                self.cmd_table.setItem(r, 0, QTableWidgetItem(cmd.name))
                # Console = dropdown
                cb = QComboBox()
                cb.addItems(["serial", "ssh"])
                cb.setCurrentText(cmd.transport)
                self.cmd_table.setCellWidget(r, 1, cb)
                # WaitFor
                wait_text = cmd.expect_pass if cmd.wait_enabled else "(off)"
                self.cmd_table.setItem(r, 2, QTableWidgetItem(wait_text))
                # SendTo: encode sftp ops as [PUT]/[GET]
                if not cmd.send_enabled:
                    sendto_text = "(off)"
                elif cmd.kind == "sftp_put":
                    sendto_text = f"[PUT] {cmd.local} -> {cmd.remote}"
                elif cmd.kind == "sftp_get":
                    sendto_text = f"[GET] {cmd.remote} -> {cmd.local}"
                else:
                    sendto_text = cmd.send
                self.cmd_table.setItem(r, 3, QTableWidgetItem(sendto_text))
                # Capture
                cap_text = cmd.expect_fail if cmd.capture_enabled else "(off)"
                self.cmd_table.setItem(r, 4, QTableWidgetItem(cap_text))
                # Timeout (shows enabled stages only; read-only)
                parts = []
                if cmd.wait_enabled:
                    parts.append(f"W:{int(cmd.wait_timeout)}s")
                if cmd.send_enabled:
                    parts.append(f"S:{int(cmd.send_timeout)}s")
                if cmd.capture_enabled:
                    parts.append(f"C:{int(cmd.timeout)}s")
                timeout_text = " ".join(parts) if parts else "-"
                timeout_item = QTableWidgetItem(timeout_text)
                from PySide6.QtCore import Qt as _Qt
                timeout_item.setFlags(timeout_item.flags() & ~_Qt.ItemIsEditable)
                self.cmd_table.setItem(r, 5, timeout_item)
                # Retry = dropdown
                rb = QComboBox()
                rb.addItems(["no", "yes"])
                rb.setCurrentText("yes" if cmd.retries > 0 else "no")
                self.cmd_table.setCellWidget(r, 6, rb)
                # persist the full command (advanced attrs) on the row
                self.cmd_table.item(r, 0).setData(_CMD_ROLE, cmd)
            # apply the serial-only / serial+ssh transport options for
            # the restored dut_type after all rows are built
            self._refresh_console_transport_options()
            w = cfg.wifi
            self.wifi_enabled.setChecked(w.enabled)
            self.wifi_interface.setText(w.interface)
            self.wifi_driver_cmd.setText(w.driver_load_cmd)
            self.wifi_scan_box.setChecked(w.scan_enabled)
            self.wifi_scan_ssid.setText(w.scan_ssid)
            self.wifi_rssi_min.setValue(w.rssi_min)
            self.wifi_scan_via.setCurrentText(w.scan_via)
            self.wifi_scan_timeout.setValue(int(w.scan_timeout))
            self.wifi_ping_box.setChecked(w.ping_enabled)
            self.wifi_ping_ssid.setText(w.ping_ssid)
            self.wifi_ping_password.setText(w.ping_password)
            self.wifi_ping_count.setValue(w.ping_count)
            self.wifi_ping_timeout.setValue(int(w.ping_timeout))
            self.wifi_iperf_box.setChecked(w.iperf_enabled)
            self.wifi_iperf_tool.setCurrentText(w.iperf_tool)
            self.wifi_iperf_min.setValue(w.iperf_min_mbps)
            self.wifi_iperf_server.setText(w.iperf_server_ip)
            self.wifi_iperf_duration.setValue(w.iperf_duration)
            self.wifi_iperf_timeout.setValue(int(w.iperf_timeout))
            b = cfg.bluetooth
            self.bt_enabled.setChecked(b.enabled)
            self.bt_rssi_box.setChecked(b.rssi_enabled)
            self.bt_name.setText(b.expected_name)
            self.bt_rssi_min.setValue(b.rssi_min)
            self.bt_rssi_timeout.setValue(int(b.rssi_timeout))
            self.bt_pair_box.setChecked(b.pair_enabled)
            self.bt_pair_timeout.setValue(int(b.pair_timeout))
            self.bt_l2ping.setValue(b.l2ping_count)
            self.bt_tone_box.setChecked(b.tone_enabled)
            self.bt_audio_confirm.setChecked(b.audio_confirm)
            self.bt_tone_timeout.setValue(int(b.tone_timeout))
            self._sync_wifi_groups()
            self._sync_bt_groups()
            s = cfg.setup
            idx = self.setup_power.findData(s.power_mode)
            self.setup_power.setCurrentIndex(idx if idx >= 0 else 0)
            self.setup_fixture.setChecked(s.use_fixture)
            self.setup_on_msg.setText(s.manual_on_message)
            self.setup_off_msg.setText(s.manual_off_message)
            self._on_setup_power_changed(self.setup_power.currentIndex())
        finally:
            self._guard = False

    def _table_lines(self, table: QTableWidget, width: int) -> list:
        rows = []
        for r in range(table.rowCount()):
            row = [(table.item(r, c).text() if table.item(r, c) else "")
                   for c in range(width)]
            if any(cell.strip() for cell in row):
                rows.append(row)
        return rows

    def values(self) -> dict:
        """Module params: legacy keys preserved + the full
        fct_test_config node as YAML text."""
        cfg = FctTestConfig(
            dut_type=self.dut_type.currentText(),
            console=None, wifi=None, bluetooth=None)
        from mtkgui.engine.fct_test_config import (
            BluetoothCfg,
            ConsoleCfg,
            ConsoleCommand,
            WifiCfg,
        )
        cfg.console = ConsoleCfg(
            enabled=self.console_enabled.isChecked(),
            port=self.console_port.currentText().strip(),
            baudrate=int(self.console_baud.currentText()),
            test_commands=[
                self._get_row_cmd(r)
                for r in range(self.cmd_table.rowCount())],
        )
        cfg.wifi = WifiCfg(
            enabled=self.wifi_enabled.isChecked(),
            interface=self.wifi_interface.text().strip(),
            driver_load_cmd=self.wifi_driver_cmd.text().strip(),
            scan_enabled=self.wifi_scan_box.isChecked(),
            scan_ssid=self.wifi_scan_ssid.text().strip(),
            rssi_min=self.wifi_rssi_min.value(),
            scan_via=self.wifi_scan_via.currentText(),
            scan_timeout=float(self.wifi_scan_timeout.value()),
            ping_enabled=self.wifi_ping_box.isChecked(),
            ping_ssid=self.wifi_ping_ssid.text().strip(),
            ping_password=self.wifi_ping_password.text(),
            ping_count=self.wifi_ping_count.value(),
            ping_timeout=float(self.wifi_ping_timeout.value()),
            iperf_enabled=self.wifi_iperf_box.isChecked(),
            iperf_tool=self.wifi_iperf_tool.currentText(),
            iperf_min_mbps=self.wifi_iperf_min.value(),
            iperf_server_ip=self.wifi_iperf_server.text().strip(),
            iperf_duration=self.wifi_iperf_duration.value(),
            iperf_timeout=float(self.wifi_iperf_timeout.value()),
        )
        cfg.bluetooth = BluetoothCfg(
            enabled=self.bt_enabled.isChecked(),
            rssi_enabled=self.bt_rssi_box.isChecked(),
            expected_name=self.bt_name.text().strip(),
            rssi_min=self.bt_rssi_min.value(),
            rssi_timeout=float(self.bt_rssi_timeout.value()),
            pair_enabled=self.bt_pair_box.isChecked(),
            pair_timeout=float(self.bt_pair_timeout.value()),
            l2ping_count=self.bt_l2ping.value(),
            tone_enabled=self.bt_tone_box.isChecked(),
            audio_confirm=self.bt_audio_confirm.isChecked(),
            tone_timeout=float(self.bt_tone_timeout.value()),
        )
        from mtkgui.engine.fct_test_config import FctSetupCfg
        cfg.setup = FctSetupCfg(
            power_mode=self.setup_power.currentData(),
            use_fixture=self.setup_fixture.isChecked(),
            manual_on_message=self.setup_on_msg.text().strip(),
            manual_off_message=self.setup_off_msg.text().strip(),
        )
        errors = cfg.validate()
        if errors:
            # the dialog shows the error list from the schema pass; the
            # panel keeps the invalid text so nothing is silently lost
            self.task_log.emit("ERROR",
                               "FCT test config: " + "; ".join(errors))
        out = dict(self._legacy)
        out["fct_test_config_yaml"] = yaml.safe_dump(
            cfg.to_yaml_node(), sort_keys=False, allow_unicode=True)
        return out
