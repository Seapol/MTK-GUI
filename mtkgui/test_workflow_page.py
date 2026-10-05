# -*- coding: utf-8 -*-
"""Test Work Flow page.

The overall flow is a table:

    ICT -> FCT

* ICT test cases run as one top -> bottom sequence. Standard operations
  (Init Instruments, Fixture Clamp Down / Lock / E-Stop Healthy, Power On
  DUT, Power Off DUT, Fixture Unlock / Release, Reset Instruments) report
  Done/Error; in between them the measurement tests report PASS/FAIL:
    - impedance shorts: 80 points, 2-wire Ω via DAQ973A, R_min threshold
    - power voltage: 80 points, ±0.1 % via DAQ973A
    - clocks: CLK1 32.768 kHz (907A totalizer), CLK2 4 MHz / CLK3 6 MHz
      (U2355A counters)
    - ADC stimulus: 2 x AO ±12 V -> TP_ADC0/1
    - fixture DIO (16 ch open-drain, 4 signals used) and DUT GPIO (24 ch)
  Values are numeric with units (ohm / V / Hz) and PASS when in range.
* Power rails up sequence is a DAQ capture: 12 critical rails are recorded
  by the U2355A analog inputs, saved as a CSV log and drawn as a waveform
  here (record only - no pass/fail).
* FCT tests are message tests: the result is judged from serial output, a
  GUI dialog (operator clicks Pass / Fail) or the output of a third-party
  CLI, by checking that "Pass"/"Success" is present and "Fail"/"Error" is
  absent.  Flashing FAT / OOBE firmware is part of FCT as well.

Demo mode: no real instruments are attached; the Run Demo button simulates
a full pass run and writes a real CSV log.
"""

import random
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QSize, Qt, QRectF, QRegularExpression, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPixmap,
    QPen,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Test flow engine (T2): the run state machine, step definitions and
# result model live in mtkgui.engine (interface_spec.md §3); this page
# keeps only the UI layer plus thin delegates for its historical
# call-sites.  The underscore aliases below stay importable because
# project_config imports them from this module.
from .engine import (
    CONSOLE_KINDS,
    FCT_METHODS,
    OP_STEPS,
    SAMPLE_HZ,
    StepStatus,
    TestRunner,
    ai_wave_review,
    capture_samples,
    console_keyword_fallback as _console_keyword_fallback,
    display_text,
    fct_kind_from_name as _fct_kind_from_name,
    generate_rails,
    is_impedance_short as is_impedance_short_row,
    op_step as _op_step,
    op_summary as _op_summary,
    rail_plot_data,
    steps_template,
    write_csv,
)
from .engine.rails import DURATION_S
from .style import gui_theme_color, saved_theme, text_for_card
from .virtual_hardware import VirtualRack
from .widgets.multi_console import MultiConsoleWidget

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
_ICON_DIR = Path(__file__).resolve().parent / "assets"

# power rails are fully YAML-defined (see TestWorkFlowPage.set_rails):
# the project file carries name / nominal_v / ramp_offset_s / color and
# the rail set is empty until a project is loaded

# ICT test cases: the sequence executes strictly top -> bottom. Standard
# operations (fixture / instrument control) report Done/Error; measurement
# tests report PASS/FAIL.
# Impedance shorts MUST run before the DUT is powered on: a short under
# power risks damaging the board, so "Stop if any short" aborts the run
# right here, before "Power On DUT".
# (kind, name, unit, measured, min / threshold, max[, op_params])
# standard op step tuples come from mtkgui.engine.steps (op_step).

ICT_STEPS = [
    _op_step("Init Instruments"),
    _op_step("Fixture Clamp Down"),
    _op_step("Fixture Lock"),
    _op_step("Fixture E-Stop Healthy"),
    ("test", "Impedance Shorts (80 pts)", "Ω", "80/80",
     "1.5", ""),
    _op_step("Power On DUT"),
    ("test", "Power Voltage (80 pts)", "V", "80/80", "3.201", "3.399"),
    ("test", "RTC - 32.768 kHz (907A TOT)", "Hz", "32768.1",
     "32752", "32784"),
    ("test", "CLKOUT1 - 4 MHz (U2355A CTR0)", "Hz", "4000200",
     "3996000", "4004000"),
    ("test", "CLKOUT2 - 6 MHz (U2355A CTR1)", "Hz", "6000100",
     "5994000", "6006000"),
    ("test", "ADC Stimulus AO0/AO1 -> TP_ADC", "V", "2/2",
     "-12", "12"),
    ("test", "Fixture DIO (16 ch, 4 used)", "ch", "4/4", "—", "—"),
    ("test", "DUT GPIO (24 ch)", "ch", "24/24", "—", "—"),
    _op_step("Power Off DUT"),
    _op_step("Fixture Unlock"),
    _op_step("Fixture Release"),
    _op_step("Reset Instruments"),
]


# --------------------------------------------------------------------------
# waveform widget (QPainter - no extra dependencies)
# --------------------------------------------------------------------------
class WaveformWidget(QWidget):
    # emitted on double-click; the page connects to show an edit dialog
    doubleClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []  # list of (label, color, y_max, samples)
        self.duration = DURATION_S
        self.t_start = 0.0  # capture start time (can be negative)
        self.virtual = False  # Virtual mode: simulated (demo) data badge
        self._cache = None    # rendered-plot pixmap (invalidated on change)
        self.setMinimumHeight(190)

    def set_data(self, data, duration, t_start=0.0):
        self.data = data
        self.duration = duration
        self.t_start = t_start
        self._cache = None
        self.update()

    def set_virtual(self, on):
        """Virtual mode: the capture is simulated demo data, not a real
        DAQ measurement (drawn with a VIRTUAL DATA badge)."""
        self.virtual = bool(on)
        self._cache = None
        self.update()

    def resizeEvent(self, event):
        # NOTE: do not invalidate the cache here - table column re-layout
        # fires a resize on every run step; slight size drift is handled
        # by scale-drawing the cached pixmap instead
        self.update()

    def paintEvent(self, event):
        # The plot is static between captures: render it once into a
        # pixmap and just blit (scaling for small size drift) on
        # repaints. Re-rendering ~12 x 1300 curve segments on every run
        # step was the second-run jank.
        key = (self.virtual, len(self.data))
        if self._cache is None or self._cache_key != key:
            pm = QPixmap(self.size())
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_plot(painter)
            painter.end()
            self._cache = pm
            self._cache_key = key
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._cache)

    def _paint_plot(self, painter):
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, QColor("#0d1b26"))
        if not self.data:
            painter.setPen(QPen(QColor("#8fa6b8")))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             "No capture yet - run the demo to record rails")
            return

        margin_l, margin_r, margin_t, margin_b = 64, 24, 34, 30
        plot = QRectF(rect.left() + margin_l, rect.top() + margin_t,
                      rect.width() - margin_l - margin_r,
                      rect.height() - margin_t - margin_b)

        # y axis: voltage, top = 110 % of the highest nominal rail
        v_top = max((y_max for _, _, y_max, _ in self.data),
                    default=1.0) * 1.1

        # grid + time axis
        painter.setPen(QPen(QColor("#24435a"), 1))
        for i in range(6):
            y = plot.top() + plot.height() * i / 5
            painter.drawLine(QPointF(plot.left(), y),
                             QPointF(plot.right(), y))
        painter.setPen(QPen(QColor("#8fa6b8"), 1))
        f = QFont()
        f.setPointSize(8)
        painter.setFont(f)
        for i in range(6):
            y = plot.top() + plot.height() * i / 5
            painter.drawText(QRectF(0, y - 8, margin_l - 8, 16),
                             Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter,
                             f"{v_top * (5 - i) / 5:.2f} V")

        n = max((len(s) for _, _, _, s in self.data), default=1)
        for i in range(6):
            x = plot.left() + plot.width() * i / 5
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            t = self.t_start + self.duration * i / 5
            painter.drawText(QRectF(x - 30, plot.bottom() + 6, 60, 16),
                             Qt.AlignmentFlag.AlignHCenter
                             | Qt.AlignmentFlag.AlignTop,
                             f"{t:.1f} s")

        # legend (two rows, 6 entries each)
        col_w = min(195, plot.width() / 6)
        for i, (label, color, y_max, samples) in enumerate(self.data):
            row, col = divmod(i, 6)
            lx = plot.left() + 10 + col * col_w
            ly = plot.top() - 12 - row * 16
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(QPointF(lx, ly), QPointF(lx + 18, ly))
            painter.setPen(QPen(QColor("#dbe7f0"), 1))
            painter.drawText(QRectF(lx + 22, ly - 9, col_w - 24, 18),
                             Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter,
                             f"{label} ({y_max:.2f} V)")

        # curves (samples are fractions of nominal; plot as voltage,
        # normalized to v_top = 110 % of the highest nominal rail; the
        # clamp allows the small post-ramp overshoot of virtual rails)
        for label, color, y_max, samples in self.data:
            pen = QPen(QColor(color), 2)
            painter.setPen(pen)
            step = max(1, len(samples) // max(1, int(plot.width())))
            pts = []
            for idx in range(0, len(samples), step):
                volts = min(1.08, max(0.0, samples[idx])) * y_max
                x = plot.left() + plot.width() * idx / (n - 1 if n > 1 else 1)
                y = plot.bottom() - plot.height() * (volts / v_top)
                pts.append(QPointF(x, y))
            if len(pts) > 1:
                painter.drawPolyline(pts)

        # Virtual mode: mark the capture as simulated demo data
        if self.virtual:
            f.setPointSize(8)
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(QPen(QColor("#f5b83d"), 2))
            painter.drawText(QRectF(plot.right() - 130, plot.top() + 2,
                                    126, 16),
                             Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter,
                             "VIRTUAL DATA (simulated)")

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------
class TestWorkFlowPage(QWidget):
    # emitted when a whole test cycle completes -> main window jumps here
    run_finished = Signal()
    # emitted with (current, total) so the status bar progress bar can update
    run_progress = Signal(int, int)
    # run phase text ("Init...", "Connecting console...", ...) for the
    # Overall Result sub-label and the status-bar progress busy state
    phase_changed = Signal(str)
    # log line / clear: routed to the central Event Log in MainWindow (the
    # log widget itself moved out of this page into the bottom area)
    log_line = Signal(str)
    log_cleared = Signal()
    # virtual equipment fault attributed to one instrument abbreviation
    # (DAQM / DAQ / PSU) so the status bar light can turn red
    instrument_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rail_samples = None
        self.rail_volts = None
        self.rail_csv_path = None
        self._rail_plot_cache = []
        # Virtual mode hardware rack (DAQ973A / U2355A / N5747A / fixture
        # simulation); None in Real mode until the SCPI drivers land
        self.rack = None
        self.cycle_times = []
        # production statistics: per PRODUCT (one complete test cycle),
        # not per individual test item
        self.products_passed = 0
        self.products_failed = 0
        # callable -> dict {"prefix": str, "length": str}, set by
        # MainWindow (Settings > Serial Number Format Check). In the
        # pre-test phase the serial number is verified against the
        # configured rule; both fields empty means no check.
        self.sn_format = None
        # run control state machine ("idle" | "running") + run timers +
        # step sequencing live in the engine (mtkgui.engine.TestRunner,
        # interface_spec.md §3).  This page keeps thin delegating
        # properties (run_state, _run_steps, ...) for its historical
        # call-sites; the runner reaches the UI through the RunnerEnv
        # bridge methods defined at the bottom of this class.
        self.project_path = None  # loaded YAML; Run is blocked until set
        self._runner = TestRunner(self)
        self._runner.cycle_reset.connect(self._on_cycle_reset)
        self._runner.stage_skipped.connect(self._on_stage_skipped)
        self._runner.run_finished.connect(self._on_run_finished)
        # per-step properties (set up in _build_ict / _build_fct):
        #   *_enables  — list[bool],  controls whether the step runs
        #   *_waits    — list[int] ms,  100-9999,  pause before the step
        #   *_timeouts — list[int] ms,  1000-99999, max time for the step
        self.ict_enables = []
        self.ict_waits = []
        self.ict_timeouts = []
        self.fct_enables = []
        self.fct_waits = []
        self.fct_timeouts = []
        # simulation hooks: row indices marked via the table context menu
        # report FAIL on the next run (used to exercise stop policies)
        self.ict_sim_fail = set()
        self.fct_sim_fail = set()
        # operator Stop pressed -> Overall Result shows IGNORE until the
        # next run starts (the engine tracks the state machine itself)
        self._interrupted = False
        # Virtual mode: simulated HW, random fault injection, "Virtual "
        # result prefix (set from MainWindow according to the login mode)
        self.virtual_mode = False
        self.fault_cfg = {"test_fail_ratio": 0, "equipment_error_ratio": 0}
        # currently executing row (highlighted + auto-scrolled into view)
        self._active_table = None
        self._active_row = -1
        # virtual serial number counter (Auto-SN)
        self._sn_counter = 0
        # account permissions (defaults = supervisor until apply_permissions)
        self._supervisor = True
        self._perm = {}
        self._can_edit_ict = True
        self._can_edit_fct = True
        self._can_toggle_stages = True
        self._overall_en = [True, True]
        self._overall_edit_guard = False
        # power rails are fully YAML-defined (project file): empty until
        # a project is loaded (see set_rails)
        self.rails = []
        self._build()
        # no seeding here: with no YAML loaded the page starts empty
        # (Power Rails Up Sequence and Console are cleared in
        # clear_tables(), called by MainWindow right after construction)

    # -------------------------------------------------- engine delegates
    # The run state machine (timers, step sequencing, stop policies,
    # result rollup) moved to mtkgui.engine.TestRunner.  These thin
    # delegating properties keep the page's historical attributes
    # working (smoke_test drives them directly).
    @property
    def run_state(self) -> str:
        """Run control state machine: "idle" | "running" (engine-owned)."""
        return self._runner.state

    @run_state.setter
    def run_state(self, value: str) -> None:
        self._runner.state = value

    @property
    def _run_steps(self) -> list:
        return self._runner._run_steps

    @_run_steps.setter
    def _run_steps(self, value: list) -> None:
        self._runner._run_steps = value

    @property
    def _run_index(self) -> int:
        return self._runner._run_index

    @_run_index.setter
    def _run_index(self, value: int) -> None:
        self._runner._run_index = value

    @property
    def _run_start(self) -> float:
        return self._runner._run_start

    @_run_start.setter
    def _run_start(self, value: float) -> None:
        self._runner._run_start = value

    @property
    def _stage_start(self) -> float:
        return self._runner._stage_start

    @_stage_start.setter
    def _stage_start(self, value: float) -> None:
        self._runner._stage_start = value

    @property
    def fct_connect_timeout(self) -> float:
        return self._runner.fct_connect_timeout

    @fct_connect_timeout.setter
    def fct_connect_timeout(self, value: float) -> None:
        self._runner.fct_connect_timeout = value

    # --- RunnerEnv bridge: live run-control data read by the engine ---
    def overall_en(self) -> list:
        """Overall Flow EN checkboxes (engine reads this live)."""
        return self._overall_en

    def _stop_flags(self) -> tuple:
        """(stop_if_failure, stop_if_any_short) checkbox states."""
        return (self.stop_if_fail_cb.isChecked(),
                self.stop_if_short_cb.isChecked())

    def _interval_s(self) -> float:
        """Long Run interval pause (seconds) between cycles."""
        return self.interval_spin.value()

    def _stage_name(self, r: int) -> str:
        """Overall Flow stage label of row r."""
        return self.overall.item(r, 1).text()

    def _fct_row_count(self) -> int:
        return self.fct.rowCount()

    # ------------------------------------------------------------ UI
    def _build(self):
        # Common parts (Product Information / Run Control / Overall Flow /
        # Overall Result) are built here as attributes but NOT added to this
        # page's layout: MainWindow places them in the top area above the
        # tabs. The Test Log also moved out -> see log_line / log_cleared.
        self.product_group = self._build_product_info()
        self.run_control_group = self._build_run_control()
        self.overall_group = self._build_overall()
        self.result_group = self._build_result()

        root = QVBoxLayout(self)

        title = QLabel("Test Work Flow")
        title.setObjectName("strong")
        title.setStyleSheet("font-size: 16px;")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scroll = scroll
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(14)

        mid = QSplitter(Qt.Orientation.Horizontal)
        mid.setChildrenCollapsible(False)
        mid.addWidget(self._build_ict())
        mid.addWidget(self._build_rails())
        mid.setStretchFactor(0, 1)   # ICT 50%
        mid.setStretchFactor(1, 1)   # Rails 50%
        mid.setSizes([500, 500])     # initial 1:1 ratio
        # first show re-splits by sizeHint -> enforce 1:1 afterwards
        QTimer.singleShot(0, lambda: mid.setSizes([500, 500]))
        mid.setHandleWidth(10)
        # the Power Rails pane may occupy at most half of the row:
        # a Resize on the splitter re-clamps the rails max width
        self._mid_splitter = mid
        mid.installEventFilter(self)

        # FCT table (50%) | multi serial/SSH console (50%)
        fct_split = QSplitter(Qt.Orientation.Horizontal)
        fct_split.setChildrenCollapsible(False)
        fct_split.addWidget(self._build_fct())
        self.multi_console = MultiConsoleWidget()
        fct_split.addWidget(self.multi_console)
        fct_split.setStretchFactor(0, 1)   # FCT 50%
        fct_split.setStretchFactor(1, 1)   # Console 50%
        fct_split.setSizes([500, 500])     # initial 1:1 ratio
        # first show re-splits by sizeHint -> enforce 1:1 afterwards
        QTimer.singleShot(0, lambda: fct_split.setSizes([500, 500]))
        fct_split.setHandleWidth(10)
        # keep the FCT table's 12-row viewport (and the console bars)
        # intact; the outer scroll area scrolls when the window is short
        fct_split.setMinimumHeight(self.fct.minimumHeight() + 30)

        # ICT / (FCT + console) rows can be resized via the splitter handle
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(mid)
        splitter.addWidget(fct_split)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

    # ------------------------------------------------------- permissions
    def apply_permissions(self, perm, supervisor):
        """Operator role: enable only what the supervisor allows.

        Run / Stop and Open / Close (connect-disconnect instruments) stay
        available; editing tables, product info, run parameters and serial
        channel settings follow the permission keys."""
        self._supervisor = supervisor
        self._perm = dict(perm)
        self._can_edit_ict = supervisor or bool(perm.get("edit_ict"))
        self._can_edit_fct = supervisor or bool(perm.get("edit_fct"))
        self._can_toggle_stages = supervisor or bool(
            perm.get("toggle_stages"))
        self._apply_overall_en_flags()
        can_product = supervisor or bool(perm.get("edit_product_info"))
        for edit in (self.part_edit, self.core_edit, self.batch_edit,
                     self.serial_edit):
            edit.setReadOnly(not can_product)
        self.auto_sn.setEnabled(can_product)
        can_run_cfg = supervisor or bool(perm.get("edit_run_control"))
        self.longrun_spin.setEnabled(can_run_cfg)
        self.interval_spin.setEnabled(
            can_run_cfg and self.longrun_spin.value() > 1)
        self.multi_console.apply_permissions(perm, supervisor)

    def eventFilter(self, obj, event):
        """Power Rails Up Sequence: horizontal width at most 50% of the
        ICT / rails row (re-clamped on every splitter resize)."""
        if (obj is self._mid_splitter
                and event.type() == QEvent.Type.Resize):
            self.rails_group.setMaximumWidth(
                max(280, obj.width() // 2))
        return super().eventFilter(obj, event)

    def _overall_item_changed(self, item):
        """EN checkbox in Overall Flow -> enable / disable the stage."""
        if self._overall_edit_guard or item.column() != 2:
            return
        r = item.row()
        if 0 <= r < len(self._overall_en):
            self._overall_en[r] = (
                item.checkState() == Qt.CheckState.Checked)
            state = "enabled" if self._overall_en[r] else "disabled"
            self._log(f"Overall Flow {self.overall.item(r, 1).text()} "
                      f"{state}")

    def set_overall_en(self, enables):
        """Restore the stage enable states (guarded, e.g. from YAML)."""
        self._overall_edit_guard = True
        for r, on in enumerate(enables[:len(self._overall_en)]):
            self._overall_en[r] = bool(on)
            self.overall.item(r, 2).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._overall_edit_guard = False

    def _apply_overall_en_flags(self):
        """Operator without the toggle_stages right: the EN checkbox
        stays visible but grayed out (not clickable)."""
        for r in range(self.overall.rowCount()):
            item = self.overall.item(r, 2)
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            if self._can_toggle_stages:
                flags |= Qt.ItemFlag.ItemIsEnabled
            else:
                flags &= ~Qt.ItemFlag.ItemIsEnabled
            item.setFlags(flags)

    def _deny_edit(self, what):
        """Info box for a blocked double-click edit (operator role)."""
        QMessageBox.information(
            self, "Permission",
            f"Operator account cannot edit {what}.\n"
            "Ask the supervisor to grant this permission.")

    def _build_product_info(self):
        """Left half of the top row: product identity fields.

        Rules:
          * Product Part#  - product model, forced to upper case
          * Core ID        - 5 or 6 digits
          * Batch#         - free text (proto / proto-1 / ... / pilot /
                             production / special); empty means "freebatch"
          * Serial Number  - 2 letters (factory code) + digits, any length
                             (default 10 digits)
        """
        group = QGroupBox("Product Information")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.part_edit = QLineEdit("FRDM-IMX93")
        self.part_edit.setPlaceholderText("product model, e.g. FRDM-IMX93")
        self.part_edit.textChanged.connect(self._force_upper)
        form.addRow("Product Part#:", self.part_edit)

        self.core_edit = QLineEdit("12345")
        self.core_edit.setMaxLength(6)
        self.core_edit.setPlaceholderText("5-6 digits, e.g. 10342")
        self.core_edit.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"\d{0,6}"), self))
        form.addRow("Core ID:", self.core_edit)

        self.batch_edit = QLineEdit("Dev")
        self.batch_edit.setPlaceholderText(
            "proto / proto-1 / pilot / production (empty = freebatch)")
        form.addRow("Batch#:", self.batch_edit)

        self.serial_edit = QLineEdit()
        self.serial_edit.setPlaceholderText(
            "2 letters + digits, e.g. FS1234567890")
        self.serial_edit.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"[A-Z]{0,2}\d*"), self))
        self.serial_edit.textChanged.connect(self._force_upper)
        form.addRow("Serial Number:", self.serial_edit)

        self.auto_sn = QCheckBox("Auto-SN (virtual serial, +1 per run)")
        self.auto_sn.toggled.connect(self._on_auto_sn_toggled)
        form.addRow("", self.auto_sn)
        return group

    def _on_auto_sn_toggled(self, checked):
        """Auto-SN = fully virtual product information: all four fields
        may be left empty; defaults are filled automatically on Run."""
        for edit in (self.part_edit, self.core_edit, self.batch_edit,
                     self.serial_edit):
            edit.setDisabled(checked)

    def _force_upper(self, text):
        edit = self.sender()
        upper = text.upper()
        if text != upper:
            pos = edit.cursorPosition()
            edit.blockSignals(True)
            edit.setText(upper)
            edit.setCursorPosition(pos)
            edit.blockSignals(False)

    def product_info(self):
        """Current product information with defaults applied."""
        return {
            "part": self.part_edit.text().strip(),
            "core_id": self.core_edit.text().strip(),
            "batch": self.batch_edit.text().strip() or "freebatch",
            "serial": self.serial_edit.text().strip(),
        }

    def _build_run_control(self):
        """Run / Stop + Long Run configuration.

        Idle: Run enabled, Stop disabled. Running: Run disabled,
        Stop enabled. Long Run repeats the whole cycle (1..999 times)
        with a configurable pause between cycles (0.5..99 s, 0.5 s
        step), skipping product information input."""
        group = QGroupBox("Run Control")
        group.setMinimumWidth(190)  # keep visible, never collapse
        layout = QVBoxLayout(group)
        # green play / red stop icons (SVG keeps a gap before the label)
        self.btn_run = QPushButton(
            QIcon(str(_ICON_DIR / "run.svg")), "Run")
        self.btn_run.setIconSize(QSize(26, 26))
        self.btn_run.setMinimumSize(130, 40)  # 50 % wider than default
        self.btn_run.clicked.connect(self.start_run)
        self.btn_stop = QPushButton(
            QIcon(str(_ICON_DIR / "stop.svg")), "Stop")
        self.btn_stop.setIconSize(QSize(26, 26))
        self.btn_stop.setMinimumSize(130, 40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_run)
        layout.addWidget(self.btn_run)
        layout.addWidget(self.btn_stop)
        layout.addStretch(1)

        # bottom of the group, one shared row, smaller font: Long Run
        # (cycles) + Interval (pause between cycles, 0.5 s step).  The
        # Interval is only editable while Long Run > 1.
        lr_row = QHBoxLayout()
        lbl_lr = QLabel("Long Run:")
        self.longrun_spin = QSpinBox()
        self.longrun_spin.setRange(1, 999)
        self.longrun_spin.setValue(1)
        lbl_iv = QLabel("Interval (s):")
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.5, 99.0)
        self.interval_spin.setSingleStep(0.5)
        self.interval_spin.setValue(2.0)
        for w in (lbl_lr, self.longrun_spin, lbl_iv, self.interval_spin):
            w.setStyleSheet("font-size:12px;")
            lr_row.addWidget(w, w is not lbl_lr and w is not lbl_iv)
        self.interval_spin.setEnabled(False)  # Long Run == 1 by default
        self.longrun_spin.valueChanged.connect(
            lambda v: self.interval_spin.setEnabled(v > 1))
        layout.addLayout(lr_row)
        return group

    def _build_result(self):
        """Right of the top row: big verdict + per-product statistics."""
        group = QGroupBox("Overall Result")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        # run phase hint ("Init...", "Connecting console...", ...) shown
        # above the verdict while the run works in the background
        self.phase_label = QLabel("")
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setObjectName("accent_label")
        self.phase_label.setStyleSheet("font-size: 14px;")
        self.phase_label.setVisible(False)
        layout.addWidget(self.phase_label)
        self.result_label = QLabel("—")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_label.setStyleSheet(
            f"font-size:36px; font-weight:bold;"
            f" color:{gui_theme_color('neutral')};")
        layout.addWidget(self.result_label, 1)
        self.result_stats = QLabel()
        self.result_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_stats.setObjectName("muted")
        self.result_stats.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.result_stats)
        self._refresh_stats()
        return group

    def _set_phase(self, text):
        """Show / clear the run phase hint (also emitted so the
        status-bar progress bar can show a busy indicator while a
        background worker (console connect) is pending)."""
        if getattr(self, "_phase_text", None) == text:
            return
        self._phase_text = text
        self.phase_label.setText(text)
        self.phase_label.setVisible(bool(text))
        self.phase_changed.emit(text)

    def _refresh_stats(self):
        """Stats line: per PRODUCT (complete test cycle), not per item."""
        total = self.products_passed + self.products_failed
        yield_text = (f"{self.products_passed / total * 100:.1f} %"
                      if total else "—")
        if self.cycle_times:
            avg = sum(self.cycle_times) / len(self.cycle_times)
            cycle_text = f"{avg:.2f} s"
        else:
            cycle_text = "—"
        self.result_stats.setText(
            f"Passed: {self.products_passed} | Failed: {self.products_failed}\n"
            f"Yield: {yield_text} | Cycle Time (avg): {cycle_text}")

    def set_mode(self, mode):
        """Virtual mode: simulated hardware, injected faults, prefix."""
        self.virtual_mode = (mode == "Virtual")
        self.rail_widget.set_virtual(self.virtual_mode)
        if self.virtual_mode:
            self.rack = VirtualRack(
                self.fault_cfg.get("test_fail_ratio", 0),
                self.fault_cfg.get("equipment_error_ratio", 0))
        else:
            self.rack = None

    def set_virtual_fault(self, cfg):
        """Fault-injection ratios (percent) used in Virtual mode only."""
        self.fault_cfg = dict(cfg or self.fault_cfg)
        if self.rack is not None:
            self.rack.set_fault_ratios(
                self.fault_cfg.get("test_fail_ratio", 0),
                self.fault_cfg.get("equipment_error_ratio", 0))

    def _virtual_fault_roll(self, allow_fail=True, allow_error=True):
        """Random Virtual-mode fault injection: one single, mutually
        exclusive draw (Error band first, then FAIL band).

        Returns "Error" (random equipment / serial fault), "FAIL"
        (random out-of-limit measurement / unexpected reply) or None."""
        if not self.virtual_mode:
            return None
        if self.rack is not None:
            return self.rack.policy.roll(allow_fail=allow_fail,
                                        allow_error=allow_error)
        u = random.random() * 100
        err = self.fault_cfg.get("equipment_error_ratio", 0)
        fail = self.fault_cfg.get("test_fail_ratio", 0)
        if allow_error and u < err:
            return "Error"
        if allow_fail and u < err + fail:
            return "FAIL"
        return None

    def _judge_verdict(self):
        """PASS/FAIL of the executed steps; None when nothing judged yet
        (rollup lives in the engine, interface_spec.md §3)."""
        return self._runner.verdict()

    def _update_result(self):
        """Refresh the big verdict + the per-product statistics."""
        if self._interrupted:
            verdict, key = "IGNORE", "warn"
        elif self.run_state == "running":
            verdict, key = "RUNNING", "run"
        else:
            judged = self._judge_verdict()
            if judged == "FAIL":
                verdict, key = "FAIL", "bad"
            elif judged == "PASS":
                verdict, key = "PASS", "ok"
            else:
                verdict, key = "—", "neutral"
        if self.virtual_mode and verdict != "—":
            verdict = f"Virtual {verdict}"
        self.result_label.setText(verdict)
        self.result_label.setStyleSheet(
            f"font-size:36px; font-weight:bold;"
            f" color:{gui_theme_color(key)};")
        self._refresh_stats()

    def _count_product(self):
        """One complete test cycle finished -> count one product."""
        if self._judge_verdict() == "FAIL":
            self.products_failed += 1
        else:
            self.products_passed += 1

    def _build_overall(self):
        group = QGroupBox("Overall Flow")
        layout = QVBoxLayout(group)

        # currently loaded/saved project YAML file
        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        file_row.addWidget(QLabel("Project File:"))
        self.project_file_lbl = QLabel("(none)")
        self.project_file_lbl.setObjectName("accent_label")
        self.project_file_lbl.setToolTip("Path of the loaded YAML file")
        self.project_file_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        file_row.addWidget(self.project_file_lbl, 1)
        layout.addLayout(file_row)

        # run stop policies
        policy_row = QHBoxLayout()
        policy_row.setContentsMargins(0, 0, 0, 0)
        policy_row.addWidget(QLabel("Stop policy:"))
        self.stop_if_fail_cb = QCheckBox("Stop if failure")
        self.stop_if_fail_cb.setChecked(False)
        self.stop_if_fail_cb.setToolTip(
            "Default OFF. When checked, any test/operation that reports "
            "FAIL aborts the whole run immediately.")
        policy_row.addWidget(self.stop_if_fail_cb)
        self.stop_if_short_cb = QCheckBox("Stop if any short")
        self.stop_if_short_cb.setChecked(True)
        self.stop_if_short_cb.setToolTip(
            "Default ON. Applies to every Impedance Shorts test: if low "
            "impedance (short risk) is found, abort before powering the "
            "DUT on.")
        policy_row.addWidget(self.stop_if_short_cb)
        policy_row.addStretch(1)
        layout.addLayout(policy_row)

        self.overall = QTableWidget(2, 5)
        self.overall.setHorizontalHeaderLabels(
            ["#", "Stage", "EN", "Status", "Duration (s)"])
        self.overall.verticalHeader().setVisible(False)
        self.overall.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # stage description shows only as a hover tooltip, no column
        rows = [
            ("1", "ICT",
             "In-Circuit Test: 80 power nets impedance -> voltage "
             "-> RTC/CLKOUT1/CLKOUT2 clocks"),
            ("2", "FCT",
             "Functional Test: LED -> Serial Console (Linux) "
             "-> Wi-Fi -> Bluetooth -> Flash FAT -> Flash OOBE"),
        ]
        self._overall_edit_guard = True
        for r, (num, stage, desc) in enumerate(rows):
            for c, val in enumerate((num, stage, "", "Pending", "--")):
                item = QTableWidgetItem(val)
                item.setToolTip(desc)
                self.overall.setItem(r, c, item)
            en = self.overall.item(r, 2)
            en.setFlags(en.flags() | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsEnabled)
            en.setCheckState(Qt.CheckState.Checked)
        self._overall_en = [True, True]
        self._overall_edit_guard = False
        self.overall.itemChanged.connect(self._overall_item_changed)
        # column layout (M0): on the 0-1000 grid ~ #30 | Stage90 |
        # EN50 | Status200 | Duration200.  Stage is compact ("ICT"/
        # "FCT" need little room); Status is wide enough for
        # "Pending..." without truncation at the default font; the
        # Duration column stretches so the table's right edge
        # auto-fits the container (total layout width unchanged).
        # Headers stay centered (QHeaderView default alignment).
        self.overall.setColumnWidth(0, 30)
        self.overall.setColumnWidth(1, 90)
        self.overall.setColumnWidth(2, 50)
        self.overall.setColumnWidth(3, 200)
        header = self.overall.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        _fit_height(self.overall)
        layout.addWidget(self.overall)
        self._apply_overall_en_flags()
        return group

    def set_project_file(self, path):
        """Show the currently loaded/saved YAML file name in Overall Flow."""
        self.project_path = path or None
        if path:
            self.project_file_lbl.setText(Path(path).name)
            self.project_file_lbl.setToolTip(path)
        else:
            self.project_file_lbl.setText("(none)")
            self.project_file_lbl.setToolTip("Path of the loaded YAML file")

    def clear_tables(self):
        """When no YAML is loaded, clear ICT/FCT to a single empty row,
        clear the Power Rails Up Sequence waveform and remove every
        Console channel."""
        self.ict_steps = [("op", "", "—", "—", "—", "—")]
        self.ict_enables = [True]
        self.ict_waits = [100]
        self.ict_timeouts = [5000]
        self.ict.setRowCount(1)
        self._ict_edit_guard = True
        self._fill_ict(placeholder=True)
        self._ict_edit_guard = False

        self.fct_rows = [""]
        self.fct_enables = [True]
        self.fct_waits = [100]
        self.fct_timeouts = [5000]
        self.fct_kinds = ["MessageOK"]
        self.fct_op_params = [None]
        self.fct.setRowCount(1)
        self._fct_edit_guard = True
        self._fill_fct_all()
        self._fct_edit_guard = False

        # Power Rails Up Sequence: fully YAML-defined — no rails, no
        # checkboxes and nothing captured before a project is loaded
        self.set_rails([])

        # Console: no YAML -> no channels
        self.multi_console.clear_channels()

    def _build_ict(self):
        group = QGroupBox("ICT Test Cases")
        layout = QVBoxLayout(group)
        self.ict = QTableWidget(len(ICT_STEPS), 8)
        self.ict.setHorizontalHeaderLabels(
            ["#", "Test / Operation", "EN",
             "Unit", "Measured", "Min", "Max", "Result"])
        self.ict.verticalHeader().setVisible(False)
        # Enable uses a checkbox (single-click toggle); double-click any
        # cell opens the full edit dialog (all yaml-backed properties).
        self.ict.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ict_steps = ICT_STEPS
        self.ict_enables = [True] * len(ICT_STEPS)
        self.ict_waits = [100] * len(ICT_STEPS)
        self.ict_timeouts = [5000] * len(ICT_STEPS)
        self._ict_edit_guard = False
        self._fill_ict(placeholder=True)
        self.ict.itemChanged.connect(self._ict_item_changed)
        self.ict.cellDoubleClicked.connect(self._edit_ict_item)
        self.ict.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.ict.customContextMenuRequested.connect(
            self._ict_context_menu)
        # every column sizes to its content except Test / Operation,
        # which absorbs all leftover width (all other columns keep
        # their content centered - see _fill_ict_row)
        ict_header = self.ict.horizontalHeader()
        ict_header.setStretchLastSection(False)
        for c in (0, 2, 3, 4, 5, 6, 7):
            ict_header.setSectionResizeMode(
                c, QHeaderView.ResizeMode.ResizeToContents)
        ict_header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        _cap_visible_rows(self.ict, 8)
        layout.addWidget(self.ict)
        return group

    def _ict_item_changed(self, item):
        """Handle Enable checkbox toggle."""
        if self._ict_edit_guard:
            return
        row = item.row()
        col = item.column()
        if col == 2:  # Enable checkbox
            self.ict_enables[row] = item.checkState() == Qt.CheckState.Checked

    def _fill_ict(self, placeholder=False):
        for r in range(len(self.ict_steps)):
            self._fill_ict_row(r, placeholder)

    def _fill_ict_row(self, r, placeholder=False):
        """Fill one ICT row. Items are created once and then REUSED
        (setText only when changed) — recreating ~8 items for every row
        of a 175-row table on every run step forced a full
        ResizeToContents re-layout each time and froze the UI."""
        step = self.ict_steps[r]
        kind, name = step[0], step[1]
        unit, measured, lo, hi = step[2], step[3], step[4], step[5]
        readonly = ~Qt.ItemFlag.ItemIsEditable

        def cell(col, text, center=True):
            item = self.ict.item(r, col)
            if item is None:
                item = QTableWidgetItem()
                item.setFlags(item.flags() & readonly)
                if center:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.ict.setItem(r, col, item)
            if item.text() != text:
                item.setText(text)
            return item

        # col 0: # (centered, auto-sized)
        cell(0, str(r + 1))
        # col 1: Test / Operation (left aligned, blue bold for ops)
        name_item = cell(1, name, center=False)
        if kind == "op":
            name_item.setForeground(QColor(gui_theme_color("run")))
            name_item.setFont(_bold())
        else:
            name_item.setForeground(QBrush())
            name_item.setFont(QFont())
        # col 2: Enable checkbox
        self._ict_edit_guard = True
        en_item = self.ict.item(r, 2)
        if en_item is None:
            en_item = QTableWidgetItem()
            en_item.setFlags(en_item.flags()
                             | Qt.ItemFlag.ItemIsUserCheckable
                             | Qt.ItemFlag.ItemIsEnabled)
            self.ict.setItem(r, 2, en_item)
        wanted = (Qt.CheckState.Checked if self.ict_enables[r]
                  else Qt.CheckState.Unchecked)
        if en_item.checkState() != wanted:
            en_item.setCheckState(wanted)
        self._ict_edit_guard = False
        # cols 3-6: Unit, Measured, Min, Max
        # (Impedance Shorts has only a Min limit — Max stays blank)
        vals = (["--", "", lo, hi] if placeholder
                else [unit, measured, lo, hi])
        for c, val in enumerate(vals):
            cell(c + 3, val)
        # col 7: Result (centered; column auto-sizes to content)
        res_val = ("Pending" if placeholder
                   else "Done" if kind == "op" else "PASS")
        res_item = cell(7, f"Virtual {res_val}"
                        if self.virtual_mode and res_val != "Pending"
                        else res_val)
        if res_val in ("PASS", "Done"):
            res_item.setForeground(QColor(gui_theme_color("ok")))
            res_item.setFont(_bold())
        else:
            res_item.setForeground(QBrush())
            res_item.setFont(QFont())

    def _build_rails(self):
        group = QGroupBox("Power Rails Up Sequence")
        self.rails_group = group   # width capped at 50% (see eventFilter)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 6, 6, 6)

        # capture settings live in the properties dialog (double-click
        # the waveform); they are not shown on the page itself.
        self.cap_start = -0.5      # s, negative = before power-on
        self.cap_end = DURATION_S  # s
        self.cap_rate = SAMPLE_HZ  # U2355A AI sample rate (YAML defined)
        self.csv_export = True     # ticked = record waveform to DAQ csv

        self.rail_widget = WaveformWidget()
        self.rail_widget.t_start = self.cap_start
        self.rail_widget.doubleClicked.connect(self._edit_rail_props)
        layout.addWidget(self.rail_widget, 1)  # fill the whole group

        # bottom: per-rail visibility checkboxes (tick = show waveform);
        # rebuilt from the YAML rail set via set_rails() — empty until a
        # project file defines the rails
        self.rail_checks = {}
        self.rail_grid = QGridLayout()
        self.rail_grid.setContentsMargins(2, 0, 2, 0)
        layout.addLayout(self.rail_grid)
        self.set_rails(self.rails)
        return group

    def set_capture_settings(self, duration_s=None, rate_hz=None):
        """U2355A capture duration / sample rate from the project YAML."""
        if rate_hz:
            try:
                self.cap_rate = int(min(250000, max(1, float(rate_hz))))
            except (TypeError, ValueError):
                pass
        if duration_s:
            try:
                self.cap_end = float(duration_s)
            except (TypeError, ValueError):
                pass

    def set_rails(self, rails):
        """Replace the rail set (from the loaded YAML project): rebuild
        the visibility checkboxes and clear any captured waveform."""
        self.rails = [tuple(r) for r in rails]
        while self.rail_grid.count():
            item = self.rail_grid.takeAt(self.rail_grid.count() - 1)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.rail_checks = {}
        for i, (label, color, _vnom, _off) in enumerate(self.rails):
            cb = QCheckBox(label)
            cb.setChecked(True)
            # waveform keeps the vivid rail color; the checkbox text is
            # darkened just enough to stay readable on the white page
            cb.setStyleSheet(
                f"color:{text_for_card(color)}; font-size:13px;"
                " font-weight:bold;")
            cb.toggled.connect(self._apply_rail_filter)
            self.rail_grid.addWidget(cb, i % 2, i // 2)
            self.rail_checks[label] = cb
        # nothing captured for the (new) rail set yet
        self.rail_samples = None
        self.rail_volts = None
        self._rail_plot_cache = []
        self.rail_csv_path = None
        self._apply_rail_filter()

    def _apply_rail_filter(self):
        """Show only the rails whose checkbox is ticked."""
        visible = {label for label, cb in self.rail_checks.items()
                   if cb.isChecked()}
        filtered = [d for d in self._rail_plot_cache if d[0] in visible]
        dur = self.cap_end - self.cap_start
        self.rail_widget.set_data(filtered, dur, self.cap_start)

    # ------------------------------------------------- AI waveform review
    def _ai_wave_review(self):
        """Rule-based AI review of the sampled power-rail waveforms
        (engine data service, mtkgui.engine.rails)."""
        return ai_wave_review(self.rails, self.rail_samples,
                              self.cap_start, self.cap_end, self.cap_rate,
                              self.virtual_mode)

    def _edit_rail_props(self):
        """Double-click the waveform -> edit capture & rail properties,
        plus an AI review page grading the sampled waveform."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Power Rails — Properties")
        dlg.resize(600, 680)
        outer = QVBoxLayout(dlg)
        tabs = QTabWidget()
        outer.addWidget(tabs)

        # page 1: capture settings + rail reference table
        prop_page = QWidget()
        form = QFormLayout(prop_page)

        # capture settings
        start_spin = QDoubleSpinBox()
        start_spin.setRange(-10.0, 0.0)
        start_spin.setSingleStep(0.1)
        start_spin.setDecimals(2)
        start_spin.setValue(self.cap_start)
        start_spin.setSuffix(" s")
        start_spin.setToolTip("Negative = start before power-on")
        form.addRow("Capture Start:", start_spin)

        end_spin = QDoubleSpinBox()
        end_spin.setRange(0.1, 30.0)
        end_spin.setSingleStep(0.1)
        end_spin.setDecimals(2)
        end_spin.setValue(self.cap_end)
        end_spin.setSuffix(" s")
        form.addRow("Capture End:", end_spin)

        dur_lbl = QLabel(f"{end_spin.value() - start_spin.value():.2f} s")
        form.addRow("Duration:", dur_lbl)

        def _upd_dur():
            dur_lbl.setText(
                f"{end_spin.value() - start_spin.value():.2f} s")
        start_spin.valueChanged.connect(_upd_dur)
        end_spin.valueChanged.connect(_upd_dur)

        rate_spin = QSpinBox()
        rate_spin.setRange(1, 250000)  # U2355A aggregate 250 kSa/s
        rate_spin.setValue(int(self.cap_rate))
        rate_spin.setSuffix(" Hz")
        rate_spin.setSingleStep(100)
        rate_spin.setToolTip("Per-channel analog input sample rate "
                             "(project YAML: sample_rate_hz)")
        form.addRow("Sample Rate:", rate_spin)

        csv_cb = QCheckBox("Record waveform data to DAQ csv file")
        csv_cb.setChecked(self.csv_export)
        form.addRow("Export DAQ CSV:", csv_cb)

        form.addRow(QLabel(""))  # spacer

        # rail table (read-only reference)
        rail_tbl = QTableWidget(len(self.rails), 4)
        rail_tbl.setHorizontalHeaderLabels(
            ["Rail", "Color", "Nominal V", "Ramp Offset (s)"])
        rail_tbl.verticalHeader().setVisible(False)
        rail_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, (label, color, vnom, off) in enumerate(self.rails):
            rail_tbl.setItem(i, 0, QTableWidgetItem(label))
            c_item = QTableWidgetItem(color)
            c_item.setForeground(QColor(color))
            rail_tbl.setItem(i, 1, c_item)
            rail_tbl.setItem(i, 2, QTableWidgetItem(f"{vnom:.2f}"))
            rail_tbl.setItem(i, 3, QTableWidgetItem(f"{off:.3f}"))
        rail_tbl.setColumnWidth(0, 140)
        rail_tbl.setColumnWidth(1, 70)
        rail_tbl.setColumnWidth(2, 70)
        rail_tbl.setColumnWidth(3, 100)
        rail_tbl.horizontalHeader().setStretchLastSection(True)
        rail_tbl.setFixedHeight(28 + len(self.rails) * 24)
        form.addRow("Rails:", rail_tbl)

        tabs.addTab(prop_page, "Properties")

        # page 2: AI review of the sampled waveform parameters
        review_page = QWidget()
        r_layout = QVBoxLayout(review_page)
        r_layout.setContentsMargins(8, 8, 8, 8)
        review = QPlainTextEdit(self._ai_wave_review())
        review.setReadOnly(True)
        mono = QFont()
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setFamilies(["Menlo", "Consolas", "monospace"])
        review.setFont(mono)
        r_layout.addWidget(review)
        re_btn = QPushButton("Re-analyze")
        re_btn.clicked.connect(
            lambda: review.setPlainText(self._ai_wave_review()))
        r_layout.addWidget(re_btn)
        tabs.addTab(review_page, "AI Review")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # apply capture time / rate / csv changes
        self.cap_start = start_spin.value()
        self.cap_end = end_spin.value()
        self.cap_rate = rate_spin.value()
        self.csv_export = csv_cb.isChecked()
        self.rail_widget.t_start = self.cap_start
        # regenerate waveform with the new time range (healthy preview)
        self.rail_samples, self.rail_volts =             self._generate_rail_samples(inject_faults=False)
        self._rail_plot_cache = self._rail_plot_data(self.rail_samples)
        self._apply_rail_filter()

    def _build_fct(self):
        group = QGroupBox("FCT Test Cases")
        layout = QVBoxLayout(group)
        self.fct = QTableWidget(7, 5)
        self.fct.setHorizontalHeaderLabels(
            ["#", "Test", "EN", "Duration (s)", "Result"])
        self.fct.verticalHeader().setVisible(False)
        self.fct.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.fct_rows = [
            "MessageYesNo: LED Test (Power / Reset)",
            "CapturefromConsole: COM1, 'Linux version' (expected)",
            "WaitforConsole: COM1, 'Pass' or 'OK' (expected)",
            "SendtoCLI: \"wifi_test --scan\", 'Pass'/'Success' (expected)",
            "SendtoCLI: \"bt_test --scan\", 'Pass'/'Success' (expected)",
            "MessageGoStop: Flash FAT Firmware (3rd-party GUI)",
            "MessageGoStop: Flash OOBE Firmware (3rd-party GUI)",
        ]
        self.fct_enables = [True] * len(self.fct_rows)
        self.fct_waits = [100] * len(self.fct_rows)
        self.fct_timeouts = [5000] * len(self.fct_rows)
        self.fct_kinds = [_fct_kind_from_name(n) for n in self.fct_rows]
        # op rows (standard steps) carry their operation parameters
        self.fct_op_params = [
            dict(OP_STEPS[n]) if n in OP_STEPS else None
            for n in self.fct_rows]
        self._fct_edit_guard = False
        for r in range(len(self.fct_rows)):
            self._fill_fct_row(r)
        self.fct.itemChanged.connect(self._fct_item_changed)
        self.fct.cellDoubleClicked.connect(self._edit_fct_item)
        self.fct.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.fct.customContextMenuRequested.connect(
            self._fct_context_menu)
        self.fct.setColumnWidth(0, 28)
        self.fct.setColumnWidth(1, 220)
        self.fct.setColumnWidth(2, 40)
        # Duration and Result auto-size to content; Test absorbs leftover
        fct_header = self.fct.horizontalHeader()
        fct_header.setStretchLastSection(False)
        fct_header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        fct_header.setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        fct_header.setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents)
        _cap_visible_rows(self.fct, 12)
        layout.addWidget(self.fct)
        return group

    def _fct_item_changed(self, item):
        """Handle Enable checkbox toggle."""
        if self._fct_edit_guard:
            return
        row = item.row()
        col = item.column()
        if col == 2:  # Enable checkbox
            self.fct_enables[row] = item.checkState() == Qt.CheckState.Checked

    # -------------------------------------------------- failure simulation
    def _ict_context_menu(self, pos):
        """Right-click an ICT test row -> simulate a FAIL on the next run."""
        row = self.ict.rowAt(pos.y())
        if row < 0 or self.ict_steps[row][0] != "test":
            return
        menu = QMenu(self)
        act = menu.addAction("Simulate FAIL on next run")
        act.setCheckable(True)
        act.setChecked(row in self.ict_sim_fail)
        chosen = menu.exec(self.ict.viewport().mapToGlobal(pos))
        if chosen is act:
            (self.ict_sim_fail.add if act.isChecked()
             else self.ict_sim_fail.discard)(row)

    def _fct_context_menu(self, pos):
        """Right-click an FCT row -> simulate a FAIL on the next run."""
        row = self.fct.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
        act = menu.addAction("Simulate FAIL on next run")
        act.setCheckable(True)
        act.setChecked(row in self.fct_sim_fail)
        chosen = menu.exec(self.fct.viewport().mapToGlobal(pos))
        if chosen is act:
            (self.fct_sim_fail.add if act.isChecked()
             else self.fct_sim_fail.discard)(row)

    def _is_impedance_short_row(self, r):
        """True for every Impedance Shorts test row (engine helper,
        mtkgui.engine.steps.is_impedance_short)."""
        return is_impedance_short_row(self.ict_steps[r])

    def _fill_fct_row(self, r):
        """Fill one FCT row: # / Test / Enable / Duration / Result."""
        name = self.fct_rows[r]
        readonly = ~Qt.ItemFlag.ItemIsEditable
        # col 0: #
        num_item = QTableWidgetItem(str(r + 1))
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        num_item.setFlags(num_item.flags() & readonly)
        self.fct.setItem(r, 0, num_item)
        # col 1: Test name
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() & readonly)
        self.fct.setItem(r, 1, item)
        # col 2: Enable checkbox
        self._fct_edit_guard = True
        en_item = QTableWidgetItem()
        en_item.setFlags(en_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                         | Qt.ItemFlag.ItemIsEnabled)
        en_item.setCheckState(Qt.CheckState.Checked
                              if self.fct_enables[r]
                              else Qt.CheckState.Unchecked)
        self.fct.setItem(r, 2, en_item)
        self._fct_edit_guard = False
        # col 3: Duration (s) — filled after execution
        dur_item = QTableWidgetItem("--")
        dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        dur_item.setFlags(dur_item.flags() & readonly)
        self.fct.setItem(r, 3, dur_item)
        # col 4: Result (centered; column auto-sizes to content)
        res_item = QTableWidgetItem("Pending")
        res_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        res_item.setFlags(res_item.flags() & readonly)
        self.fct.setItem(r, 4, res_item)

    def _fill_fct_all(self):
        for r in range(len(self.fct_rows)):
            self._fill_fct_row(r)

    # ---- sequence editor dialog (double-click ICT / FCT) ----
    def _edit_ict_item(self, row, _col):
        """Double-click ICT -> open sequence editor."""
        if not self._can_edit_ict:
            self._deny_edit("ICT test cases")
            return
        self._open_sequence_editor("ict", row)

    def _edit_fct_item(self, row, _col):
        """Double-click FCT -> open sequence editor."""
        if not self._can_edit_fct:
            self._deny_edit("FCT test cases")
            return
        self._open_sequence_editor("fct", row)

    def _open_sequence_editor(self, which, initial_row=0):
        """Open the sequence editor dialog for ICT or FCT.

        The dialog works on a *copy* of the step list; only on Accept
        does it write the new list back and refill the table.
        """
        if which == "ict":
            steps = list(self.ict_steps)
            enables = list(self.ict_enables)
            waits = list(self.ict_waits)
            timeouts = list(self.ict_timeouts)
            kinds = None
            op_params = None     # ICT op params live in the step tuples
            kind = "ict"
            title = "ICT Test Case Sequence"
        else:
            steps = list(self.fct_rows)
            enables = list(self.fct_enables)
            waits = list(self.fct_waits)
            timeouts = list(self.fct_timeouts)
            kinds = list(self.fct_kinds)
            op_params = list(self.fct_op_params)
            kind = "fct"
            title = "FCT Test Case Sequence"

        dlg = _SequenceEditorDialog(
            kind, steps, enables, waits, timeouts, self, kinds=kinds,
            op_params=op_params)
        dlg.setWindowTitle(title)
        if initial_row and initial_row < len(steps):
            dlg.select_row(initial_row)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if which == "ict":
            (new_steps, new_enables,
             new_waits, new_timeouts) = dlg.result_data()
            self.ict_steps = new_steps
            self.ict_enables = new_enables
            self.ict_waits = new_waits
            self.ict_timeouts = new_timeouts
            self.ict.setRowCount(len(new_steps))
            self._ict_edit_guard = True
            self._fill_ict(placeholder=True)
            self._ict_edit_guard = False
        else:
            (new_steps, new_enables,
             new_waits, new_timeouts,
             new_kinds, new_op_params) = dlg.result_data()
            self.fct_rows = new_steps
            self.fct_enables = new_enables
            self.fct_waits = new_waits
            self.fct_timeouts = new_timeouts
            self.fct_kinds = new_kinds
            self.fct_op_params = new_op_params
            self.fct.setRowCount(len(new_steps))
            self._fct_edit_guard = True
            self._fill_fct_all()
            self._fct_edit_guard = False


    # ------------------------------------------------------------ demo data
    def _gen_rails(self):
        """Legacy demo rail waveforms (engine data service,
        mtkgui.engine.rails.generate_rails)."""
        return generate_rails(self.rails, self.cap_start, self.cap_end,
                              self.cap_rate)

    def _generate_rail_samples(self, inject_faults=True):
        """Return (fractions, volts) for one up-sequence capture
        (engine data service, mtkgui.engine.rails.capture_samples)."""
        return capture_samples(self.rack, self.rails, self.cap_start,
                               self.cap_end, self.cap_rate,
                               inject_faults=inject_faults)

    def _rail_plot_data(self, samples):
        return rail_plot_data(self.rails, samples)

    def _write_csv(self, samples, volts=None):
        return write_csv(LOGS_DIR, self.rails, samples, volts,
                         self.cap_start, self.cap_rate, self.virtual_mode)

    # ------------------------------------------------------------ actions
    def _set_status(self, table, row, col, status):
        text = f"Virtual {status}" if self.virtual_mode else status
        item = table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, col, item)
        if item.text() != text:
            item.setText(text)   # skip unchanged: avoids column re-layout
        font = QFont()
        if status in ("PASS", "Done"):
            item.setForeground(QColor(gui_theme_color("ok")))
            font.setBold(True)
        elif status in ("FAIL", "Error"):
            item.setForeground(QColor(gui_theme_color("bad")))
            font.setBold(True)
        elif status == "Ignore":
            item.setForeground(QColor(gui_theme_color("neutral")))
            font.setBold(True)
        else:
            item.setForeground(QBrush())
        item.setFont(font)

    def _log(self, line):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_line.emit(f"[{stamp}] {line}")

    # ------------------------------------------------------------ run steps
    # ------------------------------------------------------------ row highlight

    def _highlight_row(self, table, row):
        """Highlight the row being executed and scroll it into view."""
        self._clear_highlight()
        self._active_table, self._active_row = table, row
        # theme-aware highlight: light amber on light themes, dark amber
        # on Dark (the theme text stays readable on both)
        hl = "#4a4020" if saved_theme() == "Dark" else "#ffe9a8"
        for c in range(table.columnCount()):
            item = table.item(row, c)
            if item is not None:
                item.setBackground(QColor(hl))
        # scroll only when the active row left the visible viewport:
        # unconditional scrollToItem forced a page-wide repaint on every
        # run step (second-run jank)
        vp = table.viewport().rect()
        row_rect = table.visualItemRect(table.item(row, 0))
        if not row_rect.isValid() or row_rect.top() < vp.top() \
                or row_rect.bottom() > vp.bottom():
            table.scrollToItem(table.item(row, 0),
                               QTableWidget.ScrollHint.PositionAtCenter)
            # auto-scroll the page so the active table stays visible
            self.scroll.ensureWidgetVisible(table, 60, 80)

    def _clear_highlight(self):
        table, row = self._active_table, self._active_row
        if table is not None and 0 <= row < table.rowCount():
            for c in range(table.columnCount()):
                item = table.item(row, c)
                if item is not None:
                    item.setBackground(QBrush())
        self._active_table, self._active_row = None, -1

    # --- RunnerEnv bridge: rendering hooks called by the engine ---
    def _emit_progress(self, done, total):
        """Status-bar progress (current, total) for the running cycle."""
        self.run_progress.emit(done, total)

    def _highlight_step(self, kind, row):
        """Highlight the table row being executed (engine hook)."""
        if kind == "ict":
            self._highlight_row(self.ict, row)
        elif kind == "fct":
            self._highlight_row(self.fct, row)

    def _render_step(self, kind, row, status, measured, duration):
        """Render one engine step result into its table cell(s) — the
        same cell updates the legacy inline execution code performed."""
        if kind == "ict":
            step_kind = (self.ict_steps[row][0]
                         if row < len(self.ict_steps) else "")
            if measured is not None:
                item = self.ict.item(row, 4)
                if item is not None:
                    item.setText(str(measured))
            self._set_status(self.ict, row, 7,
                             display_text(status,
                                          "op" if step_kind == "op" else ""))
        elif kind == "fct":
            step_kind = (self.fct_kinds[row]
                         if row < len(self.fct_kinds) else "")
            self._set_status(self.fct, row, 4,
                             display_text(status,
                                          "op" if step_kind == "op" else ""))
            if duration is not None:
                self._set_status(self.fct, row, 3, f"{duration:.2f}")
        elif kind == "stage":
            self._set_status(self.overall, row, 3, display_text(status))
            if duration is not None:
                self.overall.item(row, 4).setText(f"{duration:.2f}")

    def _store_rail_capture(self, samples, volts, plot_cache, csv_path,
                            review):
        """Keep the latest capture (samples / volts / plot cache / CSV
        path / AI review text) on the page for the waveform widget and
        the properties dialog (engine hook)."""
        self.rail_samples = samples
        self.rail_volts = volts
        self._rail_plot_cache = plot_cache
        self.rail_csv_path = csv_path
        self._ai_review_text = review

    def _mark_stage_skipped(self, r, text):
        """Render a disabled Overall Flow stage as Skip (engine hook)."""
        self._set_status(self.overall, r, 3, "Skip")
        self._log(text)

    def _instrument_error(self, abbr):
        """Forward a virtual equipment fault to the status bar (hook)."""
        self.instrument_error.emit(abbr)

    def _connect_failed_popup(self, labels):
        """Error popup when pre-FCT console connect failed (hook)."""
        QMessageBox.warning(
            self, "Console Connect Failed",
            f"Could not connect console channel(s): {labels}\n\n"
            "The test run was stopped. Check the console parameters "
            "and connections, then run again.")

    # --- engine delegates: historical call-sites (smoke test) ---
    def _exec_ict_row(self, r):
        """Execute one ICT test-case row (engine, TestRunner)."""
        self._runner._exec_ict_row(r)

    def _exec_fct_row(self, r, interactive=True):
        """Execute one FCT test-case row (engine, TestRunner)."""
        self._runner._exec_fct_row(r, interactive=interactive)

    def _run_step(self):
        """Run-timer tick: execute the next step (engine, TestRunner)."""
        self._runner._run_step()

    def _policy_abort_reason(self, kind, args):
        """Check the just-finished step against the Overall Flow stop
        policies (engine, mtkgui.engine.policies). Returns an abort log
        message, or None to continue."""
        return self._runner._policy_abort_reason(kind, args)

    def _fct_message_dialog(self, kind, name):
        """Modal operator dialog for the FCT message test methods.

        MessageOK     -> info box, OK      -> PASS
        MessageYesNo  -> Yes -> PASS / No (or X-close) -> FAIL
        MessageGoStop -> GO  -> PASS / STOP (or X-close) -> FAIL

        While the dialog is open the 100 ms run timer keeps ticking;
        the runner's _fct_dialog_open flag makes those ticks no-ops so
        the run does not re-enter.  The dialog is centered by the
        app-level event filter like every other dialog."""
        method, _, message = name.partition(":")
        message = message.strip() or name
        box = QMessageBox(self)
        box.setWindowTitle(f"FCT: {method.strip()}")
        box.setText(message)
        box.setModal(True)
        if kind == "MessageOK":
            box.setIcon(QMessageBox.Icon.Information)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            self._log(f"FCT {name}: waiting for operator OK ...")
        elif kind == "MessageYesNo":
            box.setIcon(QMessageBox.Icon.Question)
            box.setStandardButtons(QMessageBox.StandardButton.Yes
                                   | QMessageBox.StandardButton.No)
            self._log(f"FCT {name}: waiting for operator Yes / No ...")
        else:  # MessageGoStop
            box.setIcon(QMessageBox.Icon.Warning)
            go = box.addButton("GO", QMessageBox.ButtonRole.YesRole)
            box.addButton("STOP", QMessageBox.ButtonRole.NoRole)
            self._log(f"FCT {name}: waiting for operator GO / STOP ...")
        self._runner._fct_dialog_open = True
        try:
            box.exec()
        finally:
            self._runner._fct_dialog_open = False
        if kind == "MessageOK":
            return "PASS"
        clicked = box.clickedButton()
        if kind == "MessageYesNo":
            ok = (clicked is not None
                  and clicked.text().replace("&", "") == "Yes")
            pressed = "Yes" if ok else "No"
        else:
            ok = clicked is go
            pressed = "GO" if ok else "STOP"
        self._log(f"FCT {name}: operator pressed {pressed} "
                  f"-> {'PASS' if ok else 'FAIL'}")
        return "PASS" if ok else "FAIL"

    def run_demo(self):
        """Synchronous full pass (used by smoke test); honors the
        Overall Flow EN checkboxes (engine, TestRunner.run_demo)."""
        self._runner.run_demo()

    # ------------------------------------------------------------ run control
    def _pretest(self):
        """Pre-test phase, executed the moment Run is pressed (before any
        test case). Returns True when the run may continue.

        Serial Number Format Check (menu Settings): serial = <prefix> +
        <SN Length digits>; both configurable and optional (empty = no
        check). On failure: error dialog + behave exactly like the
        Stop button (all items blank, Overall Result = IGNORE)."""
        self._log("Pre-test: start")
        cfg = self.sn_format() if self.sn_format else None
        if cfg:
            prefix = (cfg.get("prefix") or "").strip()
            length = (cfg.get("length") or "").strip()
            if prefix or (length.isdigit() and length):
                serial = self.serial_edit.text().strip()
                fail = None
                if prefix and not serial.startswith(prefix):
                    fail = f"start with prefix '{prefix}'"
                digits = serial[len(prefix):] if prefix else serial
                if fail is None and length.isdigit() and length:
                    if not digits.isdigit() or len(digits) != int(length):
                        fail = (f"be prefix + {length} digits "
                                f"(got '{digits}')")
                if fail is not None:
                    QMessageBox.critical(
                        self, "Pre-test Failed",
                        "Serial Number format check failed:\n"
                        f"'{serial}'\n\n"
                        f"Expected: {fail}.")
                    self._log(f"Pre-test: Serial Number format check FAILED"
                              f" ('{serial}', expected {fail}) "
                              f"-> stop, IGNORE")
                    self._interrupted = True
                    self._blank_all_steps()
                    self._update_result()
                    return False
                self._log(f"Pre-test: Serial Number format check OK "
                          f"({serial})")
        return True

    def _blank_all_steps(self):
        """Blank every test item (pre-test failure == Stop pressed before
        the first step, so everything is left blank)."""
        for r in range(len(self.ict_steps)):
            self.ict.item(r, 4).setText("")
            self.ict.item(r, 7).setText("")
        for r in range(self.fct.rowCount()):
            self._set_status(self.fct, r, 3, "")
            self._set_status(self.fct, r, 4, "")
        for r in range(self.overall.rowCount()):
            self._set_status(self.overall, r, 3, "")
            self.overall.item(r, 4).setText("")

    def _next_serial(self):
        """Auto-SN checked -> all product info is virtual: empty fields
        get default values, the serial number auto-increments."""
        if not self.auto_sn.isChecked():
            return
        if not self.part_edit.text().strip():
            self.part_edit.setText("VIRTUAL-PART")
        if not self.core_edit.text().strip():
            self.core_edit.setText("000000")
        if not self.batch_edit.text().strip():
            self.batch_edit.setText("freebatch")
        self._sn_counter += 1
        self.serial_edit.setText(f"VS{self._sn_counter:010d}")

    def _steps_template(self, ict_count, fct_count):
        """Run steps for the stages enabled in Overall Flow only
        (engine helper, mtkgui.engine.steps.steps_template)."""
        return steps_template(ict_count, fct_count, self._overall_en)

    def start_run(self):
        """Run button: pre-test, then step through every test case.
        Long Run > 1 repeats the whole cycle with a pause in between.
        The Run gates + button state stay on the page; the run state
        machine itself lives in the engine (TestRunner.start)."""
        if self.run_state == "running":
            return
        if not self.project_path:
            QMessageBox.warning(
                self, "No Test Project",
                "No YAML file is loaded.\n\n"
                "Please load a test project first:\n"
                "File > Load Yaml")
            self._log("Run blocked: no YAML file loaded")
            return
        if not any(self._overall_en):
            QMessageBox.warning(
                self, "No Available Tests",
                "Both ICT and FCT are disabled in Overall Flow.\n"
                "Enable at least one stage before running.")
            self._log("Run blocked: no available tests "
                      "(ICT and FCT both disabled)")
            return
        self._next_serial()
        if not self._pretest():
            return
        self._set_phase("Init...")
        self._interrupted = False
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        # long run skips product information input
        self.product_group.setEnabled(False)
        self._runner.start(self.longrun_spin.value())

    def stop_run(self):
        """Stop button: interrupt the run. Remaining test items are left
        blank and the Overall Result is IGNORE (engine, TestRunner.abort;
        the page renders the interrupted state via _on_run_finished)."""
        self._runner.abort()

    # --- RunnerEnv bridge: run-control state rendering -----------------
    def _on_cycle_reset(self):
        """Engine begins a cycle -> blank defaults + clear Event Log."""
        self.clear_results()

    def _on_stage_skipped(self, r, text):
        """Engine marks a disabled Overall Flow stage as Skip."""
        self._mark_stage_skipped(r, text)

    def _on_run_finished(self, summary):
        """Render the end-of-cycle state the legacy code performed
        inline (abort / operator stop / cycle complete).  The engine
        already wrote the run-control Event Log lines via its sink."""
        reason = summary["reason"]
        if reason == "cycle":
            # mid long-run: count the finished cycle, show the pause
            if summary["progress"]:
                self.run_progress.emit(summary["total"], summary["total"])
            self.cycle_times.append(summary["cycle_s"])
            self._count_product()
            self._update_result()
            return
        if reason == "stop":
            self.run_progress.emit(0, 0)
            self._interrupted = True
        elif reason == "complete":
            if summary["progress"]:
                self.run_progress.emit(summary["total"], summary["total"])
        if summary["reset_phase"]:
            self._clear_highlight()
            self._set_phase("")
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.product_group.setEnabled(True)
        # remaining (not yet executed) test items -> blank
        for step in summary["remaining"]:
            kind = step[0]
            if kind == "ict":
                r = step[1]
                self.ict.item(r, 4).setText("")
                self.ict.item(r, 7).setText("")
            elif kind == "fct":
                self._set_status(self.fct, step[1], 4, "")
            elif kind == "stage":
                self._set_status(self.overall, step[1], 3, "")
                self.overall.item(step[1], 4).setText("")
        if summary["counted"]:
            self.cycle_times.append(summary["cycle_s"])
            self._count_product()
        self._update_result()
        if reason != "stop":
            # legacy: abort / complete emit run_finished (page jump);
            # operator stop does not
            self.run_finished.emit()

    def clear_results(self):
        self._interrupted = False
        self._runner.reset_results()
        if self.rack is not None:
            self.rack.reset_cycle()  # new unit: PSU off, fixture released
        self._fill_ict(placeholder=True)
        for r in range(self.fct.rowCount()):
            self._set_status(self.fct, r, 3, "--")
            self._set_status(self.fct, r, 4, "Pending")
        for r in range(self.overall.rowCount()):
            self._set_status(self.overall, r, 3, "Pending")
            self.overall.item(r, 4).setText("--")
        self.log_cleared.emit()
        self._update_result()


class _SequenceEditorDialog(QDialog):
    """Dialog for reordering, adding, removing, editing, and duplicating
    test case steps. Works on copies; only writes back on accept."""

    def __init__(self, kind, steps, enables, waits, timeouts, parent=None,
                 kinds=None, op_params=None):
        super().__init__(parent)
        self._kind = kind  # "ict" or "fct"
        self._steps = list(steps)
        self._enables = list(enables)
        self._waits = list(waits)
        self._timeouts = list(timeouts)
        # FCT only: parallel Test Method list (ICT steps carry the kind
        # inside their step tuples)
        self._kinds = list(kinds) if kinds is not None else None
        # FCT only: operation parameters for kind == "op" rows
        self._op_params = (list(op_params)
                           if op_params is not None else None)
        self._build_ui()
        self._populate()

    def _lists(self):
        """All parallel step lists (kinds / op params included for FCT)."""
        base = (self._steps, self._enables, self._waits, self._timeouts)
        if self._kinds is not None:
            base += (self._kinds,)
        if self._op_params is not None:
            base += (self._op_params,)
        return base

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- list + button column ---
        top = QHBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemDoubleClicked.connect(self._on_edit)
        self.list_widget.currentRowChanged.connect(self._update_buttons)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        top.addWidget(self.list_widget, 1)

        btn_col = QVBoxLayout()
        self.btn_up = QPushButton("Move Up")
        self.btn_down = QPushButton("Move Down")
        self.btn_add = QPushButton("Add")
        # Add offers every test type ICT / FCT support (dropdown menu)
        self.btn_add.setMenu(self._make_add_menu())
        self.btn_remove = QPushButton("Remove")
        self.btn_edit = QPushButton("Edit")
        self.btn_duplicate = QPushButton("Duplicate")
        for btn in (self.btn_up, self.btn_down, self.btn_add,
                    self.btn_remove, self.btn_edit, self.btn_duplicate):
            btn_col.addWidget(btn)
        btn_col.addStretch()
        top.addLayout(btn_col)
        layout.addLayout(top)

        self.btn_up.clicked.connect(self._on_move_up)
        self.btn_down.clicked.connect(self._on_move_down)
        self.btn_add.clicked.connect(self._on_add)
        self.btn_remove.clicked.connect(self._on_remove)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_duplicate.clicked.connect(self._on_duplicate)

        # --- ok / cancel ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 1.5x of the previous 520x460: wide list + roomy edit dialogs
        self.resize(1170, 690)

    def _make_add_menu(self):
        """Dropdown for the Add button: every supported step type."""
        menu = QMenu(self)
        if self._kind == "ict":
            # every standard operation (with its default parameters)
            # plus a custom operation and the generic measurement test
            types = [(f"Operation: {n}", _op_step(n)) for n in OP_STEPS]
            types += [
                ("Operation: Custom",
                 ("op", "New Operation", "—", "—", "—", "—")),
                ("Test (measurement)",
                 ("test", "New Test", "—", "—", "—", "—")),
            ]
        else:
            # FCT Add dropdown: standard operations first, then every
            # supported test method with a matching template name
            types = [(f"Operation: {n}", n, "op", dict(OP_STEPS[n]))
                     for n in OP_STEPS]
            types += [
                ("MessageOK — notice dialog (Ok -> Done)",
                 "MessageOK: New Test", "MessageOK"),
                ("MessageYesNo — operator Yes / No dialog",
                 "MessageYesNo: New Test", "MessageYesNo"),
                ("MessageGoStop — Go / Stop dialog (No stops the run)",
                 "MessageGoStop: New Test", "MessageGoStop"),
                ("SendtoConsole — send command to console",
                 "SendtoConsole: COM1, 'cmd'", "SendtoConsole"),
                ("WaitforConsole — wait for a console keyword",
                 "WaitforConsole: COM1, 'Pass' (expected)",
                 "WaitforConsole"),
                ("CapturefromConsole — instant buffer capture",
                 "CapturefromConsole: COM1, 'Pass' (expected)",
                 "CapturefromConsole"),
                ("Delay — plain wait (ms)",
                 "Delay: 1000 ms", "Delay"),
                ("SendtoCLI — run CLI command, check Pass / Success",
                 "SendtoCLI: \"cmd --run\", 'Pass'/'Success' (expected)",
                 "SendtoCLI"),
                ("WaitforCLI — wait for a CLI keyword",
                 "WaitforCLI: 'Pass' (expected)", "WaitforCLI"),
                ("CapturefromCLI — instant CLI buffer capture",
                 "CapturefromCLI: 'Pass' (expected)", "CapturefromCLI"),
                ("WIFI — Wi-Fi connectivity test",
                 "WIFI: scan and associate", "WIFI"),
                ("Bluetooth — Bluetooth connectivity test",
                 "Bluetooth: scan and pair", "Bluetooth"),
            ]
        for entry in types:
            act = menu.addAction(entry[0])
            method = entry[2] if len(entry) > 2 else None
            params = entry[3] if len(entry) > 3 else None
            act.triggered.connect(
                lambda _checked=False, s=entry[1], m=method, p=params:
                    self._on_add(s, m, p))
        return menu

    def _populate(self):
        self.list_widget.clear()
        for i, step in enumerate(self._steps):
            label = self._label_for(i, step)
            item = QListWidgetItem(label)
            item.setCheckState(
                Qt.CheckState.Checked if self._enables[i]
                else Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        self._update_buttons()

    def _label_for(self, i, step):
        if self._kind == "ict":
            kind, name = step[0], step[1]
            tag = ("[op]" if kind == "op"
                   else f"[{kind}]" if kind != "test" else "[test]")
            if kind == "op" and len(step) > 6 and step[6]:
                return f"{i+1:3d}. {tag} {name} · {_op_summary(step[6])}"
            return f"{i+1:3d}. {tag} {name}"
        else:
            if self._kinds is not None:
                m = self._kinds[i] if i < len(self._kinds) else ""
                return f"{i+1:3d}. [{m}] {step}"
            return f"{i+1:3d}. {step}"

    def _update_buttons(self):
        r = self.list_widget.currentRow()
        n = len(self._steps)
        self.btn_up.setEnabled(r > 0)
        self.btn_down.setEnabled(0 <= r < n - 1)
        self.btn_remove.setEnabled(n > 1)
        self.btn_edit.setEnabled(0 <= r < n)
        self.btn_duplicate.setEnabled(0 <= r < n)

    # ------------------------------------------------------- actions
    def _on_move_up(self):
        r = self.list_widget.currentRow()
        if r <= 0:
            return
        self._swap(r, r - 1)
        self._populate()
        self.list_widget.setCurrentRow(r - 1)

    def _on_move_down(self):
        r = self.list_widget.currentRow()
        if r < 0 or r >= len(self._steps) - 1:
            return
        self._swap(r, r + 1)
        self._populate()
        self.list_widget.setCurrentRow(r + 1)

    def _swap(self, i, j):
        for lst in self._lists():
            lst[i], lst[j] = lst[j], lst[i]

    def _on_add(self, new_step=None, new_kind=None, new_params=None):
        """Add a new step of the chosen type after the current row and
        open edit (new_step comes from the Add dropdown; the fallback
        keeps the blank-step behavior for programmatic callers)."""
        if new_step is None:
            new_step = (("test", "New Test", "—", "—", "—", "—")
                        if self._kind == "ict" else "New Test")
        r = self.list_widget.currentRow()
        if r < 0:
            r = len(self._steps)
        for lst in self._lists():
            lst.insert(r + 1, None)
        self._steps[r + 1] = new_step
        self._enables[r + 1] = True
        self._waits[r + 1] = 100
        self._timeouts[r + 1] = 5000
        if self._kinds is not None:
            if new_kind == "op":
                self._kinds[r + 1] = "op"
            elif new_kind in FCT_METHODS:
                self._kinds[r + 1] = new_kind
            else:
                self._kinds[r + 1] = "MessageOK"
        if self._op_params is not None:
            self._op_params[r + 1] = (dict(new_params)
                                      if new_kind == "op" and new_params
                                      else None)
        self._populate()
        self.list_widget.setCurrentRow(r + 1)
        self._on_edit()

    def _on_remove(self):
        r = self.list_widget.currentRow()
        if r < 0 or len(self._steps) <= 1:
            return
        for lst in self._lists():
            del lst[r]
        self._populate()
        self.list_widget.setCurrentRow(min(r, len(self._steps) - 1))

    def _on_edit(self, _item=None):
        r = self.list_widget.currentRow()
        if r < 0:
            return
        if self._kind == "ict":
            edited = self._edit_ict_step(r)
        else:
            edited = self._edit_fct_step(r)
        if edited:
            self._populate()
            self.list_widget.setCurrentRow(r)

    def _on_duplicate(self):
        r = self.list_widget.currentRow()
        if r < 0:
            return
        for lst in self._lists():
            lst.insert(r + 1, lst[r])
        self._populate()
        self.list_widget.setCurrentRow(r + 1)

    def _on_item_changed(self, item):
        """Sync checkbox state to the enables list."""
        r = self.list_widget.row(item)
        if 0 <= r < len(self._enables):
            self._enables[r] = item.checkState() == Qt.CheckState.Checked

    # ------------------------------------------------------- edit dialogs
    def _edit_ict_step(self, r):
        step = self._steps[r]
        if step[0] == "op":
            return self._edit_op_step(r, step)
        kind, name, unit, measured, lo, hi = step[:6]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Step {r + 1} — Edit")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(name)
        kind_combo = QComboBox()
        kind_combo.addItems(
            ["op", "test", "Static Impedance", "Power Voltage",
             "Clock Hz", "DAQ AI"])
        kind_combo.setCurrentText(kind)
        unit_edit = QLineEdit(unit)
        measured_edit = QLineEdit(measured)
        lo_edit = QLineEdit(lo)
        hi_edit = QLineEdit(hi)
        enable_cb = QCheckBox()
        enable_cb.setChecked(self._enables[r])
        wait_spin = QSpinBox()
        wait_spin.setRange(0, 99999)
        wait_spin.setValue(self._waits[r])
        wait_spin.setSuffix(" ms")
        timeout_spin = QSpinBox()
        timeout_spin.setRange(0, 999999)
        timeout_spin.setValue(self._timeouts[r])
        timeout_spin.setSuffix(" ms")
        form.addRow("Name:", name_edit)
        form.addRow("Test Method:", kind_combo)
        form.addRow("Enable:", enable_cb)
        form.addRow("Wait:", wait_spin)
        form.addRow("Timeout:", timeout_spin)
        form.addRow("Unit:", unit_edit)
        form.addRow("Measured:", measured_edit)
        form.addRow("Min:", lo_edit)
        form.addRow("Max:", hi_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        self._steps[r] = (
            kind_combo.currentText(),
            name_edit.text().strip() or name,
            unit_edit.text().strip() or "—",
            measured_edit.text().strip() or "—",
            lo_edit.text().strip() or "—",
            hi_edit.text().strip() or "—",
        )
        self._enables[r] = enable_cb.isChecked()
        self._waits[r] = wait_spin.value()
        self._timeouts[r] = timeout_spin.value()
        return True

    def _edit_op_step(self, r, step):
        """Edit one operation step: pick a standard step and configure
        its parameters (instruments / fixture signal+level / PSU
        setpoints) in per-type fields. Used by both ICT (step tuple)
        and FCT (name string + parallel kind / op-params lists)."""
        if self._kind == "ict":
            name = step[1]
            params = dict(step[6]) if len(step) > 6 and step[6] else {}
        else:
            name = step
            params = (dict(self._op_params[r])
                      if self._op_params is not None
                      and r < len(self._op_params)
                      and self._op_params[r] else {})

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Step {r + 1} — Edit (Operation)")
        outer = QVBoxLayout(dlg)

        head = QFormLayout()
        op_combo = QComboBox()
        op_combo.setEditable(True)
        op_combo.addItems(list(OP_STEPS) + ["Custom Operation"])
        op_combo.setCurrentText(
            name if (name in OP_STEPS or not name) else "Custom Operation")
        head.addRow("Standard Step:", op_combo)
        outer.addLayout(head)

        # per-type parameter area, rebuilt when the step type changes
        param_form = QFormLayout()
        param_box = QWidget()
        param_box.setLayout(param_form)
        outer.addWidget(param_box)
        fields = {}

        def current_type():
            return OP_STEPS.get(op_combo.currentText().strip(),
                                {}).get("type", "custom")

        def rebuild_params():
            fields.clear()
            while param_form.rowCount():
                param_form.removeRow(0)
            t = current_type()
            if t in ("instruments", "reset"):
                chosen = set(params.get("instruments", []) or [])
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                checks = []
                for inst in ("DAQM", "DAQ", "PSU"):
                    cb = QCheckBox(inst)
                    cb.setChecked(not chosen or inst in chosen)
                    h.addWidget(cb)
                    checks.append(cb)
                fields["instruments"] = checks
                param_form.addRow("Instruments:", row)
            elif t == "fixture":
                sig = QComboBox()
                sig.addItems(["press", "inpos", "estop"])
                sig.setCurrentText(params.get("signal", "press"))
                lvl = QComboBox()
                lvl.addItems(["H", "L"])
                lvl.setCurrentText(params.get("level", "H"))
                fields["signal"], fields["level"] = sig, lvl
                param_form.addRow("Signal:", sig)
                param_form.addRow("Level:", lvl)
            elif t == "power":
                if "voltage" in params or \
                        op_combo.currentText().strip() == "Power On DUT":
                    volt = QDoubleSpinBox()
                    volt.setRange(0.0, 60.0)
                    volt.setDecimals(2)
                    volt.setSuffix(" V")
                    volt.setValue(float(params.get("voltage", 5.0)))
                    curr = QDoubleSpinBox()
                    curr.setRange(0.0, 12.5)
                    curr.setDecimals(2)
                    curr.setSuffix(" A")
                    curr.setValue(float(params.get("current", 1.0)))
                    fields["voltage"], fields["current"] = volt, curr
                    param_form.addRow("Voltage:", volt)
                    param_form.addRow("Current limit:", curr)
                else:
                    param_form.addRow(
                        QLabel("N5747A output OFF — no setpoints."))
            else:
                param_form.addRow(
                    QLabel("Custom operation: no parameters."))

        op_combo.currentTextChanged.connect(lambda _t: rebuild_params())
        rebuild_params()

        enable_cb = QCheckBox()
        enable_cb.setChecked(self._enables[r])
        wait_spin = QSpinBox()
        wait_spin.setRange(0, 99999)
        wait_spin.setValue(self._waits[r])
        wait_spin.setSuffix(" ms")
        timeout_spin = QSpinBox()
        timeout_spin.setRange(0, 999999)
        timeout_spin.setValue(self._timeouts[r])
        timeout_spin.setSuffix(" ms")
        meta = QFormLayout()
        meta.addRow("Enable:", enable_cb)
        meta.addRow("Wait:", wait_spin)
        meta.addRow("Timeout:", timeout_spin)
        outer.addLayout(meta)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        new_name = op_combo.currentText().strip()
        if not new_name or new_name == "Custom Operation":
            new_name = name or "New Operation"
        t = current_type()
        if t in ("instruments", "reset"):
            new_params = {"type": t, "instruments": [
                cb.text() for cb in fields["instruments"]
                if cb.isChecked()]}
        elif t == "fixture":
            new_params = {"type": "fixture",
                          "signal": fields["signal"].currentText(),
                          "level": fields["level"].currentText()}
        elif t == "power":
            new_params = {"type": "power"}
            if "voltage" in fields:
                new_params["voltage"] = fields["voltage"].value()
                new_params["current"] = fields["current"].value()
        else:
            new_params = None
        if self._kind == "ict":
            self._steps[r] = ("op", new_name, "—", "—", "—", "—",
                              new_params)
        else:
            self._steps[r] = new_name
            if self._kinds is not None:
                self._kinds[r] = "op"
            if self._op_params is not None:
                self._op_params[r] = new_params
        self._enables[r] = enable_cb.isChecked()
        self._waits[r] = wait_spin.value()
        self._timeouts[r] = timeout_spin.value()
        return True

    def _edit_fct_step(self, r):
        name = self._steps[r]
        if self._kinds and r < len(self._kinds) and \
                self._kinds[r] == "op":
            # FCT op rows keep the name in _steps (plain string) and the
            # parameters in _op_params: bridge to the ICT-style op
            # editor, then split the 7-tuple it writes back
            params = (self._op_params[r]
                      if r < len(self._op_params) else None)
            ok = self._edit_op_step(r, _op_step(name, params))
            if ok:
                step = self._steps[r]
                self._steps[r] = step[1]
                while len(self._op_params) <= r:
                    self._op_params.append(None)
                self._op_params[r] = step[6]
            return ok
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Step {r + 1} — Edit")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(name)
        method_combo = QComboBox()
        method_combo.addItems(FCT_METHODS)
        method_combo.setCurrentText(
            self._kinds[r] if self._kinds and r < len(self._kinds)
            else _fct_kind_from_name(name))
        enable_cb = QCheckBox()
        enable_cb.setChecked(self._enables[r])
        wait_spin = QSpinBox()
        wait_spin.setRange(0, 99999)
        wait_spin.setValue(self._waits[r])
        wait_spin.setSuffix(" ms")
        timeout_spin = QSpinBox()
        timeout_spin.setRange(0, 999999)
        timeout_spin.setValue(self._timeouts[r])
        timeout_spin.setSuffix(" ms")
        form.addRow("Name:", name_edit)
        form.addRow("Test Method:", method_combo)
        form.addRow("Enable:", enable_cb)
        form.addRow("Wait:", wait_spin)
        form.addRow("Timeout:", timeout_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        self._steps[r] = name_edit.text().strip() or name
        if self._kinds is not None:
            self._kinds[r] = method_combo.currentText()
        self._enables[r] = enable_cb.isChecked()
        self._waits[r] = wait_spin.value()
        self._timeouts[r] = timeout_spin.value()
        return True

    # ------------------------------------------------------- helpers
    def select_row(self, row):
        if 0 <= row < len(self._steps):
            self.list_widget.setCurrentRow(row)

    def result_data(self):
        """Return (steps, enables, waits, timeouts[, kinds, op_params])."""
        for i in range(len(self._enables)):
            item = self.list_widget.item(i)
            if item:
                self._enables[i] = (
                    item.checkState() == Qt.CheckState.Checked)
        if self._kinds is not None:
            return (self._steps, self._enables,
                    self._waits, self._timeouts, self._kinds,
                    self._op_params)
        return (self._steps, self._enables,
                self._waits, self._timeouts)


def _bold():
    font = QFont()
    font.setBold(True)
    return font


def _cap_visible_rows(table, n=12):
    """Reserve a viewport n rows tall; extra rows get a scrollbar.

    The viewport keeps its n-row capacity even when the table currently
    holds fewer rows (e.g. a 12-row FCT area with only 7 cases). Only a
    minimum height is set, so the user can still resize the table
    (e.g. via a splitter handle)."""
    fm = QFontMetrics(table.font())
    row_h = fm.height() + 8
    header_h = max(table.horizontalHeader().sizeHint().height(),
                   fm.height() + 10)
    table.setMinimumHeight(header_h + n * row_h + 4
                           + table.frameWidth() * 2)


def _fit_height(table):
    """Expand a table to its full content (used inside the outer scroll).

    Row / header heights are not reliable before the widget is shown, so
    derive a minimum from the font metrics to avoid rows overlapping the
    header."""
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    fm = QFontMetrics(table.font())
    min_row = fm.height() + 8
    header_h = max(table.horizontalHeader().sizeHint().height(),
                   fm.height() + 10)
    height = header_h + 4
    for r in range(table.rowCount()):
        height += max(table.rowHeight(r), min_row)
    table.setFixedHeight(height + 2)
