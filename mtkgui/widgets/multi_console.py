# -*- coding: utf-8 -*-
"""Multi-channel serial / SSH console.

Used on the Test Work Flow page, next to the FCT table:

* 1-4 serial channels and 0-1 SSH channel, each hosted in its own tab
* per-channel accent colors identify the channels at a glance
* each tab hosts the ConsoleWidget (log), a Linux Command Helper and a
  Send line (HEX / CR+LF, Enter or Send)
* a "⧉ Float" control detaches one channel's console into a floating
  window ("Dock back" returns it); channels are managed on the Equipment
  page, so this page is read-only
* the ConsoleWidget keeps receiving data while floated
* RX / TX byte counters are tracked per channel
"""

import shiboken6
from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFontDialog,
    QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from ..at_commands import AT_COMMANDS
from ..command_library import load_command_library
from ..serial_params import BAUDRATES, BYTESIZE_MAP, STOPBITS_MAP, PARITY_MAP
from ..serial_worker import SerialWorker
from ..ssh_worker import SshWorker
from ..style import APP_NAME, APP_ORG
from ..gui.dialog_sizing import enable_dialog_controls
from ..virtual_dut import VirtualDutWorker, load_dut_profile
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


def _console_alive(console) -> bool:
    """True while the console's C++ object is still usable.

    A queued worker signal (connection_changed / data_received /
    error_occurred) can be delivered after the window tree was torn
    down at app exit - touching the widget then raises
    "Internal C++ object (_ConsoleOutput) already deleted"."""
    return (console is not None and shiboken6.isValid(console)
            and shiboken6.isValid(console.view))


class SerialConfigDialog(QDialog):
    """Serial connection parameters for one channel."""

    def __init__(self, parent, params=None):
        super().__init__(parent)
        self.setWindowTitle("Serial Connection Settings")
        enable_dialog_controls(self)
        merged = dict(DEFAULT_SERIAL_PARAMS)
        if params:
            merged.update(params)

        form = QFormLayout(self)

        self.combo_port = QComboBox()
        self.combo_port.setEditable(True)
        for p in list_ports.comports():
            self.combo_port.addItem(f"{p.device}  -  {p.description}",
                                    p.device)
        if merged.get("port"):
            self.combo_port.setCurrentText(str(merged["port"]))
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
        self.combo_baud.setCurrentText(str(merged["baudrate"]))
        form.addRow("Baud:", self.combo_baud)

        self.combo_data = QComboBox()
        self.combo_data.addItems(list(BYTESIZE_MAP))
        self.combo_data.setCurrentText(merged["bytesize_key"])
        form.addRow("Data bits:", self.combo_data)

        self.combo_parity = QComboBox()
        self.combo_parity.addItems(list(PARITY_MAP))
        self.combo_parity.setCurrentText(merged["parity_key"])
        form.addRow("Parity:", self.combo_parity)

        self.combo_stop = QComboBox()
        self.combo_stop.addItems(list(STOPBITS_MAP))
        self.combo_stop.setCurrentText(merged["stopbits_key"])
        form.addRow("Stop bits:", self.combo_stop)

        self.check_flow = QCheckBox("HW flow control (RTS/CTS)")
        self.check_flow.setChecked(bool(merged["flow_control"]))
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
        enable_dialog_controls(self)
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


# ==================================================== float / dock host
class _FloatedHost(QWidget):
    """Top-level window hosting one floated widget (a channel console or
    the Command Helper).  The ``Dock back`` button or the OS close (×)
    re-docks the widget into its tab."""

    def __init__(self, title, dock_callback):
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(title)
        self._dock_callback = dock_callback
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def closeEvent(self, event):                    # noqa: N802 - Qt
        self._dock_callback()
        event.accept()


# ==================================================== command helper
class CommandHelper(QWidget):
    """Linux-only Command Helper for one console channel.

    Docked it is a collapsible strip of command chips above the Send
    line; the ``⧉`` button floats the helper into its own window showing
    the full Linux command list (each row carries an ``Insert`` action
    that fills the Send line without sending).  The shared command
    library is the single source of truth; only ``category == "linux"``
    entries are shown here.
    """

    def __init__(self, send_panel, settings_key, parent=None):
        super().__init__(parent)
        self.send_panel = send_panel
        self._settings_key = settings_key
        # only the Linux category is rendered on this page
        self.entries = [e for e in load_command_library()
                        if e.get("category") == "linux"]
        self._collapsed = False
        self._float_win = None
        self._home_parent = None
        self._home_index = -1
        self._chips = []
        self._insert_btns = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # ------------------------------------------------ collapsible strip
        strip = QHBoxLayout()
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(4)
        self.btn_toggle = QPushButton("\u2304 Cmd Helper: Linux \u25be")
        self.btn_toggle.setObjectName("flat")
        self.btn_toggle.setToolTip(
            "Collapse / expand the Linux command chips")
        self.btn_toggle.clicked.connect(self._toggle)
        strip.addWidget(self.btn_toggle)

        self.chips = QWidget()
        chips_layout = QHBoxLayout(self.chips)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(4)
        for entry in self.entries:
            chip = QPushButton(entry["name"])
            chip.setObjectName("flat")
            chip.setToolTip(entry["command"])
            chip.clicked.connect(
                lambda checked=False, cmd=entry["command"]:
                    self.fill_send(cmd))
            chips_layout.addWidget(chip)
            self._chips.append(chip)
        chips_layout.addStretch(1)
        strip.addWidget(self.chips, 1)

        self.btn_float = QPushButton("\u29c9")
        self.btn_float.setObjectName("flat")
        self.btn_float.setToolTip(
            "Float the Command Helper into its own window")
        self.btn_float.clicked.connect(self._float_helper)
        strip.addWidget(self.btn_float)
        root.addLayout(strip)

        # --------------------------- full list (shown only while floated)
        self.list_panel = QWidget()
        self.list_panel.setVisible(False)
        list_layout = QVBoxLayout(self.list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(2)
        for entry in self.entries:
            row = QHBoxLayout()
            row.setSpacing(6)
            name = QLabel(entry["name"])
            name.setMinimumWidth(120)
            row.addWidget(name)
            cmd = QLabel(entry["command"])
            cmd.setObjectName("muted")
            cmd.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(cmd, 1)
            btn_insert = QPushButton("Insert")
            btn_insert.setObjectName("flat")
            btn_insert.setToolTip(entry["command"])
            btn_insert.clicked.connect(
                lambda checked=False, c=entry["command"]: self.fill_send(c))
            row.addWidget(btn_insert)
            self._insert_btns.append(btn_insert)
            list_layout.addLayout(row)
        list_layout.addStretch(1)
        root.addWidget(self.list_panel, 1)

    # --------------------------------------------------------- fill Send
    def fill_send(self, command: str) -> None:
        """Copy a command into the Send line (never sends)."""
        self.send_panel.set_text(command)
        self.send_panel.edit.setFocus()

    # ------------------------------------------------------ strip toggle
    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self.chips.setVisible(not self._collapsed)
        self.btn_toggle.setText(
            "\u25b8 Cmd Helper: Linux \u25be" if self._collapsed
            else "\u2304 Cmd Helper: Linux \u25be")

    # ------------------------------------------------------ float / dock
    def _float_helper(self) -> None:
        """Reparent the helper into its own window (full Linux list)."""
        if self._float_win is not None:
            return
        home = self.parentWidget()
        home_layout = home.layout() if home is not None else None
        home_index = (home_layout.indexOf(self)
                      if home_layout is not None else -1)
        self._home_parent = home
        self._home_index = home_index
        if home_layout is not None and home_index >= 0:
            home_layout.removeWidget(self)

        win = _FloatedHost("Command Helper: Linux", self._dock_helper)
        root = QVBoxLayout(win)
        bar = QHBoxLayout()
        btn_dock = QPushButton("Dock back")
        btn_dock.clicked.connect(self._dock_helper)
        bar.addWidget(btn_dock)
        bar.addStretch(1)
        root.addLayout(bar)

        self.setParent(win)
        root.addWidget(self, 1)
        self.list_panel.setVisible(True)
        self.chips.setVisible(False)

        settings = QSettings(APP_ORG, APP_NAME)
        geometry = settings.value(f"{self._settings_key}/helper_geometry")
        if geometry is not None:
            win.restoreGeometry(geometry)

        self._float_win = win
        win.show()
        win.raise_()
        win.activateWindow()

    def _dock_helper(self) -> None:
        """Re-insert the helper into its console and close its window."""
        win = self._float_win
        if win is None:
            return
        self._float_win = None
        win.layout().removeWidget(self)
        if self._home_parent is not None:
            self.setParent(self._home_parent)
            home_layout = self._home_parent.layout()
            if home_layout is not None:
                home_layout.insertWidget(self._home_index, self)
        self.list_panel.setVisible(False)
        self.chips.setVisible(not self._collapsed)
        settings = QSettings(APP_ORG, APP_NAME)
        settings.setValue(f"{self._settings_key}/helper_geometry",
                          win.saveGeometry())
        win.close()
        win.deleteLater()


# ============================================================ popup window
class ConsoleWindow(QDialog):
    """Popup per-channel console: hosts the ConsoleWidget and a Send
    line. Closing the window only hides it; the ConsoleWidget keeps
    receiving data in the background."""

    send_requested = Signal(str, str, bool, str)  # key, text, hex, ending

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
        # 2026-10-29 audit: a fixed 1200x800 minimum made the window
        # unshrinkable on 1366x768 laptop screens (bottom and the resize
        # edges left the screen).  The console only needs the inset; the
        # initial size still comes from the fit_dialog below.
        self.setMinimumSize(760, 480)
        from mtkgui.gui.dialog_sizing import fit_dialog
        fit_dialog(self, 1200, 800)

        layout = QVBoxLayout(self)

        # Console widget (reparented into this dialog by Qt)
        layout.addWidget(console, 1)

        # Send panel
        self.send_panel = SendPanel(key, "Send")
        self.send_panel.send_requested.connect(
            lambda k, text, hex_mode, ending:
                self.send_requested.emit(k, text, hex_mode, ending))
        layout.addWidget(self.send_panel)

        # M132: the Quick Commands row is gone (the AT catalog plus the
        # Send-line Tab completion covers the same need); only the font
        # picker stays, docked at the right end of the Send row.
        self._settings_key = f"console_window/{key}"
        self.btn_font = QPushButton("Font...")
        self.btn_font.setObjectName("flat")
        self.btn_font.setToolTip("Console log font (persisted)")
        self.btn_font.clicked.connect(self._choose_font)
        send_row = self.send_panel.layout()
        if send_row is not None:
            send_row.addWidget(self.btn_font)
        self._refresh_completion_candidates()

        self._restore_window_state()

        # M101-D: shared Command Helper (Linux category only) sits between
        # the log and the Send line; it can float to its own window with
        # a full command list.
        self._cmd_helper = CommandHelper(self.send_panel, self._settings_key,
                                         self)
        layout.insertWidget(layout.indexOf(self.send_panel),
                            self._cmd_helper)

    # --------------------------------------------- window state memory
    def _restore_window_state(self):
        """Restore geometry, log font and color scheme for this
        channel (no-op when nothing was persisted yet)."""
        settings = QSettings(APP_ORG, APP_NAME)
        geometry = settings.value(f"{self._settings_key}/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        font_text = settings.value(f"{self._settings_key}/font")
        if font_text:
            font = QFont()
            if font.fromString(font_text):
                self.console.set_font(font)
        bg = settings.value(f"{self._settings_key}/bg")
        if bg:
            self.set_background(bg)

    def _save_window_state(self):
        """Persist geometry, log font and color scheme for this
        channel (called on hide / close and on font change)."""
        settings = QSettings(APP_ORG, APP_NAME)
        settings.setValue(f"{self._settings_key}/geometry",
                          self.saveGeometry())
        settings.setValue(f"{self._settings_key}/font",
                          self.console.font().toString())
        settings.setValue(f"{self._settings_key}/bg", self.bg_color)

    def _choose_font(self):
        """Pick the console log font (persisted per channel)."""
        ok, font = QFontDialog.getFont(self.console.font(), self)
        if ok:
            self.console.set_font(font)
            self._save_window_state()

    # --------------------------------------------------------- close=hide
    def hideEvent(self, event):
        self._save_window_state()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._save_window_state()
        event.ignore()
        self.hide()

    # ---------------------------------------------------------- background
    def set_background(self, color):
        if isinstance(color, QColor):
            color = color.name()
        self.bg_color = color
        self.theme = THEMES[theme_for(color)]
        self.console.set_background(color)

    # --------------------------------------------------------- completion
    def _refresh_completion_candidates(self):
        """Feed the AT command catalog into the Send-line Tab completer
        (sent history is added by the line edit itself)."""
        candidates = []
        for _label, cmd, _desc in AT_COMMANDS:
            if cmd and cmd not in candidates:
                candidates.append(cmd)
        self.send_panel.edit.set_extra_candidates(candidates)

# ============================================================ compact row
class _CompactPortCombo(QComboBox):
    """Editable serial-port combo with a compact collapsed width.

    The popup list is widened to the longest entry so long
    ``COMxx  -  description`` names render completely while the
    closed widget stays narrow (M0 layout rule)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)          # manual port entry (as before)

    def showPopup(self):
        """Widen the popup container to the widest item before it
        opens (the collapsed widget keeps its compact width)."""
        super().showPopup()
        view = self.view()
        container = view.parentWidget()
        if container is not None:
            hint = view.sizeHint().width() + 24
            container.setMinimumWidth(max(self.width(), hint))


class ChannelRow(QFrame):
    """Compact inline row for one channel: colored label, inline
    connection fields, Open/Close, Console, Configure, Remove
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
            self.combo_port = _CompactPortCombo()
            self.combo_port.setToolTip("Serial port device")
            self._fill_ports()
            # M68: the compact combo keeps a bounded width - the popup
            # (widened by _CompactPortCombo) shows long device names; the
            # closed box no longer consumes the whole row slack.
            self.combo_port.setMinimumWidth(150)
            self.combo_port.setMaximumWidth(280)
            layout.addWidget(self.combo_port)

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

        self.btn_console = QPushButton("Console")
        self.btn_console.setToolTip("Show the dedicated console window")
        self.btn_console.clicked.connect(
            lambda: self.show_console_requested.emit(self.key))
        layout.addWidget(self.btn_console)

        # M68: text buttons - the global QSS padding (7px 16px) needs
        # real room; the old 32px glyph buttons clipped every label.
        self.btn_config = QPushButton("Configure")
        self.btn_config.setToolTip("Advanced parameters")
        self.btn_config.clicked.connect(
            lambda: self.config_requested.emit(self.key))
        layout.addWidget(self.btn_config)

        self.btn_remove = QPushButton("Remove")
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

    def _fill_ports(self):
        """Enumerate the serial ports into the compact port combo
        (same enumeration and item text as before - layout only)."""
        self.combo_port.clear()
        for p in list_ports.comports():
            self.combo_port.addItem(
                f"{p.device}  -  {p.description}", p.device)

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


class _InlineChannelView(QWidget):
    """M76/D6: one visible view per CONNECTED channel inside the
    Console panel - a title with the channel key, the scrolled output,
    and a single-line input that sends on Enter."""

    send_text = Signal(str)

    def __init__(self, key, label, accent, theme, parent=None):
        super().__init__(parent)
        self.key = key
        self._theme = dict(theme or {})
        self.setObjectName("inline_console_view")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.title = QLabel(f"{key} - {label}")
        self.title.setStyleSheet(
            f"background: {accent}; color: #1c2430; font-weight: bold;"
            " border-radius: 3px; padding: 1px 6px;")
        layout.addWidget(self.title)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(2000)
        self.view.setMinimumHeight(110)
        self.view.setPlaceholderText("(no output yet)")
        layout.addWidget(self.view, 1)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(f"Send to {key} - press Enter")
        self.edit.returnPressed.connect(self._emit)
        # v2-16: ready-made DUT-shell blocks inserted at the cursor
        from mtkgui.gui.yamlbuild.command_snippet_helper import (
            PAGE_LINUX, with_snippets)
        edit_box = with_snippets(self.edit, PAGE_LINUX, self)
        self._snippet_box = edit_box

        btn = QPushButton("Send")
        btn.setObjectName("flat")
        btn.clicked.connect(self._emit)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit_box, 1)
        row.addWidget(btn)
        layout.addLayout(row)
        self.setMinimumHeight(150)

    # ---------------------------------------------------------- data in
    def append_rx(self, data) -> None:
        try:
            text = data.decode("utf-8", "replace") if isinstance(
                data, (bytes, bytearray)) else str(data)
        except Exception:                 # noqa: BLE001 - never abort
            return
        self.view.appendPlainText(text.replace("\r\n", "\n").rstrip("\n"))

    def append_tx(self, text: str) -> None:
        self.view.appendPlainText(f"console send: {text!r}")

    # --------------------------------------------------------- data out
    def _emit(self) -> None:
        text = self.edit.text()
        if not text.strip():
            return
        self.send_text.emit(text)
        self.edit.clear()


# =========================================================== container
class MultiConsoleWidget(QGroupBox):
    """Compact 1-4 x serial + 0-1 x SSH console container. Each
    channel is a ChannelRow inline; the full ConsoleWidget lives in
    a popup ConsoleWindow hidden until 'Console' is clicked."""

    # emitted whenever a channel is added / removed / connected / dropped
    connection_changed = Signal()
    # M80-6e: the channel definition changed (add / remove / params) -
    # the workflow page mirrors it into the equipment DUT console/SSH
    channels_changed = Signal()
    # M76/D6: a manual console send line (mirrors "console send: ..."
    # into the Event Log)
    console_log = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Console", parent)
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

        # M101-D: the page is read-only - channels are defined on the
        # Equipment page.  Each channel gets one tab hosting its full
        # console (ConsoleWidget + Quick commands + Send + Command Helper).
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        layout.addWidget(self._tabs, 1)

        # key -> floated console host window (None while docked) and the
        # per-tab "⧉ Float" button that detaches the console
        self._float_win = {}
        self._float_btn = {}

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

    def add_serial_interactive(self):
        """Add a serial channel and immediately open its connection
        dialog.  Cancelling the dialog removes the just-added channel
        again (kept for programmatic callers)."""
        if not self._can_manage_channels():
            return None
        key = self.add_serial()
        if key is None or not self._can_configure():
            return key
        channel = self.channels[key]
        dlg = SerialConfigDialog(self, channel["params"])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.remove_channel(key)
            return None
        self.set_channel_params(key, dlg.get_params())
        channel["console"].append_message(
            "SYS", f"Settings updated (Open to connect): "
                   f"{self._endpoint(channel)}", color=self.theme["sys"])
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

        # The ChannelRow stays as the params-sync holder (its inline
        # fields feed open_channel / set_channel_params) but is not shown:
        # channel management moved to the Equipment page (M101-D).
        row = ChannelRow(key, kind, label, accent, params, parent=self)
        row.open_requested.connect(self.open_channel)
        row.close_requested.connect(self.close_channel)
        row.show_console_requested.connect(self._show_console)
        row.config_requested.connect(self.configure_channel)
        row.remove_requested.connect(self.remove_channel)
        row.params_changed.connect(self._on_row_params_changed)
        row.apply_permissions(self._can_manage_channels(),
                              self._can_configure())
        row.hide()  # params-sync holder only, never shown (M101-fix)

        # one tab per channel: a small header bar (label + ⧉ Float) above
        # the full console (ConsoleWindow hosts log + send + helper)
        tab_page = QWidget()
        tab_layout = QVBoxLayout(tab_page)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 2)
        header.addWidget(QLabel(f"{label} console"))
        header.addStretch(1)
        btn_float = QPushButton("\u29c9 Float")
        btn_float.setObjectName("flat")
        btn_float.setToolTip(
            "Detach this channel's console into a floating window")
        btn_float.clicked.connect(
            lambda checked=False, k=key: self._float_console(k))
        header.addWidget(btn_float)
        tab_layout.addLayout(header)
        tab_layout.addWidget(console_window, 1)

        idx = self._tabs.addTab(tab_page, label)
        if idx < 0:
            # extremely defensive: never strand the console window
            tab_layout.removeWidget(console_window)
            console_window.setParent(None)

        channel = {
            "kind": kind,
            "label": label,
            "accent": accent,
            "console": console,
            "console_window": console_window,
            "row": row,
            "tab_page": tab_page,
            "placeholder": None,
            "params": params,
            "worker": None,
            "connected": False,
            "stats": [0, 0],  # [tx, rx]
            "read_buffer": bytearray(),
        }
        self.channels[key] = channel
        self._float_win[key] = None
        self._float_btn[key] = btn_float

        console.append_message(
            "SYS",
            f"{label} ready. Double-click the log to configure "
            + ("serial parameters." if kind == "serial"
               else "SSH parameters."),
            color=self.theme["sys"])
        self._refresh_actions()
        self.connection_changed.emit()
        self.channels_changed.emit()

    def remove_channel(self, key):
        """Close and remove a channel row (can remove all)."""
        channel = self.channels.get(key)
        if not channel:
            return
        # M76/D6: Remove must RELEASE the port - always stop the worker
        # (wait() closes the serial handle in its finally block), even
        # when the thread state already reports not-running
        worker = channel.get("worker")
        if worker is not None:
            try:
                worker.stop()
                worker.wait(3000)
            except Exception:             # noqa: BLE001 - never abort
                pass
            channel["worker"] = None
        channel["console_window"].hide()
        # dock the channel's console back into its tab (if floated) and
        # drop the tab page
        win = self._float_win.get(key)
        if win is not None:
            self._dock_console(key)
        tab_page = channel.get("tab_page")
        if tab_page is not None:
            idx = self._tabs.indexOf(tab_page)
            if idx >= 0:
                self._tabs.removeTab(idx)
            tab_page.deleteLater()
        else:                             # backward-compatible fallback
            row = channel["row"]
            row.setParent(None)
            row.deleteLater()
        if channel["kind"] == "ssh":
            self._ssh_open = False
        else:
            n = int(key[3:])
            if n in self._serial_numbers:
                self._serial_numbers.remove(n)
        self._float_win.pop(key, None)
        self._float_btn.pop(key, None)
        del self.channels[key]
        self._refresh_actions()
        self.connection_changed.emit()
        self.channels_changed.emit()

    def remove_current(self):
        """Remove the last channel (backward compat)."""
        key = self.current_key()
        if key is None:
            return
        self.remove_channel(key)

    def _refresh_actions(self):
        """No-op: channel add / remove moved to the Equipment page
        (M101-D).  Kept for the apply_permissions / _create_channel
        call sites."""

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
        self.channels_changed.emit()

    def _on_row_params_changed(self, key):
        """An inline field in the row changed: merge into channel params."""
        if not self._can_configure():
            return
        row = self.channels[key]["row"]
        partial = row.get_inline_params()
        self.channels[key]["params"].update(partial)
        self.channels_changed.emit()

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
            # Virtual mode: simulated connection, no real hardware needed.
            # Serial channels get a configurable simulated DUT (boot log,
            # shell prompt, rule-based command replies); SSH keeps the
            # plain idle banner connection.
            p = channel["params"]
            if channel["kind"] == "serial":
                detail = (f"{p.get('port') or 'virtual-serial'} "
                          f"@ {p.get('baudrate') or 115200}")
                worker = VirtualDutWorker(load_dut_profile(), detail)
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
        if channel is not None and _console_alive(channel["console"]):
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

    def clear_channels(self):
        """Remove every channel entirely (no YAML loaded: the console
        starts empty; channels are rebuilt from the Equipment page)."""
        for key in list(self.channels):
            self.remove_channel(key)
        self._yaml_channel_keys = None

    def on_connection_changed(self, key, connected):
        channel = self.channels.get(key)
        if channel is None:  # removed while a queued signal was in flight
            return
        channel["connected"] = bool(connected)
        if not _console_alive(channel["console"]):
            return  # widgets gone (app shutdown): state only, no UI
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
        # M76/D6: the inline view is visible exactly while connected
        inline = channel.get("inline")
        if inline is not None:
            inline.setVisible(bool(connected))
        self.connection_changed.emit()

    # ------------------------------------------------------------ RX data
    def on_data(self, key, data):
        channel = self.channels.get(key)
        if channel is None:  # removed while a queued signal was in flight
            return
        if not _console_alive(channel["console"]):
            return  # widgets gone (app shutdown): drop the queued bytes
        channel["read_buffer"].extend(data)
        channel["stats"][1] += len(data)
        channel["row"].update_counts(channel["stats"][0],
                                     channel["stats"][1])
        inline = channel.get("inline")
        if inline is not None:
            inline.append_rx(data)
        console = channel["console"]
        if console.check_hex.isChecked():
            text = " ".join(f"{b:02X}" for b in data)
            console.append_message("RX", text, color=self.theme["rx"])
        else:
            console.append_rx("RX", data)

    # ------------------------------------------------------------ sending
    def _send_inline(self, key, text):
        """M76/D6: the inline input line of one connected channel."""
        if not str(text or "").strip():
            return
        self.handle_send(key, str(text), False, "crlf")
        channel = self.channels.get(key)
        if channel is not None:
            inline = channel.get("inline")
            if inline is not None:
                inline.append_tx(str(text))
        self.console_log.emit(f"console send: {text!r}")

    @staticmethod
    def ending_bytes(ending) -> bytes:
        """Line ending selector -> payload suffix.

        Accepts the explicit modes ("crlf" / "lf" / "") and the legacy
        bool (True = CR+LF, False = none) used by older callers."""
        if isinstance(ending, bool):
            return b"\r\n" if ending else b""
        return {"crlf": b"\r\n", "lf": b"\n"}.get(str(ending or ""), b"")

    @staticmethod
    def encode_payload(text, hex_mode, crlf):
        if hex_mode:
            cleaned = (text.replace(" ", "").replace(",", "")
                           .replace("0x", "").replace("\n", ""))
            return bytes.fromhex(cleaned)
        payload = text.encode("utf-8")
        payload += MultiConsoleWidget.ending_bytes(crlf)
        return payload

    def handle_send(self, key, text, hex_mode, crlf):
        """Send a payload on a specific channel (key) and mirror the
        send into the Event Log (``console_log``)."""
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
            suffix = {b"\r\n": "\\r\\n", b"\n": "\\n"}.get(
                MultiConsoleWidget.ending_bytes(crlf), "")
            shown = text + suffix
        self._write_to_channel(key, payload, shown)
        channel = self.channels.get(key)
        if (channel and channel["worker"]
                and channel["worker"].isRunning()):
            channel["console_window"].send_panel.commit_sent(text)
        self.console_log.emit(f"console send: {text!r}")

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

    def set_channel_baud(self, key, baudrate):
        """Reconfigure an open channel's link speed (FCT deploy).
        Returns True when the worker accepted the new baud."""
        channel = self.channels.get(key)
        if not channel:
            return False
        worker = channel["worker"]
        if not worker or not worker.isRunning():
            return False
        return bool(worker.set_baudrate(baudrate))

    def clear_read_buffer(self, key):
        channel = self.channels.get(key)
        if channel:
            channel["read_buffer"].clear()

    def _show_console(self, key):
        """Bring a channel's console to the front (its tab, or its
        floated window when detached)."""
        channel = self.channels.get(key)
        if not channel:
            return
        win = self._float_win.get(key)
        if win is not None:
            win.show()
            win.raise_()
            win.activateWindow()
            return
        tab_page = channel.get("tab_page")
        if tab_page is not None:
            self._tabs.setCurrentWidget(tab_page)

    # --------------------------------------------- float / dock a console
    def _float_console(self, key):
        """Reparent a channel's whole console (ConsoleWindow) into a
        top-level window; the vacated tab shows a placeholder.  The run
        engine keeps writing into the same ConsoleWidget object."""
        if self._float_win.get(key) is not None:
            return
        channel = self.channels.get(key)
        if not channel:
            return
        console_window = channel["console_window"]
        tab_page = channel["tab_page"]
        tab_layout = tab_page.layout()

        win = _FloatedHost(
            f"{channel['label']} Console",
            lambda k=key: self._dock_console(k))
        root = QVBoxLayout(win)
        bar = QHBoxLayout()
        btn_dock = QPushButton("Dock back")
        btn_dock.clicked.connect(lambda k=key: self._dock_console(k))
        bar.addWidget(btn_dock)
        bar.addStretch(1)
        root.addLayout(bar)

        idx = tab_layout.indexOf(console_window)
        if idx >= 0:
            tab_layout.removeWidget(console_window)
        console_window.setParent(win)
        root.addWidget(console_window, 1)

        placeholder = QLabel(
            f"{channel['label']} console floated — Dock back to return")
        placeholder.setObjectName("muted")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tab_layout.addWidget(placeholder, 1)
        channel["placeholder"] = placeholder

        settings = QSettings(APP_ORG, APP_NAME)
        geometry = settings.value(
            f"{console_window._settings_key}/float_geometry")
        if geometry is not None:
            win.restoreGeometry(geometry)

        self._float_win[key] = win
        win.show()
        win.raise_()
        win.activateWindow()

    def _dock_console(self, key):
        """Re-insert a floated console into its tab and close the
        window (never orphans the console)."""
        win = self._float_win.get(key)
        if win is None:
            return
        channel = self.channels.get(key)
        if channel is None:
            self._float_win[key] = None
            win.close()
            win.deleteLater()
            return
        console_window = channel["console_window"]
        tab_page = channel["tab_page"]
        tab_layout = tab_page.layout()
        placeholder = channel.get("placeholder")
        if placeholder is not None:
            tab_layout.removeWidget(placeholder)
            placeholder.deleteLater()
            channel["placeholder"] = None
        win.layout().removeWidget(console_window)
        console_window.setParent(tab_page)
        tab_layout.addWidget(console_window, 1)
        settings = QSettings(APP_ORG, APP_NAME)
        settings.setValue(f"{console_window._settings_key}/float_geometry",
                          win.saveGeometry())
        self._float_win[key] = None
        win.close()
        win.deleteLater()

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
