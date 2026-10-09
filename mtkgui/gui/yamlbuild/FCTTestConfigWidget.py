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
            ["#", "Name", "Console", "WaitFor (regex)", "SendTo",
             "Capture (regex)", "Retry"])
        self.cmd_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        lay.addWidget(self.cmd_table)
        lay.addLayout(self._row_buttons(self.cmd_table, 7))
        return w

    @staticmethod
    def _row_buttons(table: QTableWidget, width: int) -> QHBoxLayout:
        row = QHBoxLayout()
        add = QPushButton("Add row")

        def _add():
            table.setRowCount(table.rowCount() + 1)
            for col in range(width):
                if table.item(table.rowCount() - 1, col) is None:
                    table.setItem(table.rowCount() - 1, col,
                                  QTableWidgetItem(""))

        add.clicked.connect(_add)
        remove = QPushButton("Remove selected")
        remove.clicked.connect(
            lambda: table.removeRow(table.currentRow()))
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        return row

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
                for col, val in enumerate((cmd.name, cmd.send,
                                           cmd.expect_pass,
                                           cmd.expect_fail,
                                           str(cmd.timeout),
                                           str(cmd.retries))):
                    self.cmd_table.setItem(r, col,
                                           QTableWidgetItem(val))
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
                ConsoleCommand(
                    name=row[0], send=row[1], expect_pass=row[2],
                    expect_fail=row[3],
                    timeout=float(row[4] or 5),
                    retries=int(row[5] or 0))
                for row in self._table_lines(self.cmd_table, 6)],
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
