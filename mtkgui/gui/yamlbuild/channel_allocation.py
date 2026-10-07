# -*- coding: utf-8 -*-
"""Channel Allocation (P3-B2 T10): three dedicated config tables.

The parsed testable nets (T8 Parse Nets result - the single data
source) populate three independent tables:

* **Power nets**  - Net / Test point / Impedance (DAQM908A sense
  channel) / Power rails (U2355A AI channel) / Voltage (DAQM908A
  sense channel) - no Instrument / Channel / Status columns;
* **Clock nets**  - Net / Test point / SE Clock Hz (DAQM907A TOT or
  one of the two U2355A counters) / Frequency band (read-only,
  hardware-derived: DAQM907A 0 ~ 100 kHz, U2355A 0.1 Hz ~ 6 MHz) -
  no Instrument / Channel / Status columns;
* **GPIO nets**   - Net / Test point / DIO Channel (one of the 16
  DAQM907A DIO resources; the U2355A DIO stays fixture-reserved) -
  no Instrument / Channel / Status / Digital Input / Digital Output
  columns.

Rules (11.4): every configurable cell is dropdown-only (no free
text); the configuration persists to the project YAML; empty /
legacy files load blank without error.  Pure GUI/config layer - the
test engine and scheduling logic are untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.instrument_status import (
    STATUS_NOK,
    STATUS_OK,
)
from mtkgui.gui.yamlbuild.power_alloc import (
    CLOCK_BANDS,
    CLOCK_CHANNELS,
    DAQM908A_SENSE_CHANNELS,
    GPIO_DIO_CHANNELS,
    U2355A_AI_CHANNELS,
)

#: placeholder for an unconfigured dropdown cell
UNSET = "—"

#: fixed GPIO attributes (legacy row defaults - the GPIO tab itself
#: now picks a DAQM907A DIO channel directly)
GPIO_DI = "HighZ"
GPIO_DO = "No Output"

#: keys rendered as READ-ONLY auto-filled items (not user dropdowns)
AUTO_KEYS = frozenset({"band"})

#: column layout per table kind: (key, label, choices or None).
#: Power tab (user direction): NO Instrument / Channel / Status
#: columns - Impedance and Voltage pick a real DAQM908A sense
#: channel (#1 CH101-140 / #2 CH201-240), Power rails pick one of
#: the 12 offered U2355A AI channels (balanced sampling rate).
POWER_COLUMNS = (
    ("net", "Net", None),
    ("test_point", "Test point", ()),
    ("impedance", "Impedance", DAQM908A_SENSE_CHANNELS),
    ("power_rails", "Power rails", U2355A_AI_CHANNELS),
    ("voltage", "Voltage", DAQM908A_SENSE_CHANNELS),
)
CLOCK_COLUMNS = (
    ("net", "Net", None),
    ("test_point", "Test point", ()),
    ("se_clock_hz", "SE Clock Hz", CLOCK_CHANNELS),
    ("band", "Frequency band", None),
)
#: GPIO tab (user direction): NO Instrument / Channel / Status /
#: Digital Input / Digital Output columns - the DIO Channel cell
#: picks one of the 16 DAQM907A DIO resources (the U2355A DIO stays
#: reserved for the fixture control)
GPIO_COLUMNS = (
    ("net", "Net", None),
    ("test_point", "Test point", ()),
    ("dio_channel", "DIO Channel", GPIO_DIO_CHANNELS),
)
TABLE_SPECS = (("power", POWER_COLUMNS), ("clock", CLOCK_COLUMNS),
               ("gpio", GPIO_COLUMNS))

#: test-point candidates: the member pins of the net (T8 data) plus
#: a free "TP<n>" fallback is NOT allowed - dropdown only, so the
#: test point choices come from the net members
TEST_POINT_FALLBACK = ("TP1", "TP2", "TP3", "TP4")

# ---- adaptive column layout rules (Net column must NOT consume the
# whole viewport; the remaining columns share the leftover space
# evenly, every column keeps a minimum width; manual drag allowed) --
#: Net column: fixed minimum + LIMITED auto-grow (never unlimited)
NET_MIN_WIDTH = 120
NET_MAX_WIDTH = 260
#: minimum width per named column (compression protection: no column
#: gets squeezed out of view on window shrink)
MIN_COLUMN_WIDTHS = {
    "test_point": 90, "instrument": 110, "channel": 90,
    "status": 70,
}
#: minimum width for any other attribute column
MIN_DEFAULT_WIDTH = 85
#: absolute lower bound of the header (drag protection)
HEADER_MIN_SECTION = 60


@dataclass
class AllocatedRow:
    """One configurable row of a channel-allocation table."""

    net: str = ""
    test_point: str = UNSET
    instrument: str = UNSET
    channel: str = UNSET
    impedance: str = UNSET
    power_rails: str = UNSET
    voltage: str = UNSET
    se_clock_hz: str = UNSET
    band: str = UNSET
    dio_channel: str = UNSET
    digital_input: str = GPIO_DI
    digital_output: str = GPIO_DO

    def to_dict(self) -> dict:
        """Persistable plain dict (only the relevant keys per kind are
        meaningful; extra keys are harmless)."""
        return {
            "net": self.net, "test_point": self.test_point,
            "instrument": self.instrument, "channel": self.channel,
            "impedance": self.impedance,
            "power_rails": self.power_rails, "voltage": self.voltage,
            "se_clock_hz": self.se_clock_hz, "band": self.band,
            "dio_channel": self.dio_channel,
            "digital_input": self.digital_input,
            "digital_output": self.digital_output,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AllocatedRow":
        """Restore a row (tolerant: missing keys keep defaults)."""
        row = cls()
        for key in ("net", "test_point", "instrument", "channel",
                    "impedance", "power_rails", "voltage",
                    "se_clock_hz", "band", "dio_channel",
                    "digital_input", "digital_output"):
            if data.get(key):
                setattr(row, key, str(data[key]))
        return row

    def is_configured(self, kind: str) -> bool:
        """Auto-validation rule: OK when every configurable cell of
        the row kind is set (no UNSET left)."""
        required = {
            "power": ("test_point", "impedance", "power_rails",
                      "voltage"),
            "clock": ("test_point", "se_clock_hz", "band"),
            "gpio": ("test_point", "dio_channel"),
        }[kind]
        return all(getattr(self, key) not in ("", UNSET)
                   for key in required)


def rows_from_testable(testable: dict, kind: str) -> list[AllocatedRow]:
    """Build the rows for one table from the T8 parse result (the
    single data source).  Category mapping: Power / Clock / GPIO."""
    wanted = {"power": "Power", "clock": "Clock",
              "gpio": "GPIO"}[kind]
    rows = []
    for name, info in (testable or {}).items():
        if info.get("category") != wanted:
            continue
        rows.append(AllocatedRow(net=name))
    return rows


def merge_rows(existing: list[AllocatedRow],
               nets: list[AllocatedRow]) -> list[AllocatedRow]:
    """Refresh the table rows for the current net set: keep the saved
    configuration of nets that are still present, add the new nets,
    drop the removed ones (ordered by the parse result)."""
    saved = {row.net: row for row in existing}
    merged = []
    for net_row in nets:
        kept = AllocatedRow(net=net_row.net)
        old = saved.get(net_row.net)
        if old is not None:
            kept = old
        merged.append(kept)
    return merged


def test_point_choices(members: list[str]) -> tuple:
    """Dropdown choices for the Test point cell: the net's member
    pins from the parse result (fallback to the fixed TP list when
    the net has no dot-pins)."""
    pins = tuple(m for m in (members or []) if m)
    return pins or TEST_POINT_FALLBACK


@dataclass
class ChannelAllocationData:
    """The three tables' persisted configuration."""

    power: list[AllocatedRow] = field(default_factory=list)
    clock: list[AllocatedRow] = field(default_factory=list)
    gpio: list[AllocatedRow] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {kind: [row.to_dict() for row in getattr(self, kind)]
                for kind, _cols in TABLE_SPECS}

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelAllocationData":
        data = data or {}
        out = cls()
        for kind, _cols in TABLE_SPECS:
            rows = data.get(kind) or []
            setattr(out, kind,
                    [AllocatedRow.from_dict(r) for r in rows
                     if isinstance(r, dict)])
        return out

    def all_ok(self) -> bool:
        """True when every row of every table is fully configured."""
        for kind, _cols in TABLE_SPECS:
            for row in getattr(self, kind):
                if not row.is_configured(kind):
                    return False
        return True


class _NetTable(QWidget):
    """One dedicated dropdown-only table with auto Status."""

    def __init__(self, kind: str, columns, members_of,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.columns = columns
        self._members_of = members_of      # net -> member pins
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(
            [label for _key, label, *_rest in columns])
        header = self.table.horizontalHeader()
        # adaptive layout: every column is user-draggable (Interactive)
        # with a minimum width; the space distribution is done by
        # reflow() on viewport resize - NOT by a Stretch Net column
        # (that would let the Net column consume the whole viewport)
        header.setMinimumSectionSize(HEADER_MIN_SECTION)
        for c in range(len(columns)):
            header.setSectionResizeMode(
                c, QHeaderView.ResizeMode.Interactive)
        self.table.viewport().installEventFilter(self)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table)
        keys = [k for k, _l, *_rest in columns]
        # tables WITHOUT a Status column (Power) keep it as None
        self.status_col = (keys.index("status")
                           if "status" in keys else None)
        # layout bookkeeping: programmatic resize guard (user drags
        # are persisted via column_widths() on save)
        self._applying = False
        self._min_widths = [
            NET_MIN_WIDTH if key == "net"
            else MIN_COLUMN_WIDTHS.get(key, MIN_DEFAULT_WIDTH)
            for key, _l, *_rest in columns]

    # ------------------------------------------------- adaptive layout
    def eventFilter(self, obj, event) -> bool:
        """Viewport resize -> re-distribute the column widths (the
        table layout reflows automatically on window resize)."""
        if obj is self.table.viewport() \
                and event.type() == QEvent.Type.Resize:
            self.reflow()
        return super().eventFilter(obj, event)

    def reflow(self, viewport_width: int | None = None) -> None:
        """Adaptive width distribution: Net = fixed min + limited
        grow (capped), the remaining columns share the leftover
        viewport space evenly (each >= its minimum width - nothing
        gets squeezed or hidden).

        Args:
            viewport_width: Explicit width override (headless tests;
                            defaults to the live viewport width).
        """
        n = len(self._min_widths)
        if n == 0:
            return
        viewport_w = (self.table.viewport().width()
                      if viewport_width is None else viewport_width)
        mins = list(self._min_widths)
        if viewport_w <= sum(mins):
            target = mins           # narrow window: minimums only
        else:
            # Net grows first but only up to its cap
            leftover = viewport_w - sum(mins)
            net_extra = min(leftover // n, NET_MAX_WIDTH - NET_MIN_WIDTH)
            net_w = mins[0] + net_extra
            # the remaining columns share what is left EVENLY, each
            # clamped to its own minimum width
            equal = (viewport_w - net_w) // (n - 1) if n > 1 else 0
            target = [net_w] + [max(m, equal) for m in mins[1:]]
        self._applying = True
        try:
            for i, width in enumerate(target):
                self.table.setColumnWidth(i, width)
        finally:
            self._applying = False

    def column_widths(self) -> list[int]:
        """Current widths of all columns (persistable)."""
        return [self.table.columnWidth(i)
                for i in range(self.table.columnCount())]

    def apply_saved_widths(self, widths) -> None:
        """Restore a saved column layout (guarded: a restore is not a
        user drag)."""
        widths = [int(w) for w in (widths or [])]
        if not widths:
            return
        self._applying = True
        try:
            for i, width in enumerate(widths[:self.table.columnCount()]):
                self.table.setColumnWidth(i, max(HEADER_MIN_SECTION,
                                                 width))
        finally:
            self._applying = False

    # ---------------------------------------------------------- population
    def load_rows(self, rows: list[AllocatedRow]) -> None:
        """(Re)render the rows; config cells become dropdown-only
        combos wired to the auto status, Status stays read-only."""
        self.table.setRowCount(len(rows))
        self._rows = rows
        for r, row in enumerate(rows):
            members = self._members_of(row.net)
            # the Frequency band is hardware-derived from the chosen
            # SE Clock resource - normalize it on every (re)load; a
            # legacy free-text band resets to a clean state
            if row.se_clock_hz in CLOCK_BANDS:
                row.band = CLOCK_BANDS[row.se_clock_hz]
            elif row.band not in ("", UNSET):
                row.band = UNSET
            for c, (key, _label, *_rest) in enumerate(self.columns):
                if key == "net":
                    item = QTableWidgetItem(row.net)
                    item.setFlags(item.flags() &
                                  ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(r, c, item)
                elif key == "status" or key in AUTO_KEYS:
                    item = QTableWidgetItem(
                        self.row_status(row)
                        if key == "status" else getattr(row, key))
                    item.setFlags(item.flags() &
                                  ~Qt.ItemFlag.ItemIsEditable)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(r, c, item)
                else:
                    choices = {
                        "test_point": test_point_choices(members),
                    }.get(key)
                    if choices is None:
                        choices = {k: ch for k, _l, ch in
                                   self.columns if ch}[key]
                    combo = QComboBox()
                    # fixed single-attribute columns (GPIO DI / DO)
                    # carry no UNSET placeholder
                    items = ([*choices] if len(choices) == 1
                             else [UNSET, *choices])
                    combo.addItems(items)
                    current = getattr(row, key)
                    if current and current != UNSET \
                            and combo.findText(current) >= 0:
                        combo.setCurrentText(current)
                    elif current and current != UNSET:
                        # legacy value no longer offered by the pool
                        # (e.g. the pre-pool Power Yes/No cells) -> a
                        # clean unconfigured state, never a hidden one
                        setattr(row, key, UNSET)
                    combo.currentTextChanged.connect(
                        lambda value, rr=r, kk=key:
                            self._cell_changed(rr, kk, value))
                    self.table.setCellWidget(r, c, combo)
                    # single-choice combos auto-show their only option
                    # (e.g. one member pin) - the row state must mirror
                    # what is displayed, never a hidden UNSET
                    if getattr(row, key) in ("", UNSET) \
                            and combo.currentText() != UNSET:
                        setattr(row, key, combo.currentText())
        self.reflow()     # keep the adaptive layout after (re)fill

    def _cell_changed(self, row_index: int, key: str, value: str) -> None:
        """A dropdown changed: store the value + recompute Status.
        Choosing an SE Clock resource auto-fills its fixed frequency
        band (hardware mapping)."""
        if row_index >= len(self._rows):
            return
        setattr(self._rows[row_index], key, value)
        if key == "se_clock_hz":
            row = self._rows[row_index]
            row.band = CLOCK_BANDS.get(value, UNSET)
            keys = [k for k, _l, *_r in self.columns]
            if "band" in keys:
                band_col = keys.index("band")
                item = self.table.item(row_index, band_col)
                if item is not None:
                    item.setText(row.band)
        self._update_status(row_index, key)

    def _update_status(self, row_index: int, key: str) -> None:
        row = self._rows[row_index]
        if self.status_col is None or key == "status":
            return                       # table without a Status column
        status = self.row_status(row)
        item = self.table.item(row_index, self.status_col)
        if item is not None:
            item.setText(status)

    def row_status(self, row: AllocatedRow) -> str:
        """Auto-validation: OK when fully configured, else NOK."""
        return STATUS_OK if row.is_configured(self.kind) else STATUS_NOK

    def collect(self) -> list[dict]:
        """The current rows as persistable dicts (the combos already
        wrote every change back into the row objects)."""
        return [row.to_dict() for row in self._rows]

    def rows(self) -> list[AllocatedRow]:
        return list(self._rows)


class ChannelAllocationPage(QWidget):
    """The dedicated Channel Allocation tab (three tables)."""

    #: (level, message) Event-Log mirror (T6)
    task_log = Signal(str, str)
    #: Apply to YAML clicked: the tables were persisted into the
    #: model - the main window switches to the Yaml Build tab
    apply_yaml_requested = Signal()

    def __init__(self, *, parent: QWidget | None = None) -> None:
        # NOTE: the model is NOT accepted in __init__ ON PURPOSE.
        # PySide6 6.10.x shiboken GC bug: storing a plain (non-QObject)
        # Python object as a widget attribute DURING __init__ and then
        # re-parenting the widget (QTabWidget.addTab) segfaults.  The
        # model is injected after creation via set_model() (verified:
        # assignment after addTab is safe).
        super().__init__(parent)
        self.model = None
        self._edit_allowed = True

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addStretch(1)
        btn_apply = QPushButton("Apply to YAML")
        btn_apply.setToolTip(
            "Persist the channel allocation into the YAML config and "
            "switch to the Yaml Build page")
        btn_apply.clicked.connect(self._apply_to_yaml)
        top.addWidget(btn_apply)
        lay.addLayout(top)
        hint = QLabel(
            "Data source: the Parse Nets result (Parse Nets for ICT "
            "module). All configuration cells are dropdown-only.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.tabs = QTabWidget()
        self._members_of = self._net_members
        self.table_power = _NetTable("power", POWER_COLUMNS,
                                     self._members_of)
        self.table_clock = _NetTable("clock", CLOCK_COLUMNS,
                                     self._members_of)
        self.table_gpio = _NetTable("gpio", GPIO_COLUMNS,
                                    self._members_of)
        self.tabs.addTab(self.table_power, "Power Nets")
        self.tabs.addTab(self.table_clock, "Clock Nets")
        self.tabs.addTab(self.table_gpio, "GPIO Nets")
        lay.addWidget(self.tabs, 1)

        self.lbl_summary = QLabel("")
        lay.addWidget(self.lbl_summary)

    # ------------------------------------------------------------ helpers
    def set_model(self, model) -> None:
        """Inject the model AFTER construction (shiboken GC bug
        workaround, see __init__) and refresh the tables."""
        self.model = model
        self.refresh_from_model()
        self.set_edit_allowed(self._edit_allowed)

    def _net_members(self, net: str) -> list[str]:
        """Member pins of one net from the T8 parse result."""
        info = ((self.model.imported.get("testable_nets") or {})
                .get(net) if self.model else None) or {}
        return list(info.get("members") or [])

    def set_edit_allowed(self, allowed: bool) -> None:
        """Permission gate (T5 matrix): operators view only."""
        self._edit_allowed = bool(allowed)
        for table in (self.table_power, self.table_clock,
                      self.table_gpio):
            for r in range(table.table.rowCount()):
                for c in range(table.table.columnCount()):
                    widget = table.table.cellWidget(r, c)
                    if widget is not None:
                        widget.setEnabled(self._edit_allowed)

    # ---------------------------------------------------------- data flow
    def refresh_from_model(self) -> None:
        """Sync the tables with the current T8 parse result, keeping
        the saved configuration of unchanged nets."""
        data = ChannelAllocationData.from_dict(
            (self.model.channel_allocation if self.model else {}))
        testable = (self.model.imported.get("testable_nets")
                    if self.model else None) or {}
        saved_widths = ((self.model.channel_allocation or {})
                        .get("column_widths") or {}
                        if self.model else {})
        for kind, table in (("power", self.table_power),
                            ("clock", self.table_clock),
                            ("gpio", self.table_gpio)):
            nets = rows_from_testable(testable, kind)
            merged = merge_rows(getattr(data, kind), nets)
            table.load_rows(merged)
            # restore the saved user column layout (guarded - not a
            # drag); a later window resize reflows per the rules
            table.apply_saved_widths(saved_widths.get(kind))
        self._update_summary()

    def collect(self) -> dict:
        """The full configuration as a persistable dict (including the
        per-table column widths - the user layout is restored when the
        project is reopened)."""
        return {
            "power": self.table_power.collect(),
            "clock": self.table_clock.collect(),
            "gpio": self.table_gpio.collect(),
            "column_widths": {
                kind: table.column_widths()
                for kind, table in (("power", self.table_power),
                                    ("clock", self.table_clock),
                                    ("gpio", self.table_gpio))
            },
        }

    def save_to_model(self) -> None:
        """Persist the tables into the model (project YAML channel)
        and the restart-safe project store."""
        if self.model is not None:
            self.model.set_channel_allocation(self.collect())
            self.task_log.emit(
                "INFO",
                "channel allocation saved: "
                f"{self._summary_text()}")
            try:
                from mtkgui.gui.yamlbuild.store import \
                    save_project_state
                save_project_state(self.model.project_key(),
                                   self.model.to_dict())
            except Exception:     # persistence must never break the GUI
                pass

    def _apply_to_yaml(self) -> None:
        """Apply-to-YAML (user direction): persist the tables into
        the model and jump to the Yaml Build page (operators cannot
        modify the YAML config)."""
        if not self._edit_allowed:
            QMessageBox.information(
                self, "Permission",
                "Operator account cannot modify the YAML configuration.")
            return
        self.save_to_model()
        self.apply_yaml_requested.emit()

    def _update_summary(self) -> None:
        data = ChannelAllocationData.from_dict(self.collect())
        counts = {kind: len(getattr(data, kind))
                  for kind, _cols in TABLE_SPECS}
        ok = data.all_ok()
        self.lbl_summary.setText(
            f"rows: power={counts['power']} clock={counts['clock']} "
            f"gpio={counts['gpio']} - validation: "
            + (STATUS_OK if ok else "NOK (incomplete rows)"))

    def _summary_text(self) -> str:
        data = ChannelAllocationData.from_dict(self.collect())
        return (f"power={len(data.power)} clock={len(data.clock)} "
                f"gpio={len(data.gpio)}")

    # ------------------------------------------------- tab lifecycle
    def showEvent(self, event: QShowEvent) -> None:
        """Refresh on every tab entry: the tables always mirror the
        current T8 parse result (kept configurations preserved)."""
        super().showEvent(event)
        self.refresh_from_model()
        self.set_edit_allowed(self._edit_allowed)

    def hideEvent(self, event) -> None:
        """Persist the configuration when the tab is left."""
        self.save_to_model()
        super().hideEvent(event)
