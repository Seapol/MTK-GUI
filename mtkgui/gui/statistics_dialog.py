# -*- coding: utf-8 -*-
"""Report > Statistics dashboard (M10-FIX4 F1).

Real quality-statistics view on top of the pure-data
:mod:`mtkgui.gui.statistics_store` and the P2-6 QPainter chart widgets
(no external chart dependency):

  * overview cards - Total Units / Passed / Failed / Yield % / Avg
    Cycle Time / UPH
  * LineChart  - cumulative yield % and running average cycle per run
  * BarChart   - cycle time per unit (per-batch mean above 50 runs),
                 slowest unit highlighted
  * PieChart   - failure classification share by failed step name
  * CpK table  - Test | Samples | Mean | StdDev | LSL | USL | Cp | CpK
  * history    - Timestamp | Serial | Verdict | Cycle (s) | Passed |
                 Failed | Failed steps

Two data sources share the same widgets: the live session (page
counters + current row results) and the append-only history file
``config/statistics/runs.json``.  A corrupt history never crashes the
dialog - it starts fresh and shows the reason.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from mtkgui.gui import statistics_store as store
from mtkgui.gui.charts import BarChart, LineChart, PieChart

#: BarChart switches from per-unit to per-batch means above this count
BATCH_THRESHOLD = 50
#: units per bar when the batch view is active
BATCH_SIZE = 10
#: placeholder shown for a metric that has no data
NO_VALUE = "—"

#: overview cards in display order: (key, caption)
OVERVIEW_CARDS = (
    ("total", "Total Units"),
    ("passed", "Passed"),
    ("failed", "Failed"),
    ("yield_pct", "Yield %"),
    ("avg_cycle_s", "Avg Cycle Time (s)"),
    ("uph", "UPH"),
)

CPK_HEADERS = ["Test", "Samples", "Mean", "StdDev", "LSL", "USL",
               "Cp", "CpK"]
HISTORY_HEADERS = ["Timestamp", "Serial", "Verdict", "Cycle (s)",
                   "Passed", "Failed", "Failed steps"]


class _OverviewCard(QFrame):
    """One caption + big value tile of the overview row."""

    def __init__(self, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("stat_card")
        self.setStyleSheet(
            "QFrame#stat_card { border:1px solid #3a4150; border-radius:6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(2)
        title = QLabel(caption, self)
        title.setObjectName("muted")
        lay.addWidget(title)
        self.value = QLabel(NO_VALUE, self)
        self.value.setStyleSheet(
            "font-size:18px; font-weight:bold; color:#e6e9ef;")
        lay.addWidget(self.value)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class StatisticsDialog(QDialog):
    """Yield / UPH / CpK dashboard fed from the session or the history."""

    def __init__(self, page=None, parent=None, *, runs_path=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Statistics")
        self.setModal(True)
        self.resize(960, 720)
        self.page = page
        self.runs_path = runs_path
        #: records of the last refresh (test / embedder hook)
        self.last_records: list[store.RunRecord] = []

        root = QVBoxLayout(self)

        # --------------------------------------------------- source row
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Data source:"))
        self.source_combo = QComboBox(self)
        self.source_combo.addItem("Session (current run state)", "session")
        self.source_combo.addItem("History (runs.json)", "history")
        self.source_combo.currentIndexChanged.connect(self.refresh)
        source_row.addWidget(self.source_combo)
        self.path_label = QLabel("", self)
        self.path_label.setObjectName("muted")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        source_row.addWidget(self.path_label, 1)
        root.addLayout(source_row)

        # corrupt-history / empty-source notice (hidden when clean)
        self.warning_label = QLabel("", self)
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color:#e5b13a;")
        self.warning_label.setVisible(False)
        root.addWidget(self.warning_label)

        # --------------------------------------------------- overview
        cards = QHBoxLayout()
        self.cards: dict[str, _OverviewCard] = {}
        for key, caption in OVERVIEW_CARDS:
            card = _OverviewCard(caption, self)
            self.cards[key] = card
            cards.addWidget(card, 1)
        root.addLayout(cards)

        # ----------------------------------------------------- charts
        charts = QHBoxLayout()
        self.line_chart = LineChart("Yield % / avg cycle per run", self)
        self.bar_chart = BarChart(
            "Cycle time per unit (slowest highlighted)", self)
        self.pie_chart = PieChart("Failure classification share", self)
        charts.addWidget(self.line_chart, 1)
        charts.addWidget(self.bar_chart, 1)
        charts.addWidget(self.pie_chart, 1)
        root.addLayout(charts, 1)

        # -------------------------------------------------- CpK table
        cpk_box = QGroupBox("Process capability (Cp / CpK)", self)
        cpk_lay = QVBoxLayout(cpk_box)
        cpk_lay.setContentsMargins(6, 6, 6, 6)
        self.cpk_table = self._make_table(CPK_HEADERS)
        cpk_lay.addWidget(self.cpk_table)
        root.addWidget(cpk_box, 1)

        # ---------------------------------------------------- history
        history_box = QGroupBox("Run history", self)
        history_lay = QVBoxLayout(history_box)
        history_lay.setContentsMargins(6, 6, 6, 6)
        self.history_table = self._make_table(HISTORY_HEADERS)
        history_lay.addWidget(self.history_table)
        root.addWidget(history_box, 1)

        # ---------------------------------------------------- buttons
        actions = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh", self)
        self.btn_refresh.clicked.connect(self.refresh)
        actions.addWidget(self.btn_refresh)
        actions.addStretch(1)
        self.btn_close = QPushButton("Close", self)
        self.btn_close.clicked.connect(self.accept)
        actions.addWidget(self.btn_close)
        root.addLayout(actions)

        self.refresh()

    # ---------------------------------------------------------- widgets
    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers), self)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        return table

    # ------------------------------------------------------------ data
    def current_source(self) -> str:
        return str(self.source_combo.currentData() or "session")

    def _load_source(self) -> tuple[list[store.RunRecord], str]:
        if self.current_source() == "session":
            return store.session_records(self.page), ""
        return store.load_runs(self.runs_path)

    def refresh(self) -> None:
        """Reload the active source and re-render every widget."""
        target = (store.RUNS_PATH if self.runs_path is None
                  else self.runs_path)
        self.path_label.setText(str(target))
        try:
            records, warning = self._load_source()
        except Exception as exc:                # noqa: BLE001 (never crash)
            records, warning = [], f"statistics unavailable: {exc}"
        self.last_records = records
        self.warning_label.setText(warning)
        self.warning_label.setVisible(bool(warning))
        self._fill_overview(records)
        self._fill_charts(records)
        self._fill_cpk(records)
        self._fill_history(records)

    # --------------------------------------------------------- render
    def _fill_overview(self, records: list[store.RunRecord]) -> None:
        data = store.overview(records)
        has_data = data["total"] > 0
        self.cards["total"].set_value(
            str(data["total"]) if has_data else NO_VALUE)
        self.cards["passed"].set_value(
            str(data["passed"]) if has_data else NO_VALUE)
        self.cards["failed"].set_value(
            str(data["failed"]) if has_data else NO_VALUE)
        self.cards["yield_pct"].set_value(
            f"{data['yield_pct']:.1f}" if has_data else NO_VALUE)
        self.cards["avg_cycle_s"].set_value(
            f"{data['avg_cycle_s']:.2f}" if data["avg_cycle_s"] > 0
            else NO_VALUE)
        self.cards["uph"].set_value(
            f"{data['uph']:.1f}" if data["uph"] > 0 else NO_VALUE)

    def _fill_charts(self, records: list[store.RunRecord]) -> None:
        # LineChart: cumulative yield + running average cycle per run
        yield_points: list[tuple[str, float]] = []
        cycle_points: list[tuple[str, float]] = []
        passed = 0
        cycle_sum = 0.0
        for index, record in enumerate(records, start=1):
            if record.verdict == store.VERDICT_PASS:
                passed += 1
            if record.cycle_time_s > 0:
                cycle_sum += record.cycle_time_s
            label = str(index)
            yield_points.append((label, passed / index * 100.0))
            if cycle_sum > 0:
                cycle_points.append(
                    (label, cycle_sum / max(1, index)))
        self.line_chart.set_series("Yield %", yield_points)
        self.line_chart.set_series("Cycle (s)", cycle_points)

        # BarChart: unit cycle times (batch means above the threshold)
        items: list[tuple[str, float]] = []
        if len(records) > BATCH_THRESHOLD:
            for start in range(0, len(records), BATCH_SIZE):
                chunk = records[start:start + BATCH_SIZE]
                cycles = [r.cycle_time_s for r in chunk
                          if r.cycle_time_s > 0]
                if cycles:
                    items.append((f"B{start // BATCH_SIZE + 1}",
                                  sum(cycles) / len(cycles)))
        else:
            for index, record in enumerate(records, start=1):
                if record.cycle_time_s > 0:
                    items.append((f"Run {index}", record.cycle_time_s))
        highlight = max(items, key=lambda item: item[1])[0] if items else None
        self.bar_chart.set_data(items, highlight=highlight)

        # PieChart: failure classification by failed step name
        counts: dict[str, int] = {}
        for record in records:
            if record.verdict != store.VERDICT_FAIL:
                continue
            names = record.failed_steps or ["Unclassified"]
            for name in names:
                label = str(name) or "Unclassified"
                counts[label] = counts.get(label, 0) + 1
        self.pie_chart.set_data(sorted(counts.items(),
                                       key=lambda kv: -kv[1]))

    def _fill_cpk(self, records: list[store.RunRecord]) -> None:
        rows = store.cpk_rows(records)
        self.cpk_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            samples = int(row["samples"])
            limited = row["indicative"]
            if samples < 2 or row["cp"] is None or row["cpk"] is None:
                cp_text = cpk_text = "N/A"
            else:
                cp_text = f"{row['cp']:.3f}"
                cpk_text = f"{row['cpk']:.3f}"
                if limited:
                    cpk_text += " (n<5, indicative only)"
            values = [
                row["test"],
                str(samples),
                f"{row['mean']:.4g}",
                f"{row['sigma']:.4g}",
                f"{row['lsl']:.4g}",
                f"{row['usl']:.4g}",
                cp_text,
                cpk_text,
            ]
            for column, text in enumerate(values):
                self.cpk_table.setItem(
                    row_index, column, QTableWidgetItem(str(text)))

    def _fill_history(self, records: list[store.RunRecord]) -> None:
        self.history_table.setRowCount(len(records))
        for row_index, record in enumerate(records):
            values = [
                record.timestamp,
                record.serial,
                record.verdict,
                f"{record.cycle_time_s:.2f}",
                str(record.passed),
                str(record.failed),
                ", ".join(record.failed_steps),
            ]
            for column, text in enumerate(values):
                self.history_table.setItem(
                    row_index, column, QTableWidgetItem(str(text)))

    # ------------------------------------------------------ test hooks
    def showEvent(self, event):
        """Auto-refresh on every open (page state / file may change)."""
        super().showEvent(event)
        self.refresh()
