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
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QSettings, Qt, QThread,
                            QTimer, Signal)
from PySide6.QtGui import QAction, QActionGroup, QColor, QFontMetrics
from PySide6.QtWidgets import QTextBrowser
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
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

from . import project_config
from .equipment_page import EquipmentPage
from .permissions import (
    FIXTURE_ATE,
    FIXTURE_MANUAL,
    MANUAL_FIXTURE_NOTICE,
    ROLE_OPERATOR,
    ROLE_SUPERVISOR,
    LoginDialog,
    PermissionsDialog,
    load_permissions,
    save_permissions,
)
from .test_workflow_page import TestWorkFlowPage
from .engine.steps import op_step
from .version_info import get_version_info
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

#: Event Log verdict highlighting (user direction): PASS green,
#: FAIL red, Error orange - easy to spot the matching lines
_VERDICT_COLORS = {
    "pass": "#22c55e", "passed": "#22c55e",
    "fail": "#ef4444", "failed": "#ef4444",
    "error": "#f59e0b",
}
_VERDICT_RE = re.compile(
    r"\b(pass|passed|fail|failed|error)\b", re.IGNORECASE)


def _colorize_verdicts(escaped_text):
    """Wrap PASS / FAIL / Error words in colored spans (input must
    already be HTML-escaped)."""

    def _span(match):
        word = match.group(0)
        color = _VERDICT_COLORS[word.lower()]
        return (f'<span style="color:{color};'
                f'font-weight:bold;">{word}</span>')

    return _VERDICT_RE.sub(_span, escaped_text)


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
    """One colored LED per console channel (serial + SSH).

    M0 layout optimization: text names were removed - only the
    colored lights render, the channel names live on each LED's
    tooltip.  Rebuilt whenever the console channel set changes
    (add / remove) and re-colored on every connect / disconnect
    (multi_console's connection_changed signal -> sync_channels)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(6, 0, 6, 0)
        self._row.setSpacing(6)
        # user direction: a 'Console:' caption before the first LED
        caption = QLabel("Console:")
        caption.setObjectName("muted")
        self._row.addWidget(caption)
        self._leds = {}

    def sync_channels(self, channels):
        """Mirror the console channel set and connection states
        (full rebuild - channel sets change rarely; the caption at
        index 0 is kept)."""
        while self._row.count() > 1:
            item = self._row.takeAt(self._row.count() - 1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._leds = {}
        for key, ch in channels.items():
            led = StatusLed()
            led.setToolTip(f"{key}: {LED_TEXT['disconnected']}")
            self._row.addWidget(led)
            state = "connected" if ch.get("connected") else "disconnected"
            led.set_state(state)
            self._leds[key] = (led, key)


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


class _ToolsBatchWorker(QThread):
    """Background runner for one Tools > Set All instruments batch.

    Reuses the engine RealGateway public API only (execute_op with
    the instruments/reset op types + close) - no engine change.  The
    gateway is created lazily and cached on the main window so
    Connect all / Disconnect all / Reset all / Test all connections
    operate on the same session.
    """

    finished_sig = Signal(str, list, bool)

    def __init__(self, action: str, abbrs: list, gateway,
                 equipment: dict) -> None:
        """Prepare one batch run.

        Args:
            action:    One of Connect all / Disconnect all /
                       Reset all / Test all connections.
            abbrs:     Configured instrument abbreviations.
            gateway:   Cached RealGateway or None (created lazily).
            equipment: Verified equipment configuration from the
                       project YAML.
        """
        super().__init__()
        self.action = action
        self.abbrs = abbrs
        self.equipment = equipment
        self.gateway = gateway

    def run(self) -> None:
        """Execute the batch and emit the outcome (never raises)."""
        ok, lines = True, []
        try:
            from .engine.instruments import RealGateway
            gw = self.gateway
            if gw is None:
                gw = RealGateway(self.equipment)
            if self.action == "Disconnect all":
                gw.close()
                lines.append("all instrument connections closed")
            else:
                if self.action == "Test all connections":
                    # reconnect from scratch = a real connection test
                    gw.close()
                result = gw.execute_op(
                    "Init Instruments",
                    {"type": "instruments", "instruments": self.abbrs})
                lines.extend(result.lines or [])
                ok = result.verdict != "Error"
                if ok and self.action == "Reset all":
                    result = gw.execute_op(
                        "Reset Instruments",
                        {"type": "reset", "instruments": self.abbrs})
                    lines.extend(result.lines or [])
                    ok = result.verdict != "Error"
                if ok:
                    lines.append(f"{self.action}: all instruments OK")
            self.gateway = gw
        except Exception as exc:  # noqa: BLE001 - report, never crash
            ok = False
            lines.append(f"batch operation failed: {exc}")
        self.finished_sig.emit(self.action, lines, ok)


class _ComboWheelGuard(QObject):
    """App-wide guard (user direction): the mouse wheel must NOT
    change a CLOSED dropdown - scrolling over a combo changed the
    selection by accident.  Wheel events are swallowed (and propagate
    to the surrounding scroll area); the popup list itself keeps its
    wheel scrolling."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Wheel \
                and isinstance(obj, QComboBox) \
                and not obj.view().isVisible():
            event.ignore()
            return True
        return False


class MainWindow(QMainWindow):

    #: theme name whose QSS is CURRENTLY active app-wide (dedup guard
    #: for apply_gui_theme - see the docstring there)
    _applied_theme = None

    def __init__(self, role=ROLE_SUPERVISOR, mode="Real",
                 fixture=FIXTURE_ATE):
        super().__init__()
        # GUI-wide: the wheel never changes a closed dropdown
        self._wheel_guard = _ComboWheelGuard(self)
        QApplication.instance().installEventFilter(self._wheel_guard)
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
        # Fixture type from the login dialog (ATE / Manual, ATE is the
        # restart baseline): Manual globally disables fixture hardware
        # configuration, IO control and fixture-linked entries
        self.fixture_type = fixture
        self.fault_config = load_fault_config()

        # path of the currently loaded / saved project YAML (None = new)
        self._project_path = None
        # Module B report session batch (auto-captured per product)
        self._session_reports: list = []
        self._last_batch = None

        self._build_ui()
        self._build_menus()
        # restore the GUI colour theme chosen in a previous session
        self.apply_gui_theme(saved_theme())
        self.apply_permissions()

    # ---------------------------------------------------------------- size
    def _init_size(self):
        """Window sizing (V4.0 rule 6.7): a user-defined size from a
        previous session always wins; only without any saved geometry
        the window auto-fits the current screen (optimal size,
        centered, never oversized) ."""
        settings = QSettings(APP_ORG, APP_NAME)
        saved = settings.value("window/geometry")
        if saved is not None and self.restoreGeometry(saved):
            # clamp a restored size to the CURRENT screen (a geometry
            # saved on a larger display must never overflow the
            # present one) and keep the window centered
            avail = (self.screen()
                     or QApplication.primaryScreen()).availableGeometry()
            if (self.frameGeometry().width() > avail.width()
                    or self.frameGeometry().height() > avail.height()):
                self.resize(min(self.width(), avail.width() - 40),
                            min(self.height(), avail.height() - 40))
            self.move(
                avail.x() + max(0, (avail.width() - self.width()) // 2),
                avail.y() + max(0, (avail.height() - self.height()) // 2))
            return
        screen = self.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry()
        width = min(DEFAULT_WIDTH, available.width() - 40)
        height = min(DEFAULT_HEIGHT, available.height() - 40)
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2)

    def _lock_vertical_minimums(self):
        """Lock the post-polish vertical minimums (window height floor
        + Event Log pane floor) - scheduled after the first layout
        pass, see the setCentralWidget comment."""
        log = self.event_log
        # recompute the 9-row floor with the CURRENT font (the
        # construction-time value predates the global stylesheet, so
        # its metrics can be far smaller than the polished reality)
        fm = QFontMetrics(log.font())
        rows = (fm.lineSpacing() * 6 + 2 * log.frameWidth() + 6) * 1.5
        log.setMinimumHeight(max(log.minimumHeight(), int(rows)))
        if self._log_group is not None:
            self._log_group.setMinimumHeight(
                max(self._log_group.minimumHeight(),
                    self._log_group.minimumSizeHint().height()))
        # monotonic: the floor may grow (fonts, polished styles) but
        # never shrink back below an already-proven requirement
        self.setMinimumHeight(max(self.minimumHeight(),
                                  self.minimumSizeHint().height()))
        # a window already shown smaller than the fresh floor is
        # bumped up so the bottom region is never clipped
        if self.isVisible() and self.height() < self.minimumHeight():
            self.resize(self.width(), self.minimumHeight())

    def paintEvent(self, event):
        """First real paint == stylesheet polish is complete: lock the
        vertical minimums exactly once (a construction- or show-time
        snapshot still sees pre-polish font metrics)."""
        if not self._vmin_locked:
            self._vmin_locked = True
            QTimer.singleShot(0, self._lock_vertical_minimums)
        super().paintEvent(event)

    def showEvent(self, event):
        """Re-lock the vertical minimums on every show - GUI theme
        switches change fonts, so the floor must follow the current
        metrics, not a construction-time snapshot."""
        super().showEvent(event)
        QTimer.singleShot(0, self._lock_vertical_minimums)
        # the Manual-fixture notice pops once the project UI is visible
        if getattr(self, "_manual_notice_pending", False):
            self._manual_notice_pending = False
            QTimer.singleShot(0, self, self._show_manual_notice)

    def _remember_geometry(self):
        """Persist the user's manually chosen window geometry so the
        next start reuses it (restore falls back to screen-fit)."""
        QSettings(APP_ORG, APP_NAME).setValue(
            "window/geometry", self.saveGeometry())

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

        # T10: Channel Allocation tab (dedicated Power / Clock / GPIO
        # tables; data source = the Parse Nets result of the model)
        from mtkgui.gui.yamlbuild.channel_allocation import \
            ChannelAllocationPage
        self.channel_alloc_page = ChannelAllocationPage()
        self.tabs.addTab(self.channel_alloc_page, "Channel Allocation")
        # model injected AFTER addTab (PySide shiboken GC bug
        # workaround - see ChannelAllocationPage.__init__)
        self.channel_alloc_page.set_model(self.yaml_build_page.model)
        self.yaml_build_page.task_log.connect(
            self.channel_alloc_page.task_log)
        self.channel_alloc_page.task_log.connect(
            lambda level, msg:
                self._append_event_log(f"[{level}] {msg}"))

        # navigation: merged "Build ICT Test Work Flow Sequence" card
        # -> Test Work Flow tab, cursor on the ICT Test Cases table
        self.yaml_build_page.test_workflow_requested.connect(
            self._goto_test_workflow)
        # Power Rails config (Test Work Flow properties) -> Yaml Build
        # model: the configured rails land in the YAML preview / Apply
        self.workflow_page.rail_config_changed.connect(
            self._sync_rails_to_yaml)
        # the step edit dialog offers the nets PER TEST METHOD from
        # the Yaml Build model (parse result = single data source)
        self.workflow_page.net_catalog_provider = (
            lambda: self.yaml_build_page.model.imported.get(
                "testable_nets") or {})
        # Apply-to-YAML from the config pages: persist (done in the
        # page) then switch to the Yaml Build tab
        self.channel_alloc_page.apply_yaml_requested.connect(
            self._goto_yaml_build)
        # block-04 sequence builder accepted: merge the standard
        # operations on the Test Work Flow page, then apply to yaml
        self.yaml_build_page.ict_sequence_ready.connect(
            self._on_ict_sequence_ready)
        # valid Apply on the Yaml Build page -> offer the file save
        self.yaml_build_page.yaml_apply_committed.connect(
            self._on_yaml_apply_committed)

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
        # Version | Role | Mode | User | Progress (adaptive)
        # | Instruments | Consoles (LED-only) | Date
        sb = self.statusBar()

        # V4.0 / M0: dynamic GUI version label (vX.Y.Z.xxxx from
        # resources/version.json, written by the CI build pipeline);
        # missing/broken file -> static fallback + warning log
        self.version_info = get_version_info()
        from .gui_version import load_gui_version
        self.gui_version, self.gui_version_warning = load_gui_version()
        self.status_version = QLabel(f"GUI version: {self.gui_version}")
        self.status_version.setObjectName("muted")
        self.status_version.setStyleSheet("padding: 0 6px;")
        # display-only: not selectable / not editable
        self.status_version.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction)
        self.status_version.setToolTip(
            f"GUI build {self.gui_version} | "
            f"build info: {self.version_info.display()} "
            f"(source: {self.version_info.source})")
        sb.addWidget(self.status_version)
        self._append_event_log(
            f"GUI version: {self.gui_version}")
        if self.gui_version_warning:
            self._append_event_log(
                f"WARNING: {self.gui_version_warning}")
        self._append_event_log(
            f"Build: {self.version_info.display()} "
            f"(source: {self.version_info.source})")

        # Role / Mode badges: colored background + bold white text,
        # refreshed on File > Switch Account
        self.status_role = QLabel()
        self.status_mode = QLabel()
        sb.addWidget(self.status_role)
        sb.addWidget(self.status_mode)
        self._update_identity_status()

        self.status_user = QLabel(f"User: {getpass.getuser()}")
        self.status_user.setObjectName("muted")
        self.status_user.setStyleSheet("padding: 0 6px;")
        sb.addWidget(self.status_user)

        # global test-task progress: gray/empty when idle, live
        # 0-100% while running, fills full then auto-resets to 0 when
        # the job finishes (M0 layout optimization; the freed Station
        # ID space flows into the stretch here)
        self.status_progress = QProgressBar()
        self.status_progress.setTextVisible(True)
        self.status_progress.setFormat("Idle")
        self.status_progress.setRange(0, 1)
        self.status_progress.setValue(0)
        sb.addWidget(self.status_progress, 1)  # stretch = adaptive
        self._last_progress = (0, 1)
        self._progress_reset_pending = False

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

        # instrument connection lights: synced from the Equipment page
        # connect / disconnect (user report: the LEDs were force-set
        # green everywhere and never reflected the real state)
        self.equipment_page.instrument_connection_changed.connect(
            self._on_instrument_connection)
        # wire run progress to the status bar progress bar
        self.workflow_page.run_progress.connect(self._update_run_progress)
        # background phases (console connect, ...) -> busy progress bar
        self.workflow_page.phase_changed.connect(self._on_run_phase)
        self.workflow_page.instrument_error.connect(self._on_instrument_error)
        # task complete: fill the progress bar full then auto-reset
        self.workflow_page.run_finished.connect(
            self._finish_run_progress)
        # Module B: every counted product is captured into the session
        # batch (automatic report trigger, B4 §8.3)
        self.workflow_page.run_finished.connect(self._on_run_report_auto)
        # long-task progress + Event-Log detail from the Yaml Build
        # page (Excel import / publish, T6): global status bar + log
        self.yaml_build_page.task_progress.connect(self._on_task_progress)
        self.yaml_build_page.task_log.connect(
            lambda level, msg:
                self._append_event_log(f"[{level}] {msg}"))
        if self.mode == "Virtual":
            # simulated instruments come up shortly after the GUI starts
            QTimer.singleShot(800, self._connect_virtual_instruments)
        # restore the power-rails capture from the persisted Yaml Build
        # model state (channel allocation / previous rail config)
        QTimer.singleShot(0, self._sync_rails_to_workflow)

        # --- assemble the splitter: top | middle (tabs) | bottom --------
        self.splitter.addWidget(top)
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(log_group)
        # layout priority hardening (B1 final rule 4): no pane may
        # ever collapse - the Event Log and the status bar above it
        # are permanent system UI, the tabbed workspace only fills
        # the middle viewport and can never push them out
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setCollapsible(2, False)
        # hard vertical floors: the bottom region keeps at least the
        # full 9-row log plus caption under every sizing scenario
        log_group.setMinimumHeight(log_group.minimumSizeHint().height())
        self._log_group = log_group
        # top and bottom keep their natural size; the tabs take the rest
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        # initial sizes: top = all rows, bottom = log (1.5x of the
        # original 6 rows), middle = rest.  Enforced again after the
        # first layout pass - construction-time sizeHints distort the
        # distribution (same lesson as the P3 1:1 splitter fix).
        top_h = max(top.sizeHint().height(), 180)
        bottom_h = int(six_rows * 1.5) + 40
        middle_h = max(300, self.height() - top_h - bottom_h)
        initial = [top_h, middle_h, bottom_h]
        self.splitter.setSizes(initial)
        QTimer.singleShot(0, lambda: self.splitter.setSizes(initial))

        self.setCentralWidget(central)
        # hard vertical threshold (B1 final rule 2): lock the window
        # height minimum AFTER the first layout pass (stylesheets and
        # fonts only reach full size at polish time) so neither
        # programmatic resize nor user dragging can ever squeeze the
        # Event Log / status bar out of the visible area.  Width stays
        # flexible - horizontal squeeze is absorbed by internal
        # scrollbars.
        QTimer.singleShot(0, self._lock_vertical_minimums)

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
        self.act_close_yaml = file_menu.addAction(
            "Close Yaml", self.close_yaml)
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
        self.settings_menu = settings_menu  # keep the wrapper alive
        # supervisor-only: configure which rights operator accounts get
        self.act_permissions = settings_menu.addAction(
            "Operator Permissions…", self._open_permissions_dialog)
        # item 15: Auto-SN is a configuration function -> its entry
        # moved from the main running toolbar to the Settings menu
        # (checkable action owned by the workflow page).
        settings_menu.addAction(self.workflow_page.act_auto_sn)
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

        # ------------------------------------------- V4.0: Tools menu
        # final menu order (fixed): File / View / Settings -> Tools ->
        # Report -> Help (rightmost).  The menu bar is built once and
        # never reordered by page, project or window state.
        tools_menu = self.menuBar().addMenu("Tools")
        set_all = tools_menu.addMenu("Set All instruments")
        set_all.setToolTip("Batch operations on all instruments "
                           "configured in the project YAML")
        self.act_connect_all = set_all.addAction("Connect all")
        self.act_connect_all.setToolTip(
            "Batch connect all configured instruments and read the "
            "identification")
        self.act_connect_all.triggered.connect(
            lambda: self._tools_batch("Connect all"))
        self.act_disconnect_all = set_all.addAction("Disconnect all")
        self.act_disconnect_all.setToolTip(
            "Batch close all instrument connections")
        self.act_disconnect_all.triggered.connect(
            lambda: self._tools_batch("Disconnect all"))
        self.act_reset_all = set_all.addAction("Reset all")
        self.act_reset_all.setToolTip(
            "Batch reset all configured instruments")
        self.act_reset_all.triggered.connect(
            lambda: self._tools_batch("Reset all"))
        self.act_test_all = set_all.addAction("Test all connections")
        self.act_test_all.setToolTip(
            "Reconnect and identify every instrument to verify the "
            "connections")
        self.act_test_all.triggered.connect(
            lambda: self._tools_batch("Test all connections"))
        # persistent Tools gateway (lazily created, reused by the
        # batch operations; the run flow builds its own per run)
        self._tools_gateway = None
        self._tools_thread = None
        # one-shot paint-time vertical floor lock (see paintEvent)
        self._vmin_locked = False

        # ------------------- item 15: VS style Run menu -------------
        # All run / debug control entries moved here from the workflow
        # page Run Control panel; every item carries the standard
        # Visual Studio shortcut (bound on the shared QAction objects,
        # so the shortcuts work application-wide in real time).
        # item 17 rollback: the main top toolbar was removed - Run /
        # Stop returned to the Run Control panel as the primary
        # operation entrance; the Run menu keeps the VS shortcuts.
        run_menu = self.menuBar().addMenu("Run")
        self.run_menu = run_menu  # keep the Python wrapper alive
        wf = self.workflow_page
        run_menu.addAction(wf.btn_run)                  # F5
        run_menu.addAction(wf.act_run_without_debug)    # Ctrl+F5
        run_menu.addAction(wf.btn_stop)                 # Shift+F5
        run_menu.addAction(wf.act_restart)              # Ctrl+Shift+F5
        run_menu.addSeparator()
        run_menu.addAction(wf.btn_step)                 # F10
        run_menu.addAction(wf.act_step_into)            # F11
        run_menu.addAction(wf.btn_continue)             # Shift+F11
        run_menu.addSeparator()
        run_menu.addAction(wf.act_toggle_breakpoint)    # F9
        run_menu.addAction(wf.act_clear_breakpoints)    # Ctrl+Shift+F9
        run_menu.addAction(wf.act_run_to_cursor)        # Ctrl+F10

        # ---------------------------------------------- V4.0: Report menu
        self.report_menu = self.menuBar().addMenu("Report")
        self.report_menu.addAction("Generate Report…",
                                   self._open_dut_report)
        self.report_menu.addAction("Event Log", self._open_report_event_log)
        self.report_menu.addAction("Statistics", self._open_statistics)

        # ------------------------------------------------ V4.0: Help menu
        # Help stays the rightmost menu of the fixed final order
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

    # ------------------------------------------------- V4.0 Tools batch
    _TOOL_ABBRS = ("DAQM", "DAQ", "PSU")

    #: status-bar abbreviation -> the Equipment page config keys that
    # implement it (user report: the lookup used the ABBREVIATIONS as
    # config keys - daq973a / u2355a / psu - and never matched, so
    # 'No instruments are configured' popped up on a valid project)
    _TOOL_KEYS = {
        "DAQM": ("daq973a",),
        "DAQ": ("u2355a",),
        "PSU": ("psu",),
    }

    def _configured_instruments(self) -> list[str]:
        """Instrument abbreviations configured in the current project.

        Returns:
            Abbreviations whose underlying Equipment-page config keys
            exist (the verified YAML equipment section), in fixed
            order.
        """
        configs = getattr(self.equipment_page, "configs", {}) or {}

        def _configured(abbr):
            return any(k in configs and (
                (configs.get(k) or {}).get("fields")
                or (configs.get(k) or {}).get("connection"))
                for k in self._TOOL_KEYS.get(abbr, ()))

        return [k for k in self._TOOL_ABBRS if _configured(k)]

    def _tools_batch(self, action: str) -> None:
        """Tools > Set All instruments: run one batch operation over
        every instrument configured in the project YAML.

        The batch runs on a worker thread (the UI never freezes on
        slow instruments); results land in the Event Log, failures
        pop up with Equipment-page guidance.
        """
        abbrs = self._configured_instruments()
        if not abbrs:
            QMessageBox.warning(
                self, "Set All instruments",
                "No instruments are configured in the project "
                "YAML.\n\nPlease go to the Equipment page and check "
                "the instrument configuration, ports and connection "
                "parameters first.")
            return
        if self.mode == "Virtual":
            # Virtual mode: there is no real rack - the RealGateway
            # would fail on the missing 'Address' YAML field even
            # though every Equipment-page dialog connects virtually.
            # Report the virtual result directly (no worker thread).
            lines = [f"{abbr} connect OK (virtual)" for abbr in abbrs] \
                if action == "Connect all" else \
                [f"{abbr} OK (virtual)" for abbr in abbrs]
            self._tools_batch_done(action, lines, True)
            return
        if self._tools_thread is not None and self._tools_thread.isRunning():
            QMessageBox.information(
                self, "Set All instruments",
                "A batch operation is already running - please wait "
                "for it to finish.")
            return
        self._append_event_log(
            f"[Tools] {action}: start ({', '.join(abbrs)})")
        self.statusBar().showMessage(f"{action}…")
        self._tools_thread = _ToolsBatchWorker(
            action, abbrs, self._tools_gateway,
            dict(self.equipment_page.configs))
        self._tools_thread.finished_sig.connect(self._tools_batch_done)
        self._tools_thread.start()

    def _tools_batch_done(self, action: str, lines: list,
                          ok: bool) -> None:
        """Batch result: log every line, popup failures with
        Equipment-page guidance."""
        if self._tools_thread is not None:
            # keep the gateway session (opened drivers) for reuse
            self._tools_gateway = self._tools_thread.gateway
        for line in lines:
            self._append_event_log(f"[Tools] {action}: {line}")
        # the status-bar LEDs follow the batch result (same truth as
        # the Equipment page connect state)
        state = {"Connect all": "connected",
                 "Disconnect all": "disconnected"}.get(action)
        if state:
            for abbr in self._configured_instruments():
                if abbr in self.instr_status.states:
                    self.instr_status.set_state(abbr, state)
        if ok:
            self.statusBar().showMessage(f"{action}: OK", 5000)
        else:
            self.statusBar().showMessage(f"{action}: FAILED", 5000)
            QMessageBox.warning(
                self, f"{action} failed",
                "One or more instruments could not be operated.\n\n"
                "Please go to the Equipment page and check the "
                "instrument configuration, ports and connection "
                "parameters.\n\n"
                + "\n".join(lines))

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
        """Report > Generate Report: DUT detail + batch summary for the
        current session (Module B) - preview HTML + CSV export."""
        from mtkgui.engine.report import (
            BatchSummary,
            DutReport,
            save_batch_csv,
            save_dut_csv,
        )
        page = self.workflow_page
        report = DutReport.from_session(page)
        summary = BatchSummary(reports=[report])
        # preview: DUT detail + batch statistics (print view = the HTML)
        box = QMessageBox(self)
        box.setWindowTitle("Generate Report")
        browser = QTextBrowser()
        browser.setHtml(report.to_html() + "<hr>" + summary.to_html())
        browser.setMinimumSize(680, 460)
        box.layout().addWidget(browser)
        box.setStandardButtons(QMessageBox.StandardButton.Close)
        # export (Operator: current session is read-only preview only)
        if self.role == ROLE_SUPERVISOR:
            out_dir = Path("reports")
            dut_csv = save_dut_csv(report, out_dir)
            batch_csv = save_batch_csv(summary, out_dir)
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] Report exported: "
                f"{dut_csv} + {batch_csv}")
        box.exec()

    def _on_run_report_auto(self, summary: dict) -> None:
        """Automatic report capture: every counted product appends to
        the session batch (B4 §8.3 trigger)."""
        if not summary.get("counted"):
            return
        from mtkgui.engine.report import BatchSummary, DutReport
        report = DutReport.from_session(self.workflow_page)
        self._session_reports.append(report)
        # keep the latest batch on hand for Report > Batch Summary
        self._last_batch = BatchSummary(reports=list(self._session_reports))

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
        # Yaml Build page (the YAML config editor): operator accounts
        # can view the generated YAML but not edit / apply it (T5)
        can_yaml_build = supervisor or perm.get("edit_yaml_build", False)
        idx_yaml = self.tabs.indexOf(self.yaml_build_page)
        if idx_yaml >= 0:
            self.tabs.setTabVisible(idx_yaml, can_yaml_build)
        self.yaml_build_page.set_edit_allowed(can_yaml_build)
        # T10 Channel Allocation: operators view only (dropdown cells
        # disabled; the tab itself stays visible for reporting)
        self.channel_alloc_page.set_edit_allowed(can_yaml_build)
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
        self._apply_fixture_mode()
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Logged in: {self.role}")

    def _apply_fixture_mode(self):
        """Fixture-type linkage (spec item 5): Manual mode globally
        disables every fixture hardware configuration entry, IO control
        and fixture-linked operation; a fixed friendly notice pops up
        once per login (non-blocking, manually closable)."""
        manual = self.fixture_type == FIXTURE_MANUAL
        self.equipment_page.set_manual_fixture(manual)
        # notice pops once the window becomes visible (showEvent); a
        # pending flag survives mode switches without leaking timers
        self._manual_notice_pending = manual
        if manual:
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] Fixture: Manual mode - "
                "fixture hardware / IO control disabled")
            if self.isVisible():
                QTimer.singleShot(0, self, self._show_manual_notice)

    def _show_manual_notice(self):
        """One-shot Manual-fixture notice (fixed wording, closable)."""
        QMessageBox.information(
            self, "Manual Fixture", MANUAL_FIXTURE_NOTICE)

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
        role, mode, fixture = result
        self.role = role
        # Virtual mode is supervisor-only; operators fall back to Real
        self.mode = mode if role == ROLE_SUPERVISOR else "Real"
        # fixture choice is per-login only (ATE restart baseline)
        self.fixture_type = fixture
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
        if isinstance(config, dict) and \
                ("yaml_build" in config or "plan" in config):
            # published plan file (plan + yaml_build sections, the
            # Yaml Build page output) -> restore into the build model
            errors = self.yaml_build_page.model.apply_yaml_dict(config)
            self._sync_rails_to_workflow()
            self.yaml_build_page.refresh_all()
            if errors:
                QMessageBox.warning(self, "Load Warnings",
                                    "\n".join(errors))
            self._project_path = path
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] Plan yaml loaded: {path}")
            return
        project_config.apply_config(
            config, self.workflow_page, self.equipment_page,
            self.yaml_build_page.model)
        self._sync_rails_to_workflow()
        self.yaml_build_page.refresh_all()
        self._project_path = path
        self.workflow_page.set_project_file(path)
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Yaml loaded: {path}")

    def close_yaml(self):
        """File > Close Yaml: drop the current project and reset the
        GUI to the factory no-yaml state (blank product info, default
        stop policies, empty ICT/FCT tables, no rails / consoles,
        equipment defaults, fresh Yaml Build model)."""
        if self._project_path:
            answer = QMessageBox.question(
                self, "Close Yaml",
                "Close the current YAML and reset to the factory "
                "state?\n\nUnsaved changes are kept on disk only if "
                "you saved before.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        page = self.workflow_page
        # product info + stop policies back to the factory defaults
        page.part_edit.setText("")
        page.core_edit.setText("")
        page.batch_edit.setText("")
        page.serial_edit.setText("")
        page.stop_if_fail_cb.setChecked(False)
        page.stop_if_short_cb.setChecked(True)
        page.auto_sn.setChecked(False)
        page._runner.set_retry(0, source="factory")
        page._runner.reset_results()
        # overall flow EN + tables / rails / consoles -> no-yaml state
        page.set_overall_en([True, True])
        page.clear_tables()
        page.set_project_file(None)
        # equipment defaults (same shape apply_config restores into)
        from mtkgui.equipment_page import _mock_configs
        self.equipment_page.configs = _mock_configs()
        # Yaml Build model -> fresh (apply_state of an empty state
        # clears imported nets / allocation / rail config, keeps the
        # factory parameter defaults)
        self.yaml_build_page.model.apply_state({})
        self._sync_rails_to_workflow()
        self.yaml_build_page.refresh_all()
        self._project_path = None
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Yaml closed - "
            "GUI reset to the factory state")

    def _goto_test_workflow(self):
        """Merged 'Build ICT Test Work Flow Sequence' card: switch to
        the Test Work Flow tab and focus the ICT Test Cases table
        (cursor on the first case row)."""
        self.tabs.setCurrentWidget(self.workflow_page)
        table = self.workflow_page.ict
        table.setFocus()
        table.setCurrentCell(0, 1)
        table.scrollToTop()

    #: the canonical standard-operation skeleton around the generated
    #: tests (impedance tests run BEFORE power-on: a short under power
    #: risks damaging the board)
    _ICT_OPS_BEFORE_TEST = ("Init Instruments", "Fixture Clamp Down",
                            "Fixture Lock", "Fixture E-Stop Healthy")
    _ICT_OPS_MID = ("Power On DUT",)
    _ICT_OPS_AFTER_TEST = ("Power Off DUT", "Fixture Unlock",
                           "Fixture Release", "Reset Instruments")

    def _on_ict_sequence_ready(self, tests):
        """Block-04 sequence builder accepted: rebuild the ICT Test
        Cases table - the adjusted tests in order WITH the standard
        operations around them (impedance before power-on) - jump to
        the Test Work Flow page and offer the YAML save (apply)."""
        page = self.workflow_page
        by_name = {s[1]: s for s in page.ict_steps if s[0] == "op"}

        def op(name):
            return by_name.get(name) or op_step(name)

        impedance = [t for t in tests if "Impedance" in t[1]]
        rest = [t for t in tests if "Impedance" not in t[1]]
        seq = [op(n) for n in self._ICT_OPS_BEFORE_TEST] + impedance \
            + [op(n) for n in self._ICT_OPS_MID] + rest \
            + [op(n) for n in self._ICT_OPS_AFTER_TEST]
        page.ict_steps = seq
        page.ict_enables = [True] * len(seq)
        page.ict_waits = [100] * len(seq)
        page.ict_timeouts = [5000] * len(seq)
        page.ict.setRowCount(len(seq))
        page._ict_edit_guard = True
        page._fill_ict(placeholder=True)
        page._ict_edit_guard = False
        self._goto_test_workflow()
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] ICT test sequence applied: "
            f"{len(tests)} tests + standard operations")
        # apply to yaml: the same save dialog as the preview Apply
        self._on_yaml_apply_committed()

    def _goto_yaml_build(self):
        """Apply-to-YAML from the Channel Allocation / Power Tree
        page: the page already persisted its config into the model -
        switch to the Yaml Build tab and repaint the preview."""
        self._sync_rails_to_workflow()
        self.tabs.setCurrentWidget(self.yaml_build_page)
        self.yaml_build_page.refresh_all()

    def _sync_rails_to_workflow(self):
        """Feed the Test Work Flow page's power-rails capture from the
        Yaml Build model (user report: 'no rails defined' - the rail
        set was empty unless a project file carried it).  Priority:
        the model's power_rails_up_sequence rail set, else DERIVED
        from the Channel Allocation power rows (every net with an
        assigned U2355A AI power-rails channel becomes a rail; the
        nominal is parsed from the net name)."""
        model = self.yaml_build_page.model
        seq = model.power_rails_up_sequence or {}
        rails = [dict(r) for r in (seq.get("rails") or [])]
        if not rails:
            rails = self._rails_from_allocation(
                model.get_channel_allocation())
        if not rails:
            return
        palette = ("#ef4444", "#22c55e", "#3b82f6", "#f59e0b",
                   "#a855f7", "#06b6d4", "#84cc16", "#f97316")
        page_rails = []
        for i, r in enumerate(rails):
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            nominal = r.get("nominal_v")
            if nominal in (None, "", 0, "0"):
                from mtkgui.gui.yamlbuild.ict_sequence import \
                    expected_voltage
                nominal = expected_voltage(name) or 0.0
            page_rails.append((
                name, r.get("color") or palette[i % len(palette)],
                float(nominal or 0.0),
                float(r.get("ramp_offset_s") or 0.0)))
        if not page_rails:
            return
        self.workflow_page.set_rails(page_rails)
        if seq.get("sample_rate_hz"):
            self.workflow_page.cap_rate = int(seq["sample_rate_hz"])
        if seq.get("pre_trigger_s") is not None:
            self.workflow_page.cap_start = float(seq["pre_trigger_s"])
        if seq.get("post_trigger_s"):
            self.workflow_page.cap_end = float(seq["post_trigger_s"])
        self.workflow_page.rail_widget.t_start = \
            self.workflow_page.cap_start
        self._append_event_log(
            f"Power rails: {len(page_rails)} rails configured "
            f"from the Yaml Build model.")

    @staticmethod
    def _rails_from_allocation(alloc):
        """Derive rail dicts from the Channel Allocation power rows:
        every net with an assigned 'U2355A AI..' power-rails channel,
        ordered by channel number."""
        rows = (alloc or {}).get("power") or []
        derived = []
        for row in rows:
            channel = str(row.get("power_rails") or "")
            net = str(row.get("net") or "").strip()
            if not net or "U2355A AI" not in channel:
                continue
            digits = "".join(ch for ch in channel if ch.isdigit())
            derived.append((int(digits) if digits else 999,
                            {"name": net, "ramp_offset_s": 0.0}))
        derived.sort(key=lambda item: item[0])
        return [r for _ch, r in derived]

    def _on_yaml_apply_committed(self):
        """The Apply button on the Yaml Build page succeeded (YAML
        valid, config in the model): with a loaded project yaml ask
        whether to overwrite it or save to a new file; without one
        only Save-as is possible."""
        if not self._project_path:
            self.save_yaml_as()
            return
        box = QMessageBox(self)
        box.setWindowTitle("Apply Yaml")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            "The YAML is valid and applied.\n"
            "Save the configuration to a file?")
        btn_overwrite = box.addButton(
            "Overwrite current yaml",
            QMessageBox.ButtonRole.AcceptRole)
        btn_new = box.addButton(
            "Save to a new yaml file…",
            QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_overwrite:
            self._save_yaml_to(self._project_path)
        elif clicked is btn_new:
            self.save_yaml_as()

    def apply_and_save_yaml(self):
        """File > Apply and Save Yaml: save back to the current file.

        Without a current file (never loaded/saved) this falls back to
        Save as Yaml."""
        if not self._project_path:
            self.save_yaml_as()
            return
        self._save_yaml_to(self._project_path)

    def _build_project_config(self):
        """The full project configuration dict: the workflow/equipment
        pages PLUS the Yaml Build model state (parse result, channel
        allocation, power tree draft) so a reload restores the edited
        state instead of re-running the automatic analysis."""
        return project_config.build_config(
            self.workflow_page, self.equipment_page,
            self.yaml_build_page.model.to_dict())

    def _sync_rails_to_yaml(self):
        """The Power Rails properties were confirmed on the Test Work
        Flow page: push the capture config into the Yaml Build model so
        it shows up in the YAML preview and survives the Apply."""
        self.yaml_build_page.apply_power_rails(
            project_config.rails_up_sequence_config(self.workflow_page))

    def save_yaml_as(self):
        """File > Save as Yaml: always ask for a (new) file name.

        The suggested name follows
        ProductPartNumber_CoreID_Batch_rev1.0.yaml."""
        config = self._build_project_config()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as Yaml",
            project_config.default_filename(config),
            "YAML files (*.yaml *.yml)")
        if not path:
            return
        self._save_yaml_to(path)

    def _save_yaml_to(self, path):
        config = self._build_project_config()
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
        application (all windows and dialogs) and remember the choice.

        Re-setting an IDENTICAL app stylesheet is skipped: Qt re-polishes
        every widget of every live window on each setStyleSheet call,
        which is pathological with many windows alive (the test suite
        spawns dozens of MainWindow instances - each redundant re-apply
        cost seconds of 100 % CPU, appearing as a hung run)."""
        if name not in GUI_THEMES:
            return
        if MainWindow._applied_theme != name:
            QApplication.instance().setStyleSheet(build_qss(name))
            MainWindow._applied_theme = name
        QSettings(APP_ORG, APP_NAME).setValue("gui_theme", name)
        # theme fonts restyle every metric: re-prove the vertical
        # floor once the new stylesheet is polished
        QTimer.singleShot(0, self._lock_vertical_minimums)

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
        auto-save file.  Every entry carries the DATE-TIME stamp (user
        direction: no User / identity prefix); PASS / FAIL / Error
        verdicts are highlighted in their own color so the matching
        log lines are easy to find."""
        from html import escape
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plain = f"{stamp} {text}"
        colored = _colorize_verdicts(escape(text))
        self.event_log.appendHtml(
            f'<span style="color:#9ca3af;">{stamp}</span> {colored}')
        if self._event_log_file is not None:
            try:
                self._event_log_file.write(plain + "\n")
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
        """Update the status-bar progress bar during a test run.

        A running test cancels any pending finish-reset (a new job may
        start within the reset grace window)."""
        self._progress_reset_pending = False
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

    def _finish_run_progress(self):
        """Task complete: fill the bar full, then auto-reset to the
        gray empty Idle state (grace window so the 100% is visible)."""
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(100)
        self.status_progress.setFormat("Complete (100%)")
        self._progress_reset_pending = True
        QTimer.singleShot(800, self._reset_run_progress)

    def _reset_run_progress(self):
        """Auto-reset the progress bar to gray empty Idle (honours the
        pending flag so a newly started run is never clobbered)."""
        if not self._progress_reset_pending:
            return
        self._progress_reset_pending = False
        self.status_progress.setRange(0, 1)
        self.status_progress.setValue(0)
        self.status_progress.setFormat("Idle")

    # --------------------------------------- long-task progress (T6)
    def _on_task_progress(self, percent, label):
        """Global status-bar progress for page long tasks (Excel
        import, YAML publish, design parse, ...): percent 0 starts the
        task, stages update it, 100 fills it and auto-resets.  GUI
        rendering only - the task kernels are untouched."""
        if percent <= 0:
            # a new task cancels any pending reset and shows its label
            self._progress_reset_pending = False
            self.status_progress.setRange(0, 100)
            self.status_progress.setValue(0)
            self.status_progress.setFormat(label or "Working...")
        elif percent >= 100:
            self._finish_run_progress()
        else:
            self._progress_reset_pending = False
            self.status_progress.setRange(0, 100)
            self.status_progress.setValue(percent)
            self.status_progress.setFormat(f"{label} ({percent}%)")

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

    def _on_instrument_connection(self, key, connected):
        """Equipment page instrument dialog connect / disconnect ->
        sync the matching status-bar LED (user report: never synced)."""
        abbr = EquipmentPage._INSTRUMENT_ABBR.get(key)
        if abbr:
            self.instr_status.set_state(
                abbr, "connected" if connected else "disconnected")

    def _connect_virtual_instruments(self):
        """Virtual mode: the simulated instruments are READY, but the
        status-bar LEDs reflect the EQUIPMENT PAGE connect state (user
        direction: no force-green - the operator connects manually and
        the LEDs follow)."""
        self._append_event_log(
            "Virtual mode: simulated instruments ready - connect on "
            "the Equipment page; the status-bar LEDs follow that "
            "state.")

    def _on_instrument_error(self, abbr):
        """Virtual equipment fault: red light, auto-recover after 2.5 s."""
        self.instr_status.set_state(abbr, "error")
        self._append_event_log(
            f"Instrument {abbr}: equipment fault "
            f"(virtual fault injection, auto-recover).")
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
        # M0 ordered cleanup: tear down child-dialog bindings and
        # instances, flush the Qt event queue (mitigates the harmless
        # macOS IMKCFRunLoopWakeUpReliable mach-port noise on exit)
        self._cleanup_child_dialogs()
        # --- original close workflow (preserved verbatim) -----------
        # remember the user's window geometry for the next start
        self._remember_geometry()
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
        # step 4: accept the close
        event.accept()

    def _cleanup_child_dialogs(self):
        """Ordered resource cleanup before the window goes away.

        Step 1: disconnect every custom signal/slot binding of cached
        child workers (the Tools batch thread); Step 2: explicitly
        destroy all child dialog instances; Step 3: flush the pending
        Qt event queue so no queued callback outlives the window.
        """
        # step 1 - disconnect custom bindings (batch worker)
        thread = getattr(self, "_tools_thread", None)
        if thread is not None:
            import warnings
            with warnings.catch_warnings():
                # a never-connected worker would warn "Failed to
                # disconnect (None)" - harmless, silence it
                warnings.simplefilter("ignore", RuntimeWarning)
                try:
                    thread.finished_sig.disconnect()
                except (RuntimeError, TypeError):
                    pass                  # already disconnected
            if thread.isRunning():
                thread.wait(2000)
        # step 2 - destroy every child dialog instance explicitly
        for dialog in self.findChildren(QDialog):
            dialog.deleteLater()
        # step 3 - flush pending Qt events
        QApplication.processEvents()
