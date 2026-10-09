# -*- coding: utf-8 -*-
"""FCTTestConfigWidget — P3-B5 block 07 panel (three tabs).

Edits the `fct_test_config` product-YAML node (Console / Wi-Fi /
Bluetooth) for the "Build FCT Test Work Flow Sequence" module:

* Console tab   — port (serial device dropdown) + baudrate, the
  login_sequence table (wait_for / send) and the test_commands table
  (name / send / expect_pass / expect_fail / timeout); rows are
  add/removable;
* Wi-Fi tab     — enabled / mode / interface / driver_load_cmd /
  rssi_min, the full_stack-only group (ssid / password / gateway /
  ping_count / loss_max) and the bandwidth group (enabled / tool /
  min_mbps);
* Bluetooth tab — enabled / mode / expected_name / rssi_min /
  audio_confirm.

`values()` returns the legacy module params preserved plus
``fct_test_config_yaml`` — the full node as YAML text — so the
Preview & Export shows the complete configuration (spec §3.4).
"""
from __future__ import annotations

import yaml
from PySide6.QtCore import Signal
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
    ConsoleCommand,
    FctTestConfig,
)


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
        """DUT type gates the FCT test items: a Bare Metal/RTOS DUT has
        no Linux shell, so the console login chain, DUT-side iperf and
        L2CAP ping are not applicable (greyed out)."""
        is_linux = dut == "linux"
        self.wifi_driver_cmd.setEnabled(is_linux)
        self.bw_box.setEnabled(is_linux)
        self.wifi_gateway.setEnabled(is_linux)
        self.wifi_ping_count.setEnabled(is_linux)
        self.wifi_loss_max.setEnabled(is_linux)
        self.bt_l2ping.setEnabled(is_linux)
        self.dut_hint.setText(
            "Linux BSP DUT: full console test set (login, shell commands,"
            " DUT-side ping/iperf, L2CAP ping)."
            if is_linux else
            "Bare Metal/RTOS DUT: no Linux shell - console steps are "
            "capture-only (firmware output / command protocol); Wi-Fi "
            "RSSI is a host-side scan; iperf and L2CAP ping disabled.")

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
            # text columns: Name / WaitFor / SendTo / Capture / Timeout
            for col in (0, 2, 3, 4, 5):
                self.cmd_table.setItem(r, col, QTableWidgetItem(""))
            # Console column = dropdown
            cb = QComboBox()
            cb.addItems(["serial", "ssh"])
            self.cmd_table.setCellWidget(r, 1, cb)
            # Retry column = dropdown
            rb = QComboBox()
            rb.addItems(["no", "yes"])
            self.cmd_table.setCellWidget(r, 6, rb)

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
            # copy text cells
            for col in (0, 2, 3, 4, 5):
                src = self.cmd_table.item(r, col)
                if src:
                    self.cmd_table.setItem(r + 1, col,
                                           QTableWidgetItem(src.text()))
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
        """Swap two rows in cmd_table (text cells + dropdown widgets)."""
        # swap text cells
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
        # Use Regex checkbox (default off = exact match)
        regex_cb = QCheckBox("Use Regex (default off = exact substring match)")
        lay.addWidget(regex_cb)
        # Case sensitive checkbox (default on)
        case_cb = QCheckBox("Case Sensitive (uncheck = ignore case, e.g. PASS=pass)")
        case_cb.setChecked(True)
        lay.addWidget(case_cb)
        # Capture expected checkbox (only for Capture column)
        expect_cb = QCheckBox("Expect to capture this message")
        if title == "Capture":
            expect_cb.setChecked(False)
            lay.addWidget(expect_cb)
        # End line input (always visible for Capture column)
        # Regex / Case Sensitive reuse the same checkboxes above
        end_line_label = QLabel("End line (marks end of range, same Regex/Case settings):")
        end_line_edit = QLineEdit()
        end_line_edit.setPlaceholderText("e.g. # TEST COMPLETE")
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
        if title == "WaitFor":
            timeout_spin.setValue(10)
        else:
            timeout_spin.setValue(6)
        lay.addWidget(timeout_spin)
        # pattern text (3 lines)
        lay.addWidget(QLabel("Pattern text:"))
        pattern_edit = QTextEdit()
        pattern_edit.setPlainText(self.cmd_table.item(row, col).text())
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
            self.cmd_table.item(row, col).setText(pattern_edit.toPlainText())

    def _edit_sendto_cell(self, row: int, col: int) -> None:
        """SendTo editor: shell command (serial/ssh) or SFTP transfer (ssh only)."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                        QTextEdit, QLineEdit, QPushButton,
                                        QLabel, QComboBox, QFileDialog,
                                        QStackedWidget)
        transport = self.cmd_table.cellWidget(row, 1).currentText()
        current_text = self.cmd_table.item(row, col).text() if self.cmd_table.item(row, col) else ""

        dlg = QDialog(self)
        dlg.setWindowTitle("SendTo editor")
        dlg.setMinimumWidth(550)
        from PySide6.QtCore import Qt
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.raise_()
        dlg.activateWindow()
        lay = QVBoxLayout(dlg)

        # operation type (only for ssh)
        op_type = QComboBox()
        op_type.addItems(["shell_command", "sftp_put", "sftp_get"])
        lay.addWidget(QLabel("Operation:"))
        lay.addWidget(op_type)

        # stacked widget for different operation types
        stack = QStackedWidget()

        # page 0: shell command
        page_cmd = QWidget()
        lay_cmd = QVBoxLayout(page_cmd)
        cmd_edit = QTextEdit()
        lay_cmd.addWidget(cmd_edit)
        lay_cmd.addWidget(QLabel("Tip: use \\n for newline"))
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

        # restore from current cell text
        if current_text.startswith("[PUT] "):
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
            cmd_edit.setPlainText(current_text)

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
            if idx == 0:
                text = cmd_edit.toPlainText()
            elif idx == 1:
                text = f"[PUT] {put_local.text()} -> {put_remote.text()}"
            else:
                text = f"[GET] {get_remote.text()} -> {get_local.text()}"
            self.cmd_table.item(row, col).setText(text)

    # --------------------------------------------------------------- wifi
    def _build_wifi_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.wifi_enabled = QCheckBox("Enable Wi-Fi FCT")
        lay.addWidget(self.wifi_enabled)
        form = QFormLayout()
        self.wifi_mode = QComboBox()
        self.wifi_mode.addItems(list(WIFI_MODES))
        self.wifi_mode.currentTextChanged.connect(
            self._on_wifi_mode_changed)
        form.addRow("Mode:", self.wifi_mode)
        self.wifi_interface = QLineEdit("mlan0")
        form.addRow("Interface (DUT):", self.wifi_interface)
        self.wifi_driver_cmd = QLineEdit()
        self.wifi_driver_cmd.setPlaceholderText(
            "/root/load_rf_drivers.sh")
        form.addRow("Driver load cmd (DUT):", self.wifi_driver_cmd)
        self.wifi_rssi_min = QSpinBox()
        self.wifi_rssi_min.setRange(-100, 0)
        self.wifi_rssi_min.setValue(-70)
        form.addRow("RSSI min (dBm):", self.wifi_rssi_min)
        lay.addLayout(form)

        self.wifi_fs_box = QGroupBox("full_stack only")
        fs = QFormLayout(self.wifi_fs_box)
        self.wifi_ssid = QLineEdit()
        fs.addRow("SSID:", self.wifi_ssid)
        self.wifi_password = QLineEdit()
        self.wifi_password.setEchoMode(QLineEdit.Password)
        fs.addRow("Password:", self.wifi_password)
        self.wifi_gateway = QLineEdit()
        fs.addRow("Gateway:", self.wifi_gateway)
        self.wifi_ping_count = QSpinBox()
        self.wifi_ping_count.setRange(1, 200)
        self.wifi_ping_count.setValue(20)
        fs.addRow("Ping count:", self.wifi_ping_count)
        self.wifi_loss_max = QDoubleSpinBox()
        self.wifi_loss_max.setRange(0.0, 100.0)
        self.wifi_loss_max.setValue(5.0)
        fs.addRow("Loss max (%):", self.wifi_loss_max)
        lay.addWidget(self.wifi_fs_box)

        self.bw_box = QGroupBox("Bandwidth (iperf, DUT client -> host server)")
        bw = QFormLayout(self.bw_box)
        self.bw_enabled = QCheckBox("Enabled")
        bw.addRow(self.bw_enabled)
        self.bw_tool = QComboBox()
        self.bw_tool.addItems(list(BW_TOOLS))
        bw.addRow("Tool:", self.bw_tool)
        self.bw_server_ip = QLineEdit()
        self.bw_server_ip.setPlaceholderText("host PC IP, e.g. 192.168.10.141")
        bw.addRow("Server IP (host):", self.bw_server_ip)
        self.bw_min_mbps = QDoubleSpinBox()
        self.bw_min_mbps.setRange(0.0, 10000.0)
        self.bw_min_mbps.setValue(10.0)
        bw.addRow("Min Mbps:", self.bw_min_mbps)
        lay.addWidget(self.bw_box)
        lay.addStretch(1)
        return w

    def _on_wifi_mode_changed(self, mode: str) -> None:
        self.wifi_fs_box.setVisible(mode == "full_stack")

    # ---------------------------------------------------------- bluetooth
    def _build_bt_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.bt_enabled = QCheckBox("Enable Bluetooth FCT")
        lay.addWidget(self.bt_enabled)
        form = QFormLayout()
        self.bt_mode = QComboBox()
        self.bt_mode.addItems(list(BT_MODES))
        form.addRow("Mode:", self.bt_mode)
        self.bt_name = QLineEdit()
        form.addRow("Expected name:", self.bt_name)
        self.bt_rssi_min = QSpinBox()
        self.bt_rssi_min.setRange(-100, 0)
        self.bt_rssi_min.setValue(-70)
        form.addRow("RSSI min (dBm):", self.bt_rssi_min)
        self.bt_audio_confirm = QCheckBox(
            "GUI_CONFIRM on a2dp_sink (operator hears the tone)")
        form.addRow(self.bt_audio_confirm)
        self.bt_l2ping = QSpinBox()
        self.bt_l2ping.setRange(0, 100)
        self.bt_l2ping.setValue(10)
        self.bt_l2ping.setToolTip(
            "L2CAP ping DUT -> host PC (data-transfer proof); 0 = off")
        form.addRow("L2CAP ping count:", self.bt_l2ping)
        lay.addLayout(form)
        lay.addStretch(1)
        return w

    # ------------------------------------------------------- helpers
    def _row_to_console_command(self, r: int) -> ConsoleCommand:
        """Convert one cmd_table row to a ConsoleCommand.
        SendTo column encodes sftp ops as '[PUT] local -> remote' /
        '[GET] remote -> local'."""
        name = self.cmd_table.item(r, 0).text() if self.cmd_table.item(r, 0) else ""
        transport = self.cmd_table.cellWidget(r, 1).currentText()
        waitfor = self.cmd_table.item(r, 2).text() if self.cmd_table.item(r, 2) else ""
        sendto = self.cmd_table.item(r, 3).text() if self.cmd_table.item(r, 3) else ""
        capture = self.cmd_table.item(r, 4).text() if self.cmd_table.item(r, 4) else ""
        retries = 1 if self.cmd_table.cellWidget(r, 6).currentText() == "yes" else 0

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
                self.cmd_table.setItem(r, 2, QTableWidgetItem(cmd.expect_pass))
                # SendTo: encode sftp ops as [PUT]/[GET]
                if cmd.kind == "sftp_put":
                    sendto_text = f"[PUT] {cmd.local} -> {cmd.remote}"
                elif cmd.kind == "sftp_get":
                    sendto_text = f"[GET] {cmd.remote} -> {cmd.local}"
                else:
                    sendto_text = cmd.send
                self.cmd_table.setItem(r, 3, QTableWidgetItem(sendto_text))
                # Capture
                self.cmd_table.setItem(r, 4, QTableWidgetItem(cmd.expect_fail))
                # Timeout (shows all 3: wait/send/capture; editable in dialogs)
                timeout_text = f"W:{int(cmd.wait_timeout)}s S:{int(cmd.send_timeout)}s C:{int(cmd.timeout)}s"
                self.cmd_table.setItem(r, 5, QTableWidgetItem(timeout_text))
                # Retry = dropdown
                rb = QComboBox()
                rb.addItems(["no", "yes"])
                rb.setCurrentText("yes" if cmd.retries > 0 else "no")
                self.cmd_table.setCellWidget(r, 6, rb)
            w = cfg.wifi
            self.wifi_enabled.setChecked(w.enabled)
            self.wifi_mode.setCurrentText(w.mode)
            self.wifi_interface.setText(w.interface)
            self.wifi_driver_cmd.setText(w.driver_load_cmd)
            self.wifi_rssi_min.setValue(w.rssi_min)
            self.wifi_ssid.setText(w.ssid)
            self.wifi_password.setText(w.password)
            self.wifi_gateway.setText(w.gateway)
            self.wifi_ping_count.setValue(w.ping_count)
            self.wifi_loss_max.setValue(w.loss_max)
            self.bw_enabled.setChecked(w.bandwidth.enabled)
            self.bw_tool.setCurrentText(w.bandwidth.tool)
            self.bw_server_ip.setText(w.bandwidth.server_ip)
            self.bw_min_mbps.setValue(w.bandwidth.min_mbps)
            self.wifi_fs_box.setVisible(w.mode == "full_stack")
            b = cfg.bluetooth
            self.bt_enabled.setChecked(b.enabled)
            self.bt_mode.setCurrentText(b.mode)
            self.bt_name.setText(b.expected_name)
            self.bt_rssi_min.setValue(b.rssi_min)
            self.bt_audio_confirm.setChecked(b.audio_confirm)
            self.bt_l2ping.setValue(b.l2ping_count)
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
            BandwidthCfg,
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
                self._row_to_console_command(r)
                for r in range(self.cmd_table.rowCount())],
        )
        cfg.wifi = WifiCfg(
            enabled=self.wifi_enabled.isChecked(),
            mode=self.wifi_mode.currentText(),
            interface=self.wifi_interface.text().strip(),
            driver_load_cmd=self.wifi_driver_cmd.text().strip(),
            rssi_min=self.wifi_rssi_min.value(),
            ssid=self.wifi_ssid.text(),
            password=self.wifi_password.text(),
            gateway=self.wifi_gateway.text().strip(),
            ping_count=self.wifi_ping_count.value(),
            loss_max=self.wifi_loss_max.value(),
            bandwidth=BandwidthCfg(
                enabled=self.bw_enabled.isChecked(),
                tool=self.bw_tool.currentText(),
                server_ip=self.bw_server_ip.text().strip(),
                min_mbps=self.bw_min_mbps.value()),
        )
        cfg.bluetooth = BluetoothCfg(
            enabled=self.bt_enabled.isChecked(),
            mode=self.bt_mode.currentText(),
            expected_name=self.bt_name.text().strip(),
            rssi_min=self.bt_rssi_min.value(),
            audio_confirm=self.bt_audio_confirm.isChecked(),
            l2ping_count=self.bt_l2ping.value(),
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
