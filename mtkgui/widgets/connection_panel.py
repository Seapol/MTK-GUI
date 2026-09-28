# -*- coding: utf-8 -*-
"""Serial port connection panel.

One panel per physical port. It collects the serial settings and emits
``connect_requested`` / ``disconnect_requested``; it does not open the
port itself.
"""

from serial.tools import list_ports
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
)

from ..serial_params import (
    BAUDRATES,
    BYTESIZE_MAP,
    PARITY_MAP,
    STOPBITS_MAP,
)


class ConnectionPanel(QGroupBox):
    connect_requested = Signal(str, dict)   # role key, serial parameters
    disconnect_requested = Signal(str)      # role key

    def __init__(self, role_key, title, parent=None):
        super().__init__(title, parent)
        self.role_key = role_key

        grid = QGridLayout(self)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        # Row 0: port + refresh
        grid.addWidget(QLabel("Port:"), 0, 0)
        self.combo_port = QComboBox()
        self.combo_port.setMinimumWidth(170)
        grid.addWidget(self.combo_port, 0, 1, 1, 2)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setObjectName("flat")
        self.btn_refresh.clicked.connect(self.refresh_ports)
        grid.addWidget(self.btn_refresh, 0, 3)

        # Row 1: baud + data bits
        grid.addWidget(QLabel("Baud:"), 1, 0)
        self.combo_baud = QComboBox()
        self.combo_baud.setEditable(True)
        self.combo_baud.addItems(BAUDRATES)
        self.combo_baud.setCurrentText("115200")
        grid.addWidget(self.combo_baud, 1, 1)
        grid.addWidget(QLabel("Data:"), 1, 2)
        self.combo_data = QComboBox()
        self.combo_data.addItems(list(BYTESIZE_MAP))
        self.combo_data.setCurrentText("8")
        grid.addWidget(self.combo_data, 1, 3)

        # Row 2: parity + stop bits
        grid.addWidget(QLabel("Parity:"), 2, 0)
        self.combo_parity = QComboBox()
        self.combo_parity.addItems(list(PARITY_MAP))
        grid.addWidget(self.combo_parity, 2, 1)
        grid.addWidget(QLabel("Stop:"), 2, 2)
        self.combo_stop = QComboBox()
        self.combo_stop.addItems(list(STOPBITS_MAP))
        self.combo_stop.setCurrentText("1")
        grid.addWidget(self.combo_stop, 2, 3)

        # Row 3: flow control + connect
        self.check_flow = QCheckBox("HW flow control")
        grid.addWidget(self.check_flow, 3, 0, 1, 2)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self._on_button_clicked)
        grid.addWidget(self.btn_connect, 3, 2, 1, 2)

        self.refresh_ports()

    # ------------------------------------------------------------ ports
    def refresh_ports(self):
        self.combo_port.clear()
        ports = list_ports.comports()
        for p in ports:
            self.combo_port.addItem(f"{p.device}  -  {p.description}", p.device)
        if not ports:
            self.combo_port.addItem("(no serial device found)", None)

    def selected_device(self):
        return self.combo_port.currentData()

    def current_params(self):
        return {
            "port": self.combo_port.currentData(),
            "baudrate": int(self.combo_baud.currentText()),
            "bytesize": BYTESIZE_MAP[self.combo_data.currentText()],
            "parity": PARITY_MAP[self.combo_parity.currentText()],
            "stopbits": STOPBITS_MAP[self.combo_stop.currentText()],
            "flow_control": self.check_flow.isChecked(),
        }

    # ------------------------------------------------------------ events
    def _on_button_clicked(self):
        if self.btn_connect.text() == "Connect":
            if not self.selected_device():
                return  # main window shows the warning
            self.connect_requested.emit(self.role_key, self.current_params())
        else:
            self.disconnect_requested.emit(self.role_key)

    def set_connected(self, connected):
        self.btn_connect.setText("Disconnect" if connected else "Connect")
        self.btn_connect.setObjectName("danger" if connected else "")
        self.btn_connect.style().unpolish(self.btn_connect)
        self.btn_connect.style().polish(self.btn_connect)
        for w in (self.combo_port, self.btn_refresh, self.combo_baud,
                  self.combo_data, self.combo_parity, self.combo_stop,
                  self.check_flow):
            w.setEnabled(not connected)
