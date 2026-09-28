# -*- coding: utf-8 -*-
"""Multi-channel serial / SSH console.

Used on the Test Work Flow page, next to the FCT table:

* 1-4 serial channels and 0-1 SSH channel, each shown as a compact row
* per-channel accent colors identify the channels at a glance
* Add Serial / Add SSH / Remove live in the top bar; each row has its
  own Open/Close, Show Console, Configure (advanced params) and Remove
* a per-channel popup ConsoleWindow hosts the ConsoleWidget, a Quick
  Commands dropdown and a Send line (HEX / CR+LF, Enter or Send)
* closing a popup only hides it; the ConsoleWidget keeps receiving data
* RX / TX byte counters are shown per row
* a Quick Commands dropdown copies saved snippets into the Send line;
  the current line can be saved as a new snippet (max 15)
"""

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)
from serial.tools import list_ports

from ..at_commands import AT_COMMANDS
from ..quick_commands import MAX_QUICK_COMMANDS, load_commands, save_commands
from ..serial_params import BAUDRATES, BYTESIZE_MAP, STOPBITS_MAP, PARITY_MAP
from ..serial_worker import SerialWorker
from ..ssh_worker import SshWorker
from ..theme import (
    DEFAULT_BACKGROUND,
    THEMES,
    is_dark,
    theme_for,
)
from .console_widget import ConsoleWidget
from .send_panel import SendPanel

MAX_SERIAL = 4
SERIAL_COLORS = ["#33d17a", "#f9f06b", "#ffa348", "#ff7b63"]
SSH_COLOR = "#62a0ea"

DEFAULT_SERIAL_PARAMS = {
    "port": None, "baudrate": 115200, "bytesize_key": "8",
    "parity_key": "None", "stopbits_key": "1", "flow_control": False,
}
DEFAULT_SSH_PARAMS = {
    "host": "", "port": 22, "username": "", "password": "",
}


class SerialConfigDialog(QDialog):
    """Serial connection parameters for one channel."""

    def __init__(self, parent, params=None):
        super().__init__(parent)
        self.setWindowTitle("Serial Connection Settings")
        params = dict(DEFAULT_SERIAL_PARAMS)
        if params is not None:
            params.update(params or {})

        form = QFormLayout(self)

        self.combo_port = QComboBox()
        self.combo_port.setEditable(True)
        for p in list_ports.comports():
            self.combo_port.addItem(f"{p.device}  -  {p.description}",
                                    p.device)
        if params.get("port"):
            self.combo_port.setCurrentText(str(params["port"]))
        btn_refresh = QPushButton("Refresh")
        btn_refresh.setObjectName("flat")
        btn_refresh.clicked.connect(self._refresh_ports)
        port_row = QHBoxLayout()
        port_row.setContentsMargins(0, 0, 0, 0)
        port_row.addWidget(self.combo_port, 1)
        port_row.addWidget(btn_refresh)
        port_host = QWidget()
        port_host.setLayout(port_row)
        form.addRow("Port:", port_host)

        self.combo_baud = QComboBox()
        self.combo_baud.setEditable(True)
        self.combo_baud.addItems(BAUDRATES)
        self.combo_baud.setCurrentText(str(params["baudrate"]))
        form.addRow("Baud:", self.combo_baud)

        self.combo_data = QComboBox()
        self.combo_data.addItems(list(BYTESIZE_MAP))
        self.combo_data.setCurrentText(params["bytesize_key"])
        form.addRow("Data bits:", self.combo_data)

        self.combo_parity = QComboBox()
        self.combo_parity.addItems(list(PARITY_MAP))
        self.combo_parity.setCurrentText(params["parity_key"])
        form.addRow("Parity:", self.combo_parity)

        self.combo_stop = QComboBox()
        self.combo_stop.addItems(list(STOPBITS_MAP))
        self.combo_stop.setCurrentText(params["stopbits_key"])
        form.addRow("Stop bits:", self.combo_stop)

        self.check_flow = QCheckBox("HW flow control (RTS/CTS)")
        self.check_flow.setChecked(bool(params["flow_control"]))
        form.addRow("", self.check_flow)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _refresh_ports(self):
        current = self.get_params().get("port")
        self.combo_port.clear()
        for p in list_ports.comports():
            self.combo_port.addItem(f"{p.device}  -  {p.description}",
                                    p.device)
        if current:
            self.combo_port.setCurrentText(str(current))

    def get_params(self):
        port = self.combo_port.currentData()
        if not port:
            port = self.combo_port.currentText().strip() or None
        try:
            baud = int(self.combo_baud.currentText())
        except ValueError:
            baud = 115200
        return {
            "port": port,
            "baudrate": baud,
            "bytesize_key": self.combo_data.currentText(),
            "parity_key": self.combo_parity.currentText(),
            "stopbits_key": self.combo_stop.currentText(),
            "flow_control": self.check_flow.isChecked(),
        }


class SshConfigDialog(QDialog):
    """SSH shell parameters for the (single, optional) SSH channel."""

    def __init__(self, parent, params=None):
        super().__init__(parent)
        self.setWindowTitle("SSH Connection Settings")
        params = dict(DEFAULT_SSH_PARAMS)
        params.update(params or {})

        form = QFormLayout(self)
        self.edit_host = QLineEdit(params["host"])
        self.edit_host.setPlaceholderText("192.168.1.10")
        form.addRow("Host:", self.edit_host)

        self.edit_port = QLineEdit(str(params["port"] or 22))
        form.addRow("Port:", self.edit_port)

        self.edit_user = QLineEdit(params["username"])
        self.edit_user.setPlaceholderText("root")
        form.addRow("User:", self.edit_user)

        self.edit_password = QLineEdit(params["password"])
        self.edit_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self.edit_password)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def get_params(self):
        try:
            port = int(self.edit_port.text().strip() or "22")
        except ValueError:
            port = 22
        return {
            "host": self.edit_host.text().strip(),
            "port": port,
            "username": self.edit_user.text().strip(),
            "password": self.edit_password.text(),
        }


class VirtualWorker(QThread):
    """Simulated channel used in Virtual mode.

    No real hardware is behind it: it reports the connection as
    established (with a small banner) and stays idle in its own event
    loop until stopped."""

    data_received = Signal(bytes)
    error_occurred = Signal(str)
    connection_changed = Signal(bool)

    def __init__(self, detail, parent=None):
        super().__init__(parent)
        self._detail = detail

    def run(self):
        self.connection_changed.emit(True)
        banner = (f"Virtual mode: simulated connection to {self._detail}"
                  "\r\n").encode()
        self.data_received.emit(banner)
        self.exec()  # idle in the thread's event loop until quit()
        self.connection_changed.emit(False)

    def stop(self):
        self.quit()
        self.wait(2000)


# ============================================================ popup window
class ConsoleWindow(QDialog):
    """Popup per-channel console: hosts the ConsoleWidget, a Quick
    Commands dropdown and a Send line. Closing the window only hides
    it; the ConsoleWidget keeps receiving data in the background."""

    send_requested = Signal(str, str, bool, bool)  # key, text, hex, crlf
    quick_commands_changed = Signal()

    def __init__(self, key, label, accent, console, theme, bg_color,
                 parent=None):
        super().__init__(parent)
        self.key = key
        self.label = label
        self.accent = accent
        self.theme = theme
        self.bg_color = bg_color
        self.console = console
        self.setWindowTitle(f"{label} Console")
        self.setMinimumSize(1200, 800)

        layout = QVBoxLayout(self)

        # Console widget (reparented into this dialog by Qt)
        layout.addWidget(console, 1)

        # Quick commands row
        quick_row = QHBoxLayout()
        quick_row.addWidget(QLabel("Quick:"))
        self.combo_quick = QComboBox()
        self.combo_quick.setToolTip(
            "Select a saved command to copy it into the Send line")
        quick_row.addWidget(self.combo_quick, 1)
        self.btn_save_cmd = QPushButton("Save Cmd")
        self.btn_save_cmd.setObjectName("flat")
        self.btn_save_cmd.setToolTip(
            "Save the current Send line as a quick command (max "
            f"{MAX_QUICK_COMMANDS})")
        self.btn_save_cmd.clicked.connect(self.save_current_quick)
        quick_row.addWidget(self.btn_save_cmd)
        self.btn_clear_cmd = QPushButton("Clear Cmd")
        self.btn_clear_cmd.setObjectName("flat")
        self.btn_clear_cmd.setToolTip(
            "Remove all saved quick commands")
        self.btn_clear_cmd.clicked.connect(self.clear_all_quick)
        quick_row.addWidget(self.btn_clear_cmd)
        layout.addLayout(quick_row)

        # Send panel
        self.send_panel = SendPanel(key, "Send")
        self.send_panel.send_requested.connect(
            lambda k, text, hex_mode, crlf:
                self.send_requested.emit(k, text, hex_mode, crlf))
        layout.addWidget(self.send_panel)

        self.quick_entries = load_commands()
        self._reload_quick_combo()
        self.combo_quick.activated.connect(self._on_quick_picked)
        self._refresh_completion_candidates()

    # --------------------------------------------------------- close=hide
    def closeEvent(self, event):
        event.ignore()
        self.hide()

    # ---------------------------------------------------------- background
    def set_background(self, color):
        if isinstance(color, QColor):
            color = color.name()
        self.bg_color = color
        self.theme = THEMES[theme_for(color)]
        self.console.set_background(color)

    # --------------------------------------------------------- quick cmds
    def reload_quick_combo(self):
        """Reload entries from disk and repopulate the combo (called
        when another window saved or cleared quick commands)."""
        self.quick_entries = load_commands()
        self._reload_quick_combo()
        self._refresh_completion_candidates()

    def _reload_quick_combo(self):
        self.combo_quick.blockSignals(True)
        self.combo_quick.clear()
        self.combo_quick.addItem("Quick Commands\u2026", None)
        for entry in self.quick_entries:
            label = entry["label"]
            shown = label if len(label) <= 24 else label[:21] + "..."
            self.combo_quick.addItem(shown, entry)
        self.combo_quick.setCurrentIndex(0)
        self.combo_quick.blockSignals(False)
        self.btn_save_cmd.setEnabled(
            len(self.quick_entries) < MAX_QUICK_COMMANDS)

    def _refresh_completion_candidates(self):
        """Feed quick commands + AT commands into the Send-line Tab
        completer (history is added by the line edit itself)."""
        candidates = []
        for entry in self.quick_entries:
            cmd = entry.get("command", "")
            if cmd:
                candidates.append(cmd)
        for _label, cmd, _desc in AT_COMMANDS:
            if cmd and cmd not in candidates:
                candidates.append(cmd)
        self.send_panel.edit.set_extra_candidates(candidates)

    def _on_quick_picked(self, index):
        entry = self.combo_quick.itemData(index)
        if not entry:
            return
        # copy the saved command into the Send line (sent on Enter/Send)
        self.send_panel.set_text(entry["command"])
        self.send_panel.check_crlf.setChecked(bool(entry.get("crlf", True)))
        self.send_panel.check_hex.setChecked(False)
        self.send_panel.edit.setFocus()
        self.combo_quick.setCurrentIndex(0)

    def save_current_quick(self):
        """Add the current Send line text to the quick command list."""
        command = self.send_panel.edit.text().strip()
        if not command:
            return
        crlf = self.send_panel.check_crlf.isChecked()
        entry = {"label": command, "command": command, "crlf": crlf}

        # update an identical command instead of duplicating it
        for existing in self.quick_entries:
            if existing["command"] == command:
                existing["crlf"] = crlf
                break
        else:
            if len(self.quick_entries) >= MAX_QUICK_COMMANDS:
                QMessageBox.information(
                    self, "Quick Commands",
                    f"Quick command limit reached ({MAX_QUICK_COMMANDS}). "
                    "Remove unused entries by editing config/commands.json.")
                return
            self.quick_entries.append(entry)

        try:
            self.quick_entries = save_commands(self.quick_entries)
        except OSError as exc:
            QMessageBox.critical(
                self, "Quick Commands", f"Failed to save: {exc}")
            return
        self._reload_quick_combo()
        self._refresh_completion_candidates()
        self.console.append_message(
            "SYS", f"Quick command saved: {command}",
            color=self.theme["sys"])
        # tell sibling windows to reload
        self.quick_commands_changed.emit()

    def clear_all_quick(self):
        """Remove every saved quick command (persist the empty list)."""
        if not self.quick_entries:
            return
        try:
            self.quick_entries = save_commands([])
        except OSError as exc:
            QMessageBox.critical(
                self, "Quick Commands", f"Failed to save: {exc}")
            return
        self._reload_quick_combo()
        self._refresh_completion_candidates()
        self.console.append_message(
            "SYS", "All quick commands cleared", color=self.theme["sys"])
        # tell sibling windows to reload
        self.quick_commands_changed.emit()


# ============================================================ compact row
class ChannelRow(QFrame):
    """Compact inline row for one channel: colored label, inline
    connection fields, Open/Close, Show Console, Configure, Remove
    buttons, and RX/TX counters."""

    open_requested = Signal(str)
    close_requested = Signal(str)
    show_console_requested = Signal(str)
    config_requested = Signal(str)
    remove_requested = Signal(str)
    params_changed = Signal(str)

    def __init__(self, key, kind, label, accent, params, parent=None):
        super().__init__(parent)
        self.key = key
        self.kind = kind
        self.label_text = label
        self.accent = accent
        self.setObjectName("channel_row")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setLineWidth(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self.label = QLabel(label)
        self.label.setMinimumWidth(48)
        self.set_accent(accent)
        layout.addWidget(self.label)

        if kind == "serial":
            self.combo_port = QComboBox()
            self.combo_port.setEditable(True)
            self.combo_port.setToolTip("Serial port device")
            for p in list_ports.comports():
                self.combo_port.addItem(
                    f"{p.device}  -  {p.description}", p.device)
            layout.addWidget(self.combo_port, 1)

            self.combo_baud = QComboBox()
            self.combo_baud.setEditable(True)
            self.combo_baud.addItems(BAUDRATES)
            self.combo_baud.setMaximumWidth(100)
            layout.addWidget(self.combo_baud)
        else:
            self.edit_host = QLineEdit()
            self.edit_host.setPlaceholderText("192.168.1.10")
            layout.addWidget(self.edit_host, 1)

            self.spin_port = QSpinBox()
            self.spin_port.setRange(1, 65535)
            self.spin_port.setValue(22)
            self.spin_port.setMaximumWidth(80)
            layout.addWidget(self.spin_port)

            self.edit_user = QLineEdit()
            self.edit_user.setPlaceholderText("root")
            self.edit_user.setMaximumWidth(120)
            layout.addWidget(self.edit_user)

        self.btn_open = QPushButton("Open")
        self.btn_open.clicked.connect(self._on_open_clicked)
        layout.addWidget(self.btn_open)

        self.btn_console = QPushButton("Show Console")
        self.btn_console.clicked.connect(
            lambda: self.show_console_requested.emit(self.key))
        layout.addWidget(self.btn_console)

        self.btn_config = QPushButton("\u2699")
        self.btn_config.setMaximumWidth(32)
        self.btn_config.setToolTip("Advanced parameters")
        self.btn_config.clicked.connect(
            lambda: self.config_requested.emit(self.key))
        layout.addWidget(self.btn_config)

        self.btn_remove = QPushButton("\u00d7")
        self.btn_remove.setMaximumWidth(32)
        self.btn_remove.setToolTip("Remove this channel")
        self.btn_remove.clicked.connect(
            lambda: self.remove_requested.emit(self.key))
        layout.addWidget(self.btn_remove)

        self.label_counts = QLabel("RX: 0  TX: 0")
        self.label_counts.setObjectName("strong")
        layout.addWidget(self.label_counts)

        if params:
            self.update_params(params)

        self._wire_params_changed()

    # ----------------------------------------------------- inline params
    def _wire_params_changed(self):
        if self.kind == "serial":
            self.combo_port.currentTextChanged.connect(
                lambda _: self.params_changed.emit(self.key))
            self.combo_baud.currentTextChanged.connect(
                lambda _: self.params_changed.emit(self.key))
        else:
            self.edit_host.textChanged.connect(
                lambda: self.params_changed.emit(self.key))
            self.spin_port.valueChanged.connect(
                lambda: self.params_changed.emit(self.key))
            self.edit_user.textChanged.connect(
                lambda: self.params_changed.emit(self.key))

    def update_params(self, params):
        """Sync inline fields from a params dict (does not re-emit
        params_changed)."""
        if self.kind == "serial":
            self.combo_port.blockSignals(True)
            self.combo_baud.blockSignals(True)
            port = params.get("port")
            if port:
                self.combo_port.setCurrentText(str(port))
            baud = params.get("baudrate")
            if baud is not None:
                self.combo_baud.setCurrentText(str(baud))
            self.combo_port.blockSignals(False)
            self.combo_baud.blockSignals(False)
        else:
            self.edit_host.blockSignals(True)
            self.spin_port.blockSignals(True)
            self.edit_user.blockSignals(True)
            host = params.get("host")
            if host is not None:
                self.edit_host.setText(str(host))
            port = params.get("port")
            if port is not None:
                self.spin_port.setValue(int(port) or 22)
            user = params.get("username")
            if user is not None:
                self.edit_user.setText(str(user))
            self.edit_host.blockSignals(False)
            self.spin_port.blockSignals(False)
            self.edit_user.blockSignals(False)

    def get_inline_params(self):
        """Read inline fields, return partial params dict."""
        if self.kind == "serial":
            text = self.combo_port.currentText().strip()
            idx = self.combo_port.currentIndex()
            port = None
            # currentData is only valid when currentText matches the
            # current item's display text (user picked from dropdown);
            # otherwise the user (or a programmatic set) typed a custom
            # string into the editable line edit.
            if (idx >= 0 and text
                    and text == self.combo_port.itemText(idx).strip()):
                port = self.combo_port.currentData()
            if not port:
                port = text or None
            try:
                baud = int(self.combo_baud.currentText())
            except ValueError:
                baud = 115200
            return {"port": port, "baudrate": baud}
        return {
            "host": self.edit_host.text().strip(),
            "port": self.spin_port.value(),
            "username": self.edit_user.text().strip(),
        }

    # ----------------------------------------------------------- buttons
    def _on_open_clicked(self):
        if self.btn_open.text() == "Open":
            self.open_requested.emit(self.key)
        else:
            self.close_requested.emit(self.key)

    def set_connected(self, connected):
        """Update btn_open text/style for the connected state."""
        self.btn_open.setText("Close" if connected else "Open")
        self.btn_open.setObjectName("danger" if connected else "")
        self.btn_open.style().unpolish(self.btn_open)
        self.btn_open.style().polish(self.btn_open)

    def update_counts(self, tx, rx):
        self.label_counts.setText(f"RX: {rx}  TX: {tx}")

    def set_accent(self, color):
        self.accent = color
        # badge style: accent background + a text color that always
        # reads clearly on it (bright accents like yellow get dark text,
        # dark accents get white text)
        text = "#ffffff" if is_dark(color) else "#1c2430"
        self.label.setStyleSheet(
            f"background: {color}; color: {text}; font-weight: bold;"
            " border-radius: 4px; padding: 2px 8px;")

    # ------------------------------------------------------- permissions
    def apply_permissions(self, can_manage, can_configure):
        self.btn_remove.setEnabled(can_manage)
        self.btn_config.setEnabled(can_configure)
        if self.kind == "serial":
            self.combo_port.setEnabled(can_configure)
            self.combo_baud.setEnabled(can_configure)
        else:
            self.edit_host.setReadOnly(not can_configure)
            self.spin_port.setReadOnly(not can_configure)
            self.edit_user.setReadOnly(not can_configure)
        # operators can still open/close and view the console
        self.btn_open.setEnabled(True)
        self.btn_console.setEnabled(True)


# =========================================================== container
class MultiConsoleWidget(QGroupBox):
    """Compact 1-4 x serial + 0-1 x SSH console container. Each
    channel is a ChannelRow inline; the full ConsoleWidget lives in
    a popup ConsoleWindow hidden until 'Show Console' is clicked."""

    # emitted whenever a channel is added / removed / connected / dropped
    connection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Serial Console", parent)
        self.bg_color = DEFAULT_BACKGROUND
        self.theme = THEMES[theme_for(self.bg_color)]

        # key -> {"kind", "label", "accent", "console", "console_window",
        #         "row", "params", "worker", "stats", "read_buffer"}
        self.channels = {}
        self._serial_numbers = []
        self._ssh_open = False
        # account permissions (defaults = supervisor until apply_permissions)
        self._supervisor = True
        self._perm = {}
        self.virtual_mode = False
        # keys of the channels defined by the loaded YAML "console"
        # section (None = no console section loaded)
        self._yaml_channel_keys = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # --------------------------------------------------- top tool bar
        bar = QHBoxLayout()
        self.btn_add_serial = QPushButton("Add Serial")
        self.btn_add_serial.setObjectName("flat")
        self.btn_add_serial.clicked.connect(self.add_serial)
        self.btn_add_ssh = QPushButton("Add SSH")
        self.btn_add_ssh.setObjectName("flat")
        self.btn_add_ssh.clicked.connect(self.add_ssh)
        # top-level Remove kept for backward compat (removes last channel)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setObjectName("flat")
        self.btn_remove.clicked.connect(self.remove_current)
        bar.addWidget(self.btn_add_serial)
        bar.addWidget(self.btn_add_ssh)
        bar.addWidget(self.btn_remove)
        bar.addStretch(1)
        layout.addLayout(bar)

        # ------------------------------------------- scrollable channel rows
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_content = QWidget()
        self.rows_layout = QVBoxLayout(self.scroll_content)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(4)
        self.rows_layout.addStretch(1)  # rows packed at the top
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll, 1)

        # one serial channel always exists
        self.add_serial()

    # ------------------------------------------------------- permissions
    def apply_permissions(self, perm, supervisor):
        """Operator role: Open / Close (connect-disconnect) stays allowed;
        adding / removing channels and parameter dialogs follow the keys."""
        self._supervisor = supervisor
        self._perm = dict(perm)
        self._refresh_actions()
        can_manage = self._can_manage_channels()
        can_configure = self._can_configure()
        for channel in self.channels.values():
            channel["row"].apply_permissions(can_manage, can_configure)

    def _can_manage_channels(self):
        return self._supervisor or bool(self._perm.get("manage_channels"))

    def _can_configure(self):
        return self._supervisor or bool(self._perm.get("edit_serial_params"))

    def set_virtual_mode(self, enabled):
        """Virtual mode: Open simulates the connection (no real HW)."""
        self.virtual_mode = bool(enabled)

    # ---------------------------------------------------------- channels
    def _next_serial_number(self):
        for n in range(1, MAX_SERIAL + 1):
            if n not in self._serial_numbers:
                return n
        return None

    def add_serial(self):
        """Add a serial channel row (max 4). Returns its key."""
        n = self._next_serial_number()
        if n is None:
            return None
        key = f"ser{n}"
        self._serial_numbers.append(n)
        accent = SERIAL_COLORS[n - 1]
        label = f"SER{n}"
        self._create_channel(key, "serial", label, accent,
                             dict(DEFAULT_SERIAL_PARAMS))
        return key

    def add_ssh(self):
        """Add the single optional SSH channel row. Returns its key."""
        if self._ssh_open:
            return None
        key = "ssh1"
        self._ssh_open = True
        self._create_channel(key, "ssh", "SSH1", SSH_COLOR,
                             dict(DEFAULT_SSH_PARAMS))
        return key

    def _create_channel(self, key, kind, label, accent, params):
        console = ConsoleWidget(key, f"{label} Console", f"{key}_log")
        console.set_accent(accent)
        console.set_background(self.bg_color)
        console.doubleClicked.connect(
            lambda k=key: self.configure_channel(k))

        console_window = ConsoleWindow(
            key, label, accent, console, self.theme, self.bg_color,
            parent=self)
        console_window.send_requested.connect(self.handle_send)
        console_window.quick_commands_changed.connect(
            self._on_quick_commands_changed)

        row = ChannelRow(key, kind, label, accent, params, parent=self)
        row.open_requested.connect(self.open_channel)
        row.close_requested.connect(self.close_channel)
        row.show_console_requested.connect(self._show_console)
        row.config_requested.connect(self.configure_channel)
        row.remove_requested.connect(self.remove_channel)
        row.params_changed.connect(self._on_row_params_changed)
        row.apply_permissions(self._can_manage_channels(),
                              self._can_configure())

        channel = {
            "kind": kind,
            "label": label,
            "accent": accent,
            "console": console,
            "console_window": console_window,
            "row": row,
            "params": params,
            "worker": None,
            "connected": False,
            "stats": [0, 0],  # [tx, rx]
            "read_buffer": bytearray(),
        }
        self.channels[key] = channel

        # insert the row before the trailing stretch
        self.rows_layout.insertWidget(
            self.rows_layout.count() - 1, row)

        console.append_message(
            "SYS",
            f"{label} ready. Click \u2699 to configure "
            + ("serial parameters." if kind == "serial"
               else "SSH parameters."),
            color=self.theme["sys"])
        self._refresh_actions()
        self.connection_changed.emit()

    def remove_channel(self, key):
        """Close and remove a channel row (can remove all)."""
        channel = self.channels.get(key)
        if not channel:
            return
        if channel["worker"] and channel["worker"].isRunning():
            channel["worker"].stop()
        channel["console_window"].hide()
        row = channel["row"]
        self.rows_layout.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        if channel["kind"] == "ssh":
            self._ssh_open = False
        else:
            n = int(key[3:])
            if n in self._serial_numbers:
                self._serial_numbers.remove(n)
        del self.channels[key]
        self._refresh_actions()
        self.connection_changed.emit()

    def remove_current(self):
        """Remove the last channel (backward compat)."""
        key = self.current_key()
        if key is None:
            return
        self.remove_channel(key)

    def _refresh_actions(self):
        can_manage = self._can_manage_channels()
        serial_count = len(self._serial_numbers)
        self.btn_add_serial.setEnabled(
            can_manage and serial_count < MAX_SERIAL)
        self.btn_add_ssh.setEnabled(can_manage and not self._ssh_open)
        self.btn_remove.setEnabled(can_manage and len(self.channels) > 0)

    def current_key(self):
        """Key of the last channel in insertion order (backward compat)."""
        keys = list(self.channels.keys())
        return keys[-1] if keys else None

    def console(self, key):
        return self.channels[key]["console"]

    def _endpoint(self, channel):
        p = channel["params"]
        if channel["kind"] == "serial":
            return p.get("port") or ""
        return p.get("host") or ""

    # ------------------------------------------------------ configuration
    def configure_channel(self, key):
        """Open the advanced parameters dialog for one channel
        (row \u2699 button or a double-click inside the ConsoleWidget)."""
        if not self._can_configure():
            QMessageBox.information(
                self, "Permission",
                "Operator account cannot change channel parameters.\n"
                "Ask the supervisor to grant this permission.")
            return
        channel = self.channels[key]
        if channel["kind"] == "serial":
            dlg = SerialConfigDialog(self, channel["params"])
        else:
            dlg = SshConfigDialog(self, channel["params"])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.set_channel_params(key, dlg.get_params())
        running = bool(channel["worker"] and channel["worker"].isRunning())
        note = "applied on next Open" if running else "Open to connect"
        channel["console"].append_message(
            "SYS",
            f"Settings updated ({note}): {self._endpoint(channel)}",
            color=self.theme["sys"])

    def set_channel_params(self, key, params):
        """Programmatic parameter set (used by tests / config loading).
        Also syncs the row's inline fields."""
        channel = self.channels[key]
        merged = dict(channel["params"])
        merged.update(params or {})
        channel["params"] = merged
        channel["row"].update_params(merged)

    def _on_row_params_changed(self, key):
        """An inline field in the row changed: merge into channel params."""
        if not self._can_configure():
            return
        row = self.channels[key]["row"]
        partial = row.get_inline_params()
        self.channels[key]["params"].update(partial)

    # ------------------------------------------------------- YAML channels
    def yaml_channels(self):
        """Every channel in row order -> the 'console' section of the
        project YAML (kind + connection parameters)."""
        entries = []
        for key, ch in self.channels.items():
            entries.append({"kind": ch["kind"],
                            "params": dict(ch["params"])})
        return entries

    def apply_yaml_channels(self, entries):
        """Apply the YAML 'console' section: reuse existing channels of
        the same kind in order (add the missing ones), update their
        parameters and remember the channel keys for the pre-FCT auto
        connect. Returns the YAML channel keys."""
        reuse = {"serial": [], "ssh": []}
        for key, ch in self.channels.items():
            reuse[ch["kind"]].append(key)
        keys = []
        si = ss = 0
        for entry in entries or []:
            kind = str(entry.get("kind", "serial"))
            key = None
            if kind == "serial":
                if si < len(reuse["serial"]):
                    key = reuse["serial"][si]
                si += 1
                key = key or self.add_serial()
            elif kind == "ssh":
                if ss < len(reuse["ssh"]):
                    key = reuse["ssh"][ss]
                ss += 1
                key = key or self.add_ssh()
            else:
                continue
            if not key:
                continue  # e.g. a 5th serial channel -> capacity cap
            self.set_channel_params(key, entry.get("params") or {})
            keys.append(key)
        self._yaml_channel_keys = keys
        return keys

    def yaml_channel_keys(self):
        """Keys of the channels defined by the loaded YAML 'console'
        section; None when no console section was loaded."""
        return (None if self._yaml_channel_keys is None
                else list(self._yaml_channel_keys))

    def channel_connected(self, key):
        """True when the channel has an established connection
        (connection_changed(True) received), not merely a worker
        thread that is still starting up / already failing."""
        ch = self.channels.get(key)
        return bool(ch and ch.get("connected"))

    def channel_endpoint(self, key):
        """Configured endpoint of a channel ('' when not configured)."""
        ch = self.channels.get(key)
        return self._endpoint(ch) if ch else ""

    # ------------------------------------------------------------ open/close
    def open_channel(self, key):
        channel = self.channels.get(key)
        if not channel:
            return
        if channel["worker"] and channel["worker"].isRunning():
            return

        # sync inline fields from the row into the params dict
        partial = channel["row"].get_inline_params()
        channel["params"].update(partial)

        # first time: make sure the endpoint is configured
        # (skipped in Virtual mode - no real endpoint is required)
        if not self.virtual_mode:
            if (channel["kind"] == "serial"
                    and not channel["params"].get("port")):
                self.configure_channel(key)
                if not channel["params"].get("port"):
                    return
            elif (channel["kind"] == "ssh"
                    and not channel["params"].get("host")):
                self.configure_channel(key)
                if not channel["params"].get("host"):
                    return

        if self.virtual_mode:
            # Virtual mode: simulated connection, no real hardware needed
            p = channel["params"]
            if channel["kind"] == "serial":
                detail = (f"{p.get('port') or 'virtual-serial'} "
                          f"@ {p.get('baudrate') or 115200}")
            else:
                detail = (f"{p.get('username') or 'user'}"
                          f"@{p.get('host') or 'virtual-host'}")
            worker = VirtualWorker(detail)
        elif channel["kind"] == "serial":
            p = channel["params"]
            try:
                worker = SerialWorker(
                    port=p["port"],
                    baudrate=p["baudrate"],
                    bytesize=BYTESIZE_MAP[p["bytesize_key"]],
                    parity=PARITY_MAP[p["parity_key"]],
                    stopbits=STOPBITS_MAP[p["stopbits_key"]],
                    flow_control=p["flow_control"],
                )
            except Exception as exc:
                channel["console"].append_message(
                    "SYS", f"Failed to create serial worker: {exc}",
                    color=self.theme["err"])
                return
        else:
            p = channel["params"]
            worker = SshWorker(
                host=p["host"], port=p["port"],
                username=p["username"], password=p["password"])

        worker.data_received.connect(
            lambda data, k=key: self.on_data(k, data))
        worker.error_occurred.connect(
            lambda msg, k=key: self._on_worker_error(k, msg))
        worker.connection_changed.connect(
            lambda ok, k=key: self.on_connection_changed(k, ok))
        channel["worker"] = worker
        worker.start()

    def _on_worker_error(self, key, msg):
        channel = self.channels.get(key)
        if channel is not None:
            channel["console"].append_message(
                "SYS", msg, color=self.theme["err"])

    def close_channel(self, key):
        channel = self.channels.get(key)
        if channel and channel["worker"]:
            channel["worker"].stop()

    def close_all_channels(self):
        """Disconnect every channel (called on application exit)."""
        for key in list(self.channels):
            self.close_channel(key)

    def on_connection_changed(self, key, connected):
        channel = self.channels.get(key)
        if channel is None:  # removed while a queued signal was in flight
            return
        channel["connected"] = bool(connected)
        if connected:
            p = channel["params"]
            if channel["kind"] == "serial":
                detail = f"{p['port']} @ {p['baudrate']}"
            else:
                detail = f"{p['username']}@{p['host']}:{p['port']}"
            channel["console"].append_message(
                "SYS", f"Connected {detail}", color=self.theme["sys"])
        else:
            channel["console"].append_message(
                "SYS", "Channel disconnected", color=self.theme["sys"])
        channel["row"].set_connected(connected)
        self.connection_changed.emit()

    # ------------------------------------------------------------ RX data
    def on_data(self, key, data):
        channel = self.channels.get(key)
        if channel is None:  # removed while a queued signal was in flight
            return
        channel["read_buffer"].extend(data)
        channel["stats"][1] += len(data)
        channel["row"].update_counts(channel["stats"][0],
                                     channel["stats"][1])
        console = channel["console"]
        if console.check_hex.isChecked():
            text = " ".join(f"{b:02X}" for b in data)
            console.append_message("RX", text, color=self.theme["rx"])
        else:
            console.append_rx("RX", data)

    # ------------------------------------------------------------ sending
    @staticmethod
    def encode_payload(text, hex_mode, crlf):
        if hex_mode:
            cleaned = (text.replace(" ", "").replace(",", "")
                           .replace("0x", "").replace("\n", ""))
            return bytes.fromhex(cleaned)
        payload = text.encode("utf-8")
        if crlf:
            payload += b"\r\n"
        return payload

    def handle_send(self, key, text, hex_mode, crlf):
        """Send a payload on a specific channel (key)."""
        try:
            payload = self.encode_payload(text, hex_mode, crlf)
        except ValueError:
            QMessageBox.warning(
                self, "Invalid HEX",
                'Invalid HEX input. Use a format such as "41 54 0D 0A".')
            return

        if hex_mode:
            shown = " ".join(f"{b:02X}" for b in payload)
        else:
            shown = text + ("\\r\\n" if crlf else "")
        self._write_to_channel(key, payload, shown)
        channel = self.channels.get(key)
        if (channel and channel["worker"]
                and channel["worker"].isRunning()):
            channel["console_window"].send_panel.commit_sent(text)

    def _write_to_channel(self, key, payload, shown):
        """Send a payload on a channel and show the TX line; updates
        per-row counters."""
        channel = self.channels[key]
        worker = channel["worker"]
        if not worker or not worker.isRunning():
            channel["console"].append_message(
                "SYS", "Channel not connected; data not sent.",
                color=self.theme["sys"])
            return
        n = worker.write(payload)
        if n >= 0:
            channel["stats"][0] += n
            channel["row"].update_counts(channel["stats"][0],
                                         channel["stats"][1])
            channel["console"].append_message(
                "TX", shown, color=self.theme["tx"])

    def write_to_channel(self, key, payload):
        """Programmatic write for FCT tests: silent (no shown text),
        updates stats only. No-op when the channel is offline."""
        channel = self.channels.get(key)
        if not channel:
            return
        worker = channel["worker"]
        if not worker or not worker.isRunning():
            return
        n = worker.write(payload)
        if n >= 0:
            channel["stats"][0] += n
            channel["row"].update_counts(channel["stats"][0],
                                         channel["stats"][1])

    # --------------------------------------------------------- read buffer
    def get_read_buffer(self, key):
        """Bytes accumulated on RX (for FCT console tests to search)."""
        channel = self.channels.get(key)
        return bytes(channel["read_buffer"]) if channel else b""

    def clear_read_buffer(self, key):
        channel = self.channels.get(key)
        if channel:
            channel["read_buffer"].clear()

    # ------------------------------------------------------- quick cmds
    def _on_quick_commands_changed(self):
        """One window saved or cleared a quick command: reload combos
        in all windows."""
        for channel in self.channels.values():
            channel["console_window"].reload_quick_combo()

    def _show_console(self, key):
        """Popup the per-channel ConsoleWindow."""
        channel = self.channels.get(key)
        if not channel:
            return
        win = channel["console_window"]
        win.show()
        win.raise_()
        win.activateWindow()

    # ------------------------------------------------------------ theme
    def set_background(self, color):
        """Set the background color (and matching theme) on every
        console and ConsoleWindow."""
        if isinstance(color, QColor):
            color = color.name()
        self.bg_color = color
        self.theme = THEMES[theme_for(color)]
        for channel in self.channels.values():
            channel["console"].set_background(color)
            channel["console_window"].set_background(color)
