# -*- coding: utf-8 -*-
"""Test Work Flow page.

The overall flow is a table:

    ICT -> FCT

* ICT test cases run as one top -> bottom sequence. Standard operations
  (Init Instruments, Fixture Clamp Down / Lock / E-Stop Healthy, Power On
  DUT, Power Off DUT, Fixture Unlock / Release, Reset Instruments) report
  Done/Error; in between them the measurement tests report PASS/FAIL:
    - R-GND shorts: 80 points, 2-wire Ω via DAQ973A, R_min threshold
    - power voltage: 80 points, ±0.1 % via DAQ973A
    - clocks: CLK1 32.768 kHz (907A totalizer), CLK2 4 MHz / CLK3 6 MHz
      (U2355A counters)
    - ADC stimulus: 2 x AO ±12 V -> TP_ADC0/1
    - fixture DIO (16 ch open-drain, 4 signals used)
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
    QAction,
    QKeySequence,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QApplication,
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
    QInputDialog,
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
    rail_plot_data,
    steps_template,
    write_csv,
)
from .engine.rails import DURATION_S
from .gui.steps_editor import StepsEditorDialog as _SequenceEditorDialog
from .gui.dialog_sizing import fit_dialog
from .gui.test_case_viewer import TestCaseViewer
from .qt_guard import qt_safe
from .startup_timing import mark as _startup_mark
from .startup_timing import begin, end
from .style import gui_theme_color, saved_theme, text_for_card
from .virtual_hardware import VirtualRack
from .widgets.console_widget import ERROR_COLOR
from .widgets.multi_console import MultiConsoleWidget

_ICON_DIR = Path(__file__).resolve().parent / "assets"

# power rails are fully YAML-defined (see TestWorkFlowPage.set_rails):
# the project file carries name / nominal_v / ramp_offset_s / color and
# the rail set is empty until a project is loaded

# ICT test cases: the sequence executes strictly top -> bottom. Standard
# operations (fixture / instrument control) report Done/Error; measurement
# tests report PASS/FAIL.
# R-GND shorts MUST run before the DUT is powered on: a short under
# power risks damaging the board, so "Stop if any short" aborts the run
# right here, before "Power On DUT".
# (kind, name, unit, measured, min / threshold, max[, op_params])
# standard op step tuples come from mtkgui.engine.steps (op_step).

ICT_STEPS = [
    _op_step("Init Instruments"),
    _op_step("Fixture Clamp Down"),
    _op_step("Fixture Lock"),
    _op_step("Fixture E-Stop Healthy"),
    ("test", "R-GND Shorts (80 pts)", "Ω", "80/80",
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
    _op_step("Power Off DUT"),
    _op_step("Fixture Unlock"),
    _op_step("Fixture Release"),
    _op_step("Reset Instruments"),
]


# --------------------------------------------------------------------------
# waveform widget (QPainter - no extra dependencies)
# --------------------------------------------------------------------------
#: plot margins (px) - shared by the widget painter and the cursor
#: mapping (WaveformWidget class constants mirror these)
WAVE_MARGIN_L, WAVE_MARGIN_R, WAVE_MARGIN_T, WAVE_MARGIN_B = 64, 24, 34, 30


def paint_waveform_plot(painter, width: float, height: float, data,
                        duration: float, t_start: float,
                        virtual: bool = False) -> None:
    """Render the power-rails plot (background / grid / legend /
    curves / virtual badge) into ANY painter.  Widget-free on purpose:
    the DUT report's PDF worker thread uses it to render the chart
    image off the GUI thread, the live widget uses the very same code
    so the report chart always matches the on-screen waveform."""
    from PySide6.QtCore import QRectF, QPointF, Qt
    from PySide6.QtGui import QColor, QPen, QFont

    rect = QRectF(0, 0, width, height).adjusted(0, 0, -1, -1)
    painter.fillRect(rect, QColor("#0d1b26"))
    if not data:
        painter.setPen(QPen(QColor("#8fa6b8")))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                         "No capture yet - run the demo to record rails")
        return

    ml, mr, mt, mb = WAVE_MARGIN_L, WAVE_MARGIN_R, WAVE_MARGIN_T, \
        WAVE_MARGIN_B
    plot = QRectF(ml, mt,
                  max(1.0, width - ml - mr),
                  max(1.0, height - mt - mb)).adjusted(0, 0, -1, 0)

    # y axis: voltage, top = 110 % of the highest nominal rail
    v_top = max((y_max for _, _, y_max, _ in data), default=1.0) * 1.1

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
        painter.drawText(QRectF(0, y - 8, ml - 8, 16),
                         Qt.AlignmentFlag.AlignRight
                         | Qt.AlignmentFlag.AlignVCenter,
                         f"{v_top * (5 - i) / 5:.2f} V")

    n = max((len(s) for _, _, _, s in data), default=1)
    for i in range(6):
        x = plot.left() + plot.width() * i / 5
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        t = t_start + duration * i / 5
        painter.drawText(QRectF(x - 30, plot.bottom() + 6, 60, 16),
                         Qt.AlignmentFlag.AlignHCenter
                         | Qt.AlignmentFlag.AlignTop,
                         f"{t:.1f} s")

    # legend (two rows, 6 entries each)
    col_w = min(195, plot.width() / 6)
    for i, (label, color, y_max, samples) in enumerate(data):
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
    for label, color, y_max, samples in data:
        painter.setPen(QPen(QColor(color), 2))
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
    if virtual:
        f.setPointSize(8)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QPen(QColor("#f5b83d"), 2))
        painter.drawText(QRectF(plot.right() - 130, plot.top() + 2,
                                126, 16),
                         Qt.AlignmentFlag.AlignRight
                         | Qt.AlignmentFlag.AlignVCenter,
                         "VIRTUAL DATA (simulated)")


class WaveformWidget(QWidget):
    # emitted on double-click; the page connects to show an edit dialog
    doubleClicked = Signal()
    #: cursor readout line for the zoom page toolbar (hover t/V, A/B Δ)
    cursorInfo = Signal(str)

    #: plot margins (px) - shared by the painter and the cursor mapping
    MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = (
        WAVE_MARGIN_L, WAVE_MARGIN_R, WAVE_MARGIN_T, WAVE_MARGIN_B)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = []  # list of (label, color, y_max, samples)
        self.duration = DURATION_S
        self.t_start = 0.0  # capture start time (can be negative)
        self.virtual = False  # Virtual mode: simulated (demo) data badge
        self._cache = None    # rendered-plot pixmap (invalidated on change)
        self.setMinimumHeight(190)
        # cursor machinery (user direction 2026-10-16): OFF for the
        # embedded preview (a pure live view); the ZOOM page turns it
        # on - hover crosshair with a t / per-rail V readout box and
        # click-pinned A/B measurement cursors with a Δt / ΔV readout
        self.cursor_enabled = False
        self._hover = None          # (x, y) widget coords or None
        self._pins: list[float] = []  # pinned cursor times (max 2)
        self._cursor_text = ""
        self.setMouseTracking(True)

    # --------------------------------------------------- cursor mapping
    def _v_top(self) -> float:
        """Y axis top = 110 % of the highest nominal rail (the same
        normalization the painter uses)."""
        return max((y_max for _, _, y_max, _ in self.data), default=1.0) * 1.1

    def plot_rect(self) -> QRectF:
        """The plot area inside the widget (margins excluded)."""
        return QRectF(self.MARGIN_L, self.MARGIN_T,
                      max(1.0, self.width() - self.MARGIN_L - self.MARGIN_R),
                      max(1.0, self.height() - self.MARGIN_T - self.MARGIN_B))

    def x_to_time(self, x: float) -> float:
        """Widget x -> capture time (clamped to the plot area)."""
        rect = self.plot_rect()
        frac = (min(max(x, rect.left()), rect.right()) - rect.left()) \
            / rect.width()
        return self.t_start + self.duration * frac

    def time_to_x(self, t: float) -> float:
        """Capture time -> widget x (unclamped, callers clamp)."""
        rect = self.plot_rect()
        frac = ((t - self.t_start) / self.duration
                if self.duration else 0.0)
        return rect.left() + rect.width() * frac

    def rail_v_at(self, entry, t: float) -> float:
        """One rail's interpolated voltage at capture time t (the
        samples are fractions of the nominal; linear between points)."""
        _label, _color, y_max, samples = entry
        if not samples:
            return 0.0
        frac = (t - self.t_start) / self.duration if self.duration else 0.0
        pos = min(max(frac, 0.0), 1.0) * (len(samples) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(samples) - 1)
        k = pos - lo
        return (samples[lo] + (samples[hi] - samples[lo]) * k) * y_max

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
        if self.cursor_enabled:
            # cursor overlay on TOP of the cached plot: the hover
            # crosshair / pinned cursors repaint ONLY this cheap pass
            # (the base plot stays the cached pixmap - zero re-render)
            self._paint_cursors(painter)

    def _paint_plot(self, painter):
        """The cached base plot - delegates to the widget-free
        :func:`paint_waveform_plot` (shared with the report's
        off-thread chart renderer)."""
        paint_waveform_plot(painter, self.width(), self.height(),
                            self.data, self.duration, self.t_start,
                            self.virtual)

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()

    # ------------------------------------------------ cursor interaction
    def mouseMoveEvent(self, event):
        if not self.cursor_enabled:
            return
        pos = event.position()
        self._hover = (pos.x(), pos.y())
        self._emit_cursor_info()
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        """Click pins the measurement cursors: 1st click = A, 2nd = B
        (the toolbar readout shows dt / dV), a 3rd click clears both
        and starts a new A.  Only inside the plot area."""
        if not self.cursor_enabled:
            return
        rect = self.plot_rect()
        x = event.position().x()
        if not (rect.left() <= x <= rect.right()):
            return
        if len(self._pins) >= 2:
            self._pins = []
        self._pins.append(self.x_to_time(x))
        self._emit_cursor_info()
        self.update()

    def _cursor_readout(self) -> str:
        """The toolbar readout line: pinned-cursor dt / per-rail dV,
        else the hover position time."""
        if len(self._pins) == 2:
            dt = self._pins[1] - self._pins[0]
            parts = [f"dt = {dt:+.3f} s"]
            for entry in self.data:
                dv = (self.rail_v_at(entry, self._pins[1])
                      - self.rail_v_at(entry, self._pins[0]))
                parts.append(f"{entry[0]} dV = {dv:+.3f} V")
            return "   |   ".join(parts)
        if self._hover is not None:
            return f"cursor t = {self.x_to_time(self._hover[0]):.3f} s"
        return ""

    def _emit_cursor_info(self) -> None:
        text = self._cursor_readout()
        if text != self._cursor_text:
            self._cursor_text = text
            self.cursorInfo.emit(text)

    def _paint_cursors(self, painter):
        """Overlay painter (AFTER the cached plot blit): hover
        crosshair + readout box, pinned A/B cursors + dt / dV box."""
        if not self.data:
            return
        rect = self.rect().adjusted(0, 0, -1, -1)
        plot = self.plot_rect().adjusted(0, 0, -1, 0)
        f = QFont()
        f.setPointSize(8)
        painter.setFont(f)

        def _vline(t, color, label):
            x = self.time_to_x(t)
            if not (plot.left() - 1 <= x <= plot.right() + 1):
                return
            painter.setPen(QPen(QColor(color), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x, plot.top()),
                             QPointF(x, plot.bottom()))
            painter.setPen(QPen(QColor(color), 2))
            painter.drawText(QRectF(x - 40, plot.top() + 2, 80, 14),
                             Qt.AlignmentFlag.AlignHCenter
                             | Qt.AlignmentFlag.AlignTop, label)

        # pinned cursors: A amber, B violet, dt / dV box on the right
        colors = ("#f5b83d", "#c084fc")
        names = ("A", "B")
        for i, t in enumerate(self._pins[:2]):
            _vline(t, colors[i], f"{names[i]} {t:.3f} s")
        if len(self._pins) == 2:
            lines = [f"dt = {self._pins[1] - self._pins[0]:+.3f} s"]
            for entry in self.data:
                dv = (self.rail_v_at(entry, self._pins[1])
                      - self.rail_v_at(entry, self._pins[0]))
                lines.append(f"{entry[0]} dV = {dv:+.3f} V")
            box_w = max(150, 12 + max(len(x) for x in lines) * 6)
            box = QRectF(plot.right() - box_w, plot.top() + 18,
                         box_w, 6 + 13 * len(lines))
            painter.setPen(QPen(QColor("#24435a"), 1))
            painter.fillRect(box, QColor(13, 27, 38, 230))
            painter.drawRect(box)
            painter.setPen(QPen(QColor("#dbe7f0"), 1))
            for i, line in enumerate(lines):
                painter.drawText(QRectF(box.left() + 6,
                                        box.top() + 2 + 13 * i,
                                        box_w - 8, 14),
                                 Qt.AlignmentFlag.AlignLeft, line)

        # hover crosshair + t / V readout box at the cursor
        if self._hover is not None:
            hx, hy = self._hover
            if plot.left() <= hx <= plot.right():
                t = self.x_to_time(hx)
                painter.setPen(QPen(QColor("#4ec9b0"), 1,
                                    Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(hx, plot.top()),
                                 QPointF(hx, plot.bottom()))
                painter.drawLine(QPointF(plot.left(), hy),
                                 QPointF(plot.right(), hy))
                lines = [f"t = {t:.3f} s"]
                for entry in self.data:
                    lines.append(f"{entry[0]} = "
                                 f"{self.rail_v_at(entry, t):.3f} V")
                box_w = max(140, 12 + max(len(x) for x in lines) * 6)
                box_h = 6 + 13 * len(lines)
                # keep the box inside the plot (flip when near the edge)
                bx = hx + 12 if hx + 12 + box_w < plot.right() \
                    else hx - 12 - box_w
                by = min(max(hy - box_h / 2, plot.top() + 2),
                         plot.bottom() - box_h - 2)
                box = QRectF(bx, by, box_w, box_h)
                painter.setPen(QPen(QColor("#24435a"), 1))
                painter.fillRect(box, QColor(13, 27, 38, 230))
                painter.drawRect(box)
                painter.setPen(QPen(QColor("#dbe7f0"), 1))
                for i, line in enumerate(lines):
                    painter.drawText(QRectF(box.left() + 6,
                                            box.top() + 2 + 13 * i,
                                            box_w - 8, 14),
                                     Qt.AlignmentFlag.AlignLeft, line)


class _ZoomWaveformPage(QWidget):
    """Enlarged, zoomable copy of the Power Rails capture (user
    direction 2026-10-16): the properties dialog gains a page showing
    the waveform BIG - the mouse wheel zooms (50% - 300%), the
    scrollbars pan, and the larger plot area also draws MORE curve
    samples (the sampling step follows the plot width), so zooming in
    reveals real detail instead of stretched pixels.  The small
    embedded plot stays the live preview; this page CLONES its data at
    open time (repaints use the widget's own pixmap cache, so a 3x
    zoom costs one render, no per-frame cost)."""

    BASE_W, BASE_H = 1300, 650
    MIN_SCALE, MAX_SCALE = 0.5, 3.0

    def __init__(self, source: "WaveformWidget", parent=None):
        super().__init__(parent)
        self.scale = 1.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        zout = QPushButton("Zoom Out (-)")
        self.lbl = QLabel("Zoom: 100%")
        self.lbl.setObjectName("muted")
        zin = QPushButton("Zoom In (+)")
        fit = QPushButton("Fit 100%")
        zout.clicked.connect(lambda: self._zoom_step(0.8))
        zin.clicked.connect(lambda: self._zoom_step(1.25))
        fit.clicked.connect(lambda: self._set_scale(1.0))
        hint = QLabel("wheel = zoom, click = cursor A / B, scrollbars = pan")
        hint.setObjectName("muted")
        bar.addWidget(zout)
        bar.addWidget(self.lbl)
        bar.addWidget(zin)
        bar.addWidget(fit)
        bar.addStretch(1)
        bar.addWidget(hint)
        lay.addLayout(bar)
        self.wave = WaveformWidget()
        self.wave.set_data(source.data, source.duration, source.t_start)
        self.wave.set_virtual(source.virtual)
        self.wave.cursor_enabled = True   # hover crosshair + A/B cursors
        # the toolbar readout line: hover t / the pinned dt + dV values
        self.cursor_lbl = QLabel("")
        self.cursor_lbl.setObjectName("muted")
        self.wave.cursorInfo.connect(self.cursor_lbl.setText)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.wave)   # fixed-size widget -> scrollbars
        self.scroll.viewport().installEventFilter(self)
        lay.addWidget(self.scroll, 1)
        lay.addWidget(self.cursor_lbl)
        self._apply()

    # ------------------------------------------------------------- zoom
    def eventFilter(self, obj, event) -> bool:
        """Mouse wheel over the plot zooms (the scrollbars pan via
        drag / arrow keys)."""
        if event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            if delta:
                self._zoom_step(1.15 if delta > 0 else 1 / 1.15)
                return True
        return super().eventFilter(obj, event)

    def _zoom_step(self, factor: float) -> None:
        self._set_scale(max(self.MIN_SCALE,
                            min(self.MAX_SCALE, self.scale * factor)))

    def _set_scale(self, s: float) -> None:
        self.scale = s
        self._apply()

    def _apply(self) -> None:
        self.wave.setFixedSize(int(self.BASE_W * self.scale),
                               int(self.BASE_H * self.scale))
        self.lbl.setText(f"Zoom: {self.scale * 100:.0f}%")


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------
class TestWorkFlowPage(QWidget):
    # emitted when a whole test cycle completes -> main window jumps here
    run_finished = Signal()
    # the power-rails capture config changed (properties OK) -> the
    # main window syncs it into the Yaml Build model (YAML preview)
    rail_config_changed = Signal()
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
    # double-click on an ICT / FCT result row asks the main window to open
    # the matching "Build ... Test Work Flow Sequence" dialog - the SINGLE
    # sequence edit source (this page's table is a read-only result view)
    ict_build_requested = Signal()
    fct_build_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        _startup_mark("twf: init start")
        self.rail_samples = None
        self.rail_volts = None
        self.rail_csv_path = None
        self._rail_plot_cache = []
        self._ai_review_text = None
        # B4 §1.3: configurable FCT keyword tables (negative-wins);
        # persisted in the project YAML as test_workflow.fct_keywords
        from mtkgui.gui.yamlbuild.fct_build import (
            DEFAULT_KEYWORD_FAIL, DEFAULT_KEYWORD_PASS)
        self.fct_keyword_pass = list(DEFAULT_KEYWORD_PASS)
        self.fct_keyword_fail = list(DEFAULT_KEYWORD_FAIL)
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
        # net catalog provider (set by the main window): returns the
        # testable_nets dict of the Yaml Build model - the step edit
        # dialog offers the nets PER TEST METHOD from it
        self.net_catalog_provider = None
        # DAQ AI rail-count provider (set by the main window): returns
        # the number of power rails assigned to DAQ AI channels in the
        # Channel Allocation tables (the DAQ AI Net cell is read-only)
        self.daq_ai_rail_count_provider = None
        # M7: allocated control-IO rows (net / DIO channel / isolation
        # verdict) set by the main window - the U2355A DIO Read/Write
        # ops consume it (DIO Write runs the isolation preflight)
        self.control_io_provider = None
        self._runner = TestRunner(self)
        self._runner.cycle_reset.connect(self._on_cycle_reset)
        self._runner.stage_skipped.connect(self._on_stage_skipped)
        self._runner.run_finished.connect(self._on_run_finished)
        # P3-B2 debug bridge (GUI layer): breakpoint hits and the
        # single-step mode request a pause at the safe step boundary
        # via the runner's public pause() API
        self._runner.step_started.connect(self._on_debug_step_started)
        self._runner.step_finished.connect(self._on_debug_step_finished)
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
        # per-node comments (P3-B2 debug feature): edited via the table
        # context menu, archived to the project YAML when non-empty
        self.ict_comments: list[str] = []
        self.fct_comments: list[str] = []
        # debug breakpoints (P3-B2, GUI layer only): row indices that
        # pause the run after the node completes; plus the single-step
        # mode flag. Both drive the runner via its public pause() /
        # resume() API at safe step boundaries.
        self.ict_breakpoints: set[int] = set()
        self.fct_breakpoints: set[int] = set()
        self._step_mode = False
        # item 15 (VS style): Run Without Debug ignores breakpoints for
        # one run; Run to Cursor places a temporary breakpoint that is
        # removed when hit; Restart re-arms a fresh run after the abort
        self._no_debug = False
        self._temp_bp = None
        self._restart_pending = False
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
        # M12: detachable Test Case Viewer (created on first open)
        self._case_viewer = None
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
        _startup_mark("twf: header groups built")

        root = QVBoxLayout(self)

        header_row = QHBoxLayout()
        title = QLabel("Test Work Flow")
        title.setObjectName("strong")
        title.setStyleSheet("font-size: 16px;")
        header_row.addWidget(title)
        header_row.addStretch(1)
        # M19f: a CHECKBOX on the right of the page title (default ON):
        # each Run auto-opens the merged ICT/FCT case viewer and closes
        # it when the Run finishes; unchecking disables the auto-open
        self.chk_case_viewer = QCheckBox("Test Case Viewer")
        self.chk_case_viewer.setChecked(True)
        self.chk_case_viewer.setToolTip(
            "Auto-open the ICT/FCT case viewer at each Run start and "
            "close it when the Run finishes")
        header_row.addWidget(self.chk_case_viewer)
        root.addLayout(header_row)

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
        QTimer.singleShot(
            0, self, qt_safe(lambda: mid.setSizes([500, 500])))
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
        _startup_mark("twf: fct + console built")
        fct_split.setStretchFactor(0, 1)   # FCT 50%
        fct_split.setStretchFactor(1, 1)   # Console 50%
        fct_split.setSizes([500, 500])     # initial 1:1 ratio
        # first show re-splits by sizeHint -> enforce 1:1 afterwards
        QTimer.singleShot(
            0, self, qt_safe(lambda: fct_split.setSizes([500, 500])))
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
        _startup_mark("twf: page layout done")

    def open_test_case_viewer(self):
        """M12: open the detachable viewer (one merged ICT + FCT table)."""
        if self._case_viewer is None:
            self._case_viewer = TestCaseViewer(self, self.window())
        self._case_viewer.show()
        self._case_viewer.raise_()
        self._case_viewer.activateWindow()

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
        # Item 15: part / core / batch are 100% YAML-driven - read-only
        # for every role (the YAML file is the only editing entrance).
        for edit in (self.part_edit, self.core_edit, self.batch_edit):
            edit.setReadOnly(True)
        # run-policy checkboxes (M0 permission matrix): Supervisor has
        # native rw; Operator is read-only unless the supervisor
        # granted the specific run_policy_* key.  Every panel load
        # re-evaluates (dynamic enable/disable).
        self.stop_if_fail_cb.setEnabled(
            supervisor or bool(perm.get("run_policy_stop_failure")))
        self.stop_if_short_cb.setEnabled(
            supervisor or bool(perm.get("run_policy_stop_short")))
        self.auto_sn.setEnabled(
            supervisor or bool(perm.get("run_policy_auto_sn")))
        self.act_auto_sn.setEnabled(
            supervisor or bool(perm.get("run_policy_auto_sn")))
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

        Item 15 (Main UI Product Info Read-Only Rule): part / core /
        batch are 100% YAML-driven - the only valid editing entrance
        is the project YAML file, so they are read-only on the GUI
        layer, start empty (no default placeholder text, no residual
        cached data) and only refresh on a YAML load / switch.
        Serial Number stays the single per-unit manual input field.
        """
        group = QGroupBox("Product Information")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.part_edit = QLineEdit()
        self.part_edit.setReadOnly(True)
        self.part_edit.textChanged.connect(self._force_upper)
        form.addRow("Product Part#:", self.part_edit)

        self.core_edit = QLineEdit()
        # 4..10 digits: the parser's Core ID domain (the historical
        # 6-digit limit silently truncated longer project numbers)
        self.core_edit.setMaxLength(10)
        self.core_edit.setReadOnly(True)
        self.core_edit.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"\d{0,10}"), self))
        form.addRow("Core ID:", self.core_edit)

        self.batch_edit = QLineEdit()
        self.batch_edit.setReadOnly(True)
        form.addRow("Batch#:", self.batch_edit)

        self.serial_edit = QLineEdit()
        self.serial_edit.setPlaceholderText(
            "2 letters + digits, e.g. FS1234567890")
        self.serial_edit.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"[A-Z]{0,2}\d*"), self))
        self.serial_edit.textChanged.connect(self._force_upper)
        form.addRow("Serial Number:", self.serial_edit)

        # item 15: Auto-SN is a configuration entry -> it lives in the
        # Settings top-level menu (checkable action).  The checkbox
        # stays on the page as the hidden state holder (the YAML save /
        # restore + permission logic keep using it).
        self.auto_sn = QCheckBox("Auto-SN (virtual serial, +1 per run)")
        self.auto_sn.hide()
        self.act_auto_sn = QAction("Auto-SN (virtual serial, +1 per run)",
                                   self)
        self.act_auto_sn.setCheckable(True)
        self.act_auto_sn.setStatusTip(
            "Fully virtual product information: all four fields may be "
            "left empty, defaults are filled automatically on Run")
        self.act_auto_sn.toggled.connect(self._on_auto_sn_toggled)
        self.act_auto_sn.toggled.connect(self.auto_sn.setChecked)
        self.auto_sn.toggled.connect(self.act_auto_sn.setChecked)
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
        """Run / Stop + Long Run configuration (item 17 rollback).

        The two core buttons Run / Stop returned to the Run Control
        panel as the most prominent primary buttons of the whole GUI
        (accent colours + enlarged layout = ultra-high visual priority
        core operation entrance).  The shared QAction objects stay the
        state source of truth and carry the VS shortcuts - the button
        widgets mirror their enabled state, so menu / shortcuts / page
        buttons always agree.  Step / Continue remain in the Run menu.

        Idle: Run enabled, Stop disabled. Running: Run disabled,
        Stop enabled. Long Run repeats the whole cycle (1..999 times)
        with a configurable pause between cycles (0.5..99 s, 0.5 s
        step), skipping product information input."""
        group = QGroupBox("Run Control")
        group.setMinimumWidth(190)  # keep visible, never collapse
        layout = QVBoxLayout(group)
        # green play / red stop icons (SVG keeps a gap before the label)
        self.btn_run = QAction(QIcon(str(_ICON_DIR / "run.svg")),
                               "Start / Continue Run", self)
        self.btn_run.setShortcut(QKeySequence("F5"))
        self.btn_run.setToolTip("Start the run, or continue from the "
                                "paused breakpoint (F5)")
        self.btn_run.triggered.connect(self.run_or_continue)
        self.btn_stop = QAction(QIcon(str(_ICON_DIR / "stop.svg")),
                                "Stop Run", self)
        self.btn_stop.setShortcut(QKeySequence("Shift+F5"))
        self.btn_stop.setEnabled(False)
        self.btn_stop.triggered.connect(self.stop_run)

        # primary buttons (item 17): prominent colours + enlarged
        # layout - the core operation entrance of the whole GUI
        primary = (
            "QPushButton { color:#ffffff; font-weight:bold; "
            "font-size:15px; border-radius:4px; min-height:48px; }")
        self.btn_run_button = QPushButton(
            QIcon(str(_ICON_DIR / "run_white.svg")), "Run")
        self.btn_run_button.setToolTip(self.btn_run.toolTip())
        self.btn_run_button.setStyleSheet(primary + (
            "QPushButton { background:#1d7a3c; }"
            "QPushButton:hover { background:#239149; }"
            "QPushButton:disabled { background:#5a7a64; }"))
        self.btn_run_button.setMinimumWidth(150)
        # item 19: enlarge the play / stop symbols - clearly visible
        # inside the 48px primary buttons at standard window size
        self.btn_run_button.setIconSize(QSize(30, 30))
        self.btn_run_button.setDefault(True)
        self.btn_run_button.clicked.connect(self.btn_run.trigger)
        self.btn_run.enabledChanged.connect(
            self.btn_run_button.setEnabled)
        self.btn_stop_button = QPushButton(
            QIcon(str(_ICON_DIR / "stop_white.svg")), "Stop")
        self.btn_stop_button.setToolTip(self.btn_stop.toolTip())
        self.btn_stop_button.setStyleSheet(primary + (
            "QPushButton { background:#b3261e; }"
            "QPushButton:hover { background:#d32f27; }"
            "QPushButton:disabled { background:#7a5f5d; }"))
        self.btn_stop_button.setMinimumWidth(150)
        self.btn_stop_button.setIconSize(QSize(30, 30))
        self.btn_stop_button.clicked.connect(self.btn_stop.trigger)
        self.btn_stop.enabledChanged.connect(
            self.btn_stop_button.setEnabled)
        rs_row = QHBoxLayout()
        rs_row.setSpacing(8)
        rs_row.addWidget(self.btn_run_button)
        rs_row.addWidget(self.btn_stop_button)
        layout.addLayout(rs_row)
        # initial mirror (the actions were configured before the
        # button widgets existed - enabledChanged fired unheard)
        self.btn_run_button.setEnabled(self.btn_run.isEnabled())
        self.btn_stop_button.setEnabled(self.btn_stop.isEnabled())

        # ---- Run menu-only debug actions (VS standard shortcuts) ----
        self.act_run_without_debug = QAction("Run Without Debug", self)
        self.act_run_without_debug.setShortcut(QKeySequence("Ctrl+F5"))
        self.act_run_without_debug.setToolTip(
            "Run ignoring every breakpoint (Ctrl+F5)")
        self.act_run_without_debug.triggered.connect(
            lambda: self.start_run(no_debug=True))
        self.act_restart = QAction("Restart Run", self)
        self.act_restart.setShortcut(QKeySequence("Ctrl+Shift+F5"))
        self.act_restart.triggered.connect(self.restart_run)
        self.btn_step = QAction("Step Over (Single Node Run)", self)
        self.btn_step.setShortcut(QKeySequence("F10"))
        self.btn_step.setToolTip(
            "Execute the next workflow node, then pause again (F10)")
        self.btn_step.setEnabled(False)
        self.btn_step.triggered.connect(self.debug_step)
        self.act_step_into = QAction("Step Into", self)
        self.act_step_into.setShortcut(QKeySequence("F11"))
        self.act_step_into.setToolTip(
            "Single-step the next workflow node (F11) - the engine "
            "granularity is one workflow node")
        self.act_step_into.setEnabled(False)
        self.act_step_into.triggered.connect(self.debug_step)
        self.btn_continue = QAction("Step Out", self)
        self.btn_continue.setShortcut(QKeySequence("Shift+F11"))
        self.btn_continue.setToolTip(
            "Leave the single-step mode and resume (Shift+F11)")
        self.btn_continue.setEnabled(False)
        self.btn_continue.triggered.connect(self.debug_continue)
        self.act_toggle_breakpoint = QAction("Toggle Breakpoint", self)
        self.act_toggle_breakpoint.setShortcut(QKeySequence("F9"))
        self.act_toggle_breakpoint.triggered.connect(
            self.toggle_breakpoint_current)
        self.act_clear_breakpoints = QAction("Clear All Breakpoints", self)
        self.act_clear_breakpoints.setShortcut(
            QKeySequence("Ctrl+Shift+F9"))
        self.act_clear_breakpoints.triggered.connect(
            self.clear_all_breakpoints)
        self.act_run_to_cursor = QAction("Run to Cursor", self)
        self.act_run_to_cursor.setShortcut(QKeySequence("Ctrl+F10"))
        self.act_run_to_cursor.triggered.connect(self.run_to_cursor)

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

    def _ict_virtual_seen(self):
        """True when at least one ICT Result cell carries the Virtual
        prefix - the Overall verdict is only Virtual-prefixed when the
        (virtualised) instrument stage actually contributed a result;
        a pure-FCT run reports plain PASS / FAIL even in Virtual mode
        (FCT always runs against real hardware)."""
        for r in range(self.ict.rowCount()):
            item = self.ict.item(r, 7)
            if item is not None and item.text().startswith("Virtual"):
                return True
        return False

    def _update_result(self):
        """Refresh the big verdict + the per-product statistics."""
        if self.run_state == "running":
            verdict, key = "RUNNING", "run"
        else:
            judged = self._judge_verdict()
            if judged == "FAIL":
                # FAIL wins over Stop: a stopped run with FAIL items
                # reports FAIL, never IGNORE (user rule)
                verdict, key = "FAIL", "bad"
            elif self._interrupted:
                # IGNORE only for a stop with NO failed item
                verdict, key = "IGNORE", "warn"
            elif judged == "PASS":
                verdict, key = "PASS", "ok"
            else:
                verdict, key = "—", "neutral"
        if self.virtual_mode and verdict in ("PASS", "FAIL") \
                and self._ict_virtual_seen():
            # only the virtualised ICT stage earns the Virtual prefix
            # + the dedicated virtual verdict colours
            verdict = f"Virtual {verdict}"
            key = "virtual_ok" if verdict == "Virtual PASS" \
                else "virtual_bad"
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
        # factory default 2026-10-14: BOTH stop policies ON - every
        # loaded plan (the 8 demo plans included) runs with
        # stop_if_failure + stop_if_any_short enabled unless the
        # operator or a project YAML explicitly changes them
        self.stop_if_fail_cb.setChecked(True)
        self.stop_if_fail_cb.setToolTip(
            "Default ON. When checked, any test/operation that reports "
            "FAIL aborts the whole run immediately.")
        policy_row.addWidget(self.stop_if_fail_cb)
        self.stop_if_short_cb = QCheckBox("Stop if any short")
        self.stop_if_short_cb.setChecked(True)
        self.stop_if_short_cb.setToolTip(
            "Default ON. Applies to every R-GND Shorts test: if low "
            "resistance (short risk) is found, abort before powering the "
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
             "In-Circuit Test: 80 power nets R-GND -> voltage "
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
        # column layout (item 20): automatic width adaptation - every
        # column resizes to its content (headers and cells always
        # fully visible, e.g. "Duration (s)" no longer truncated to
        # "atior"); the last column stretches so the table stays
        # responsive when the main window resizes.  Header texts,
        # checkboxes and cell content are unchanged.
        header = self.overall.horizontalHeader()
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
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
        """When no YAML is loaded, clear ICT/FCT COMPLETELY (zero rows,
        user direction 2026-10-15: the former single empty placeholder
        row - an empty op / MessageOK entry - is gone), clear the Power
        Rails Up Sequence waveform and remove every Console channel."""
        self.ict_steps = []
        self.ict_enables = []
        self.ict_waits = []
        self.ict_timeouts = []
        self.ict_comments = []
        self.ict_breakpoints = set()
        self.ict.setRowCount(0)

        self.fct_rows = []
        self.fct_enables = []
        self.fct_waits = []
        self.fct_timeouts = []
        self.fct_kinds = []
        self.fct_op_params = []
        self.fct_comments = []
        self.fct_breakpoints = set()
        self.fct.setRowCount(0)

        # Power Rails Up Sequence: fully YAML-defined — no rails, no
        # checkboxes and nothing captured before a project is loaded
        self.set_rails([])

        # Console: no YAML -> no channels
        self.multi_console.clear_channels()

    def _build_ict(self):
        # read-only result view (task: single sequence source): the
        # sequence itself is edited in the "Build ICT Test Work Flow
        # Sequence" dialog (double-click here opens it)
        group = QGroupBox("ICT Test Results")
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
        if col == 2 and 0 <= row < len(self.ict_enables):  # Enable checkbox
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

        # col 0: # (centered, auto-sized); a ● prefix marks a debug
        # breakpoint (P3-B2)
        cell(0, f"● {r + 1}" if r in self.ict_breakpoints
             else str(r + 1))
        # col 1: Test / Operation (left aligned, blue bold for ops)
        name_item = cell(1, name, center=False)
        # node comment (P3-B2 debug feature) -> row tooltip
        comments = getattr(self, "ict_comments", None) or []
        name_item.setToolTip(comments[r] if r < len(comments) else "")
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
        # (R-GND Shorts has only a Min limit — Max stays blank)
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
            key = "virtual_ok" if self.virtual_mode else "ok"
            res_item.setForeground(QColor(gui_theme_color(key)))
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
        """Double-click the waveform -> the Power Rails properties
        dialog: an ENLARGED zoomable waveform page, capture & rail
        properties, and an AI review page grading the sample."""
        dlg, ui = self._build_rail_props_dialog()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # apply capture time / rate / csv changes
        self.cap_start = ui["start"].value()
        self.cap_end = ui["end"].value()
        self.cap_rate = ui["rate"].value()
        self.csv_export = ui["csv"].isChecked()
        self.rail_widget.t_start = self.cap_start
        # regenerate waveform with the new time range (healthy preview)
        self.rail_samples, self.rail_volts =             self._generate_rail_samples(inject_faults=False)
        self._rail_plot_cache = self._rail_plot_data(self.rail_samples)
        self._apply_rail_filter()
        # the rail config feeds the Yaml Build model (user question:
        # configured power rails MUST land in the YAML)
        self.rail_config_changed.emit()

    def _build_rail_props_dialog(self):
        """Build the "Power Rails — Properties" dialog (three pages:
        the zoomable Waveform / Properties / AI Review).  Staged out of
        _edit_rail_props so tests can inspect the pages without the
        blocking exec()."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Power Rails — Properties")
        fit_dialog(dlg, 980, 760)
        outer = QVBoxLayout(dlg)
        tabs = QTabWidget()
        outer.addWidget(tabs)

        # page 1: the ENLARGED, zoomable waveform (user direction
        # 2026-10-16: wheel zoom + pan, more samples at bigger widths)
        tabs.addTab(_ZoomWaveformPage(self.rail_widget), "Waveform")

        # page 2: capture settings + rail reference table
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
        return dlg, {"start": start_spin, "end": end_spin,
                     "rate": rate_spin, "csv": csv_cb}

    def _build_fct(self):
        # read-only result view (task: single sequence source)
        group = QGroupBox("FCT Test Results")
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
        if col == 2 and 0 <= row < len(self.fct_enables):  # Enable checkbox
            self.fct_enables[row] = item.checkState() == Qt.CheckState.Checked

    # --------------------------------------------- debug (P3-B2, GUI only)
    def _debug_node_name(self, kind, row):
        """Display name of an ict/fct run-step for the log."""
        try:
            return (self.ict_steps[row][1] if kind == "ict"
                    else self.fct_rows[row])
        except (IndexError, TypeError):
            return f"{kind}#{row}"

    def _on_debug_step_started(self, index):
        """Runner signal: a step is about to execute. When the node is
        a breakpointed ict/fct row, request a pause after it completes
        (runner.pause() takes effect at the safe step boundary)."""
        steps = self._runner._run_steps
        if index >= len(steps):
            return
        kind, *args = steps[index]
        if kind not in ("ict", "fct"):
            return
        bps = self.ict_breakpoints if kind == "ict" \
            else self.fct_breakpoints
        if args[0] in bps:
            self._log(f"Breakpoint: {self._debug_node_name(kind, args[0])}"
                      " -> pause after this node")

    def _on_debug_step_finished(self, index, result):
        """Runner signal: the step finished. A breakpoint hit or the
        single-step mode parks the engine at the next boundary (the
        state machine itself is untouched; only the public pause() API
        is used)."""
        if not (self._step_mode or self._breakpoint_hit(index)):
            return
        try:
            self._runner.pause()
            # settle the state machine at the boundary tick (executes
            # nothing: the pause check runs before the step body)
            self._runner._run_step()
        except RuntimeError:
            return  # race with abort / finish: nothing to pause
        self._step_mode = False
        # Run to Cursor: the temporary breakpoint was hit - remove it
        if self._temp_bp is not None and self._breakpoint_hit(index):
            table, bps, row = self._temp_bp
            if row in bps:
                self._toggle_breakpoint(table, row, bps)
            self._temp_bp = None
            self._log("Run to Cursor: target reached, temporary "
                      "breakpoint removed")
        self._update_debug_buttons()

    def _breakpoint_hit(self, index):
        """True when the finished run-step is a breakpointed node.
        Run Without Debug (Ctrl+F5) ignores every breakpoint for the
        current run (GUI-layer flag only)."""
        if self._no_debug:
            return False
        steps = self._runner._run_steps
        if index >= len(steps):
            return False
        kind, *args = steps[index]
        if kind not in ("ict", "fct"):
            return False
        bps = self.ict_breakpoints if kind == "ict" \
            else self.fct_breakpoints
        return args[0] in bps

    def debug_step(self):
        """Step button: run exactly one more workflow node, then pause
        again (arms the single-step mode and resumes the engine)."""
        if self._runner.state == "paused":
            self._step_mode = True
            self._update_debug_buttons()
            self._runner.resume()
        elif self._runner.state == "running":
            # first Step press while running: pause after the current
            # node, then immediately single-step from the boundary
            try:
                self._runner.pause()
                self._runner._run_step()
            except RuntimeError:
                return
            self._update_debug_buttons()
            self.debug_step()          # state is 'paused' now

    def debug_continue(self):
        """Continue button: leave the single-step mode and resume."""
        self._step_mode = False
        if self._runner.state == "paused":
            self._update_debug_buttons()
            self._runner.resume()

    def run_or_continue(self):
        """F5 (VS Start / Continue): start when idle, continue when
        paused; no-op while already running."""
        if self._runner.state == "paused":
            self.debug_continue()
        else:
            self.start_run()

    def restart_run(self):
        """Ctrl+Shift+F5 (VS Restart): abort the current run, then
        start a fresh one as soon as the abort has settled (the page
        consumes _restart_pending in _on_run_finished)."""
        if self.run_state == "running" or self._runner.state == "paused":
            self._restart_pending = True
            self._log("Restart Run: aborting the current run ...")
            self.stop_run()
        else:
            self.start_run()

    def toggle_breakpoint_current(self):
        """F9 (VS Toggle Breakpoint): toggle the breakpoint of the
        current row of the focused ICT / FCT table."""
        target = self._current_bp_target()
        if target is None:
            self._log("Toggle Breakpoint: no ICT / FCT row selected")
            return
        table, bps, row = target
        self._toggle_breakpoint(table, row, bps)

    def clear_all_breakpoints(self):
        """Ctrl+Shift+F9: remove every ICT / FCT breakpoint."""
        removed = 0
        for table, bps in ((self.ict, self.ict_breakpoints),
                           (self.fct, self.fct_breakpoints)):
            for row in sorted(bps):
                self._toggle_breakpoint(table, row, bps)
                removed += 1
        self._temp_bp = None
        self._log(f"Clear All Breakpoints: {removed} breakpoint(s) "
                  "removed")

    def run_to_cursor(self):
        """Ctrl+F10 (VS Run to Cursor): place a temporary breakpoint on
        the current row, then start / continue; the temporary
        breakpoint is removed again as soon as it is hit."""
        target = self._current_bp_target()
        if target is None:
            self._log("Run to Cursor: no ICT / FCT row selected")
            return
        table, bps, row = target
        if row not in bps:
            self._toggle_breakpoint(table, row, bps)
        self._temp_bp = (table, bps, row)
        self._log(f"Run to Cursor: temporary breakpoint at row "
                  f"{row + 1}")
        self.run_or_continue()

    def _current_bp_target(self):
        """Current breakpoint target: the focused ICT / FCT table and
        its current row (ICT preferred when nothing has focus)."""
        focused = QApplication.focusWidget()
        for table, bps in ((self.ict, self.ict_breakpoints),
                           (self.fct, self.fct_breakpoints)):
            vp = table.viewport()
            if focused is table or focused is vp or (
                    isinstance(focused, QWidget)
                    and vp.isAncestorOf(focused)):
                if table.currentRow() >= 0:
                    return table, bps, table.currentRow()
        for table, bps in ((self.ict, self.ict_breakpoints),
                           (self.fct, self.fct_breakpoints)):
            if table.currentRow() >= 0:
                return table, bps, table.currentRow()
        return None

    def _update_debug_buttons(self):
        """Sync the debug QActions with the engine state (the Run menu
        and the toolbar render the same action objects)."""
        state = self._runner.state
        running = state in ("running", "paused")
        self.btn_step.setEnabled(running)
        self.act_step_into.setEnabled(running)
        self.btn_continue.setEnabled(state == "paused")
        # F5 semantics: start when idle, continue while paused
        self.btn_run.setEnabled(state != "running")

    # -------------------------------------------------- failure simulation
    def _toggle_breakpoint(self, table, row, breakpoints):
        """Breakpoint toggle from the context menu: store the row index
        and mark the '#' cell (● prefix, red bold number, tooltip)."""
        on = row not in breakpoints
        (breakpoints.add if on else breakpoints.discard)(row)
        item = table.item(row, 0)
        if item is None:
            return
        if on:
            item.setForeground(QColor(ERROR_COLOR))
            item.setFont(_bold())
            item.setText(f"● {row + 1}")
            tip = item.toolTip()
            item.setToolTip("breakpoint\n" + tip if tip else "breakpoint")
        else:
            item.setForeground(QBrush())
            item.setFont(QFont())
            item.setText(str(row + 1))
            tip = item.toolTip()
            if tip.startswith("breakpoint\n"):
                item.setToolTip(tip[len("breakpoint\n"):])
            elif tip == "breakpoint":
                item.setToolTip("")

    def _ict_context_menu(self, pos):
        """Right-click an ICT row -> breakpoint / simulate FAIL / edit
        the node comment (P3-B2 debug feature)."""
        row = self.ict.rowAt(pos.y())
        if row < 0:
            return
        is_test = self.ict_steps[row][0] == "test"
        menu = QMenu(self)
        act_bp = menu.addAction("Breakpoint")
        act_bp.setCheckable(True)
        act_bp.setChecked(row in self.ict_breakpoints)
        act_fail = None
        if is_test:
            act_fail = menu.addAction("Simulate FAIL on next run")
            act_fail.setCheckable(True)
            act_fail.setChecked(row in self.ict_sim_fail)
        # node comments are archived to the project YAML: editing them
        # follows the ICT test-case edit permission (T5)
        act_comment = None
        if self._can_edit_ict:
            act_comment = menu.addAction("Edit comment...")
        chosen = menu.exec(self.ict.viewport().mapToGlobal(pos))
        if chosen is act_bp:
            self._toggle_breakpoint(self.ict, row, self.ict_breakpoints)
        elif act_fail is not None and chosen is act_fail:
            (self.ict_sim_fail.add if act_fail.isChecked()
             else self.ict_sim_fail.discard)(row)
        elif act_comment is not None and chosen is act_comment:
            self._edit_comment(self.ict, row, self.ict_comments)

    def _fct_context_menu(self, pos):
        """Right-click an FCT row -> breakpoint / simulate FAIL / edit
        the node comment (P3-B2 debug feature)."""
        row = self.fct.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
        act_bp = menu.addAction("Breakpoint")
        act_bp.setCheckable(True)
        act_bp.setChecked(row in self.fct_breakpoints)
        act_fail = menu.addAction("Simulate FAIL on next run")
        act_fail.setCheckable(True)
        act_fail.setChecked(row in self.fct_sim_fail)
        # node comments are archived to the project YAML: editing them
        # follows the FCT test-case edit permission (T5)
        act_comment = None
        if self._can_edit_fct:
            act_comment = menu.addAction("Edit comment...")
        chosen = menu.exec(self.fct.viewport().mapToGlobal(pos))
        if chosen is act_bp:
            self._toggle_breakpoint(self.fct, row, self.fct_breakpoints)
        elif chosen is act_fail:
            (self.fct_sim_fail.add if act_fail.isChecked()
             else self.fct_sim_fail.discard)(row)
        elif act_comment is not None and chosen is act_comment:
            self._edit_comment(self.fct, row, self.fct_comments)

    def _edit_comment(self, table, row, comments):
        """Node comment editor: a small QInputDialog, stored per row and
        shown as the row tooltip; an empty text clears the comment."""
        while len(comments) <= row:
            comments.append("")
        old = comments[row]
        text, ok = QInputDialog.getMultiLineText(
            self, "Node comment",
            f"Comment for '{table.item(row, 1).text()}' "
            f"(empty clears it):", old)
        if not ok:
            return
        comments[row] = text.strip()
        item = table.item(row, 1)
        if item is not None:
            item.setToolTip(comments[row])

    def _is_impedance_short_row(self, r):
        """True for every R-GND Shorts test row (engine helper,
        mtkgui.engine.steps.is_impedance_short)."""
        return is_impedance_short_row(self.ict_steps[r])

    def _fill_fct_row(self, r):
        """Fill one FCT row: # / Test / Enable / Duration / Result."""
        name = self.fct_rows[r]
        readonly = ~Qt.ItemFlag.ItemIsEditable
        # col 0: #
        # ● prefix marks a debug breakpoint (P3-B2)
        num_item = QTableWidgetItem(
            f"● {r + 1}" if r in self.fct_breakpoints else str(r + 1))
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        num_item.setFlags(num_item.flags() & readonly)
        self.fct.setItem(r, 0, num_item)
        # col 1: Test name
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() & readonly)
        # node comment (P3-B2 debug feature) -> row tooltip
        comments = getattr(self, "fct_comments", None) or []
        item.setToolTip(comments[r] if r < len(comments) else "")
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

    # ---- double-click a result row -> open the Build dialog ----
    # (task: single sequence source) the page no longer owns a sequence
    # editor: double-clicking asks the main window to open the matching
    # "Build ICT / FCT Test Work Flow Sequence" dialog, which is the one
    # place where the sequence is edited.  The permission / staged-yaml
    # gates stay here.
    def _edit_ict_item(self, row, _col):
        """Double-click ICT -> request the Build ICT dialog."""
        if getattr(self, "_yaml_loading", False):
            return                  # staged yaml load in progress
        if not self._can_edit_ict:
            self._deny_edit("ICT test cases")
            return
        self.ict_build_requested.emit()

    def _edit_fct_item(self, row, _col):
        """Double-click FCT -> request the Build FCT dialog."""
        if getattr(self, "_yaml_loading", False):
            return                  # staged yaml load in progress
        if not self._can_edit_fct:
            self._deny_edit("FCT test cases")
            return
        self.fct_build_requested.emit()


    # ------------------------------------------------------------ demo data
    def current_ict_case_tuples(self) -> list:
        """The live ICT result rows returned VERBATIM (task: single
        sequence source).

        Every row is carried, standard operations included - the old
        s[:6] slicing dropped the op parameters (the flash settings)
        and the op filter dropped the operations themselves, which was
        the other half of the "two conflicting sources" defect.  The
        Build ICT dialog re-seeds its whole sequence from this list.
        """
        return list(self.ict_steps)

    def current_fct_case_dicts(self) -> list:
        """The live FCT Test Cases as case dicts (kind / name /
        op_params) - the source of truth for the Build FCT dialog's
        reverse sync (user direction 2026-10-14).  Standard operations
        are dialog-side sections and are not carried."""
        out: list = []
        for i, kind in enumerate(self.fct_kinds):
            if kind == "op":
                continue
            out.append({
                "kind": kind,
                "name": (self.fct_rows[i]
                         if i < len(self.fct_rows) else ""),
                "op_params": (self.fct_op_params[i] or {})
                if i < len(self.fct_op_params) else {},
            })
        return out

    def load_fct_cases(self, cases: list) -> None:
        """P3-B5: the Yaml Build block 07 FCT sequence was accepted -
        replace the FCT Test Cases table with the generated cases
        (name / kind / enable / wait_ms / timeout_ms / op_params with
        the fct_step marker).

        Merge protection (P3-B7): standard operator dialogs added by
        hand on this page (MessageOK / MessageYesNo / MessageGoStop
        rows WITHOUT the generated fct_step marker) are not part of
        the sequence built in block 07 — they are kept and appended
        after the generated cases, so a sequence rebuild no longer
        wipes them."""
        # unified model (M26): LEGACY published rows ((wait) pre-steps,
        # implicit confirm markers) normalize into ONE row per FCT step
        # before they reach the table, so the table and the runner see
        # exactly the same steps.
        from mtkgui.gui.yamlbuild.fct_build import normalize_fct_cases
        cases = normalize_fct_cases(list(cases))
        generated = {str(c.get("name", "")) for c in cases}
        kept: list = []
        for i, kind in enumerate(self.fct_kinds):
            name = (self.fct_rows[i] if i < len(self.fct_rows) else "")
            marker = (self.fct_op_params[i] or {}
                      if i < len(self.fct_op_params) else {})
            if (kind in ("MessageOK", "MessageYesNo", "MessageGoStop",
                         "MessageOKtoConsole", "MessageYesNotoConsole",
                         "MessageGoStoptoConsole")
                    and not marker.get("fct_step")
                    and name and name not in generated):
                kept.append({
                    "name": name, "kind": kind,
                    "enable": (self.fct_enables[i]
                               if i < len(self.fct_enables) else True),
                    "wait_ms": (self.fct_waits[i]
                                if i < len(self.fct_waits) else 100),
                    "timeout_ms": (self.fct_timeouts[i]
                                   if i < len(self.fct_timeouts) else 5000),
                    "op_params": self.fct_op_params[i]
                    if i < len(self.fct_op_params) else None,
                })
        if kept:
            cases = list(cases) + kept
            self._log(f"FCT sequence rebuilt: {len(kept)} manual standard "
                      f"op(s) kept (appended at the end)")
        self.fct_rows = [str(c.get("name", "")) for c in cases]
        self.fct_enables = [bool(c.get("enable", True)) for c in cases]
        self.fct_waits = [int(c.get("wait_ms", 100)) for c in cases]
        self.fct_timeouts = [int(c.get("timeout_ms", 5000))
                             for c in cases]
        self.fct_kinds = [str(c.get("kind", "MessageOK")) for c in cases]
        self.fct_op_params = [c.get("op_params") for c in cases]
        self.fct_breakpoints = set()
        self.fct.setRowCount(len(cases))
        self._fct_edit_guard = True
        self._fill_fct_all()
        self._fct_edit_guard = False

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
        """DAQ capture CSV - 2026-10-17 identity naming: the capture
        lives in its own identity folder under the DUT Report root,
        folder AND file name carry Part# / Core ID / Batch# / Serial# /
        timestamp.  The DUT report joins the SAME folder at run finish
        (via rail_csv_path)."""
        from datetime import datetime as _dt
        from mtkgui import report_paths
        from mtkgui.gui.dut_pdf import safe_name
        info = self.product_info()
        ident = tuple(safe_name(v) for v in
                      (info["part"] or "NA", info["core_id"] or "NA",
                       info["batch"] or "NA", info["serial"] or "DUT"))
        # identity folder: Part#_CoreID_Batch#_SN_+ capture timestamp
        run_dir = (report_paths.dut_folder()
                   / ("_".join(ident)
                      + f"_{_dt.now():%Y%m%d_%H%M%S}"))
        stem = "power_rails_" + "_".join(ident)
        return write_csv(run_dir, self.rails, samples, volts,
                         self.cap_start, self.cap_rate,
                         self.virtual_mode, stem=stem)

    # ------------------------------------------------------------ actions
    def _set_status(self, table, row, col, status, virtual=False):
        """Write one status cell. Virtual mode prefixes ICT results
        with 'Virtual' and colours them with the dedicated virtual
        verdict palette (yellow-green PASS / orange-red FAIL); FCT
        always runs on real hardware and is never prefixed."""
        virtual = virtual and self.virtual_mode
        text = f"Virtual {status}" if virtual else status
        item = table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, col, item)
        if item.text() != text:
            item.setText(text)   # skip unchanged: avoids column re-layout
        font = QFont()
        if status in ("PASS", "Done"):
            key = "virtual_ok" if virtual else "ok"
            item.setForeground(QColor(gui_theme_color(key)))
            font.setBold(True)
        elif status in ("FAIL", "Error"):
            key = "virtual_bad" if virtual else "bad"
            item.setForeground(QColor(gui_theme_color(key)))
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
        viewer = self._case_viewer
        if viewer is not None and viewer.isVisible():
            viewer.highlight_step(kind, row)

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
                                          "op" if step_kind == "op" else ""),
                             virtual=self.virtual_mode)
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
        the properties dialog (engine hook); the waveform is DRAWN on
        the right immediately after the capture (user direction)."""
        self.rail_samples = samples
        self.rail_volts = volts
        self._rail_plot_cache = plot_cache
        self.rail_csv_path = csv_path
        self._ai_review_text = review
        self.rail_widget.t_start = self.cap_start
        self._apply_rail_filter()

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

    def _dio_write_preflight_dialog(self, blocked):
        """M7: STRONG / SOFT isolation warning before a DIO Write.

        *blocked* is the list of control-net rows the algorithm could
        not clear (isolated False = active IO source, None = unknown).
        Returns ``"force"`` when the operator chooses Force-Continue,
        ``"cancel"`` otherwise (Cancel is the DEFAULT button).
        """
        box = QMessageBox(self)
        box.setWindowTitle("U2355A DIO Write - isolation check")
        box.setIcon(QMessageBox.Icon.Critical)
        lines = []
        for row in blocked or []:
            net = str(row.get("net") or "")
            drivers = ", ".join(str(d) for d in
                                (row.get("active_drivers") or []))
            if row.get("isolated") is False:
                lines.append(
                    f"Control IO {net} connects active IO - NOT "
                    f"isolated; driving may conflict / short. "
                    f"Active IO sources: {drivers}.")
            else:
                lines.append(
                    f"Control IO {net}: isolation cannot be confirmed "
                    f"(unknown refdes {drivers or 'unknown'}) - drive "
                    f"at your own risk?")
        box.setText("\n\n".join(lines) + "\n\nForce-Continue drives the "
                   "U2355A DIO bank anyway.")
        force = box.addButton("Force-Continue",
                              QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        return "force" if box.clickedButton() is force else "cancel"

    def _dio_passive_reminder(self, net, members):
        """M7: BENIGN reminder for an isolated (passive-only) control
        net - review request, no cancel gate (INFO level)."""
        QMessageBox.information(
            self, "U2355A DIO Write - review request",
            f"Algorithm assessed {net} as passive-only (no active IO "
            f"found) - please human-review to avoid algorithm error.\n\n"
            f"All connections: {members}")

    def _fct_message_dialog(self, kind, name, timeout_s: float = 0.0):
        """Modal operator dialog for the FCT message test methods.

        Returns the operator ANSWER (user direction 2026-10-14; the
        Console-domain kinds added 2026-10-18):

        MessageOK     -> ``"ok"``      (acknowledge, no console action)
        MessageYesNo  -> ``"yes"`` / ``"no"``   (the runner sends y / n)
        MessageGoStop -> ``"go"`` / ``"stop"``  (the runner sends y / n;
                         STOP fails the step and stops the run)

        The Console-domain kinds MessageYesNotoConsole /
        MessageGoStoptoConsole share the plain dialog (their expected
        console message is WAITED before the dialog opens); the OK
        variant MessageOKtoConsole uses the non-blocking
        :meth:`_fct_message_notice` instead.

        ``timeout_s`` > 0 auto-closes the dialog after that many
        seconds -> ``"timeout"`` (no send, the step fails).  While the
        dialog is open the 100 ms run timer keeps ticking; the runner's
        _fct_dialog_open flag makes those ticks no-ops so the run does
        not re-enter.  The dialog is centered by the app-level event
        filter like every other dialog."""
        from PySide6.QtCore import QTimer
        kind = {"MessageOKtoConsole": "MessageOK",
                "MessageYesNotoConsole": "MessageYesNo",
                "MessageGoStoptoConsole": "MessageGoStop"}.get(kind, kind)
        method, _, message = name.partition(":")
        message = message.strip() or name
        box = QMessageBox(self)
        box.setWindowTitle(f"FCT: {method.strip()}")
        box.setText(message)
        box.setModal(True)
        go = None
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
        expired = {"flag": False}
        if timeout_s and timeout_s > 0:

            def _auto_close():
                # Qt auto-detects the NoRole button as the escape button
                # and reports it via clickedButton() after close() - mark
                # the expiry explicitly so a dialog timeout is never
                # mistaken for an operator STOP (bug report 2026-10-15:
                # the Power on DUT GoStop auto-close sent 'n' to the DUT
                # and failed the run with nobody touching the dialog)
                expired["flag"] = True
                box.close()

            QTimer.singleShot(int(timeout_s * 1000), _auto_close)
        self._runner._fct_dialog_open = True
        try:
            box.exec()
        finally:
            self._runner._fct_dialog_open = False
        if expired["flag"]:
            return "timeout"
        if kind == "MessageOK":
            return "ok"
        clicked = box.clickedButton()
        if clicked is None:
            return "timeout"
        if kind == "MessageYesNo":
            return "yes" if clicked.text().replace("&", "") == "Yes" \
                else "no"
        return "go" if clicked is go else "stop"

    def _fct_message_notice(self, name):
        """Non-blocking OK notice for MessageOKtoConsole (user direction
        2026-10-18): the operator is notified once the expected console
        message arrived, but the Console keeps streaming and the run
        does NOT stop for the OK click - no command is sent to the
        Console.  Shown modelessly (kept referenced so it is not garbage
        collected); returns immediately."""
        method, _, message = name.partition(":")
        box = QMessageBox(self)
        box.setWindowTitle(f"FCT: {method.strip()}")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(message.strip() or name)
        box.setModal(False)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        if not hasattr(self, "_fct_notice_boxes"):
            self._fct_notice_boxes = []
        self._fct_notice_boxes.append(box)
        box.finished.connect(
            lambda _r, b=box: self._fct_notice_closed(b))
        box.show()
        self._log(f"FCT {name}: operator notified (OK notice, "
                  f"no console action)")

    def _fct_notice_closed(self, box):
        """Drop a closed MessageOKtoConsole notice from the keep-alive
        list."""
        boxes = getattr(self, "_fct_notice_boxes", None)
        if boxes and box in boxes:
            boxes.remove(box)

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

    def test_item_counts(self) -> tuple[int, int]:
        """(ICT, FCT) usable test item counts: rows that actually test
        something (kind != "op" with a non-empty name).  Standard
        operations and the fresh-page placeholder rows never count -
        user direction 2026-10-14: each stage may legally run empty,
        only the BOTH-empty case means "no usable test items"."""
        ict = sum(1 for s in self.ict_steps
                  if len(s) > 1 and s[0] != "op" and str(s[1]).strip())
        fct = 0
        for i, name in enumerate(self.fct_rows):
            kind = (self.fct_kinds[i]
                    if i < len(self.fct_kinds) else "")
            if kind != "op" and str(name).strip():
                fct += 1
        return ict, fct

    def start_run(self, no_debug=False):
        """Run button: pre-test, then step through every test case.
        Long Run > 1 repeats the whole cycle with a pause in between.
        The Run gates + button state stay on the page; the run state
        machine itself lives in the engine (TestRunner.start).
        no_debug=True (Ctrl+F5, Run Without Debug): breakpoints are
        ignored for this run (GUI-layer flag only)."""
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
        ict_n, fct_n = self.test_item_counts()
        if not ict_n and not fct_n:
            # user direction 2026-10-14: each stage may run empty, but
            # a run with NO test items at all is never meaningful
            QMessageBox.warning(
                self, "No Test Items",
                "No usable test items (ICT and FCT are both empty).\n"
                "Add at least one test case before running.")
            self._log("Run blocked: no test items "
                      "(ICT and FCT both empty)")
            return
        self._next_serial()
        if not self._pretest():
            return
        begin("testflow: run")
        self._set_phase("Init...")
        self._interrupted = False
        # debug session starts clean (P3-B2 / item 15)
        self._step_mode = False
        self._no_debug = bool(no_debug)
        if self._no_debug:
            self._log("Run Without Debug: breakpoints are ignored "
                      "for this run")
        self._update_debug_buttons()
        # the F5 action is disabled for the whole run (VS behaviour)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        # long run skips product information input
        self.product_group.setEnabled(False)
        # M19f: auto-open the case viewer when the checkbox is on
        if self.chk_case_viewer.isChecked():
            self.open_test_case_viewer()
        self._runner.start(self.longrun_spin.value())

    def stop_run(self):
        """Stop button: interrupt the run. Remaining test items are left
        blank and the Overall Result is IGNORE (engine, TestRunner.abort;
        the page renders the interrupted state via _on_run_finished)."""
        self._runner.abort()

    # --- RunnerEnv bridge: run-control state rendering -----------------
    def _on_cycle_reset(self):
        """Engine begins a cycle -> blank defaults + clear Event Log.

        The engine clears every channel read buffer at this point (see
        TestRunner._begin_cycle); mark the round boundary in each
        console window so the operator can tell the rounds apart."""
        self.clear_results()
        for channel in self.multi_console.channels.values():
            console = channel.get("console")
            if console is not None:
                console.append_message(
                    "SYS",
                    "New run cycle - console RX buffer cleared",
                    color=self.multi_console.theme["sys"])

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
        # debug session over (P3-B2 / item 15)
        self._step_mode = False
        self._no_debug = False
        self._temp_bp = None
        self._update_debug_buttons()
        self.product_group.setEnabled(True)
        # M19f: auto-close the case viewer when the run ends
        if self._case_viewer is not None and self._case_viewer.isVisible():
            self._case_viewer.close()
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
        # P3-B5: keep the summary for the page-level run_finished
        # consumers (B3 auto-report reads it - the page signal is
        # argument-less by legacy contract)
        self.last_run_summary = dict(summary)
        if reason != "stop":
            # legacy: abort / complete emit run_finished (page jump);
            # operator stop does not
            self.run_finished.emit()
        # item 15: Restart Run (Ctrl+Shift+F5) - the abort has settled,
        # arm the fresh run on the next event-loop turn
        if self._restart_pending:
            self._restart_pending = False
            QTimer.singleShot(0, self, qt_safe(self.start_run))
        end("testflow: run")

    def clear_results(self, keep_log: bool = False):
        """Blank the last run: statuses / durations / verdict / stats.
        keep_log=True skips the Event-Log clear signal (Close Yaml
        resets the run state but keeps the session log history)."""
        self._interrupted = False
        self._runner.reset_results()
        if self.rack is not None:
            self.rack.reset_cycle()  # new unit: PSU off, fixture released
        # user direction: every new run clears the last power-rails
        # capture - the waveform is re-captured and redrawn when the
        # DAQ AI step executes again
        self.rail_samples = None
        self.rail_volts = None
        self._rail_plot_cache = []
        self.rail_csv_path = None
        self._ai_review_text = None
        self._apply_rail_filter()
        self._fill_ict(placeholder=True)
        for r in range(self.fct.rowCount()):
            self._set_status(self.fct, r, 3, "--")
            self._set_status(self.fct, r, 4, "Pending")
        for r in range(self.overall.rowCount()):
            self._set_status(self.overall, r, 3, "Pending")
            self.overall.item(r, 4).setText("--")
        if not keep_log:
            self.log_cleared.emit()
        self._update_result()


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
