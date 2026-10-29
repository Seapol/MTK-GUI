# -*- coding: utf-8 -*-
"""P2-6 visual production report & trend dashboard (pure incremental).

Route key ``reports`` — replaces the P2-1 placeholder.  All data comes
from the P2-5 :class:`MetricsEngine` (zero metric recomputation logic
duplicated here):

  * yield trend line        (time-bucketed real yield)
  * cycle-time bars         (per-case mean, bottleneck highlighted)
  * CpK trend line          (per batch, one configurable parameter)
  * defect TOP bars + failure classification pie
  * batch comparison table  (multi-batch KPI side-by-side)
  * filter / refresh / reset / detail dialog / auto-refresh timer

Zero intrusion into the engine: the page only reads engine records.
"""
from __future__ import annotations

import math
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QGridLayout,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from mtkgui.engine.metrics import (MetricsEngine, TestRecord,
                                   compute_cpk, compute_cycle_time,
                                   compute_yield, filter_records)

from .charts import BarChart, LineChart, PieChart
from .dialog_sizing import wrap_scrollable
from .theme import StyleSpec

AUTO_REFRESH_MS = 5000
TREND_BUCKETS = 6


class ReportPage(QWidget):
    """Visual quality dashboard (route ``reports``)."""

    #: emitted after every refresh with the filtered record count
    report_refreshed = Signal(int)

    def __init__(self, engine: MetricsEngine | None = None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.engine = engine or MetricsEngine()
        self.interactive = True  # False -> headless-safe (no dialogs)
        # CpK trend parameter (configurable by later stages / tests)
        self.cpk_case = ""
        self.cpk_lsl = 0.0
        self.cpk_usl = 0.0
        self._snapshots: list[int] = []   # refresh history sizes

        root = QVBoxLayout(self)

        # filter / action bar ----------------------------------------------
        root.addWidget(self._build_bar())

        # chart grid ---------------------------------------------------------
        grid = QGridLayout()
        self.yield_chart = LineChart("Yield trend (real product yield)", self)
        self.cycle_chart = BarChart("Cycle time per case "
                                    "(bottleneck highlighted)", self)
        self.cpk_chart = LineChart("CpK trend (per batch)", self)
        self.defect_chart = BarChart("Defect TOP", self)
        self.pie_chart = PieChart("Failure classification share", self)
        grid.addWidget(self.yield_chart, 0, 0)
        grid.addWidget(self.cpk_chart, 0, 1)
        grid.addWidget(self.cycle_chart, 1, 0)
        grid.addWidget(self.defect_chart, 1, 1)
        grid.addWidget(self.pie_chart, 2, 0)
        self.batch_table = QTableWidget(0, 4, self)
        self.batch_table.setHorizontalHeaderLabels(
            ["Batch", "Yield", "Mean cycle (s)", "Tests"])
        grid.addWidget(self.batch_table, 2, 1)
        root.addLayout(grid, 1)

        # detail viewer (in-page; dialog when interactive) --------------------
        self.detail = QPlainTextEdit(self)
        self.detail.setReadOnly(True)
        self.detail.setFixedHeight(90)
        root.addWidget(self.detail)

        # auto-refresh ---------------------------------------------------------
        self.auto_btn = QPushButton("Auto refresh: off", self)
        self.auto_btn.setCheckable(True)
        self.auto_btn.toggled.connect(self._toggle_auto)
        bar_widget = root.itemAt(0).widget()
        bar_widget.layout().addWidget(self.auto_btn)
        self.timer = QTimer(self)
        self.timer.setInterval(AUTO_REFRESH_MS)
        self.timer.timeout.connect(self.refresh)

        self.refresh()

    # UI construction -----------------------------------------------------
    def _build_bar(self) -> QWidget:
        host = QWidget(self)
        from PySide6.QtWidgets import QHBoxLayout
        lay = QHBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Batch:", host))
        self.batch_combo = QComboBox(host)
        self.batch_combo.addItem("All")
        lay.addWidget(self.batch_combo)
        lay.addWidget(QLabel("Shift:", host))
        self.shift_combo = QComboBox(host)
        self.shift_combo.addItems(["All", "day", "night"])
        lay.addWidget(self.shift_combo)
        self.refresh_btn = QPushButton("Refresh", host)
        self.reset_btn = QPushButton("Reset", host)
        self.detail_btn = QPushButton("Data detail", host)
        lay.addWidget(self.refresh_btn)
        lay.addWidget(self.reset_btn)
        lay.addWidget(self.detail_btn)
        lay.addStretch(1)
        self.refresh_btn.clicked.connect(self.refresh)
        self.reset_btn.clicked.connect(self.reset)
        self.detail_btn.clicked.connect(self.show_detail)
        return host

    # data access ----------------------------------------------------------
    def _filtered(self) -> list[TestRecord]:
        batch = self.batch_combo.currentText()
        shift = self.shift_combo.currentText()
        return filter_records(
            self.engine.records,
            **({} if batch == "All" else {"batch": batch}),
            **({} if shift == "All" else {"shift": shift}))

    # refresh / reset --------------------------------------------------------
    def refresh(self) -> None:
        """Recompute every chart from the engine's latest records."""
        batches = sorted({r.batch for r in self.engine.records if r.batch})
        cur = self.batch_combo.currentText()
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self.batch_combo.addItem("All")
        for b in batches:
            self.batch_combo.addItem(b)
        if cur in batches:
            self.batch_combo.setCurrentText(cur)
        self.batch_combo.blockSignals(False)

        rows = self._filtered()
        self._snapshots.append(len(rows))
        self._render_yield_trend(rows)
        self._render_cycle(rows)
        self._render_cpk_trend()
        self._render_defects(rows)
        self._render_batch_table()
        self.detail.appendPlainText(
            f"[{datetime.now():%H:%M:%S}] refresh: {len(rows)} record(s) "
            f"in scope")
        self.report_refreshed.emit(len(rows))

    def reset(self) -> None:
        """Reset filters to All and refresh."""
        self.batch_combo.setCurrentText("All")
        self.shift_combo.setCurrentText("All")
        self.refresh()

    # chart renderers -----------------------------------------------------
    def _render_yield_trend(self, rows: list[TestRecord]) -> None:
        """Bucket the in-scope rows by ~equal time slices and plot the
        per-bucket real product yield."""
        timed = sorted((r for r in rows if r.ts is not None
                        and not r.is_invalid),
                       key=lambda r: r.ts)
        if not timed:
            self.yield_chart.set_series("yield", [])
            return
        t0, t1 = timed[0].ts, timed[-1].ts
        span = max((t1 - t0).total_seconds(), 1.0)
        buckets: list[list[TestRecord]] = [[] for _ in range(TREND_BUCKETS)]
        for r in timed:
            idx = min(int((r.ts - t0).total_seconds() / span
                          * TREND_BUCKETS), TREND_BUCKETS - 1)
            buckets[idx].append(r)
        points = []
        for i, bucket in enumerate(buckets):
            if not bucket:
                continue
            y = compute_yield(bucket)
            label = bucket[0].ts.strftime("%H:%M")
            if y.real_yield is not None:
                points.append((label, round(y.real_yield, 4)))
        self.yield_chart.set_series("yield", points)

    def _render_cycle(self, rows: list[TestRecord]) -> None:
        c = compute_cycle_time(rows, top_n=8)
        items = sorted(c.per_case_mean.items(), key=lambda kv: -kv[1])[:8]
        highlight = c.bottlenecks[0][0] if c.bottlenecks else None
        self.cycle_chart.set_data([(k, round(v, 4))
                                   for k, v in items],
                                  highlight=highlight)

    def _render_cpk_trend(self) -> None:
        if not (self.cpk_case and self.cpk_usl > self.cpk_lsl):
            self.cpk_chart.set_series("cpk", [])
            return
        points = []
        for b in sorted({r.batch for r in self.engine.records
                         if r.batch}):
            rows = filter_records(self.engine.records, batch=b)
            k = compute_cpk(rows, self.cpk_case,
                            lsl=self.cpk_lsl, usl=self.cpk_usl)
            if k.cpk is not None and not math.isinf(k.cpk):
                points.append((b, round(k.cpk, 4)))
        self.cpk_chart.set_series("cpk", points)

    def _render_defects(self, rows: list[TestRecord]) -> None:
        y = compute_yield(rows, top_n=8)
        self.defect_chart.set_data([(name, n)
                                    for name, n, _r in y.top_defects],
                                   highlight=(y.top_defects[0][0]
                                              if y.top_defects else None))
        # classification share: real FAILs vs each invalid kind
        fail_n = y.failed
        shares: list[tuple[str, float]] = []
        if fail_n:
            shares.append(("Product defect", float(fail_n)))
        for kind, n in sorted(y.invalid_by_kind.items()):
            shares.append((str(kind), float(n)))
        self.pie_chart.set_data(shares)

    def _render_batch_table(self) -> None:
        batches = sorted({r.batch for r in self.engine.records if r.batch})
        self.batch_table.setRowCount(len(batches))
        for row, b in enumerate(batches):
            rows = filter_records(self.engine.records, batch=b)
            y = compute_yield(rows)
            c = compute_cycle_time(rows)
            vals = [b,
                    "—" if y.real_yield is None
                    else f"{y.real_yield * 100:.2f}%",
                    "—" if c.mean_s is None else f"{c.mean_s:.3f}",
                    str(y.total)]
            for col, v in enumerate(vals):
                self.batch_table.setItem(
                    row, col, QTableWidgetItem(v))

    # detail / auto refresh -------------------------------------------------
    def show_detail(self) -> None:
        """Data detail view: in-page always, modal when interactive."""
        rows = self._filtered()
        lines = [f"{r.ts or '—'} {r.batch or '—'} {r.station or '—'} "
                 f"{r.name} {r.status.value} "
                 f"measured={r.measured} dur={r.duration_s}s"
                 for r in rows[:200]]
        text = "\n".join(lines) or "(no data in scope)"
        self.detail.setPlainText(text)
        if self.interactive:
            box = QDialog(self)
            box.setWindowTitle(f"Data detail ({len(rows)})")
            v = QVBoxLayout(box)
            viewer = QPlainTextEdit(box)
            viewer.setReadOnly(True)
            viewer.setPlainText(text)
            # M34: the detail text scrolls on small windows
            v.addWidget(wrap_scrollable(viewer), 1)
            box.resize(640, 420)
            box.exec()

    def _toggle_auto(self, on: bool) -> None:
        self.auto_btn.setText(f"Auto refresh: {'on' if on else 'off'}")
        if on:
            self.timer.start()
        else:
            self.timer.stop()
