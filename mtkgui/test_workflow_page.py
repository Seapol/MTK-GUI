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

import csv
import random
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QRectF, QRegularExpression, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
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

from .style import gui_theme_color, text_for_card
from .widgets.multi_console import MultiConsoleWidget

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
_ICON_DIR = Path(__file__).resolve().parent / "assets"

# power rails (name, color, nominal voltage, ramp start offset [s])
RAILS = [
    ("VDD_SNVS_3V3", "#ef4444", 3.30, 0.00),
    ("VDD_HIGH_3V3", "#2f6fb3", 3.30, 0.05),
    ("VDDA_1V8",     "#1f8a70", 1.80, 0.10),
    ("VDD_DDR_1V1",  "#0ea5e9", 1.10, 0.15),
    ("NVCC_DRAM_1V2","#14b8a6", 1.20, 0.20),
    ("VDD_SOC_0V8",  "#c07a2d", 0.80, 0.25),
    ("VDD_ARM_0V85", "#7a4fa8", 0.85, 0.30),
    ("VDD_PHY_1V8",  "#eab308", 1.80, 0.35),
    ("VDD_USB_3V3",  "#b3424a", 3.30, 0.40),
    ("NVCC_SD1_3V3", "#ec4899", 3.30, 0.45),
    ("NVCC_EMC_3V3", "#8b5cf6", 3.30, 0.50),
    ("VDD_PCIE_1V8", "#64748b", 1.80, 0.55),
]

DURATION_S = 10.0
SAMPLE_HZ = 200

# ICT test cases: the sequence executes strictly top -> bottom. Standard
# operations (fixture / instrument control) report Done/Error; measurement
# tests report PASS/FAIL.
# Impedance shorts MUST run before the DUT is powered on: a short under
# power risks damaging the board, so "Stop if any short" aborts the run
# right here, before "Power On DUT".
# (kind, name, unit, measured, min / threshold, max)
ICT_STEPS = [
    ("op", "Init Instruments", "—", "—", "—", "—"),
    ("op", "Fixture Clamp Down", "—", "—", "—", "—"),
    ("op", "Fixture Lock", "—", "—", "—", "—"),
    ("op", "Fixture E-Stop Healthy", "—", "—", "—", "—"),
    ("test", "Impedance Shorts (80 pts)", "Ω", "80/80",
     "1.5 Ω", ""),
    ("op", "Power On DUT", "—", "—", "—", "—"),
    ("test", "Power Voltage (80 pts)", "V", "80/80", "±0.1 %", "—"),
    ("test", "RTC - 32.768 kHz (907A TOT)", "Hz", "32.7681k",
     "32.752k", "32.784k"),
    ("test", "CLKOUT1 - 4 MHz (U2355A CTR0)", "Hz", "4.0002M",
     "3.996M", "4.004M"),
    ("test", "CLKOUT2 - 6 MHz (U2355A CTR1)", "Hz", "6.0001M",
     "5.994M", "6.006M"),
    ("test", "ADC Stimulus AO0/AO1 -> TP_ADC", "V", "2/2",
     "±12 V 16-bit", "—"),
    ("test", "Fixture DIO (16 ch, 4 used)", "ch", "4/4", "—", "—"),
    ("test", "DUT GPIO (24 ch)", "ch", "24/24",
     "drive/read/toggle", "—"),
    ("op", "Power Off DUT", "—", "—", "—", "—"),
    ("op", "Fixture Unlock", "—", "—", "—", "—"),
    ("op", "Fixture Release", "—", "—", "—", "—"),
    ("op", "Reset Instruments", "—", "—", "—", "—"),
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
        self.setMinimumHeight(190)

    def set_data(self, data, duration, t_start=0.0):
        self.data = data
        self.duration = duration
        self.t_start = t_start
        self.update()

    def set_virtual(self, on):
        """Virtual mode: the capture is simulated demo data, not a real
        DAQ measurement (drawn with a VIRTUAL DATA badge)."""
        self.virtual = bool(on)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
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
        self.rail_csv_path = None
        self._rail_plot_cache = []
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
        # run control state machine: "idle" | "running"
        self.run_state = "idle"
        self.project_path = None  # loaded YAML; Run is blocked until set
        self._interrupted = False
        self._wait_done = False
        self._run_steps = []
        self._run_index = 0
        # pre-FCT console connect step ("fctconn"): open every console
        # channel the project YAML defines. The worker threads run in
        # the background, so the step polls until they are up or the
        # timeout (seconds) elapses.
        self.fct_connect_timeout = 10.0
        self._fctconn_pending = []
        self._fctconn_failed = []
        self._fctconn_deadline = 0.0
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
        # Virtual mode: simulated HW, random fault injection, "Virtual "
        # result prefix (set from MainWindow according to the login mode)
        self.virtual_mode = False
        self.fault_cfg = {"test_fail_ratio": 0, "equipment_error_ratio": 0}
        # currently executing row (highlighted + auto-scrolled into view)
        self._active_table = None
        self._active_row = -1
        self._run_timer = QTimer(self)
        self._run_timer.setInterval(100)  # one test step every 100 ms
        self._run_timer.timeout.connect(self._run_step)
        # long run: repeat whole cycles with a pause in between
        self._lr_total = 1
        self._lr_done = 0
        self._lr_wait_timer = QTimer(self)
        self._lr_wait_timer.setSingleShot(True)
        self._lr_wait_timer.timeout.connect(self._start_next_cycle)
        # virtual serial number counter (Auto-SN)
        self._sn_counter = 0
        # account permissions (defaults = supervisor until apply_permissions)
        self._supervisor = True
        self._perm = {}
        self._can_edit_ict = True
        self._can_edit_fct = True
        self._build()
        self._seed_demo_data()

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
        can_product = supervisor or bool(perm.get("edit_product_info"))
        for edit in (self.part_edit, self.core_edit, self.batch_edit,
                     self.serial_edit):
            edit.setReadOnly(not can_product)
        self.auto_sn.setEnabled(can_product)
        can_run_cfg = supervisor or bool(perm.get("edit_run_control"))
        self.longrun_spin.setEnabled(can_run_cfg)
        self.interval_spin.setEnabled(can_run_cfg)
        self.multi_console.apply_permissions(perm, supervisor)

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
        with a configurable pause between cycles (1..99 s), skipping
        product information input."""
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

        # Long Run: how many cycles to loop
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("Long Run:"))
        self.longrun_spin = QSpinBox()
        self.longrun_spin.setRange(1, 999)
        self.longrun_spin.setValue(1)
        count_row.addWidget(self.longrun_spin, 1)
        layout.addLayout(count_row)

        # pause between cycles
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Interval (s):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 99)
        self.interval_spin.setValue(1)
        interval_row.addWidget(self.interval_spin, 1)
        layout.addLayout(interval_row)

        layout.addStretch(1)
        return group

    def _build_result(self):
        """Right of the top row: big verdict + per-product statistics."""
        group = QGroupBox("Overall Result")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
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

    def set_virtual_fault(self, cfg):
        """Fault-injection ratios (percent) used in Virtual mode only."""
        if cfg:
            self.fault_cfg = dict(cfg)

    def _virtual_fault_roll(self):
        """Random Virtual-mode fault injection.

        Returns "Error" (random equipment / serial fault), "FAIL"
        (random out-of-limit measurement / unexpected reply) or None."""
        if not self.virtual_mode:
            return None
        if (random.random() * 100
                < self.fault_cfg.get("equipment_error_ratio", 0)):
            return "Error"
        if random.random() * 100 < self.fault_cfg.get("test_fail_ratio", 0):
            return "FAIL"
        return None

    @staticmethod
    def _raw_status(text):
        """Undo the 'Virtual ' prefix shown on results in Virtual mode."""
        return text[8:] if text.startswith("Virtual ") else text

    def _judge_verdict(self):
        """PASS/FAIL of the current tables; None when nothing judged yet."""
        judged_any = False
        failed = False
        for r in range(self.ict.rowCount()):
            text = self._raw_status(self.ict.item(r, 7).text())
            if text in ("PASS", "Done"):
                judged_any = True
            elif text in ("FAIL", "Error"):
                judged_any = True
                failed = True
        for r in range(self.fct.rowCount()):
            text = self._raw_status(self.fct.item(r, 4).text())
            if text == "PASS":
                judged_any = True
            elif text in ("FAIL", "Error"):
                judged_any = True
                failed = True
        if not judged_any:
            return None
        return "FAIL" if failed else "PASS"

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

        self.overall = QTableWidget(2, 4)
        self.overall.setHorizontalHeaderLabels(
            ["#", "Stage", "Status", "Duration (s)"])
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
        for r, (num, stage, desc) in enumerate(rows):
            for c, val in enumerate((num, stage, "Pending", "--")):
                item = QTableWidgetItem(val)
                item.setToolTip(desc)
                self.overall.setItem(r, c, item)
        self.overall.setColumnWidth(0, 28)
        self.overall.setColumnWidth(1, 180)
        self.overall.setColumnWidth(2, 70)
        self.overall.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        self.overall.horizontalHeader().setStretchLastSection(False)
        _fit_height(self.overall)
        layout.addWidget(self.overall)
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
        """When no YAML is loaded, clear ICT/FCT to a single empty row."""
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
        self.fct.setRowCount(1)
        self._fct_edit_guard = True
        self._fill_fct_all()
        self._fct_edit_guard = False

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
        self.ict.setColumnWidth(0, 28)
        self.ict.setColumnWidth(1, 220)
        self.ict.setColumnWidth(2, 40)
        # Max column absorbs leftover width; Result auto-sizes to its
        # content (Pending / PASS / FAIL / Ignore / Done) and stays centered
        ict_header = self.ict.horizontalHeader()
        ict_header.setStretchLastSection(False)
        ict_header.setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents)
        ict_header.setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents)
        ict_header.setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents)
        ict_header.setSectionResizeMode(
            6, QHeaderView.ResizeMode.Stretch)
        ict_header.setSectionResizeMode(
            7, QHeaderView.ResizeMode.ResizeToContents)
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
        kind, name, unit, measured, lo, hi = self.ict_steps[r]
        readonly = ~Qt.ItemFlag.ItemIsEditable
        # col 0: #
        num_item = QTableWidgetItem(str(r + 1))
        num_item.setFlags(num_item.flags() & readonly)
        self.ict.setItem(r, 0, num_item)
        # col 1: Test / Operation
        name_item = QTableWidgetItem(name)
        if kind == "op":
            name_item.setForeground(QColor("#2c5fa8"))
            name_item.setFont(_bold())
        name_item.setFlags(name_item.flags() & readonly)
        self.ict.setItem(r, 1, name_item)
        # col 2: Enable checkbox
        self._ict_edit_guard = True
        en_item = QTableWidgetItem()
        en_item.setFlags(en_item.flags() | Qt.ItemFlag.ItemIsUserCheckable
                         | Qt.ItemFlag.ItemIsEnabled)
        en_item.setCheckState(Qt.CheckState.Checked
                              if self.ict_enables[r]
                              else Qt.CheckState.Unchecked)
        self.ict.setItem(r, 2, en_item)
        self._ict_edit_guard = False
        # cols 3-6: Unit, Measured, Min, Max
        # (Impedance Shorts has only a Min limit — Max stays blank)
        vals = (["--", "", lo, hi] if placeholder
                else [unit, measured, lo, hi])
        for c, val in enumerate(vals):
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() & readonly)
            self.ict.setItem(r, c + 3, item)
        # col 7: Result (centered; column auto-sizes to content)
        res_val = ("Pending" if placeholder
                   else "Done" if kind == "op" else "PASS")
        res_item = QTableWidgetItem(
            f"Virtual {res_val}"
            if self.virtual_mode and res_val != "Pending" else res_val)
        res_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if res_val in ("PASS", "Done"):
            res_item.setForeground(QColor("#1d7a3c"))
            res_item.setFont(_bold())
        res_item.setFlags(res_item.flags() & readonly)
        self.ict.setItem(r, 7, res_item)

    def _build_rails(self):
        group = QGroupBox("Power Rails Up Sequence")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 6, 6, 6)

        # capture settings live in the properties dialog (double-click
        # the waveform); they are not shown on the page itself.
        self.cap_start = -0.5      # s, negative = before power-on
        self.cap_end = DURATION_S  # s
        self.csv_export = True     # ticked = record waveform to DAQ csv

        self.rail_widget = WaveformWidget()
        self.rail_widget.t_start = self.cap_start
        self.rail_widget.doubleClicked.connect(self._edit_rail_props)
        layout.addWidget(self.rail_widget, 1)  # fill the whole group

        # bottom: per-rail visibility checkboxes (tick = show waveform)
        self.rail_checks = {}
        grid = QGridLayout()
        grid.setContentsMargins(2, 0, 2, 0)
        for i, (label, color, _vnom, _off) in enumerate(RAILS):
            cb = QCheckBox(label)
            cb.setChecked(True)
            # waveform keeps the vivid rail color; the checkbox text is
            # darkened just enough to stay readable on the white page
            cb.setStyleSheet(
                f"color:{text_for_card(color)}; font-size:13px;"
                " font-weight:bold;")
            cb.toggled.connect(self._apply_rail_filter)
            grid.addWidget(cb, i % 2, i // 2)
            self.rail_checks[label] = cb
        layout.addLayout(grid)
        return group

    def _apply_rail_filter(self):
        """Show only the rails whose checkbox is ticked."""
        visible = {label for label, cb in self.rail_checks.items()
                   if cb.isChecked()}
        filtered = [d for d in self._rail_plot_cache if d[0] in visible]
        dur = self.cap_end - self.cap_start
        self.rail_widget.set_data(filtered, dur, self.cap_start)

    # ------------------------------------------------- AI waveform review
    def _ai_wave_review(self):
        """Rule-based AI review of the sampled power-rail waveforms.

        Grades every rail's parameters - steady level, start delay, rise
        time, overshoot, settling, ripple and ramp monotonicity - and
        returns a plain-text report page."""
        if not self.rail_samples:
            return ("AI Waveform Review\n"
                    "==================\n"
                    "No waveform captured yet - run a sequence first.")
        hz = SAMPLE_HZ
        kind = ("virtual demo data" if self.virtual_mode
                else "DAQ capture")
        lines = [
            "AI Waveform Review - Power Rails Up Sequence",
            "=" * 62,
            f"Capture : {self.cap_start:+.2f} s .. {self.cap_end:.2f} s "
            f"@ {hz} Hz, {len(self.rail_samples)} rails ({kind})",
            "Windows : level +/-3 %, overshoot <=5 %, ripple <=1 % p-p,",
            "          monotonic ramp, settle within 1 %",
            "",
        ]
        grades = []
        for (label, _color, vnom, _off), s in zip(RAILS,
                                                  self.rail_samples):
            # steady level & ripple from the last 20 % of the capture
            tail = s[int(len(s) * 0.8):]
            level = sum(tail) / len(tail)
            dev = (level - 1.0) * 100
            p2p = (max(tail) - min(tail)) * 100
            # timing: first 10 % / 90 % crossings during the ramp
            i10 = next((i for i, v in enumerate(s) if v >= 0.1), None)
            i90 = None
            if i10 is not None:
                i90 = next((i for i in range(i10, len(s))
                            if s[i] >= 0.9), None)
            rise_ms = ((i90 - i10) * 1000 / hz
                       if i10 is not None and i90 is not None else 0.0)
            t10 = (i10 / hz) if i10 is not None else 0.0
            over = (max(s) - 1.0) * 100
            # settling: first moment |v-1| stays within 1 % for 50 ms
            win = max(1, int(hz * 0.05))
            settle_ms = None
            if i10 is not None and i90 is not None:
                for j in range(i90, max(i90 + 1, len(s) - win)):
                    if all(abs(v - 1.0) <= 0.01 for v in s[j:j + win]):
                        settle_ms = (j - i10) * 1000 / hz
                        break
            # monotonicity: biggest downward step inside the ramp
            drop = 0.0
            if i10 is not None and i90 is not None and i90 > i10 + 1:
                seg = s[i10:i90 + 1]
                drop = max(a - b for a, b in zip(seg, seg[1:])) * 100
            lvl_ok = abs(dev) <= 3.0
            over_ok = over <= 5.0
            rip_ok = p2p <= 1.0
            mono_ok = drop <= 2.0
            ok_all = lvl_ok and over_ok and rip_ok and mono_ok
            grades.append(ok_all)
            lines += [
                f"{label}  (nominal {vnom:.2f} V)  ->  "
                f"{'Good' if ok_all else 'Check'}",
                f"  steady level    : {level * 100:6.1f} % of nominal "
                f"({dev:+.2f} %)  "
                f"{'ok' if lvl_ok else 'OUT of +/-3 % window'}",
                f"  start (10 %)    : t = {t10:+.3f} s",
                f"  rise 10 -> 90 % : {rise_ms:6.1f} ms",
                f"  overshoot       : {over:+.2f} %  "
                f"{'ok' if over_ok else 'too high (>5 %)'}",
                f"  settle in 1 %   : "
                + (f"{settle_ms:.0f} ms" if settle_ms is not None
                   else "not settled"),
                f"  ripple p-p      : {p2p:.2f} %  "
                f"{'ok' if rip_ok else 'noisy (>1 %)'}",
                f"  ramp monotonic  : "
                f"{'ok' if mono_ok else f'dip of {drop:.2f} %'}",
                "",
            ]
        n_good = sum(grades)
        n_all = len(grades)
        if n_good == n_all:
            overall = (f"OVERALL: {n_good}/{n_all} rails pass all windows "
                       f"- waveform is realistic and healthy.")
        else:
            overall = (f"OVERALL: {n_good}/{n_all} rails pass all windows; "
                       f"review the CHECK items above.")
        lines += ["-" * 62, overall]
        return "\n".join(lines)

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

        sr_lbl = QLabel(f"{SAMPLE_HZ} Hz")
        form.addRow("Sample Rate:", sr_lbl)

        csv_cb = QCheckBox("Record waveform data to DAQ csv file")
        csv_cb.setChecked(self.csv_export)
        form.addRow("Export DAQ CSV:", csv_cb)

        form.addRow(QLabel(""))  # spacer

        # rail table (read-only reference)
        rail_tbl = QTableWidget(len(RAILS), 4)
        rail_tbl.setHorizontalHeaderLabels(
            ["Rail", "Color", "Nominal V", "Ramp Offset (s)"])
        rail_tbl.verticalHeader().setVisible(False)
        rail_tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, (label, color, vnom, off) in enumerate(RAILS):
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
        rail_tbl.setFixedHeight(28 + len(RAILS) * 24)
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

        # apply capture time / csv changes
        self.cap_start = start_spin.value()
        self.cap_end = end_spin.value()
        self.csv_export = csv_cb.isChecked()
        self.rail_widget.t_start = self.cap_start
        # regenerate waveform with new time range
        self.rail_samples, _ = self._gen_rails()
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
        """True for every Impedance Shorts test row — the scope of the
        'Stop if any short' policy. Detected by unit Ω (per-net rows)
        or by the legacy aggregate name containing 'impedance short'."""
        unit = self.ict_steps[r][2].strip()
        if unit == "Ω":
            return True
        name = self.ict_steps[r][1].lower()
        return "impedance" in name and "short" in name

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
            kind = "ict"
            title = "ICT Test Case Sequence"
        else:
            steps = list(self.fct_rows)
            enables = list(self.fct_enables)
            waits = list(self.fct_waits)
            timeouts = list(self.fct_timeouts)
            kind = "fct"
            title = "FCT Test Case Sequence"

        dlg = _SequenceEditorDialog(
            kind, steps, enables, waits, timeouts, self)
        dlg.setWindowTitle(title)
        if initial_row and initial_row < len(steps):
            dlg.select_row(initial_row)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_steps, new_enables, new_waits, new_timeouts = dlg.result_data()
        if which == "ict":
            self.ict_steps = new_steps
            self.ict_enables = new_enables
            self.ict_waits = new_waits
            self.ict_timeouts = new_timeouts
            self.ict.setRowCount(len(new_steps))
            self._ict_edit_guard = True
            self._fill_ict(placeholder=True)
            self._ict_edit_guard = False
        else:
            self.fct_rows = new_steps
            self.fct_enables = new_enables
            self.fct_waits = new_waits
            self.fct_timeouts = new_timeouts
            self.fct.setRowCount(len(new_steps))
            self._fct_edit_guard = True
            self._fill_fct_all()
            self._fct_edit_guard = False


    # ------------------------------------------------------------ demo data
    def _seed_demo_data(self):
        """Pre-generate one capture so the page already looks alive."""
        self.rail_samples, _ = self._gen_rails()
        self._rail_plot_cache = self._rail_plot_data(self.rail_samples)
        self._apply_rail_filter()

    def _gen_rails(self):
        """Generate simulated rail waveforms.

        start_s can be negative — the capture begins before power-on
        (all rails flat at 0 V until t = 0, then ramps begin).
        """
        start_s = self.cap_start
        end_s = self.cap_end
        rng = random.Random(42)
        n = int((end_s - start_s) * SAMPLE_HZ)
        power_on_idx = int(abs(start_s) * SAMPLE_HZ)
        samples = []
        for label, color, vnom, ramp_off in RAILS:
            ramp_pts = max(1, int((0.25 + ramp_off) * SAMPLE_HZ))
            # realistic converters slightly overshoot (1-4 %) when the
            # ramp completes, then settle within ~20 ms
            overshoot = rng.uniform(0.01, 0.04)
            series = []
            for i in range(n):
                if i < power_on_idx:
                    frac = 0.0
                elif i < power_on_idx + ramp_pts:
                    local_i = i - power_on_idx
                    frac = local_i / ramp_pts
                    frac = frac * frac * (3 - 2 * frac)  # smoothstep
                else:
                    frac = 1.0
                ripple = 0.004 * (1 - frac) * rng.uniform(-1, 1)
                noise = 0.0015 * rng.uniform(-1, 1) if frac >= 1 else 0
                over = 0.0
                if frac >= 1.0 and overshoot:
                    settle = (i - power_on_idx - ramp_pts) / SAMPLE_HZ
                    over = overshoot * 2.718 ** (-settle / 0.02)
                series.append(min(1.06, max(
                    0.0, frac + ripple + noise + over)))
            samples.append(series)
        return samples, n

    def _rail_plot_data(self, samples):
        return [(label, color, vnom, series)
                for (label, color, vnom, _), series
                in zip(RAILS, samples)]

    def _write_csv(self, samples):
        LOGS_DIR.mkdir(exist_ok=True)
        mid = "_virtual" if self.virtual_mode else ""
        name = f"power_rails{mid}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path = LOGS_DIR / name
        start_s = self.cap_start
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["time_ms"] + [r[0] for r in RAILS])
            for i in range(len(samples[0])):
                t_ms = (start_s + i / SAMPLE_HZ) * 1000
                row = [f"{t_ms:.1f}"]
                for series in samples:
                    row.append(f"{series[i]:.6f}")
                writer.writerow(row)
        return path

    # ------------------------------------------------------------ actions
    def _set_status(self, table, row, col, status):
        old = table.item(row, col)
        text = f"Virtual {status}" if self.virtual_mode else status
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if old is not None and old.toolTip():
            item.setToolTip(old.toolTip())
        if status in ("PASS", "Done"):
            item.setForeground(QColor("#1d7a3c"))
            item.setFont(_bold())
        elif status in ("FAIL", "Error"):
            item.setForeground(QColor("#c0392b"))
            item.setFont(_bold())
        elif status == "Ignore":
            item.setForeground(QColor("#64748b"))
            item.setFont(_bold())
        table.setItem(row, col, item)

    def _log(self, line):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_line.emit(f"[{stamp}] {line}")

    # ------------------------------------------------------------ run steps
    # ------------------------------------------------------------ row highlight

    def _highlight_row(self, table, row):
        """Highlight the row being executed and scroll it into view."""
        self._clear_highlight()
        self._active_table, self._active_row = table, row
        for c in range(table.columnCount()):
            item = table.item(row, c)
            if item is not None:
                item.setBackground(QColor("#ffe9a8"))
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

    def _exec_ict_row(self, r):
        """Execute one ICT test-case row.

        op -> Done; test -> PASS, except rows flagged through the
        context menu (ict_sim_fail) which simulate a real FAIL —
        Impedance Shorts rows then show low-impedance (short) points.
        """
        self._fill_ict_row(r, placeholder=False)
        self._highlight_row(self.ict, r)
        kind, name, unit, measured, lo, hi = self.ict_steps[r]
        if kind == "op":
            self._log(f"ICT sequence: {name} -> Done")
        elif r in self.ict_sim_fail:
            if self._is_impedance_short_row(r):
                # 2 of 80 points below the minimum resistance -> short risk
                self.ict.item(r, 4).setText("2/80")
                self._set_status(self.ict, r, 7, "FAIL")
                self._log(f"ICT {name}: 2 low-impedance points < 1.5 Ω "
                          f"(short risk) -> FAIL")
            else:
                self._set_status(self.ict, r, 7, "FAIL")
                self._log(f"ICT {name}: {measured} {unit} out of limit "
                          f"({lo}..{hi}) -> FAIL")
        else:
            fault = self._virtual_fault_roll()
            if fault == "Error":
                self._set_status(self.ict, r, 7, "Error")
                self.instrument_error.emit("DAQM")
                self._log(f"ICT {name}: random equipment / serial fault "
                          f"(virtual) -> Error")
            elif fault == "FAIL":
                self._set_status(self.ict, r, 7, "FAIL")
                self._log(f"ICT {name}: {measured} {unit} out of limit "
                          f"({lo}..{hi}) (virtual fail) -> FAIL")
            else:
                self._log(f"ICT {name}: {measured} {unit} "
                          f"(threshold {lo}..{hi}) -> PASS")

    def _capture_rails(self):
        """Capture the power rails up sequence (between ICT and FCT)."""
        self.rail_samples, _ = self._gen_rails()
        self._rail_plot_cache = self._rail_plot_data(self.rail_samples)
        self._apply_rail_filter()
        # Virtual mode: simulated demo data (marked on the plot + CSV)
        tag = " (virtual)" if self.virtual_mode else ""
        if self.csv_export:
            path = self._write_csv(self.rail_samples)
            self.rail_csv_path = path
            # AI review page: grade every rail's waveform parameters
            review = self._ai_wave_review()
            self._ai_review_text = review
            rpath = path.with_name(path.stem + "_ai_review.txt")
            try:
                rpath.write_text(review, encoding="utf-8")
                self._log(f"Power rails up sequence: captured 12 rails"
                          f"{tag}, CSV saved ({path.name}), "
                          f"AI review ({rpath.name})")
            except OSError:
                self._log(f"Power rails up sequence: captured 12 rails"
                          f"{tag}, CSV saved ({path.name}), "
                          f"AI review save failed")
        else:
            self.rail_csv_path = None
            self._ai_review_text = self._ai_wave_review()
            self._log(f"Power rails up sequence: captured 12 rails{tag} "
                      f"(display only, CSV export off)")

    def _exec_fct_row(self, r):
        self._highlight_row(self.fct, r)
        name = self.fct.item(r, 1).text()
        t0 = time.monotonic()
        if r in self.fct_sim_fail:
            self._set_status(self.fct, r, 4, "FAIL")
            self._log(f"FCT {name}: expected pass marker not found -> FAIL")
        else:
            fault = self._virtual_fault_roll()
            if fault == "Error":
                self._set_status(self.fct, r, 4, "Error")
                self.instrument_error.emit(random.choice(("DAQ", "PSU")))
                self._log(f"FCT {name}: random equipment / serial fault "
                          f"(virtual) -> Error")
            elif fault == "FAIL":
                self._set_status(self.fct, r, 4, "FAIL")
                self._log(f"FCT {name}: unexpected reply (virtual fail) "
                          f"-> FAIL")
            else:
                self._set_status(self.fct, r, 4, "PASS")
                if r < 5:
                    self._log(f"FCT {name}: output contained 'Pass' -> PASS")
                else:
                    self._log(f"FCT {name}: operator confirmed PASS")
        duration = time.monotonic() - t0
        self._set_status(self.fct, r, 3, f"{duration:.2f}")

    def _complete_stage(self, r):
        """Mark one Overall Flow stage PASS and record its duration (s)."""
        self._set_status(self.overall, r, 2, "PASS")
        duration = time.monotonic() - self._stage_start
        self.overall.item(r, 3).setText(f"{duration:.2f}")
        self._stage_start = time.monotonic()

    def run_demo(self):
        """Synchronous full pass (used by smoke test)."""
        t0 = time.monotonic()
        self._stage_start = t0
        for r in range(len(self.ict_steps)):
            self._exec_ict_row(r)
        self._complete_stage(0)
        self._capture_rails()
        for r in range(self.fct.rowCount()):
            self._exec_fct_row(r)
        self._complete_stage(1)
        self._log("Overall flow: ICT -> FCT all PASS")
        self.cycle_times.append(time.monotonic() - t0)
        self._count_product()
        self._update_result()
        self.run_finished.emit()

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
            self._set_status(self.overall, r, 2, "")
            self.overall.item(r, 3).setText("")

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

    @staticmethod
    def _steps_template(ict_count, fct_count):
        steps = [("ict", r) for r in range(ict_count)]
        steps.append(("stage", 0))
        steps.append(("rails",))
        if fct_count:
            steps.append(("fctconn",))  # console connect before FCT
        steps += [("fct", r) for r in range(fct_count)]
        steps.append(("stage", 1))
        return steps

    def start_run(self):
        """Run button: pre-test, then step through every test case.
        Long Run > 1 repeats the whole cycle with a pause in between."""
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
        self._next_serial()
        if not self._pretest():
            return
        self.run_state = "running"
        self._interrupted = False
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        # long run skips product information input
        self.product_group.setEnabled(False)
        self._lr_total = self.longrun_spin.value()
        self._lr_done = 0
        self._begin_cycle()

    def _begin_cycle(self):
        self.clear_results()
        self._interrupted = False
        self._wait_done = False
        self._run_start = time.monotonic()
        self._stage_start = self._run_start
        self._run_steps = self._steps_template(
            len(self.ict_steps), self.fct.rowCount())
        self._run_index = 0
        if self._lr_total > 1:
            self._log(f"Long Run cycle {self._lr_done + 1}/"
                      f"{self._lr_total} started.")
        else:
            self._log("Run started.")
        self._run_timer.start()

    def _start_next_cycle(self):
        """Long Run pause elapsed -> auto-increment SN and start again."""
        if self.run_state != "running":
            return  # stopped during the interval
        self._next_serial()
        self._begin_cycle()

    def _run_step(self):
        if self._run_index >= len(self._run_steps):
            self._finish_run()
            return
        self.run_progress.emit(self._run_index, len(self._run_steps))
        kind, *args = self._run_steps[self._run_index]
        # disabled ICT / FCT steps are marked Ignore
        if kind == "ict" and not self.ict_enables[args[0]]:
            self._set_status(self.ict, args[0], 7, "Ignore")
            self._log(f"ICT {self.ict_steps[args[0]][1]} -> Ignore (disabled)")
            self._run_index += 1
            self._wait_done = False
            return
        if kind == "fct" and not self.fct_enables[args[0]]:
            self._set_status(self.fct, args[0], 4, "Ignore")
            self._log(f"FCT {self.fct_rows[args[0]]} -> Ignore (disabled)")
            self._run_index += 1
            self._wait_done = False
            return
        # console channels must be connected before the FCT stage starts
        if kind == "fctconn":
            self._run_fct_connect_step()
            return
        # per-step wait time (ms): pause before executing
        if kind in ("ict", "fct", "stage"):
            if kind == "ict":
                wait = self.ict_waits[args[0]]
            elif kind == "fct":
                wait = self.fct_waits[args[0]]
            else:
                wait = 0
            if wait > 0 and not self._wait_done:
                self._wait_done = True
                self._log(f"Wait {wait} ms ...")
                self._run_timer.stop()
                QTimer.singleShot(wait, self._resume_step)
                return
        self._wait_done = False
        self._run_index += 1
        if kind == "ict":
            self._exec_ict_row(args[0])
        elif kind == "rails":
            self._capture_rails()
        elif kind == "fct":
            self._exec_fct_row(args[0])
        elif kind == "stage":
            self._complete_stage(args[0])
        self._update_result()
        # Overall Flow stop policies (stop if failure / stop if any short)
        reason = self._policy_abort_reason(kind, args)
        if reason:
            self._abort_run(reason)

    def _policy_abort_reason(self, kind, args):
        """Check the just-finished step against the Overall Flow stop
        policies. Returns an abort log message, or None to continue."""
        if kind == "ict":
            r = args[0]
            result = self._raw_status(self.ict.item(r, 7).text())
            if result not in ("FAIL", "Error"):
                return None
            name = self.ict_steps[r][1]
            if (self._is_impedance_short_row(r)
                    and self.stop_if_short_cb.isChecked()):
                return (f"Stop policy (Stop if any short): low impedance "
                        f"detected at '{name}' -> run aborted BEFORE power "
                        f"on. Overall Result: FAIL")
            if self.stop_if_fail_cb.isChecked():
                return (f"Stop policy (Stop if failure): '{name}' reported "
                        f"{result} -> run aborted. Overall Result: FAIL")
        elif kind == "fct":
            r = args[0]
            if (self._raw_status(self.fct.item(r, 4).text()) == "FAIL"
                    and self.stop_if_fail_cb.isChecked()):
                return (f"Stop policy (Stop if failure): FCT "
                        f"'{self.fct_rows[r]}' reported FAIL -> run "
                        f"aborted. Overall Result: FAIL")
        return None

    def _fct_connect_targets(self):
        """Console channels that must be connected before the FCT stage:
        the channels defined by the loaded project YAML (fallback: every
        channel with an endpoint configured) that are still offline."""
        mc = self.multi_console
        keys = mc.yaml_channel_keys()
        if keys is None:
            keys = [k for k in mc.channels if mc.channel_endpoint(k)]
        return [k for k in keys if not mc.channel_connected(k)]

    def _run_fct_connect_step(self):
        """("fctconn",) step: make sure every console channel from the
        project YAML is connected before FCT starts. Channels the user
        connected manually beforehand are skipped, missing ones are
        opened now. Channels that cannot be connected stop the run with
        an error popup and Overall Result FAIL (first FCT row -> Error)."""
        targets = self._fct_connect_targets()
        if not targets:
            self._run_index += 1
            self._wait_done = False
            return  # run timer continues with the FCT stage
        self._wait_done = True
        self._run_timer.stop()
        self._log("Connecting console channel(s) before FCT: "
                  + ", ".join(targets))
        self._fctconn_failed = []
        self._fctconn_pending = []
        mc = self.multi_console
        for key in targets:
            if mc.virtual_mode or mc.channel_endpoint(key):
                mc.open_channel(key)  # asynchronous worker thread
                self._fctconn_pending.append(key)
            else:
                # Real mode, endpoint not configured -> cannot connect
                self._fctconn_failed.append(key)
        self._fctconn_deadline = time.monotonic() + self.fct_connect_timeout
        self._poll_fct_connect()

    def _poll_fct_connect(self):
        """Poll the connecting channels every 300 ms until all of them
        are up, their connect attempt has ended without a connection
        (worker thread finished) or the timeout elapses (Stop pressed
        -> just leave)."""
        if self.run_state != "running":
            return
        mc = self.multi_console
        still = []
        for key in self._fctconn_pending:
            if mc.channel_connected(key):
                continue  # endpoint open
            worker = mc.channels[key]["worker"]
            if (worker is None
                    or (hasattr(worker, "_running")
                        and not worker.isRunning())):
                # connect attempt ended without a connection
                self._fctconn_failed.append(key)
            else:
                still.append(key)  # worker alive, still connecting
        self._fctconn_pending = still
        if (self._fctconn_pending
                and time.monotonic() < self._fctconn_deadline):
            QTimer.singleShot(300, self._poll_fct_connect)
            return
        self._fctconn_failed.extend(self._fctconn_pending)
        self._fctconn_pending = []
        self._finish_fct_connect()

    def _finish_fct_connect(self):
        """Connect phase over: resume the run, or abort it with an error
        popup when any channel could not be connected."""
        if self._fctconn_failed:
            labels = ", ".join(
                self.multi_console.channels[k]["label"]
                for k in self._fctconn_failed)
            self._abort_run(
                f"Stop: console channel(s) {labels} could not be "
                f"connected before FCT. Overall Result: FAIL")
            # _abort_run blanked the remaining steps -> mark the first
            # FCT row as Error afterwards, then re-judge the result
            if self.fct.rowCount() > 0:
                self._set_status(self.fct, 0, 4, "Error")
            self._update_result()
            QMessageBox.warning(
                self, "Console Connect Failed",
                f"Could not connect console channel(s): {labels}\n\n"
                "The test run was stopped. Check the console parameters "
                "and connections, then run again.")
            return
        self._log("Console channel(s) connected.")
        self._run_index += 1
        self._wait_done = False
        # polling stopped the run timer -> resume stepping from the
        # next step (the timer drives the per-step wait handling)
        self._run_timer.start()

    def _abort_run(self, reason):
        """Stop-policy abort: a FAIL/short triggered an Overall Flow
        policy. Remaining items are blanked and the product is counted
        FAIL — unlike the operator Stop button, which yields IGNORE."""
        self._run_timer.stop()
        self._lr_wait_timer.stop()
        self._clear_highlight()
        self.run_state = "idle"
        self._interrupted = False
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.product_group.setEnabled(True)
        for step in self._run_steps[self._run_index:]:
            kind = step[0]
            if kind == "ict":
                r = step[1]
                self.ict.item(r, 4).setText("")
                self.ict.item(r, 7).setText("")
            elif kind == "fct":
                self._set_status(self.fct, step[1], 4, "")
            elif kind == "stage":
                self._set_status(self.overall, step[1], 2, "")
                self.overall.item(step[1], 3).setText("")
        self._log(reason)
        self.cycle_times.append(time.monotonic() - self._run_start)
        self._count_product()
        self._update_result()
        self.run_finished.emit()

    def _resume_step(self):
        """Per-step wait elapsed -> continue the sequence."""
        if self.run_state != "running":
            return  # stopped during the wait
        self._run_step()
        self._run_timer.start()

    def _finish_run(self):
        """One cycle completed without interruption -> judge result;
        Long Run may start the next cycle after the pause."""
        self._run_timer.stop()
        self.run_progress.emit(len(self._run_steps), len(self._run_steps))
        self.cycle_times.append(time.monotonic() - self._run_start)
        self._count_product()
        self._update_result()
        self._lr_done += 1
        if self._lr_done < self._lr_total:
            wait = self.interval_spin.value()
            self._log(f"Long Run cycle {self._lr_done}/{self._lr_total} "
                      f"finished; next cycle in {wait} s")
            self._lr_wait_timer.start(wait * 1000)
            return  # still "running": Run disabled, Stop enabled
        # all cycles done
        self.run_state = "idle"
        self._clear_highlight()
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.product_group.setEnabled(True)
        self._update_result()
        if self._judge_verdict() == "FAIL":
            self._log("Run finished with failures (stop policy off) "
                      "-> Overall Result: FAIL")
        else:
            self._log("Overall flow: ICT -> FCT all PASS")
        if self._lr_total > 1:
            self._log(f"Long Run complete: {self._lr_total} cycles.")
        self.run_finished.emit()

    def stop_run(self):
        """Stop button: interrupt the run. Remaining test items are left
        blank and the Overall Result is IGNORE."""
        if self.run_state != "running":
            return
        self._run_timer.stop()
        self._lr_wait_timer.stop()
        self.run_progress.emit(0, 0)
        self._clear_highlight()
        self.run_state = "idle"
        self._interrupted = True
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.product_group.setEnabled(True)
        # remaining (not yet executed) test items -> blank
        for step in self._run_steps[self._run_index:]:
            kind = step[0]
            if kind == "ict":
                r = step[1]
                self.ict.item(r, 4).setText("")
                self.ict.item(r, 7).setText("")
            elif kind == "fct":
                self._set_status(self.fct, step[1], 4, "")
            elif kind == "stage":
                self._set_status(self.overall, step[1], 2, "")
                self.overall.item(step[1], 3).setText("")
        self._log("Run interrupted by operator -> Overall Result: IGNORE")
        self._update_result()

    def clear_results(self):
        self._interrupted = False
        self._fill_ict(placeholder=True)
        for r in range(self.fct.rowCount()):
            self._set_status(self.fct, r, 3, "--")
            self._set_status(self.fct, r, 4, "Pending")
        for r in range(self.overall.rowCount()):
            self._set_status(self.overall, r, 2, "Pending")
            self.overall.item(r, 3).setText("--")
        self.log_cleared.emit()
        self._update_result()


class _SequenceEditorDialog(QDialog):
    """Dialog for reordering, adding, removing, editing, and duplicating
    test case steps. Works on copies; only writes back on accept."""

    def __init__(self, kind, steps, enables, waits, timeouts, parent=None):
        super().__init__(parent)
        self._kind = kind  # "ict" or "fct"
        self._steps = list(steps)
        self._enables = list(enables)
        self._waits = list(waits)
        self._timeouts = list(timeouts)
        self._build_ui()
        self._populate()

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

        self.resize(520, 460)

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
            tag = "[op]" if kind == "op" else "[test]"
            return f"{i+1:3d}. {tag} {name}"
        else:
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
        for lst in (self._steps, self._enables,
                    self._waits, self._timeouts):
            lst[i], lst[j] = lst[j], lst[i]

    def _on_add(self):
        """Add a new blank step after the current row and open edit."""
        if self._kind == "ict":
            new_step = ("test", "New Test", "—", "—", "—", "—")
        else:
            new_step = "New Test"
        r = self.list_widget.currentRow()
        if r < 0:
            r = len(self._steps)
        self._steps.insert(r + 1, new_step)
        self._enables.insert(r + 1, True)
        self._waits.insert(r + 1, 100)
        self._timeouts.insert(r + 1, 5000)
        self._populate()
        self.list_widget.setCurrentRow(r + 1)
        self._on_edit()

    def _on_remove(self):
        r = self.list_widget.currentRow()
        if r < 0 or len(self._steps) <= 1:
            return
        del self._steps[r]
        del self._enables[r]
        del self._waits[r]
        del self._timeouts[r]
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
        self._steps.insert(r + 1, self._steps[r])
        self._enables.insert(r + 1, self._enables[r])
        self._waits.insert(r + 1, self._waits[r])
        self._timeouts.insert(r + 1, self._timeouts[r])
        self._populate()
        self.list_widget.setCurrentRow(r + 1)

    def _on_item_changed(self, item):
        """Sync checkbox state to the enables list."""
        r = self.list_widget.row(item)
        if 0 <= r < len(self._enables):
            self._enables[r] = item.checkState() == Qt.CheckState.Checked

    # ------------------------------------------------------- edit dialogs
    def _edit_ict_step(self, r):
        kind, name, unit, measured, lo, hi = self._steps[r]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Step {r + 1} — Edit")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(name)
        kind_combo = QComboBox()
        kind_combo.addItems(["op", "test"])
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

    def _edit_fct_step(self, r):
        name = self._steps[r]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Step {r + 1} — Edit")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(name)
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
        self._enables[r] = enable_cb.isChecked()
        self._waits[r] = wait_spin.value()
        self._timeouts[r] = timeout_spin.value()
        return True

    # ------------------------------------------------------- helpers
    def select_row(self, row):
        if 0 <= row < len(self._steps):
            self.list_widget.setCurrentRow(row)

    def result_data(self):
        """Return (steps, enables, waits, timeouts) after accept."""
        for i in range(len(self._enables)):
            item = self.list_widget.item(i)
            if item:
                self._enables[i] = (
                    item.checkState() == Qt.CheckState.Checked)
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
