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
    QAbstractSpinBox,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import project_config
from .equipment_page import EquipmentPage
from .gui.shell import resolve_tenant_base
from .gui.event_log_levels import (
    DETAILED,
    IMPORTANT,
    SIMPLIFIED,
    resolve_level,
    should_display,
    strip_leading_stamp,
)
from .gui.dialog_sizing import fit_dialog
from .gui.progress_dialog import ProgressDialog, busy_progress
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
from .qt_guard import qt_safe
from .startup_timing import (
    begin as _startup_begin,
    end as _startup_end,
    mark as _startup_mark,
)
from .test_workflow_page import TestWorkFlowPage
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

# Event Log auto-save lives in the modifiable Event Report folder
# (mtkgui.report_paths) - resolved at session start

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


#: QSettings key of the Event Log display level (M11)
EVENT_LOG_LEVEL_KEY = "event_log/level"
#: tooltip of the (disabled) Event Log entries on Operator accounts
OPERATOR_EVENT_LOG_TIP = "Operator accounts use the simplified event log"


def load_event_log_level(role, settings=None):
    """Display level of the Event Log for ``role`` (M11 F3).

    Operator accounts ALWAYS get the simplified log - their Settings
    entries are disabled, so Detailed can never be enabled for them.
    A Supervisor keeps the persisted choice; without a saved value the
    detailed log is the default.

    Args:
        role: ``ROLE_OPERATOR`` or ``ROLE_SUPERVISOR``.
        settings: Optional QSettings instance (tests inject a temp
                  file instead of the user preferences).

    Returns:
        ``"simplified"`` or ``"detailed"``.
    """
    if role == ROLE_OPERATOR:
        return SIMPLIFIED
    if settings is None:
        settings = QSettings(APP_ORG, APP_NAME)
    saved = str(settings.value(EVENT_LOG_LEVEL_KEY, "") or "").strip().lower()
    return saved if saved in (SIMPLIFIED, DETAILED) else DETAILED


def save_event_log_level(level, settings=None):
    """Persist the Supervisor's Event Log choice (next login keeps it).

    Args:
        level: ``"simplified"`` or ``"detailed"``.
        settings: Optional QSettings instance (tests inject a temp
                  file instead of the user preferences).
    """
    if settings is None:
        settings = QSettings(APP_ORG, APP_NAME)
    settings.setValue(
        EVENT_LOG_LEVEL_KEY,
        level if level in (SIMPLIFIED, DETAILED) else DETAILED)
    settings.sync()


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
        # hard minimum: the QStatusBar squeeze must hit the stretch
        # progress bar, never overlap the LEDs / captions (polish first
        # so the hint uses the real stylesheet font metrics)
        self.ensurePolished()
        self.setMinimumWidth(self.sizeHint().width())

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
                # hide IMMEDIATELY: after takeAt the widget keeps its
                # parent and renders at (0,0) - on top of the caption -
                # until the deferred delete lands (user report: a ghost
                # LED overlapped 'Console:' at startup)
                w.hide()
                w.deleteLater()
        self._leds = {}
        for key, ch in channels.items():
            led = StatusLed()
            led.setToolTip(f"{key}: {LED_TEXT['disconnected']}")
            self._row.addWidget(led)
            state = "connected" if ch.get("connected") else "disconnected"
            led.set_state(state)
            self._leds[key] = (led, key)
        # hard minimum: keeps the caption + LEDs from being squeezed into
        # each other when the status bar runs out of width (user report:
        # the LED overlapped the 'Console:' caption at 1920x1080).
        # ensurePolished first - the hint measured before the stylesheet /
        # fonts land is ~19px too small and the overlap returns.
        self.ensurePolished()
        self.setMinimumWidth(self.sizeHint().width())


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
                                       int(avail.height() * 0.85))
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
    change a CLOSED dropdown OR a numeric spin box - scrolling over
    either changed the value / selection by accident (e.g. over the
    Channel Allocation Nominal / Limit cells or the run-interval /
    failure-rate boxes).  Wheel events are swallowed for both; the
    popup list of a combo keeps its own wheel scrolling."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return False
        if isinstance(obj, QComboBox) and not obj.view().isVisible():
            event.ignore()
            return True
        if isinstance(obj, QAbstractSpinBox):
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
            # Python reference (not a Qt property): M13 suspends this
            # filter while the WebEngine sign-in window is on screen
            app._dialog_centerer = centerer
            self._dialog_centerer = centerer

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
        # Event Log display level (M11): role default, only a supervisor
        # may switch it (persisted under event_log/level); it must exist
        # before _build_ui writes the first log lines
        self._event_log_level = load_event_log_level(role)

        # path of the currently loaded / saved project YAML (None = new)
        self._project_path = None
        # Module B report session batch (auto-captured per product)
        self._session_reports: list = []
        self._report_workers: set = set()
        self._report_jobs: set = set()
        self._last_batch = None

        # M14 F1: apply the GUI theme BEFORE any widget is created.  A
        # global setStyleSheet re-polishes every already-built widget
        # (18 s on the Windows frozen build); applying it first lets the
        # widgets adopt the stylesheet incrementally while they are
        # created.
        # M14 F2 state: the secondary pages are built lazily after the
        # window is shown (see _build_secondary_ui).
        self._secondary_built = False
        self._secondary_scheduled = False
        self._can_yaml_build = True
        self._can_equipment_config = True
        self._manual_fixture = False
        self.apply_gui_theme(saved_theme())
        _startup_mark("ui: theme applied")

        self._build_ui()
        _startup_mark("ui: _build_ui done")
        self._build_menus()
        _startup_mark("ui: _build_menus done")
        self.apply_permissions()
        _startup_mark("ui: permissions applied")

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
        # M14 F1: the theme is applied before the UI exists, so its
        # scheduled first pass can run while _build_ui is still in
        # flight (the startup progress handler pumps events).  Nothing
        # to lock until the Event Log exists; paint / show re-lock it.
        log = getattr(self, "event_log", None)
        if log is None:
            return
        # recompute the 9-row floor with the CURRENT font (the
        # construction-time value predates the global stylesheet, so
        # its metrics can be far smaller than the polished reality)
        fm = QFontMetrics(log.font())
        rows = (fm.lineSpacing() * 6 + 2 * log.frameWidth() + 6) * 1.5
        log.setMinimumHeight(max(log.minimumHeight(), int(rows)))
        log_group = getattr(self, "_log_group", None)
        if log_group is not None:
            log_group.setMinimumHeight(
                max(log_group.minimumHeight(),
                    log_group.minimumSizeHint().height()))
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
            QTimer.singleShot(0, self, qt_safe(self._lock_vertical_minimums))
        super().paintEvent(event)

    def showEvent(self, event):
        """Re-lock the vertical minimums on every show - GUI theme
        switches change fonts, so the floor must follow the current
        metrics, not a construction-time snapshot."""
        super().showEvent(event)
        QTimer.singleShot(0, self, qt_safe(self._lock_vertical_minimums))
        # M14 F2: build the secondary tabs exactly once, after the
        # window is actually on screen (QTimer.singleShot(0) runs on
        # the first event-loop turn, i.e. before any user input is
        # processed - every menu action reaching those pages is safe).
        self._ensure_secondary_ui_deferred()
        # the Manual-fixture notice pops once the project UI is visible
        if getattr(self, "_manual_notice_pending", False):
            self._manual_notice_pending = False
            QTimer.singleShot(0, self, qt_safe(self._show_manual_notice))
        # same one-shot pattern for the Virtual-mode notice
        if getattr(self, "_virtual_notice_pending", False):
            self._virtual_notice_pending = False
            QTimer.singleShot(0, self, qt_safe(self._show_virtual_notice))

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
        _startup_mark("ui: TestWorkFlowPage built")
        self.tabs.addTab(self.workflow_page, "Test Work Flow")

        # M14 F2: Equipment / Yaml Build are only built after the
        # window is shown (_build_secondary_ui).  Empty placeholders
        # keep the fixed tab order (0 workflow, 1 equipment, 2 yaml)
        # visible from the first paint.
        self._equipment_placeholder = QWidget()
        self.tabs.addTab(self._equipment_placeholder, "Equipment")
        self._yaml_build_placeholder = QWidget()
        self.tabs.addTab(self._yaml_build_placeholder, "Yaml Build")
        # M10-FIX2 F7: make the tab switch immediate on the press and
        # idempotent - a first click that lands while a page is still
        # settling no longer gets swallowed (same index is a no-op)
        self.tabs.tabBarClicked.connect(self._on_tab_clicked)

        # NOTE: the dedicated Channel Allocation tab is GONE (user
        # direction 2026-10-13: single-page vertical workflow) - the
        # allocation tables are EMBEDDED in the Yaml Build page below
        # the block cards (yaml_build_page.channel_alloc); its task
        # log funnels through the page's own task_log signal below
        # (M11: ONE connection only - a second wiring doubled every
        # Event-Log line)

        # M14 F2: every Yaml Build / Equipment signal wiring lives in
        # _build_secondary_ui (the pages do not exist yet).  Only the
        # workflow-side hooks are set up here.
        # Power Rails config (Test Work Flow properties) -> Yaml Build
        # model: the configured rails land in the YAML preview / Apply
        self.workflow_page.rail_config_changed.connect(
            self._sync_rails_to_yaml)
        # M7: control-IO rows (net <-> U2355A DIO channel + isolation
        # verdict) consumed by the U2355A DIO Read/Write operations
        self.workflow_page.control_io_provider = self._control_io_rows

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

        # --- bottom: Event Log (slim flat header, collapsible) --------
        # renamed from "Test Log"; moved out of the Test Work Flow page.
        # 2026-10-13 (user direction): the macOS QGroupBox chrome wasted
        # vertical space - a flat one-row header (title + flat arrow
        # toggle) replaces it, margins stay minimal
        log_group = QWidget()
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(6, 2, 6, 2)
        log_layout.setSpacing(2)
        log_header = QHBoxLayout()
        log_title = QLabel("Event Log")
        log_title.setStyleSheet(
            "font-weight: bold; font-size: 11px;")
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        self._log_toggle = QToolButton()
        self._log_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._log_toggle.setAutoRaise(True)     # flat, native look
        self._log_toggle.setFixedSize(18, 16)
        self._log_toggle.setToolTip("Collapse Event Log")
        self._log_toggle.clicked.connect(self._toggle_event_log)
        log_header.addWidget(self._log_toggle)
        log_layout.addLayout(log_header)
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
        # 2026-10-13 (user direction): the log pane shrank 30 % (1.5x
        # of the original 6-row design -> 1.05x) and is collapsible
        self._log_expanded_h = int(six_rows * 1.05)
        self.event_log.setMinimumHeight(self._log_expanded_h)
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

        # THE single GUI version (user directive 2026-10-14): every
        # label renders the release version mtkgui.__version__
        # (starting v1.0.0.0) - develop commits never change it; the
        # build facts (branch / commit) come from version_info.
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
                f"WARNING: {self.gui_version_warning}", level="WARNING")
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
        self._progress_args = (0, 0)
        self._progress_reset_pending = False
        # 2026-10-17 user direction: the bar carries the ELAPSED task
        # time while a run is active (1 s clock tick)
        self._run_started_at = None
        self._run_clock = QTimer(self)
        self._run_clock.setInterval(1000)
        self._run_clock.timeout.connect(self._tick_run_clock)

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

        # instrument connection lights are wired to the Equipment page
        # in _build_secondary_ui (M14 F2)
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
        self.workflow_page.run_finished.connect(
            lambda: self._on_run_report_auto(
                getattr(self.workflow_page, "last_run_summary", {})))
        # long-task progress + Event-Log detail from the Yaml Build
        # page (Excel import / publish, T6) are wired in
        # _build_secondary_ui (M14 F2)
        if self.mode == "Virtual":
            # simulated instruments come up shortly after the GUI starts
            QTimer.singleShot(800, self, qt_safe(self._connect_virtual_instruments))

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
        # initial sizes: top = all rows, bottom = the shrunken log
        # (1.05x of the original 6 rows), middle = rest.  Enforced
        # again after the first layout pass - construction-time
        # sizeHints distort the distribution (same lesson as the P3
        # 1:1 splitter fix).
        top_h = max(top.sizeHint().height(), 180)
        bottom_h = self._log_expanded_h + 40
        middle_h = max(300, self.height() - top_h - bottom_h)
        initial = [top_h, middle_h, bottom_h]
        self.splitter.setSizes(initial)
        QTimer.singleShot(
            0, self, qt_safe(lambda: self.splitter.setSizes(initial)))

        self.setCentralWidget(central)
        # hard vertical threshold (B1 final rule 2): lock the window
        # height minimum AFTER the first layout pass (stylesheets and
        # fonts only reach full size at polish time) so neither
        # programmatic resize nor user dragging can ever squeeze the
        # Event Log / status bar out of the visible area.  Width stays
        # flexible - horizontal squeeze is absorbed by internal
        # scrollbars.
        QTimer.singleShot(0, self, qt_safe(self._lock_vertical_minimums))

        # Apply the default background to every console channel.
        self.apply_background(self.bg_color)

        # No YAML loaded yet -> clear ICT/FCT tables to 1 empty row each
        self.workflow_page.clear_tables()

    # ------------------------------------------- M14 F2 lazy pages
    def _ensure_secondary_ui_deferred(self) -> None:
        """Schedule the one-shot secondary-page build (showEvent)."""
        if self._secondary_built or self._secondary_scheduled:
            return
        self._secondary_scheduled = True
        QTimer.singleShot(0, self, qt_safe(self._build_secondary_ui))

    def _ensure_secondary_ui(self) -> None:
        """Build the secondary pages on demand (tests / early access).

        In the running application ``showEvent`` schedules the build,
        so nothing here runs during MainWindow construction; property
        access before that (test suite) builds them immediately.
        """
        if not self._secondary_built:
            self._build_secondary_ui()

    @property
    def equipment_page(self):
        """Equipment tab page (built lazily, M14 F2)."""
        self._ensure_secondary_ui()
        return self._equipment_page

    @property
    def yaml_build_page(self):
        """Yaml Build tab page (built lazily, M14 F2)."""
        self._ensure_secondary_ui()
        return self._yaml_build_page

    def _replace_secondary_tab(self, placeholder, page, title: str) -> None:
        """Swap a placeholder tab for the real page, keeping the index
        (and therefore the fixed tab order) and visibility."""
        idx = self.tabs.indexOf(placeholder)
        visible = self.tabs.isTabVisible(idx) if idx >= 0 else True
        if idx >= 0:
            self.tabs.removeTab(idx)
            self.tabs.insertTab(idx, page, title)
        else:  # pragma: no cover - defensive
            self.tabs.addTab(page, title)
        self.tabs.setTabVisible(self.tabs.indexOf(page), visible)
        placeholder.deleteLater()

    def _build_secondary_ui(self) -> None:
        """Build the Equipment / Yaml Build tabs after the window is up.

        M14 F2: these two pages cost ~4.4 s on the Windows build and the
        operator only sees the Test Work Flow tab first.  All signal
        wiring that touches them lives here; the workflow-side lambdas
        (net catalog / DAQ AI rail count) are evaluated at CALL time and
        are re-bound once the pages exist.
        """
        if self._secondary_built:
            return
        self._secondary_built = True
        self._secondary_scheduled = False

        self._equipment_page = EquipmentPage()
        _startup_mark("ui: EquipmentPage built")
        self._replace_secondary_tab(
            self._equipment_placeholder, self._equipment_page,
            "Equipment")

        self._yaml_build_page = YamlBuildPage()
        _startup_mark("ui: YamlBuildPage built")
        self._replace_secondary_tab(
            self._yaml_build_placeholder, self._yaml_build_page,
            "Yaml Build")

        yb = self._yaml_build_page
        # navigation: merged "Build ICT Test Work Flow Sequence" card
        # -> Test Work Flow tab, cursor on the ICT Test Cases table
        yb.test_workflow_requested.connect(self._goto_test_workflow)
        # the page-level "Close Yaml" / "Load current yaml" buttons
        # run the SAME slots as the File menu actions
        yb.close_yaml_requested.connect(self.close_yaml)
        yb.load_yaml_requested.connect(self._load_current_yaml)
        # the step edit dialog offers the nets PER TEST METHOD from
        # the Yaml Build model (parse result = single data source)
        self.workflow_page.net_catalog_provider = (
            lambda: yb.model.imported.get("testable_nets") or {})
        # the DAQ AI Net cell is read-only: its count comes from the
        # Channel Allocation tables (U2355A AI power rails)
        self.workflow_page.daq_ai_rail_count_provider = (
            lambda: len(self._rails_from_allocation(
                yb.model.channel_allocation)))
        # bidirectional sync (user direction 2026-10-14): the Build ICT
        # dialog seeds from the CURRENT ICT result rows (page -> dialog);
        # on OK the whole sequence flows back through ict_sequence_ready
        yb.current_ict_cases_provider = \
            self.workflow_page.current_ict_case_tuples
        # single sequence source (task): double-clicking a result row
        # asks the ONE Build dialog to open
        self.workflow_page.ict_build_requested.connect(yb.open_ict_sequence)
        self.workflow_page.fct_build_requested.connect(yb.open_fct_sequence)
        # block-04 sequence builder accepted: merge the standard
        # operations on the Test Work Flow page, then apply to yaml
        yb.ict_sequence_ready.connect(self._on_ict_sequence_ready)
        # P3-B5: block-07 FCT config accepted -> replace the FCT Test
        # Cases table with the generated sequence, then apply to yaml
        yb.fct_sequence_ready.connect(self._on_fct_sequence_ready)
        # reverse sync: the Build FCT dialog seeds its console commands
        # from the CURRENT FCT Test Cases rows whenever it opens
        yb.current_fct_cases_provider = \
            self.workflow_page.current_fct_case_dicts
        # valid Apply on the Yaml Build page -> offer the file save
        yb.yaml_apply_committed.connect(self._on_yaml_apply_committed)
        # instrument connection lights: synced from the Equipment page
        self._equipment_page.instrument_connection_changed.connect(
            self._on_instrument_connection)
        # Event-Log detail from the Yaml Build page (T6); the long-task
        # progress now drives the page's own FOREGROUND dialog
        # (ProgressBridge, M15) - the status-bar progress bar no longer
        # receives page tasks (user direction 2026-10-25)
        yb.task_log.connect(
            lambda level, msg:
                self._append_event_log(f"[{level}] {msg}"))

        self._apply_page_permissions()
        # restore the power-rails capture from the persisted Yaml Build
        # model state (channel allocation / previous rail config)
        QTimer.singleShot(0, self, qt_safe(self._sync_rails_to_workflow))

    def _apply_page_permissions(self) -> None:
        """Apply the role / mode / fixture state to the secondary pages
        (called once they exist; M14 F2)."""
        idx = self.tabs.indexOf(self._yaml_build_page)
        if idx >= 0:
            self.tabs.setTabVisible(idx, self._can_yaml_build)
        self._yaml_build_page.set_edit_allowed(self._can_yaml_build)
        self._yaml_build_page.channel_alloc.set_edit_allowed(
            self._can_yaml_build)
        self.act_import_excel.setEnabled(self._can_yaml_build)
        self.act_export_excel.setEnabled(self._can_yaml_build)
        self.act_export_ict_plan.setEnabled(self._can_yaml_build)
        self.act_import_ict_plan.setEnabled(self._can_yaml_build)
        self._equipment_page.set_config_allowed(self._can_equipment_config)
        self._equipment_page.set_mode(self.mode)
        self._equipment_page.set_manual_fixture(self._manual_fixture)

    def _on_tab_clicked(self, index: int) -> None:
        """M10-FIX2 F7: apply the tab click immediately and idempotently.

        ``QTabWidget`` switches on the mouse release; if the first
        press lands while the page is still settling (layout / focus
        hand-off) the switch can be lost.  Setting the index on the
        press makes it deterministic; clicking the current tab is a
        no-op.
        """
        if index >= 0 and index != self.tabs.currentIndex():
            _startup_mark(
                f"page switch -> {self.tabs.tabText(index)}",
                category="page")
            self.tabs.setCurrentIndex(index)

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
        # M19d: the Yaml Build page buttons are gone - Excel import /
        # export live here (permission-gated like the old buttons)
        self.act_import_excel = file_menu.addAction(
            "Import from Excel…", self._import_excel_menu)
        self.act_export_excel = file_menu.addAction(
            "Export to Excel…", self._export_excel_menu)
        # M19e: ICT Test Plan workbook <-> YAML sync (was the four
        # Parse-Nets buttons)
        self.act_export_ict_plan = file_menu.addAction(
            "Export ICT Test plan from Yaml to Excel",
            self._export_ict_plan_menu)
        self.act_import_ict_plan = file_menu.addAction(
            "Import ICT Test from Excel to Yaml",
            self._import_ict_plan_menu)
        file_menu.addSeparator()
        self.act_switch = file_menu.addAction(
            "Switch Account…", self.switch_account)
        file_menu.addAction("Exit", self.close)

        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(
            "Console Background Color…", self.choose_background)
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
        # M11: Event Log display level - exclusive pair, the choice is
        # persisted and re-applied on the next login.  Operators keep
        # the entries VISIBLE but disabled (simplified only).
        settings_menu.addSeparator()
        self._event_log_group = QActionGroup(self)
        self._event_log_group.setExclusive(True)
        self.act_event_log_simplified = settings_menu.addAction(
            "Event Log: Simplified")
        self.act_event_log_simplified.setCheckable(True)
        self._event_log_group.addAction(self.act_event_log_simplified)
        self.act_event_log_simplified.triggered.connect(
            lambda _checked=False: self._set_event_log_level(SIMPLIFIED))
        self.act_event_log_detailed = settings_menu.addAction(
            "Event Log: Detailed")
        self.act_event_log_detailed.setCheckable(True)
        self._event_log_group.addAction(self.act_event_log_detailed)
        self.act_event_log_detailed.triggered.connect(
            lambda _checked=False: self._set_event_log_level(DETAILED))
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
        # 2026-10-17 user direction: the menu items OPEN the output
        # folders - the reports themselves are generated automatically
        # after every counted test run
        self.report_menu = self.menuBar().addMenu("Report")
        self.report_menu.addAction("DUT Report",
                                   self._open_dut_report_folder)
        self.report_menu.addAction("Event Log",
                                   self._open_report_event_log)
        self.report_menu.addAction("DAQ CSV Data",
                                   self._open_daq_csv_folder)
        self.report_menu.addAction("Report Folder…",
                                   self._open_report_folder_settings)
        self.report_menu.addAction("Statistics", self._open_statistics)
        # 2026-10-27 user direction: SharePoint upload is temporarily
        # DISABLED for the general operator (the browser-session import
        # flow is too involved for the shop floor).  Keep the handler;
        # re-enable with setEnabled(True) once a simpler path is
        # approved by IT.
        self.sp_upload_action = self.report_menu.addAction(
            "SharePoint Upload…", self._open_sharepoint_upload)
        self.sp_upload_action.setEnabled(False)
        self.sp_upload_action.setToolTip(
            "Temporarily disabled (2026-10-27): SharePoint upload is "
            "turned off for the general operator. Re-enable in "
            "main_window.py when a simpler path is approved.")

        # ------------------------------------------------ V4.0: Help menu
        # Help stays the rightmost menu of the fixed final order; the
        # User Guide opens ONE web page containing every chapter and
        # Version History opens the release log (releases only).
        self.help_menu = self.menuBar().addMenu("Help")
        self.help_menu.addAction("User Guide", self._open_help)
        self.help_menu.addAction("Version History",
                                 self._open_version_history)
        self.help_menu.addSeparator()
        self.help_menu.addAction("About", self._open_about)

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
        # the RUN path shares this gateway session: Real-mode ICT
        # measurement rows / standard ops / rail capture go through it.
        # Without a connected gateway they fail honestly (Real mode
        # never simulates) - so hand it to the workflow page here and
        # retract it on Disconnect all.
        self.workflow_page.gateway = (
            None if action == "Disconnect all" else self._tools_gateway)
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
    def _open_help(self):
        """Help > User Guide: render the all-in-one User Guide (Module
        C, every docs/help/ chapter with a sidebar TOC) into a styled
        HTML page and open it in the system web browser."""
        from .gui.help_content import open_guide
        open_guide()

    def _open_version_history(self):
        """Help > Version History: render the release log (one entry
        per Release; develop commits are not recorded) into a styled
        HTML page and open it in the system web browser."""
        from .gui.help_content import open_version_history
        open_version_history()

    def _open_about(self):
        """Help > About: version, branch, build info (Module C)."""
        from .gui.help_content import about_html
        dlg = QDialog(self)
        dlg.setWindowTitle("About MTK GUI")
        lay = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setHtml(about_html())
        browser.setOpenExternalLinks(False)
        lay.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dlg.accept)
        lay.addWidget(buttons)
        fit_dialog(dlg, 460, 360)
        dlg.exec()

    def _generate_dut_report_files(self, report) -> None:
        """Write one DUT's certificate PDF + MES CSV into its IDENTITY
        folder under the DUT Report root (2026-10-17 user direction:
        folder AND file names carry Part# / Core ID / Batch# / Serial#
        / timestamp).  When this run captured a DAQ CSV, the report
        joins THAT folder; otherwise an identity folder is created.
        The CSV is written synchronously (fast file IO); the heavy
        1200-dpi PDF rasterization runs on a WORKER THREAD - the GUI
        stays responsive while the report renders (the user can start
        testing the next DUT immediately).  Failures are logged, never
        raised into the run path."""
        from mtkgui import report_paths
        try:
            from mtkgui.engine.report import save_dut_csv
            from mtkgui.gui import dut_pdf
            meta = self.workflow_page.product_info()
            out = report_paths.dut_folder()
            # identity folder: prefer THIS run's DAQ capture folder
            capture_csv = getattr(self.workflow_page, "rail_csv_path", None)
            if capture_csv and Path(capture_csv).is_file():
                run_dir = Path(capture_csv).parent
            else:
                run_dir = out / (
                    "_".join(dut_pdf.safe_name(v) for v in
                             (meta.get("part") or "NA",
                              meta.get("core_id") or "NA",
                              meta.get("batch") or "NA",
                              report.serial_no or "DUT"))
                    + f"_{datetime.now():%Y%m%d_%H%M%S}")
            run_dir.mkdir(parents=True, exist_ok=True)
            csv = save_dut_csv(report, run_dir, batch=meta.get("batch", ""),
                               core_id=meta.get("core_id", ""),
                               part=meta.get("part", ""))
            pdf_path = run_dir / dut_pdf.dut_pdf_name(report, meta)
            # dedup guard: the same run must never be rendered twice
            # (double run_finished / retried trigger would race two
            # workers on the same file)
            if str(pdf_path) in self._report_jobs:
                return
            self._report_jobs.add(str(pdf_path))
            html, images, chart_spec = dut_pdf.report_pdf_payload(report, meta)
            worker = dut_pdf.PdfRenderWorker(html, images, pdf_path,
                                             chart_spec)
            worker.done.connect(qt_safe(self._on_dut_pdf_done))
            worker.failed.connect(qt_safe(self._on_dut_pdf_failed))
            worker.fitted.connect(qt_safe(self._on_dut_pdf_fitted))
            worker.finished.connect(
                lambda w=worker, p=str(pdf_path):
                (self._report_workers.discard(w),
                 self._report_jobs.discard(p)))
            self._report_workers.add(worker)
            worker.start()
        except Exception as e:                   # noqa: BLE001
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] DUT report generation "
                f"failed: {e}")

    def _on_dut_pdf_done(self, path: str) -> None:
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] DUT report generated: "
            f"{Path(path).name}")

    def _on_dut_pdf_failed(self, error: str) -> None:
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] DUT report generation "
            f"failed: {error}")

    def _on_dut_pdf_fitted(self, pt: float) -> None:
        """AUTO-FIT observability: when wide content forced the body
        font below 8 pt, say so - a recurring shrink means the report
        layout needs a proper fix for that content shape."""
        if pt < 8.0:
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] DUT report auto-fit: body "
                f"font reduced to {pt} pt (content wider than A4)")

    def _on_run_report_auto(self, summary: dict) -> None:
        """Automatic report capture (B4 §8.3 trigger): every counted
        product appends to the session batch AND gets its certificate
        report generated immediately (2026-10-17 user direction).
        2026-10-17 refinement: the start is announced in the Event Log
        right away and the (heavier) rendering is DEFERRED a beat onto
        the event loop so the finished-run UI never freezes."""
        if not summary.get("counted"):
            return
        # M10-FIX4 F1: persist the finished unit into the statistics
        # history BEFORE any counter reset (Close Yaml).  Statistics
        # must never break a run: a failure only logs a WARNING.
        try:
            from mtkgui.gui.statistics_store import (
                append_run,
                record_from_page,
            )
            page = self.workflow_page
            runs = getattr(page, "cycle_times", None) or []
            if runs and append_run(record_from_page(page)) is None:
                raise OSError("run history is not writable")
        except Exception as exc:                # noqa: BLE001
            self._append_event_log(
                f"WARNING: statistics record not saved: {exc}",
                level=IMPORTANT)
        from mtkgui.engine.report import BatchSummary, DutReport
        report = DutReport.from_session(self.workflow_page)
        self._session_reports.append(report)
        # keep the latest batch on hand for Report > Batch Summary
        self._last_batch = BatchSummary(reports=list(self._session_reports))
        if report.items:
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] DUT report generating "
                f"({len(report.items)} items, serial "
                f"{report.serial_no or 'n/a'})...")
            QTimer.singleShot(
                150, self,
                qt_safe(lambda: self._generate_dut_report_files(report)))

    def _open_dut_report_folder(self):
        """Report > DUT Report: open the folder where the automatic
        DUT reports (PDF + MES CSV) land - <program>/DUT Report by
        default, the name is modifiable via Report > Report Folder…."""
        from mtkgui import report_paths
        self._open_report_dir(
            report_paths.dut_folder(), "DUT Report")

    def _open_daq_csv_folder(self):
        """Report > DAQ CSV Data: the DAQ captures live INSIDE the
        per-DUT identity folders under the DUT Report root - open
        that root."""
        from mtkgui import report_paths
        self._open_report_dir(report_paths.dut_folder(), "DAQ CSV Data")

    def _open_report_dir(self, path: Path, title: str) -> None:
        """Create-if-missing and open a report folder in the system
        file manager."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, title,
                                f"Cannot create the folder:\n{path}\n\n{e}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Opened {title} folder: {path}")

    def _open_report_folder_settings(self):
        """Report > Report Folder…: rename the two output folders
        (defaults 'DUT Report' / 'Event Report', next to the
        program).  New names apply to newly created files."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                                       QFormLayout, QLineEdit)
        from mtkgui import report_paths
        dut, event = report_paths.folder_names()
        dlg = QDialog(self)
        dlg.setWindowTitle("Report Folder Settings")
        form = QFormLayout(dlg)
        ed_dut = QLineEdit(dut)
        ed_event = QLineEdit(event)
        form.addRow("DUT Report folder:", ed_dut)
        form.addRow("Event Log folder:", ed_event)
        note = QLabel("Next to the program:\n"
                      f"{report_paths.program_dir()}\n\n"
                      "New names apply to newly created files.")
        note.setObjectName("muted")
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        report_paths.set_folder_names(ed_dut.text(), ed_event.text())
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] Report folders set: "
            f"'{ed_dut.text()}' / '{ed_event.text()}' "
            f"(under {report_paths.program_dir()})")

    def _open_report_event_log(self):
        """Report > Event Log: open the Event Log folder - the session
        .log auto-save files land in <program>/Event Report by
        default (name modifiable via Report > Report Folder…)."""
        from mtkgui import report_paths
        self._open_report_dir(
            report_paths.event_folder(), "Event Log")

    def _open_sharepoint_upload(self):
        """Report > SharePoint Upload…: site link + connectivity test +
        local folder + upload mode (real-time sync / packaged upload
        with a period).  Virtual mode drives the FakeSharePoint
        transport (demo), Real mode talks HTTP to the configured site.
        The 30 s auto-drive runs while the dialog is open.

        Temporarily disabled (2026-10-27) - the guard below keeps the
        handler from opening even if the menu item is re-enabled by
        another path."""
        if not (getattr(self, "sp_upload_action", None)
                and self.sp_upload_action.isEnabled()):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "SharePoint Upload",
                "SharePoint upload is temporarily disabled for the "
                "general operator (2026-10-27).\n\nRe-enable it in "
                "main_window.py when a simpler path is approved.")
            return
        from .gui.sharepoint_upload_dialog import SharePointUploadDialog
        dlg = SharePointUploadDialog(
            self, virtual=self.workflow_page.virtual_mode)
        # M11: the dialog stamps its own lines - the level marks the
        # upload result as an important event (shown in Simplified too)
        dlg.action_logged.connect(
            lambda msg: self._append_event_log(msg, level=IMPORTANT))
        # M13: PySide 6.10.3 segfaults (SIGSEGV in sbk_o_eventFilter ->
        # PySide::getWrapperForQObject) when a Python QApplication
        # event filter is installed while a QWebEngineView is alive -
        # i.e. the embedded SharePoint sign-in window.  Suspend the
        # app-wide Python filters for the dialog lifetime; they are
        # restored when it closes.
        suspended = self._suspend_app_filters()
        try:
            dlg.exec()
        finally:
            self._restore_app_filters(suspended)

    # ------------------------------------------------- event filters
    def _suspend_app_filters(self):
        """Remove the app-wide Python event filters (combo-wheel guard +
        dialog centerer) and return them so they can be restored."""
        app = QApplication.instance()
        filters = [self._wheel_guard,
                   getattr(app, "_dialog_centerer",
                           getattr(self, "_dialog_centerer", None))]
        installed = []
        for f in filters:
            if f is not None:
                app.removeEventFilter(f)
                installed.append(f)
        return installed

    def _restore_app_filters(self, filters):
        app = QApplication.instance()
        for f in filters:
            app.installEventFilter(f)

    def _open_statistics(self):
        """Report > Statistics: quality statistics dashboard (Yield /
        Avg Cycle Time / UPH / CpK / failure classification) fed from
        the live session or the append-only run history
        (config/statistics/runs.json), M10-FIX4 F1."""
        from .gui.statistics_dialog import StatisticsDialog
        dlg = StatisticsDialog(self.workflow_page, self)
        dlg.exec()

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
        # can view the generated YAML but not edit / apply it (T5);
        # T10 Channel Allocation (embedded there): operators view only.
        # M14 F2: stored here, applied by _apply_page_permissions once
        # the lazy pages exist.
        self._can_yaml_build = supervisor or perm.get(
            "edit_yaml_build", False)
        self._can_equipment_config = supervisor or perm.get(
            "equipment_config", False)
        # Virtual mode (supervisor only): fault-injection menu + pages
        virtual = supervisor and self.mode == "Virtual"
        self.act_fault_inject.setEnabled(virtual)
        self.workflow_page.set_mode(self.mode)
        self.workflow_page.set_virtual_fault(self.fault_config)
        self.workflow_page.multi_console.set_virtual_mode(virtual)
        # M11 F3: Event Log level follows the role (Operator always
        # simplified); the two Settings entries stay visible but are
        # supervisor-only, so an Operator can never enable Detailed
        operator = self.role != ROLE_SUPERVISOR
        self._event_log_level = load_event_log_level(self.role)
        for act in (self.act_event_log_simplified,
                    self.act_event_log_detailed):
            act.setEnabled(not operator)
            act.setToolTip(OPERATOR_EVENT_LOG_TIP if operator else "")
        self._sync_event_log_menu()
        # Virtual mode only simulates the ICT instruments - FCT always
        # runs on real hardware: one fixed notice per login (same
        # pattern as the Manual-fixture notice)
        self._virtual_notice_pending = virtual
        if virtual:
            self._append_event_log(
                "Mode: Virtual - only ICT instrument measurements are "
                "simulated; FCT always runs on real hardware",
                level=IMPORTANT)
            if self.isVisible():
                QTimer.singleShot(0, self, qt_safe(self._show_virtual_notice))
        self._apply_fixture_mode()
        # account switch (pages already built) re-applies the page bits
        if self._secondary_built:
            self._apply_page_permissions()
        self._append_event_log(
            f"Logged in: {self.role}", level=IMPORTANT)

    def _apply_fixture_mode(self):
        """Fixture-type linkage (spec item 5): Manual mode globally
        disables every fixture hardware configuration entry, IO control
        and fixture-linked operation; a fixed friendly notice pops up
        once per login (non-blocking, manually closable)."""
        manual = self.fixture_type == FIXTURE_MANUAL
        # M14 F2: remembered here, pushed into the lazy Equipment page
        # by _apply_page_permissions
        self._manual_fixture = manual
        # notice pops once the window becomes visible (showEvent); a
        # pending flag survives mode switches without leaking timers
        self._manual_notice_pending = manual
        if manual:
            self._append_event_log(
                "Fixture: Manual mode - fixture hardware / IO control "
                "disabled", level=IMPORTANT)
            if self.isVisible():
                QTimer.singleShot(0, self, qt_safe(self._show_manual_notice))

    def _show_manual_notice(self):
        """One-shot Manual-fixture notice (fixed wording, closable)."""
        QMessageBox.information(
            self, "Manual Fixture", MANUAL_FIXTURE_NOTICE)

    def _show_virtual_notice(self):
        """One-shot Virtual-mode notice (fixed wording, closable)."""
        import os
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            # headless runs (smoke / CI) have no user to acknowledge a
            # modal dialog - the Event-Log entry carries the notice
            self._append_event_log(
                "[Virtual] only ICT instrument measurements are "
                "simulated; FCT always runs on real hardware")
            return
        from .permissions import VIRTUAL_MODE_NOTICE
        QMessageBox.information(self, "Virtual Mode", VIRTUAL_MODE_NOTICE)

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
            "Virtual Fault Injection updated "
            f"(fail {cfg['test_fail_ratio']:.2f} %, "
            f"equipment error {cfg['equipment_error_ratio']:.2f} %)",
            level=IMPORTANT)

    def _set_event_log_level(self, level):
        """Settings > Event Log: Simplified / Detailed (M11 F3).

        Supervisor-only: the choice is persisted so the next login
        keeps it.  An Operator trigger (programmatic or a stale menu)
        only re-syncs the menu to the forced simplified state.

        Args:
            level: ``"simplified"`` or ``"detailed"``.
        """
        if self.role != ROLE_SUPERVISOR:
            self._sync_event_log_menu()
            return
        self._event_log_level = (
            level if level in (SIMPLIFIED, DETAILED) else DETAILED)
        save_event_log_level(self._event_log_level)
        self._sync_event_log_menu()
        self._append_event_log(
            f"Event log level: {self._event_log_level.capitalize()}",
            level=IMPORTANT)

    def _sync_event_log_menu(self):
        """Check the Settings action matching the active level."""
        simplified = self._event_log_level == SIMPLIFIED
        self.act_event_log_simplified.setChecked(simplified)
        self.act_event_log_detailed.setChecked(not simplified)

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
        """File > Load Yaml: pick a project YAML file and apply it.

        The load runs as a QTimer-driven stage chain in FRONT of a
        foreground modal progress dialog (2026-10-26: the big ICT plans
        used to show only a status-bar progress; the front dialog keeps
        the window responsive and visible) - see _begin_yaml_load."""
        _startup_begin("load yaml: file pick", category="ui",
                       wait=True)
        try:
            path, _ = QFileDialog.getOpenFileName(
                self, "Load Yaml", "", "YAML files (*.yaml *.yml)")
        finally:
            _startup_end("load yaml: file pick")
        if not path:
            return
        if self.workflow_page._runner.state != "idle":
            QMessageBox.information(
                self, "Run Active",
                "A test run is active - stop it before loading "
                "another project.")
            return
        self._begin_yaml_load(path)

    # ------------------------------------------------- staged yaml load
    def _begin_yaml_load(self, path: str) -> None:
        """Non-blocking YAML load (user direction 2026-10-15):

        1. a previously loaded project is closed FIRST - two test
           projects must never blend in the tables (silent auto-close,
           the manual File > Close Yaml keeps its confirm dialog);
        2. Run Control (Run/Stop, Long Run, Interval) and the
           double-click table editing are disabled while loading;
        3. a FOREGROUND modal progress dialog tracks the stages
           (2026-10-26: front progress bar replaces the status-bar-only
           progress for big plans like 96624);
        4. every control is restored once the load completes."""
        if getattr(self, "_yaml_loading", False):
            return
        self._yaml_loading = True
        self._yaml_config = None
        self._yaml_plan_errors = None
        _startup_begin("yaml load", category="io")
        self._yaml_load_dlg = ProgressDialog(
            self, "Loading project…", 0, 100, delay=0.3)
        self._yaml_load_dlg.show_delayed()
        self._yaml_load_queue = [
            ("Close previous project", 5,
             lambda: self._reset_to_factory(auto=True)
             if self._project_path else None),
            ("Reading file", 25, lambda: self._yaml_parse(path)),
            ("Applying project", 45, lambda: self._yaml_apply(path)),
            ("Yaml Build refresh", 95, lambda: self._yaml_finish(path)),
            ("Done", 100, lambda: self._yaml_done()),
        ]
        self._yaml_loading_ui(True)
        self._yaml_load_next()

    def _yaml_load_next(self) -> None:
        """Run one load stage, then hand control back to the event
        loop before the next one (the GUI stays alive throughout)."""
        if not getattr(self, "_yaml_load_queue", None):
            return
        label, weight, fn = self._yaml_load_queue.pop(0)
        self._yaml_progress(weight, label)
        try:
            fn()
        except Exception as exc:      # noqa: BLE001 - a failed load
            # must never wedge the GUI in the loading state
            self._yaml_load_queue = []
            self._yaml_done()
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] Yaml load FAILED: {exc}")
            QMessageBox.critical(self, "Load Failed", str(exc))
            return
        if self._yaml_load_queue:
            QTimer.singleShot(0, self, qt_safe(self._yaml_load_next))

    def _yaml_progress(self, value: int, label: str) -> None:
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(value)
        self.status_progress.setFormat(f"Loading project: {label}")
        # the FOREGROUND modal dialog carries the same stage (2026-10-26)
        dlg = getattr(self, "_yaml_load_dlg", None)
        if dlg is not None:
            dlg.set_stage(value, f"Loading project: {label}")

    def _yaml_loading_ui(self, loading: bool) -> None:
        """Disable / restore Run Control + table editing during the
        staged load (the double-click handlers check the flag too)."""
        page = self.workflow_page
        page._yaml_loading = loading
        page.btn_run.setEnabled(not loading)
        page.btn_stop.setEnabled(not loading)
        page.longrun_spin.setEnabled(not loading)
        page.interval_spin.setEnabled(not loading)

    def _yaml_parse(self, path: str) -> None:
        self._yaml_config = project_config.load_config(path)

    def _yaml_apply(self, path: str) -> None:
        config = self._yaml_config
        if isinstance(config, dict) and \
                ("yaml_build" in config or "plan" in config):
            # published plan file (plan + yaml_build sections, the
            # Yaml Build page output) -> restore into the build model;
            # machine-generated plans load silently (the no-UI legacy
            # modules rails/clocks/gpios are not validated)
            self._yaml_plan_errors = self.yaml_build_page.model.\
                apply_yaml_dict(config, validate_no_ui=False)
        else:
            self._yaml_plan_errors = None
            project_config.apply_config(
                config, self.workflow_page, self.equipment_page,
                self.yaml_build_page.model)

    def _yaml_finish(self, path: str) -> None:
        self._sync_rails_to_workflow()
        self.yaml_build_page.refresh_all()
        self._project_path = path
        # a published plan file ("yaml_build" section) is just as
        # runnable as a legacy project yaml - register it for the Run
        # gate in BOTH branches (GUI-FIX2 F3: plan loads used to show
        # "Project File: (none)" and block Run)
        self.workflow_page.set_project_file(path)
        if self._yaml_plan_errors is not None:
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] Plan yaml loaded: {path}")
        else:
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] Yaml loaded: {path}")

    def _yaml_done(self) -> None:
        self._yaml_loading = False
        _startup_end("yaml load")
        self._yaml_loading_ui(False)
        # the plan-branch identity sync + warnings happen here, after
        # the UI is restored (a modal warning box must not sit inside
        # the stage chain)
        if self._yaml_plan_errors is not None:
            # user direction 2026-10-14: the plan's Design Input
            # identity lands in Product Information too
            project_config.sync_product_identity(
                self._yaml_config, self.workflow_page,
                self.yaml_build_page.model)
            if self._yaml_plan_errors:
                QMessageBox.warning(self, "Load Warnings",
                                    "\n".join(self._yaml_plan_errors))
        self.status_progress.setRange(0, 1)
        self.status_progress.setValue(0)
        self.status_progress.setFormat("Idle")
        # close the front progress dialog on EVERY exit path
        dlg = getattr(self, "_yaml_load_dlg", None)
        if dlg is not None:
            self._yaml_load_dlg = None
            dlg.close_done()
        self._yaml_config = None
        self._yaml_plan_errors = None

    def close_yaml(self):
        """File > Close Yaml: drop the current project and reset the
        GUI to the factory no-yaml state (blank product info, default
        stop policies, EMPTY ICT/FCT tables - zero rows since the
        2026-10-15 direction - no rails / consoles, equipment
        defaults, fresh Yaml Build model)."""
        if self._project_path:
            answer = QMessageBox.question(
                self, "Close Yaml",
                "Close the current YAML and reset to the factory "
                "state?\n\nUnsaved changes are kept on disk only if "
                "you saved before.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._reset_to_factory()

    def _reset_to_factory(self, auto: bool = False) -> None:
        """Factory reset shared by Close Yaml (confirmed) and the
        auto-close before loading a different project (silent)."""
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
        # user direction 2026-10-14: Close Yaml also clears the last
        # RUN state - Overall Flow statuses / durations, the Overall
        # Result verdict and the per-product statistics (the screenshot
        # showed a stale "Virtual PASS" panel next to Project File:
        # (none))
        page.products_passed = 0
        page.products_failed = 0
        page.cycle_times = []
        page.clear_results(keep_log=True)   # keep the session log
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
        # the preview pane must NOT keep showing the stale document
        # (user direction: Close Yaml clears the Yaml Preview)
        self.yaml_build_page.clear_preview()
        self._project_path = None
        self._append_event_log(
            f"[{datetime.now():%H:%M:%S}] "
            + ("Previous project auto-closed (project switch)"
               if auto else
               "Yaml closed - GUI reset to the factory state"))

    def _goto_test_workflow(self):
        """Merged 'Build ICT Test Work Flow Sequence' card: switch to
        the Test Work Flow tab and focus the ICT Test Cases table
        (cursor on the first case row)."""
        _startup_mark("page switch -> Test Work Flow", category="page")
        self.tabs.setCurrentWidget(self.workflow_page)
        table = self.workflow_page.ict
        table.setFocus()
        table.setCurrentCell(0, 1)
        table.scrollToTop()

    def _fill_ict_sequence(self, steps, enables=None, waits=None,
                           timeouts=None):
        """Write the WHOLE sequence returned by the Build ICT dialog
        verbatim into the ICT result table (task: single sequence
        source).

        The dialog now owns the standard operations, the flash
        operations and the Delay steps, so NOTHING is injected here any
        more: the rows land exactly as the operator ordered them.  The
        optional enable / wait / timeout lists carry the dialog's
        per-step settings; when absent (the Load-current-yaml and demo
        build paths) the defaults apply.
        """
        page = self.workflow_page
        # the DAQ AI row and the rails capture share the same resource
        # set: sync the page rails from the Yaml Build model (Channel
        # Allocation) BEFORE the table refresh - without this a dialog
        # OK on a fresh page (empty rail set) silently DROPPED the
        # user-added DAQ AI test (root cause of the "not saved to yaml"
        # report)
        if not page.rails:
            self._sync_rails_to_workflow()
        seq = list(steps)
        n = len(seq)
        page.ict_steps = seq
        page.ict_enables = (list(enables) if enables is not None
                            else [True] * n)
        page.ict_waits = (list(waits) if waits is not None
                          else [100] * n)
        page.ict_timeouts = (list(timeouts) if timeouts is not None
                             else [5000] * n)
        page.ict.setRowCount(n)
        page._ict_edit_guard = True
        page._fill_ict(placeholder=True)
        page._ict_edit_guard = False

    def _on_ict_sequence_ready(self, result):
        """Block-04 sequence builder accepted: write the WHOLE sequence
        (test items + standard operations + flash + Delay) into the ICT
        result table verbatim, jump to the Test Work Flow page and offer
        the YAML save (apply)."""
        steps, enables, waits, timeouts = result
        self._fill_ict_sequence(steps, enables, waits, timeouts)
        self._goto_test_workflow()
        self._append_event_log(
            f"ICT test sequence applied: {len(steps)} steps",
            level=IMPORTANT)
        # apply to yaml: the same save dialog as the preview Apply
        self._on_yaml_apply_committed()

    def _on_fct_sequence_ready(self, cases):
        """P3-B5 block-07 FCT config accepted: replace the FCT Test
        Cases table with the generated sequence and offer the YAML
        save (same apply flow as the ICT sequence builder)."""
        page = self.workflow_page
        page.load_fct_cases(cases)
        self._goto_test_workflow()
        self._append_event_log(
            f"FCT test sequence applied: {len(cases)} cases",
            level=IMPORTANT)
        self._on_yaml_apply_committed()

    def _load_current_yaml(self):
        """Load current yaml (user direction 2026-10-13): derive the
        ICT / FCT sequences from the CURRENT Yaml Build model and push
        them into the Test Work Flow page, then jump there.

        Readiness gate (blocks 01-04 / 01-05 / 05): ICT is usable when
        parsed nets are fully channel-allocated and the rails / clocks
        / gpios modules are enabled; FCT is usable when the fct_build
        module carries a configured fct_test_config.  Without either a
        warning is shown and NOTHING is executed."""
        model = self.yaml_build_page.model
        ict_ready = bool(model.allocated_testable()) and all(
            model.is_enabled(k) for k in ("rails", "clocks", "gpios"))
        fct_params = model.get_params("fct_build") or {}
        fct_ready = model.is_enabled("fct_build") and bool(
            str(fct_params.get("fct_test_config_yaml") or "").strip())
        if not ict_ready and not fct_ready:
            QMessageBox.warning(
                self, "Load current yaml",
                "No usable ICT / FCT configuration.\n\nComplete the "
                "blocks 01-04 (ICT), 01-05 or 05 (FCT) first.")
            return
        loaded = []
        page = self.workflow_page
        # M10-FIX3 F3: the derivation blocks the GUI on a big project -
        # drive a delayed foreground progress dialog and disable the
        # triggering page button for the whole run
        try:
            with busy_progress(self, "Load current yaml…") as stage:
                # the power-rails capture set feeds the DAQ AI test row
                # inserted by _fill_ict_sequence - sync it model -> page
                # BEFORE building
                stage(0, "Load current yaml: syncing rails")
                self._sync_rails_to_workflow()
                if ict_ready:
                    from mtkgui.gui.yamlbuild.ict_sequence import (
                        canonical_ict_sequence,
                        daq_ai_rail_count,
                    )
                    # user direction 2026-10-14: the regeneration only
                    # re-derives what Auto can - previously filled
                    # Expected / Min / Max cells (manual corrections)
                    # win over the fresh derivation
                    previous = list(page.ict_steps)
                    # M8: the parsed nominal (nominal_v / nominal_khz)
                    # carried in imported.testable_nets wins over the
                    # net-name heuristic
                    testable = model.imported.get("testable_nets") or {}
                    # M9: the Build ICT dialog is the single EDIT source
                    # - this Load path runs the SAME canonical pipeline
                    # (auto-filled tests + the DIO operations when GPIO
                    # nets exist + the standard-operation skeleton)
                    stage(25, "Load current yaml: building ICT tests")
                    rows = canonical_ict_sequence(
                        testable, previous,
                        daq_ai_rail_count(model.channel_allocation),
                        allocation=model.channel_allocation)
                    self._fill_ict_sequence(rows)
                    loaded.append(f"ICT {len(rows)} tests")
                if fct_ready:
                    stage(60, "Load current yaml: building FCT cases")
                    cases, errors = self.yaml_build_page._emit_fct_sequence(
                        fct_params)
                    if errors:
                        QMessageBox.warning(
                            self, "Load current yaml",
                            "The FCT configuration is invalid:\n"
                            + "\n".join(errors[:10]))
                    else:
                        self.workflow_page.load_fct_cases(cases)
                        loaded.append(f"FCT {len(cases)} cases")
                if not fct_ready:
                    # ICT-only load (user direction 2026-10-13): clear
                    # the FCT placeholder row - with the Overall Flow FCT
                    # stage enabled a stale MessageOK step would stop the
                    # run on an operator dialog that has no place in an
                    # ICT-only project
                    self.workflow_page.load_fct_cases([])
                # user direction 2026-10-14: carry the Design Input
                # identity into the Product Information group (it
                # previously stayed empty after a Load; the serial
                # number stays manual)
                stage(80, "Load current yaml: product information")
                project_config.sync_product_identity({}, page, model)
                loaded.append("Product Info")
                self._goto_test_workflow()
                self._append_event_log(
                    f"[{datetime.now():%H:%M:%S}] Current yaml loaded - "
                    + "; ".join(loaded))
                # user direction 2026-10-14: a Load must leave the GUI
                # runnable - without a project file the Run button
                # blocks ("No YAML file is loaded"), so the fresh state
                # is saved automatically
                if not self._project_path:
                    self._auto_save_project()
                stage(100, "Load current yaml: done")
        finally:
            pass

    def _auto_save_project(self):
        """Dialog-free project save after Load current yaml: the
        derived configuration lands under ./projects/ with the standard
        name (Part#_CoreID_Batch_rev_<plan version>_Draft.yaml) so the
        Run gate cannot hit right after a Load."""
        # M19: the auto-save lands in the resolved projects workspace
        # (env override -> exe-side -> built-in bundle -> CWD fallback)
        out_dir = Path(resolve_tenant_base())
        path = out_dir / project_config.default_filename(
            self._build_project_config())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] Auto-save skipped: {exc}")
            return
        self._save_yaml_to(str(path))

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

    def _control_io_rows(self):
        """M7: allocated control-IO rows for the U2355A DIO ops.

        Merges the Channel Allocation DIO assignment (net -> DIO
        channel) with the parsed isolation evidence carried in
        ``testable_nets`` (isolated / active_drivers / members).
        """
        testable = (self.yaml_build_page.model.imported.get(
            "testable_nets") or {})
        alloc = self.yaml_build_page.channel_alloc.collect()
        rows = []
        for row in alloc.get("gpio") or []:
            net = str(row.get("net") or "").strip()
            dio = str(row.get("dio_channel") or "").strip()
            if not net or not dio or dio == "—":
                continue
            info = testable.get(net) or {}
            rows.append({
                "net": net,
                "dio": dio,
                "isolated": info.get("isolated"),
                "active_drivers": list(info.get("active_drivers") or []),
                "members": list(info.get("members") or []),
            })
        return rows

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

    def _import_excel_menu(self):
        """File > Import from Excel… (the page button is gone, M19d)."""
        self.yaml_build_page._import_excel()

    def _export_excel_menu(self):
        """File > Export to Excel… (the page button is gone, M19d)."""
        self.yaml_build_page._export_excel()

    def _export_ict_plan_menu(self):
        """File > Export ICT Test plan from Yaml to Excel: write the
        workbook + evidence markdown from the CURRENT project YAML
        (user direction 2026-10-25; the four Parse-Nets buttons are
        gone)."""
        from PySide6.QtWidgets import QFileDialog

        from mtkgui.gui.yamlbuild.testplan_sync import yaml_to_testplan
        model = self.yaml_build_page.model
        if not (model.imported or {}).get("testable_nets"):
            QMessageBox.warning(
                self, "Export ICT Test plan",
                "No parsed ICT data in the project YAML - parse the "
                "nets first.")
            return
        default = (f"ICT Test Plan for "
                   f"{self.yaml_build_page._project_name()}.xlsx")
        path, _selected = QFileDialog.getSaveFileName(
            self, "Export ICT Test plan from Yaml to Excel",
            default, "Excel (*.xlsx)")
        if not path:
            return
        md_path = str(Path(path).with_name(
            Path(path).stem + "_evidence.md"))
        from mtkgui.gui.progress_dialog import guarded_run

        def work(stage):
            stage(0, "Export ICT Test plan: writing workbook")
            yaml_to_testplan(model, path, md_path)
            stage(100, "Export ICT Test plan: done")
            return True

        if guarded_run(self, None, "Export ICT Test plan",
                       work) is not True:
            return
        report = list(getattr(model, "testplan_sync_report", None)
                      or [])
        for line in report:
            self._append_event_log(f"export ICT Test plan: {line}")

    def _import_ict_plan_menu(self):
        """File > Import ICT Test from Excel to Yaml.

        Guides the user to NEW or OVERWRITE the project YAML; an
        overwrite replaces ONLY the ICT portion (power rails / channel
        allocation / clocks / control IO / DNT) - every other YAML
        section stays untouched (user direction 2026-10-25)."""
        from PySide6.QtWidgets import QFileDialog

        from mtkgui.gui.progress_dialog import guarded_run
        from mtkgui.gui.yamlbuild.testplan_sync import testplan_to_yaml
        path, _selected = QFileDialog.getOpenFileName(
            self, "Import ICT Test from Excel to Yaml",
            "", "Excel (*.xlsx)")
        if not path:
            return
        model = self.yaml_build_page.model
        if not self._project_path:
            answer = QMessageBox.question(
                self, "Import ICT Test",
                "No project YAML is loaded.\n\nCreate a NEW YAML from "
                "this Test Plan?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            mode = "new"
        else:
            answer = QMessageBox.question(
                self, "Import ICT Test",
                "Overwrite the ICT portion of the current YAML?\n\n"
                "Only the ICT section (power / clocks / control IO / "
                "limits / channels) is replaced - all other sections "
                "stay unchanged.")
            if answer != QMessageBox.StandardButton.Yes:
                return
            mode = "overwrite"

        def work(stage):
            stage(0, "Import ICT Test: reading workbook")
            testplan_to_yaml(model, path, None, None, overwrite=True)
            stage(100, "Import ICT Test: done")
            return True

        if guarded_run(self, None, "Import ICT Test", work) is not True:
            return
        report = list(getattr(model, "testplan_sync_report", None)
                      or [])
        for line in report:
            self._append_event_log(f"import ICT Test: {line}")
        self.yaml_build_page.refresh_all()
        if mode == "new":
            self.save_yaml_as()
        else:
            self._save_yaml_to(self._project_path)

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
        _startup_begin("save yaml: file pick", category="ui",
                       wait=True)
        try:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save as Yaml",
                project_config.default_filename(config),
                "YAML files (*.yaml *.yml)")
        finally:
            _startup_end("save yaml: file pick")
        if not path:
            return
        self._save_yaml_to(path)

    def _save_yaml_to(self, path):
        _startup_begin("save yaml: write", category="io")
        try:
            # user direction 2026-10-14: each stage may legally be empty,
            # but a YAML with NO test items at all (ICT and FCT both
            # empty) is warned about at save time (working files may still
            # be checkpointed on purpose)
            ict_n, fct_n = self.workflow_page.test_item_counts()
            if not ict_n and not fct_n:
                answer = QMessageBox.question(
                    self, "No Test Items",
                    "The YAML contains no usable test items (ICT and FCT "
                    "are both empty).\n\nSave anyway?")
                if answer != QMessageBox.StandardButton.Yes:
                    self._append_event_log(
                        f"[{datetime.now():%H:%M:%S}] Yaml save "
                        "cancelled: no test items")
                    return
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
        finally:
            _startup_end("save yaml: write")

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
        QTimer.singleShot(0, self, qt_safe(self._lock_vertical_minimums))

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
        """Open the per-session auto-save log file under the Event Log
        folder (<program>/Event Report by default, name modifiable via
        Report > Report Folder…).

        One file covers a whole GUI run, from startup to exit; every log
        line is appended (and flushed) immediately so a crash still leaves
        the record on disk."""
        try:
            from mtkgui import report_paths
            event_dir = report_paths.event_folder()
            event_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = event_dir / f"event_{stamp}.log"
            self._event_log_path = path
            self._event_log_file = open(path, "a", encoding="utf-8")
            self._event_log_file.write(
                f"=== mtk-gui session started {stamp} ===\n")
            self._event_log_file.flush()
        except OSError:
            # logging must never block the GUI from starting
            self._event_log_path = None
            self._event_log_file = None

    def _append_event_log(self, text, level="INFO"):
        """Show a line in the Event Log and mirror it into the session
        auto-save file.

        M11: exactly ONE ``YYYY-MM-DD HH:MM:SS`` stamp per line (an
        embedded LEADING stamp from the caller / producer signal is
        stripped first), and the entry carries a level.  The UI honours
        the Simplified / Detailed filter; the auto-save file ALWAYS
        records every line (full audit), regardless of the UI level.
        PASS / FAIL / Error verdicts are highlighted in their own color.

        Args:
            text: The message; a leading ``[YYYY-MM-DD HH:MM:SS]`` or
                  ``[HH:MM:SS]`` prefix and a leading ``[LEVEL]`` tag
                  are tolerated.
            level: Producer level (DEBUG / INFO / WARNING / ERROR) or
                   the display classes TEST / IMPORTANT.
        """
        from html import escape
        entry = strip_leading_stamp(text)
        entry_level = resolve_level(entry, level)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plain = f"{stamp} {entry}"
        if should_display(entry_level,
                          self._event_log_level == DETAILED):
            colored = _colorize_verdicts(escape(entry))
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
    @staticmethod
    def _fmt_elapsed(delta) -> str:
        """Seconds -> MM:SS (H:MM:SS past one hour)."""
        total = max(0, int(delta.total_seconds()))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _update_run_progress(self, current, total):
        """Update the status-bar progress bar during a test run.

        A running test cancels any pending finish-reset (a new job may
        start within the reset grace window).  2026-10-17: the bar also
        carries the ELAPSED run time, and the Event Log records the
        run process (started / finished lines)."""
        self._progress_reset_pending = False
        self._progress_args = (current, total)
        if total > 1:
            self._last_progress = (current, total)  # restore point after
        if total <= 0:                              # a busy phase
            self.status_progress.setRange(0, 1)
            self.status_progress.setValue(0)
            self.status_progress.setFormat("Idle")
        else:
            if self._run_started_at is None:
                # first progress of this run: start the elapsed clock
                # and note the process in the Event Log
                self._run_started_at = datetime.now()
                self._run_clock.start()
                self._append_event_log(
                    f"[{datetime.now():%H:%M:%S}] Test run started "
                    f"({total} steps)")
            elapsed = self._fmt_elapsed(
                datetime.now() - self._run_started_at)
            self.status_progress.setRange(0, total)
            self.status_progress.setValue(current)
            self.status_progress.setFormat(
                f"{current}/{total} ({current * 100 // total}%)"
                f" · {elapsed}")

    def _tick_run_clock(self):
        """1 s heartbeat: refresh the elapsed time in the progress bar
        (keeps the same current/total values)."""
        if self._run_started_at is None or self._progress_reset_pending:
            return
        current, total = self._progress_args
        if total <= 0:
            return
        elapsed = self._fmt_elapsed(datetime.now() - self._run_started_at)
        self.status_progress.setFormat(
            f"{current}/{total} ({current * 100 // total}%) · {elapsed}")

    def _finish_run_progress(self):
        """Task complete: fill the bar full, then auto-reset to the
        gray empty Idle state (grace window so the 100% is visible)."""
        started = getattr(self, "_run_started_at", None)
        if started is not None:
            elapsed = self._fmt_elapsed(datetime.now() - started)
            self.status_progress.setFormat(f"Complete (100%) · {elapsed}")
            # the Event Log carries the run process: started -> finished
            self._append_event_log(
                f"[{datetime.now():%H:%M:%S}] Test run finished · "
                f"elapsed {elapsed}")
        else:
            self.status_progress.setFormat("Complete (100%)")
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(100)
        clock = getattr(self, "_run_clock", None)
        if clock is not None:
            clock.stop()
        self._run_started_at = None
        self._progress_reset_pending = True
        QTimer.singleShot(800, self, qt_safe(self._reset_run_progress))

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
            "state.", level=IMPORTANT)

    def _on_instrument_error(self, abbr):
        """Virtual equipment fault: red light, auto-recover after 2.5 s."""
        self.instr_status.set_state(abbr, "error")
        self._append_event_log(
            f"Instrument {abbr}: equipment fault "
            f"(virtual fault injection, auto-recover).")
        QTimer.singleShot(2500, self,
                          qt_safe(lambda: self._recover_instrument(abbr)))

    def _recover_instrument(self, abbr):
        if self.instr_status.states.get(abbr) == "error":
            self.instr_status.set_state(abbr, "connected")
            self._append_event_log(f"Instrument {abbr}: reconnected.")

    def _toggle_event_log(self):
        """Collapse / expand the Event Log pane (user direction
        2026-10-13): collapsed shows only the pane title bar, the
        freed height goes to the tabbed workspace."""
        self._log_collapsed = not getattr(self, "_log_collapsed", False)
        self.event_log.setVisible(not self._log_collapsed)
        if self._log_collapsed:
            self._log_toggle.setArrowType(Qt.ArrowType.UpArrow)
            self._log_toggle.setToolTip("Expand Event Log")
            # the pane floor drops to the title bar height, the freed
            # space flows into the tabbed workspace
            self._log_group.setMinimumHeight(0)
            slim = max(34, self._log_group.minimumSizeHint().height())
            sizes = self.splitter.sizes()
            if len(sizes) == 3:
                freed = sizes[2] - slim
                self.splitter.setSizes(
                    [sizes[0], sizes[1] + max(0, freed), slim])
        else:
            self._log_toggle.setArrowType(Qt.ArrowType.DownArrow)
            self._log_toggle.setToolTip("Collapse Event Log")
            self._log_group.setMinimumHeight(
                max(self._log_group.minimumSizeHint().height(),
                    self._log_expanded_h))
            sizes = self.splitter.sizes()
            if len(sizes) == 3:
                self.splitter.setSizes(
                    [sizes[0], max(300, sizes[1] - self._log_expanded_h),
                     self._log_expanded_h + 40])

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
        # step 3 - flush ONLY the deferred deletes.  A full
        # QApplication.processEvents() pump here activates pending
        # timers whose context-less callbacks touch widgets destroyed
        # in this same flush -> SIGSEGV on close (5/5 identical macOS
        # crash stacks: Sbk_QCoreApplicationFunc_processEvents ->
        # QTimerInfoList::activateTimers -> EXC_BAD_ACCESS @ NULL).
        # sendPostedEvents(DeferredDelete) drains the deleteLater
        # queue without running timers / input / queued signals.
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
