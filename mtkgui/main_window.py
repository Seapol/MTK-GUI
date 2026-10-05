# -*- coding: utf-8 -*-
"""MTK GUI main window.

Two independent serial channels:

* DUT  - the Device Under Test, UART1
* AUX  - either the DUT UART2 or a companion / test board

Each channel has its own connection settings, console and send line.
The console background is adjustable (View menu) and defaults to black;
received ANSI color sequences are rendered in place.
"""

import getpass
import platform
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QGroupBox,
    QVBoxLayout,
    QWidget,
)

from . import __version__, project_config
from .equipment_page import EquipmentPage
from .permissions import (
    ROLE_OPERATOR,
    ROLE_SUPERVISOR,
    LoginDialog,
    PermissionsDialog,
    load_permissions,
    save_permissions,
)
from .test_workflow_page import TestWorkFlowPage
from .yaml_build_page import YamlBuildPage
from .style import (
    APP_NAME,
    APP_ORG,
    GUI_THEMES,
    build_qss,
    saved_theme,
)
from .theme import DEFAULT_BACKGROUND, THEMES, theme_for
from .virtual_dut import (
    VirtualDutDialog,
    load_dut_profile,
    save_dut_profile,
)
from .virtual_mode import (
    VirtualFaultDialog,
    load_fault_config,
    save_fault_config,
)
from .virtual_dut import (
    VirtualDutDialog,
    load_dut_profile,
    save_dut_profile,
)

# Event Log auto-save: one plain-text file per GUI session (start->exit)
EVENT_DIR = Path(__file__).resolve().parent.parent / "event"

# Doubled default size; clamped to the screen at runtime.
DEFAULT_WIDTH = 2560
DEFAULT_HEIGHT = 1600

# Instruments shown in the status bar, as (abbreviation, full name).
# Abbreviations match the badges on the Equipment block diagram:
#   DAQM = DAQ973A + 2x DAQM908A + DAQM907A
#   DAQ  = U2355A
#   PSU  = N5747A
INSTRUMENTS = (
    ("DAQM", "DAQ973A + 2x DAQM908A + DAQM907A"),
    ("DAQ", "U2355A"),
    ("PSU", "N5747A"),
)

LED_COLORS = {
    "connected": "#22c55e",      # green
    "disconnected": "#9ca3af",   # gray
    "error": "#ef4444",           # red
}
LED_TEXT = {
    "connected": "Connected",
    "disconnected": "Disconnected",
    "error": "Error",
}


class StatusLed(QLabel):
    """Round connection-state indicator light."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(13, 13)
        self.set_state("disconnected")

    def set_state(self, state):
        color = LED_COLORS[state]
        self.setStyleSheet(
            f"background:{color}; border-radius:6px;"
            f"border:1px solid rgba(0,0,0,0.25);")


class InstrumentStatusBar(QWidget):
    """'Instruments:' caption plus one LED + abbreviation per instrument."""

    def __init__(self, instruments, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(6)

        caption = QLabel("Instruments:")
        caption.setObjectName("muted")
        row.addWidget(caption)

        self.titles = {}
        self.leds = {}
        for i, (abbr, title) in enumerate(instruments):
            self.titles[abbr] = title
            led = StatusLed()
            self.leds[abbr] = led
            row.addWidget(led)
            name = QLabel(abbr)
            name.setObjectName("strong")
            row.addWidget(name)
            if i < len(instruments) - 1:
                row.addSpacing(10)

        self.states = {abbr: "disconnected" for abbr, _ in instruments}
        self._refresh_tooltips()

    def set_state(self, abbr, state):
        if self.states.get(abbr) == state:
            return
        self.states[abbr] = state
        self.leds[abbr].set_state(state)
        self._refresh_tooltips()

    def set_all(self, state):
        for abbr in self.states:
            self.set_state(abbr, state)

    def _refresh_tooltips(self):
        for abbr, led in self.leds.items():
            led.setToolTip(
                f"{self.titles[abbr]}: {LED_TEXT[self.states[abbr]]}")


class SerialStatusBar(QWidget):
    """'Consoles:' caption plus one LED + channel key per console
    channel (serial + SSH).

    Rebuilt whenever the console channel set changes (add / remove) and
    re-colored on every connect / disconnect (multi_console's
    connection_changed signal -> sync_channels)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(6, 0, 6, 0)
        self._row.setSpacing(6)
        caption = QLabel("Consoles:")
        caption.setObjectName("muted")
        self._row.addWidget(caption)
        self._leds = {}

    def sync_channels(self, channels):
        """Mirror the multi-console channel set and connection states
        (full rebuild - channel sets change rarely)."""
        while self._row.count() > 1:          # keep the caption at 0
            item = self._row.takeAt(self._row.count() - 1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._leds = {}
        for i, (key, ch) in enumerate(channels.items()):
            led = StatusLed()
            lbl = QLabel(key)
            lbl.setObjectName("strong")
            self._row.addWidget(led)
            self._row.addWidget(lbl)
            if i < len(channels) - 1:
                self._row.addSpacing(8)
            state = "connected" if ch.get("connected") else "disconnected"
            led.set_state(state)
            lbl.setToolTip(f"{key}: {LED_TEXT[state]}")
            self._leds[key] = (led, lbl)


class DialogCenterer(QObject):
    """QApplication event filter: every dialog window (config dialogs,
    message boxes, the login box, ...) shows up centered on the screen
    it appears on - re-centered each time it is re-shown.

    On its FIRST show a dialog is also enlarged to 1.5x its natural
    sizeHint (never shrunk, capped to 92% of the screen) - the dialogs
    were all too small. Manual resizes after that first show are kept."""

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Show
                and isinstance(obj, QDialog) and obj.isWindow()):
            screen = obj.screen() or QApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                # QMessageBox sizes itself to its content by design:
                # only center it, do not force-enlarge
                if not isinstance(obj, QMessageBox):
                    if obj.property("_dlg_enlarged") is None:
                        obj.setProperty("_dlg_enlarged", True)
                        hint = obj.sizeHint()
                        target_w = min(int(hint.width() * 1.5),
                                       int(avail.width() * 0.92))
                        target_h = min(int(hint.height() * 1.5),
                                       int(avail.height() * 0.92))
                        if (obj.width() < target_w
                                or obj.height() < target_h):
                            obj.resize(max(obj.width(), target_w),
                                       max(obj.height(), target_h))
                fg = obj.frameGeometry()
                fg.moveCenter(avail.center())
                obj.move(fg.topLeft())
        return False


class MainWindow(QMainWindow):
    def __init__(self, role=ROLE_SUPERVISOR, mode="Real"):
        super().__init__()
        self.setWindowTitle("MTK - Manufacturing Test Kit")
        self._init_size()

        # every dialog window pops up centered on the primary screen
        app = QApplication.instance()
        if app is not None and not app.property("_dialog_centerer"):
            centerer = DialogCenterer(app)
            app.installEventFilter(centerer)
            app.setProperty("_dialog_centerer", True)

        self.bg_color = DEFAULT_BACKGROUND
        self.theme = THEMES[theme_for(self.bg_color)]

        # account role (Supervisor / Operator) and operator permissions
        self.role = role
        self.permissions = load_permissions()
        # Real (physical HW required) / Virtual (simulated HW) mode;
        # Virtual mode is supervisor-only, operators always run Real
        self.mode = mode if role == ROLE_SUPERVISOR else "Real"
        self.fault_config = load_fault_config()

        # path of the currently loaded / saved project YAML (None = new)
        self._project_path = None

        self._build_ui()
        self._build_menus()
        # restore the GUI colour theme chosen in a previous session
        self.apply_gui_theme(saved_theme())
        self.apply_permissions()

    # ---------------------------------------------------------------- size
    def _init_size(self):
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        width = min(DEFAULT_WIDTH, available.width() - 40)
        height = min(DEFAULT_HEIGHT, available.height() - 40)
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        # vertical splitter: common header | tabs | event log
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter)

        # --- tabs (built first so the common groups can be pulled out of
        #     the Test Work Flow page into the top area) -------------------
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self.workflow_page = TestWorkFlowPage()
        self.tabs.addTab(self.workflow_page, "Test Work Flow")

        self.equipment_page = EquipmentPage()
        self.tabs.addTab(self.equipment_page, "Equipment")

        # V4.0: Yaml Build tab, fixed at the rightmost position
        self.yaml_build_page = YamlBuildPage()
        self.tabs.addTab(self.yaml_build_page, "Yaml Build")

        # jump back to the Test Work Flow page when a test completes
        self.workflow_page.run_finished.connect(
            lambda: self.tabs.setCurrentWidget(self.workflow_page))
        self.tabs.setCurrentWidget(self.workflow_page)

        # --- top: common parts pulled out of the Test Work Flow page ----
        # Product Information / Run Control / Overall Flow / Overall Result.
        # All rows visible by default (no scrollbar); the vertical splitter
        # handle above the tabs lets the operator adjust the ratio.
        top = QWidget()
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)
        top_row.addWidget(self.workflow_page.product_group, 1)
        top_row.addWidget(self.workflow_page.run_control_group, 0)
        top_row.addWidget(self.workflow_page.overall_group, 1)
        top_row.addWidget(self.workflow_page.result_group, 1)

        # The serial / SSH console lives on the Test Work Flow page,
        # beside the FCT table (self.workflow_page.multi_console).

        # --- bottom: Event Log (6 rows, auto-scroll, date-time stamps) --
        # renamed from "Test Log"; moved out of the Test Work Flow page.
        log_group = QGroupBox("Event Log")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(8, 8, 8, 8)
        self.event_log = QPlainTextEdit()
        self.event_log.setReadOnly(True)
        # right-click menu: Copy / Clear / Save as
        self.event_log.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.event_log.customContextMenuRequested.connect(
            self._event_log_menu)
        fm = QFontMetrics(self.event_log.font())
        six_rows = (fm.lineSpacing() * 6
                    + 2 * self.event_log.frameWidth() + 6)
        # Event Log is 50% taller than the original 6-row design
        self.event_log.setMinimumHeight(int(six_rows * 1.5))
        log_layout.addWidget(self.event_log)

        # one auto-saved session log file per GUI run (start -> exit)
        self._event_log_file = None
        self._start_event_log()

        # route the workflow page log signals into the central Event Log
        self.workflow_page.log_line.connect(self._append_event_log)
        self.workflow_page.log_cleared.connect(self._clear_event_log)

        # --- status bar, flat left -> right:
        # Version | Role | Mode | Station ID | User | Progress (adaptive)
        # | Instruments | Consoles | Date
        sb = self.statusBar()

        self.status_version = QLabel(f"Version: {__version__}")
        self.status_version.setObjectName("muted")
        self.status_version.setStyleSheet("padding: 0 6px;")
        sb.addWidget(self.status_version)

        # Role / Mode badges: colored background + bold white text,
        # refreshed on File > Switch Account
        self.status_role = QLabel()
        self.status_mode = QLabel()
        sb.addWidget(self.status_role)
        sb.addWidget(self.status_mode)
        self._update_identity_status()

        station = platform.node() or "UNKNOWN"
        self.status_station = QLabel(f"Station ID: {station}")
        self.status_station.setObjectName("muted")
        self.status_station.setStyleSheet("padding: 0 6px;")
        sb.addWidget(self.status_station)

        self.status_user = QLabel(f"User: {getpass.getuser()}")
        self.status_user.setObjectName("muted")
        self.status_user.setStyleSheet("padding: 0 6px;")
        sb.addWidget(self.status_user)

        # run progress: adaptive width (wired to the workflow page below)
        self.status_progress = QProgressBar()
        self.status_progress.setTextVisible(True)
        self.status_progress.setFormat("Idle")
        self.status_progress.setRange(0, 1)
        self.status_progress.setValue(0)
        sb.addWidget(self.status_progress, 1)  # stretch = adaptive
        self._last_progress = (0, 1)

        # Instruments connection LEDs
        self.instr_status = InstrumentStatusBar(INSTRUMENTS)
        sb.addPermanentWidget(self.instr_status)

        # Consoles: one LED per console channel, updated live on
        # channel add / remove / connect / disconnect
        self.serial_status = SerialStatusBar()
        sb.addPermanentWidget(self.serial_status)
        mcw = self.workflow_page.multi_console
        mcw.connection_changed.connect(
            lambda: self.serial_status.sync_channels(mcw.channels))
        self.serial_status.sync_channels(mcw.channels)

        # current date (far right)
        self.status_date = QLabel(
            f"{datetime.now():%Y-%m-%d}")
        self.status_date.setObjectName("muted")
        self.status_date.setStyleSheet("padding: 0 6px;")
        sb.addPermanentWidget(self.status_date)

        # instrument connection lights:
        # running -> all connected; virtual fault -> red, auto-recover;
        # run end -> clear any red back to connected
        self.workflow_page.run_progress.connect(
            lambda *_: self.instr_status.set_all("connected"))
        # wire run progress to the status bar progress bar
        self.workflow_page.run_progress.connect(self._update_run_progress)
        # background phases (console connect, ...) -> busy progress bar
        self.workflow_page.phase_changed.connect(self._on_run_phase)
        self.workflow_page.instrument_error.connect(self._on_instrument_error)
        self.workflow_page.run_finished.connect(
            lambda: self.instr_status.set_all("connected"))
        if self.mode == "Virtual":
            # simulated instruments come up shortly after the GUI starts
            QTimer.singleShot(800, self._connect_virtual_instruments)

        # --- assemble the splitter: top | middle (tabs) | bottom --------
        self.splitter.addWidget(top)
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(log_group)
        # top and bottom keep their natural size; the tabs take the rest
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        # initial sizes: top = all rows, bottom = log (1.5x of the
        # original 6 rows), middle = rest
        top_h = max(top.sizeHint().height(), 180)
        bottom_h = int(six_rows * 1.5) + 40
        middle_h = max(300, self.height() - top_h - bottom_h)
        self.splitter.setSizes([top_h, middle_h, bottom_h])

        self.setCentralWidget(central)

        # Apply the default background to every console channel.
        self.apply_background(self.bg_color)

        # No YAML loaded yet -> clear ICT/FCT tables to 1 empty row each
        self.workflow_page.clear_tables()

    def _build_menus(self):
        # macOS: keep the menus inside the window - the native macOS menu
        # bar moves them to the top of the screen and the window shows none
        self.menuBar().setNativeMenuBar(False)
        file_menu = self.menuBar().addMenu("File")
        self.act_load_yaml = file_menu.addAction(
            "Load Yaml…", self.load_yaml)
        self.act_save_yaml = file_menu.addAction(
            "Apply and Save Yaml", self.apply_and_save_yaml)
        self.act_save_yaml_as = file_menu.addAction(
            "Save as Yaml…", self.save_yaml_as)
        file_menu.addSeparator()
        self.act_switch = file_menu.addAction(
            "Switch Account…", self.switch_account)
        file_menu.addAction("Exit", self.close)

        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(
            "Console Background Color…", self.choose_background)
        view_menu.addAction(
            "Reset Background (Black)",
            lambda: self.apply_background(QColor(DEFAULT_BACKGROUND)))
        # selectable GUI colour themes (whole application restyled)
        theme_menu = view_menu.addMenu("GUI Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        current = saved_theme()
        for name in GUI_THEMES:
            act = theme_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(name == current)
            self._theme_group.addAction(act)
            act.triggered.connect(
                lambda _checked=False, n=name: self.apply_gui_theme(n))

        settings_menu = self.menuBar().addMenu("Settings")
        # supervisor-only: configure which rights operator accounts get
        self.act_permissions = settings_menu.addAction(
            "Operator Permissions…", self._open_permissions_dialog)
        # Serial Number format rule: {"prefix": str, "length": str};
        # both optional, empty means that part is not checked.
        self.sn_config = {"prefix": "", "length": ""}
        act_serial_check = QAction("Serial Number Format Check...", self)
        act_serial_check.triggered.connect(self._open_serial_format_dialog)
        self.act_serial_check = act_serial_check
        settings_menu.addAction(act_serial_check)
        # Virtual mode only (supervisor): random fault-injection config
        self.act_fault_inject = settings_menu.addAction(
            "Virtual Fault Injection...", self._open_fault_dialog)
        # the Test Work Flow page queries this in its pre-test phase
        self.workflow_page.sn_format = lambda: dict(self.sn_config)

        # ------------------------------------------------ V4.0: Help menu
        self.help_menu = self.menuBar().addMenu("Help")
        self.help_menu.addAction(
            "User Guide", lambda: self._open_help("user_guide"))
        self.help_menu.addAction(
            "Developer Guide", lambda: self._open_help("developer_guide"))
        self.help_menu.addAction(
            "Version History", lambda: self._open_help("version_history"))
        self.help_menu.addAction(
            "Readme & Quick Start",
            lambda: self._open_help("readme_quickstart"))

        # ---------------------------------------------- V4.0: Report menu
        self.report_menu = self.menuBar().addMenu("Report")
        self.report_menu.addAction("DUT Report", self._open_dut_report)
        self.report_menu.addAction("Event Log", self._open_report_event_log)
        self.report_menu.addAction("Statistics", self._open_statistics)

    # ------------------------------------------------- V4.0 Help/Report
    def _open_help(self, key):
        """Help menu: open the built-in guide dialog for one topic.

        Phase A mounts the menu; the full guide content provider lands
        with V4.0 phase B2 (interface_spec.md section 29).

        Args:
            key: One of the HELP_KEYS topic identifiers.
        """
        titles = {
            "user_guide": "User Guide",
            "developer_guide": "Developer Guide",
            "version_history": "Version History",
            "readme_quickstart": "Readme & Quick Start",
        }
        text = (f"[ {titles.get(key, key)} ]\n\n"
                "Full built-in guide content ships with V4.0 phase B2 "
                "(feature/help-report-menus).")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Help - {titles.get(key, key)}")
        lay = QVBoxLayout(dlg)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        lay.addWidget(view)
        dlg.resize(720, 520)
        dlg.exec()

    def _open_dut_report(self):
        """Report > DUT Report: per-unit PDF export placeholder.

        The PDF builder (Qt QPdfWriter, fixed DUT_[PASS/FAIL]_...
        naming) ships with V4.0 phase B3 (interface_spec.md 30)."""
        QMessageBox.information(
            self, "DUT Report",
            "Per-unit DUT report (PDF) export ships with V4.0 phase B3 "
            "(feature/report-backend).")

    def _open_report_event_log(self):
        """Report > Event Log: full-lifecycle TXT log viewer
        placeholder (ships with V4.0 phase B3)."""
        QMessageBox.information(
            self, "Event Log",
            "Full-lifecycle event log viewer and TXT export ship with "
            "V4.0 phase B3 (feature/report-backend). The live session "
            "log stays available in the Event Log panel below.")

    def _open_statistics(self):
        """Report > Statistics: quality-statistics dialog placeholder
        (Yield / Avg Cycle Time / UPH / CpK / Error List, shipped with
        V4.0 phase B3 on top of the P2-5 metrics engine)."""
        QMessageBox.information(
            self, "Statistics",
            "Quality statistics (Yield, Avg Cycle Time, UPH/UPD, CpK, "
            "Error List) ship with V4.0 phase B3 "
            "(feature/report-backend).")

    # -------------------------------------------------------- permissions
    def apply_permissions(self):
        """Enable / disable menus and pages for the current account role."""
        supervisor = self.role == ROLE_SUPERVISOR
        perm = self.permissions
        can_save = supervisor or perm.get("save_yaml", False)
        self.act_save_yaml.setEnabled(can_save)
        self.act_save_yaml_as.setEnabled(can_save)
        self.act_serial_check.setEnabled(
            supervisor or perm.get("sn_format_check", False))
        self.act_permissions.setVisible(supervisor)
        self.workflow_page.apply_permissions(perm, supervisor)
        self.equipment_page.set_config_allowed(
            supervisor or perm.get("equipment_config", False))
        # Virtual mode drives the instrument dialog's connect / test behavior
        self.equipment_page.set_virtual_mode(self.mode == "Virtual")
        # Virtual mode (supervisor only): fault-injection menu + pages
        virtual = supervisor and self.mode == "Virtual"
        self.act_fault_inject.setEnabled(virtual)
        self.workflow_page.set_mode(self.mode)
        self.workflow_page.set_virtual_fault(self.fault_config)
        self.workflow_page.multi_console.set_virtual_mode(virtual)
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Logged in: {self.role}")

    def _update_identity_status(self):
        """Status bar identity badges: Role + Mode with distinct
        background colors (File > Switch Account refreshes both)."""
        badge = ("padding: 1px 10px; border-radius: 9px;"
                 "font-weight: bold; font-size: 12px;")
        role_colors = {
            ROLE_SUPERVISOR: "background:#2f6fb3; color:#ffffff;",
            ROLE_OPERATOR: "background:#b45309; color:#ffffff;",
        }
        mode_colors = {
            "Real": "background:#1d7a3c; color:#ffffff;",
            "Virtual": "background:#7c3aed; color:#ffffff;",
        }
        self.status_role.setText(f"Role: {self.role}")
        self.status_role.setStyleSheet(
            badge + role_colors.get(self.role, ""))
        self.status_mode.setText(f"Mode: {self.mode}")
        self.status_mode.setStyleSheet(
            badge + mode_colors.get(self.mode, ""))

    def switch_account(self):
        """File > Switch Account: re-login without restarting the GUI."""
        result = LoginDialog.login(self, allow_cancel=True)
        if result is None:
            return
        role, mode = result
        self.role = role
        # Virtual mode is supervisor-only; operators fall back to Real
        self.mode = mode if role == ROLE_SUPERVISOR else "Real"
        self.permissions = load_permissions()
        self.apply_permissions()
        self._update_identity_status()

    def _open_fault_dialog(self):
        """Settings > Virtual Fault Injection (Virtual mode + supervisor)."""
        if self.mode != "Virtual" or self.role != ROLE_SUPERVISOR:
            return
        cfg = VirtualFaultDialog.edit(self.fault_config, self)
        if cfg is None:
            return
        self.fault_config = cfg
        try:
            save_fault_config(cfg)
        except OSError as exc:
            QMessageBox.warning(self, "Virtual Fault Injection",
                                f"Failed to save configuration: {exc}")
        self.workflow_page.set_virtual_fault(cfg)
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Virtual Fault Injection "
            f"updated (fail {cfg['test_fail_ratio']:.2f} %, "
            f"equipment error {cfg['equipment_error_ratio']:.2f} %)")

    def _open_permissions_dialog(self):
        """Settings > Operator Permissions (supervisor only)."""
        if self.role != ROLE_SUPERVISOR:
            return
        perm = PermissionsDialog.edit(self.permissions, self)
        if perm is None:
            return
        self.permissions = perm
        try:
            save_permissions(perm)
        except OSError as exc:
            QMessageBox.warning(self, "Permissions",
                                f"Failed to save permissions: {exc}")
        self.apply_permissions()

    def _open_serial_format_dialog(self):
        """Config dialog for the pre-test serial number format rule."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Serial Number Format Check")
        form = QFormLayout(dlg)
        desc = QLabel(
            "Rule: Serial Number = <prefix> + <SN Length digits>.\n"
            "SN Length counts the digits only, excluding the prefix.\n"
            "Both fields are optional; leave both empty to skip checking.")
        desc.setWordWrap(True)
        desc.setObjectName("muted")
        form.addRow(desc)
        prefix_edit = QLineEdit(self.sn_config["prefix"])
        prefix_edit.setPlaceholderText("e.g. VS (empty = not checked)")
        length_edit = QLineEdit(self.sn_config["length"])
        length_edit.setPlaceholderText("e.g. 10 (empty = not checked)")
        form.addRow("Prefix:", prefix_edit)
        form.addRow("SN Length:", length_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.sn_config["prefix"] = prefix_edit.text().strip()
            self.sn_config["length"] = length_edit.text().strip()

    # ------------------------------------------------------------ File menu
    def load_yaml(self):
        """File > Load Yaml: pick a project YAML file and apply it."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Yaml", "", "YAML files (*.yaml *.yml)")
        if not path:
            return
        try:
            config = project_config.load_config(path)
        except (OSError, project_config.yaml.YAMLError) as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))
            return
        project_config.apply_config(
            config, self.workflow_page, self.equipment_page)
        self._project_path = path
        self.workflow_page.set_project_file(path)
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Yaml loaded: {path}")

    def apply_and_save_yaml(self):
        """File > Apply and Save Yaml: save back to the current file.

        Without a current file (never loaded/saved) this falls back to
        Save as Yaml."""
        if not self._project_path:
            self.save_yaml_as()
            return
        self._save_yaml_to(self._project_path)

    def save_yaml_as(self):
        """File > Save as Yaml: always ask for a (new) file name.

        The suggested name follows
        ProductPartNumber_CoreID_Batch_rev1.0.yaml."""
        config = project_config.build_config(
            self.workflow_page, self.equipment_page)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as Yaml",
            project_config.default_filename(config),
            "YAML files (*.yaml *.yml)")
        if not path:
            return
        self._save_yaml_to(path)

    def _save_yaml_to(self, path):
        config = project_config.build_config(
            self.workflow_page, self.equipment_page)
        try:
            project_config.save_config(config, path)
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return
        self._project_path = path
        self.workflow_page.set_project_file(path)
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Yaml saved: {path}")

    # ------------------------------------------------------------ theme
    def apply_gui_theme(self, name):
        """Apply one of the selectable GUI colour themes to the whole
        application (all windows and dialogs) and remember the choice."""
        if name not in GUI_THEMES:
            return
        QApplication.instance().setStyleSheet(build_qss(name))
        QSettings(APP_ORG, APP_NAME).setValue("gui_theme", name)

    def choose_background(self):
        color = QColorDialog.getColor(
            QColor(self.bg_color), self, "Console background color")
        if color.isValid():
            self.apply_background(color)

    def apply_background(self, color):
        if isinstance(color, QColor):
            color = color.name()
        self.bg_color = color
        self.theme = THEMES[theme_for(color)]
        self.workflow_page.multi_console.set_background(color)

    # -------------------------------------------------------- Event Log
    def _start_event_log(self):
        """Open the per-session auto-save log file under ./event/.

        One file covers a whole GUI run, from startup to exit; every log
        line is appended (and flushed) immediately so a crash still leaves
        the record on disk."""
        try:
            EVENT_DIR.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = EVENT_DIR / f"event_{stamp}.log"
            self._event_log_path = path
            self._event_log_file = open(path, "a", encoding="utf-8")
            self._event_log_file.write(
                f"=== mtk-gui session started {stamp} ===\n")
            self._event_log_file.flush()
        except OSError:
            # logging must never block the GUI from starting
            self._event_log_path = None
            self._event_log_file = None

    def _append_event_log(self, text):
        """Show a line in the Event Log and mirror it into the session
        auto-save file."""
        self.event_log.appendPlainText(text)
        if self._event_log_file is not None:
            try:
                self._event_log_file.write(text + "\n")
                self._event_log_file.flush()
            except OSError:
                pass

    def _clear_event_log(self):
        """Clear the visible log. The session file keeps the full run and
        gets a separator so the audit trail stays complete."""
        self.event_log.clear()
        if self._event_log_file is not None:
            try:
                self._event_log_file.write(
                    "----- event log cleared on screen "
                    f"{datetime.now():%Y-%m-%d %H:%M:%S} -----\n")
                self._event_log_file.flush()
            except OSError:
                pass

    # ------------------------------------------------ instrument lights
    def _update_run_progress(self, current, total):
        """Update the status-bar progress bar during a test run."""
        if total > 1:
            self._last_progress = (current, total)  # restore point after
        if total <= 0:                              # a busy phase
            self.status_progress.setRange(0, 1)
            self.status_progress.setValue(0)
            self.status_progress.setFormat("Idle")
        else:
            self.status_progress.setRange(0, total)
            self.status_progress.setValue(current)
            self.status_progress.setFormat(
                f"{current}/{total} ({current * 100 // total}%)")

    def _on_run_phase(self, text):
        """Reflect background run phases on the progress bar: a busy
        (indeterminate) pulse while e.g. console channels connect, the
        numeric position once the sequence steps again."""
        if text == "Connecting console...":
            self.status_progress.setRange(0, 0)   # busy pulse
            self.status_progress.setFormat("Connecting console...")
        elif text:
            cur, total = self._last_progress
            if total > 1:
                self.status_progress.setRange(0, total)
                self.status_progress.setValue(cur)
                self.status_progress.setFormat(
                    f"{cur}/{total} ({cur * 100 // total}%)")
        else:
            self._update_run_progress(0, 0)

    def _connect_virtual_instruments(self):
        """Virtual mode: simulated instruments report connected at start."""
        self.instr_status.set_all("connected")
        for abbr, title in INSTRUMENTS:
            self._append_event_log(
                f"Instrument {abbr} ({title}): connected (virtual).")

    def _on_instrument_error(self, abbr):
        """Virtual equipment fault: red light, auto-recover after 2.5 s."""
        self.instr_status.set_state(abbr, "error")
        self._append_event_log(f"Instrument {abbr}: connection error.")
        QTimer.singleShot(2500,
                          lambda: self._recover_instrument(abbr))

    def _recover_instrument(self, abbr):
        if self.instr_status.states.get(abbr) == "error":
            self.instr_status.set_state(abbr, "connected")
            self._append_event_log(f"Instrument {abbr}: reconnected.")

    def _event_log_menu(self, pos):
        """Right-click menu: Copy / Clear / Save as."""
        menu = QMenu(self)
        act_copy = menu.addAction("Copy")
        act_clear = menu.addAction("Clear")
        menu.addSeparator()
        act_save = menu.addAction("Save as…")
        chosen = menu.exec(self.event_log.viewport().mapToGlobal(pos))
        if chosen is act_copy:
            self._copy_event_log()
        elif chosen is act_clear:
            self._clear_event_log()
        elif chosen is act_save:
            self._save_event_log_as()

    def _copy_event_log(self):
        """Copy selected text; with no selection copy the whole log."""
        cursor = self.event_log.textCursor()
        if cursor.hasSelection():
            QApplication.clipboard().setText(cursor.selectedText())
        else:
            QApplication.clipboard().setText(
                self.event_log.toPlainText())

    def _save_event_log_as(self):
        """Save all currently visible log content to a user-chosen file."""
        default = f"event_{datetime.now():%Y%m%d_%H%M%S}.log"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Event Log", default,
            "Log files (*.log);;Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            Path(path).write_text(
                self.event_log.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Event log saved: {path}")

    # ------------------------------------------------------------ close
    def closeEvent(self, event):
        # disconnect every serial / SSH console channel
        self.workflow_page.multi_console.close_all_channels()
        if self._event_log_file is not None:
            try:
                self._event_log_file.write(
                    f"=== session ended "
                    f"{datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
                self._event_log_file.close()
            except OSError:
                pass
            self._event_log_file = None
        event.accept()
