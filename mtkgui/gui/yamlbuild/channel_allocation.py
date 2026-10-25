# -*- coding: utf-8 -*-
"""Channel Allocation (P3-B2 T10): three dedicated config tables.

The parsed testable nets (T8 Parse Nets result - the single data
source) populate three independent tables:

* **Power nets**  - Net / Test point / R-GND (DAQM908A sense
  channel) / Power rails (U2355A AI channel) / Voltage (DAQM908A
  sense channel) - no Instrument / Channel / Status columns;
* **Clock nets**  - Net / Test point / SE Clock Hz (DAQM907A TOT or
  one of the two U2355A counters) / Frequency band (read-only,
  hardware-derived: DAQM907A 0 ~ 100 kHz, U2355A 0.1 Hz ~ 6 MHz) -
  no Instrument / Channel / Status columns;
* **Control IO nets** - Net / Test point / DIO Channel (one of the 24
  U2355A DIO resources for the DUT Control IO; the DAQM907A DIO stays
  fixture-reserved) - no Instrument / Channel / Status / Digital
  Input / Digital Output columns.  Nets beyond the 24-channel capacity
  stay classified but get no channel (capacity overflow, not tested).

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
    QDoubleSpinBox,
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
from mtkgui.gui.yamlbuild.ict_sequence import (
    CLOCK_TOL_PPM,
    POWER_TOL,
)
from mtkgui.ict.netparse.isolation import assess_net
from mtkgui.gui.yamlbuild.power_alloc import (
    CLOCK_BANDS,
    CLOCK_CHANNELS,
    DAQM908A_SENSE_CHANNELS,
    GPIO_CHANNEL_CAPACITY,
    GPIO_DIO_CHANNELS,
    U2355A_AI_CHANNELS,
)

#: placeholder for an unconfigured dropdown cell
UNSET = "—"

#: fixed GPIO attributes (legacy row defaults - the GPIO tab itself
#: now picks a U2355A DIO channel directly)
GPIO_DI = "HighZ"
GPIO_DO = "No Output"

#: keys rendered as READ-ONLY auto-filled items (not user dropdowns)
AUTO_KEYS = frozenset({"band"})

#: viewport-lazy rendering: dropdown widgets render for the visible
#: rows plus this margin above/below; scrolling tops the rest up
LAZY_MARGIN_ROWS = 30

#: Control-IO operation choice (M19b: every Control IO net defaults
#: to High Z = NOT TESTED; the operator arms the nets that must be
#: read / driven - Read needs the DIO channel, Write additionally the
#: Drive level, and a DIO Write passes the active-IO isolation guard)
OP_HIGH_Z = "High Z (Not Tested)"
OP_CHOICES = (OP_HIGH_Z, "U2355A DIO Read", "U2355A DIO Write")
#: drive level for the Control IO nets armed as DIO Write (M19b)
DRIVE_LEVELS = ("High", "Low")
#: numeric (user-editable) columns - rendered as spin boxes, their
#: values feed the 04 ICT sequence Expected / Min / Max (M19)
NUMERIC_COLUMNS = frozenset({
    "nominal_v", "lower_v", "upper_v",
    "nominal_khz", "lower_khz", "upper_khz"})

#: column layout per table kind: (key, label, choices or None).
#: Power tab (user direction): NO Instrument / Channel / Status
#: columns - Impedance and Voltage pick a real DAQM908A sense
#: channel (#1 CH101-140 / #2 CH201-240), Power rails pick one of
#: the 12 offered U2355A AI channels (balanced sampling rate).
#: M19: Nominal / Lower / Upper (V) columns let the operator fix the
#: test limits right here in the allocation page.
POWER_COLUMNS = (
    ("net", "Net", None),
    ("test_point", "Test point", ()),
    ("impedance", "R-GND", DAQM908A_SENSE_CHANNELS),
    ("power_rails", "Power rails", U2355A_AI_CHANNELS),
    ("voltage", "Voltage", DAQM908A_SENSE_CHANNELS),
    ("nominal_v", "Nominal (V)", None),
    ("lower_v", "Lower limit (V)", None),
    ("upper_v", "Upper limit (V)", None),
)
CLOCK_COLUMNS = (
    ("net", "Net", None),
    ("test_point", "Test point", ()),
    ("se_clock_hz", "SE Clock Hz", CLOCK_CHANNELS),
    ("band", "Frequency band", None),
    ("nominal_khz", "Nominal (kHz)", None),
    ("lower_khz", "Lower limit (kHz)", None),
    ("upper_khz", "Upper limit (kHz)", None),
)
#: GPIO tab (user direction): NO Instrument / Channel / Status /
#: Digital Input / Digital Output columns - the DIO Channel cell
#: picks one of the 24 U2355A DIO resources (the DAQM907A DIO stays
#: reserved for the fixture control)
GPIO_COLUMNS = (
    ("net", "Net", None),
    ("test_point", "Test point", ()),
    ("dio_channel", "DIO Channel", GPIO_DIO_CHANNELS),
    ("op_type", "Operation", OP_CHOICES),
    ("drive_level", "Drive level", DRIVE_LEVELS),
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
    # M19: user-editable test limits (03 page) inherited by the 04
    # sequence; op_type = Control-IO operation (IO Read / IO Write)
    nominal_v: str = UNSET
    lower_v: str = UNSET
    upper_v: str = UNSET
    nominal_khz: str = UNSET
    lower_khz: str = UNSET
    upper_khz: str = UNSET
    op_type: str = UNSET
    # M19b: drive level for a Control IO armed as DIO Write
    drive_level: str = UNSET

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
            "nominal_v": self.nominal_v,
            "lower_v": self.lower_v,
            "upper_v": self.upper_v,
            "nominal_khz": self.nominal_khz,
            "lower_khz": self.lower_khz,
            "upper_khz": self.upper_khz,
            "op_type": self.op_type,
            "drive_level": self.drive_level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AllocatedRow":
        """Restore a row (tolerant: missing keys keep defaults)."""
        row = cls()
        for key in ("net", "test_point", "instrument", "channel",
                    "impedance", "power_rails", "voltage",
                    "se_clock_hz", "band", "dio_channel",
                    "digital_input", "digital_output",
                    "nominal_v", "lower_v", "upper_v",
                    "nominal_khz", "lower_khz", "upper_khz",
                    "op_type", "drive_level"):
            if data.get(key):
                setattr(row, key, str(data[key]))
        return row

    def is_configured(self, kind: str) -> bool:
        """Auto-validation rule: OK when every configurable cell of
        the row kind is set (no UNSET left).

        M19: power_rails is NOT required - the U2355A AI pool is 12
        channels while a board can carry 55+ rails; R-GND / Voltage
        (DAQM908A, 80 channels) and the test limits ARE required.
        M19b: a Control IO row defaulting to High Z (NOT TESTED) is a
        valid row - no DIO channel / drive level required.  Read needs
        the DIO channel, Write additionally the drive level."""
        if kind == "gpio":
            op = self.op_type
            if op in ("", UNSET):
                return False
            if op == OP_HIGH_Z:
                return True
            if op == "U2355A DIO Read":
                return (self.test_point not in ("", UNSET)
                        and self.dio_channel not in ("", UNSET))
            return (self.test_point not in ("", UNSET)
                    and self.dio_channel not in ("", UNSET)
                    and self.drive_level not in ("", UNSET))
        required = {
            "power": ("test_point", "impedance", "voltage",
                      "nominal_v", "lower_v", "upper_v"),
            "clock": ("test_point", "se_clock_hz", "band",
                      "nominal_khz", "lower_khz", "upper_khz"),
        }[kind]
        return all(getattr(self, key) not in ("", UNSET)
                   for key in required)


def rows_from_testable(testable: dict, kind: str) -> list[AllocatedRow]:
    """Build the rows for one table from the T8 parse result (the
    single data source).  Category mapping: Power / Clock / GPIO
    (legacy display labels such as ``Signal`` / ``SE Clock`` and the
    Control IO label are accepted too)."""
    wanted = {"power": "Power", "clock": "Clock",
              "gpio": "GPIO"}[kind]
    aliases = {"SE Clock": "Clock", "Signal": "GPIO",
               "Control IO (non-mux GPIO/EN/CS/RST)": "GPIO"}
    rows = []
    for name, info in (testable or {}).items():
        category = (info or {}).get("category")
        if aliases.get(category, category) != wanted:
            continue
        row = AllocatedRow(net=name)
        # M19: seed the test limits from the parse result (nominal_v /
        # nominal_khz, tolerance defaults power +/- 5 %, clock +/- 50
        # ppm) - the operator edits them here and 04 inherits them
        if kind == "power":
            nom = _stored_num(info.get("nominal_v"))
            if nom is not None:
                row.nominal_v = f"{nom:.3f}"
                row.lower_v = f"{nom * (1 - POWER_TOL):.3f}"
                row.upper_v = f"{nom * (1 + POWER_TOL):.3f}"
        elif kind == "clock":
            khz = _stored_num(info.get("nominal_khz"))
            if khz is not None:
                row.nominal_khz = f"{khz:.4f}"
                row.lower_khz = f"{khz * (1 - CLOCK_TOL_PPM * 1e-6):.4f}"
                row.upper_khz = f"{khz * (1 + CLOCK_TOL_PPM * 1e-6):.4f}"
        else:
            row.op_type = OP_CHOICES[0]
        rows.append(row)
    return rows


def merge_rows(existing: list[AllocatedRow],
               nets: list[AllocatedRow]) -> list[AllocatedRow]:
    """Refresh the table rows for the current net set: keep the saved
    configuration of nets that are still present, add the new nets
    WITH their defaults (nominal / limits / op_type - M19), drop the
    removed ones (ordered by the parse result)."""
    saved = {row.net: row for row in existing}
    merged = []
    for net_row in nets:
        old = saved.get(net_row.net)
        # a fresh net keeps the parsed defaults (nominal_v / nominal_khz
        # / op_type); a saved net keeps the operator's configuration
        merged.append(old if old is not None else net_row)
    return merged


def _stored_num(value) -> float | None:
    """A stored nominal as a positive float (M19 seed)."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


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

    #: (net, old, new) - a Control-IO operation cell changed (M19b the
    #: page runs the DIO-write isolation preflight on this)
    operation_changed = Signal(str, str, str)

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
        # click a header section -> whole-row sort asc/desc (user
        # direction); the sort is OURS (re-render via load_rows) and
        # NOT the default QTableWidget sorting (that would break the
        # per-cell widgets)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._on_header_clicked)
        self._sort_col: int | None = None
        self._sort_desc = False
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
        # viewport-lazy dropdown rendering (2026-10-15): a 652-net GPIO
        # table means 4000+ QComboBox objects and ~12 s of QSS polish at
        # every project load - the row DATA is always complete (the
        # _rows objects are the single source of truth, collect() reads
        # them), only the dropdown WIDGETS render for the visible
        # window (+ margin) and top up while scrolling.
        self._rendered: set[int] = set()
        self.table.verticalScrollBar().valueChanged.connect(
            lambda _v: self._render_window())
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
        table layout reflows automatically on window resize) and top
        up the lazy-rendered dropdown window."""
        if obj is self.table.viewport() \
                and event.type() == QEvent.Type.Resize:
            self.reflow()
            self._render_window()
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
        """(Re)load the row DATA and render the visible window.

        The row objects are the single source of truth: they are fully
        normalized here (single-choice columns auto-show their only
        option, legacy values reset), while the dropdown WIDGETS are
        rendered lazily for the visible rows only (see
        :meth:`_render_window`) - a full render of a 652-row GPIO table
        costs ~12 s of widget polish."""
        # drop the previous row widgets FIRST: setCellWidget does not
        # delete the replaced widget in every Qt build - the old combos
        # stay parented to the viewport and stack as ghosts over row 0
        # (user report: stray dropdowns covered the first data row)
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                old = self.table.cellWidget(r, c)
                if old is not None:
                    self.table.removeCellWidget(r, c)
                    old.hide()
                    old.deleteLater()
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
                elif key in NUMERIC_COLUMNS:
                    # numeric spin-box cells: no dropdown normalization
                    continue
                else:
                    # data-level normalization (the widget mirror is
                    # deferred to the render window): single-choice
                    # columns auto-show their only option - the row
                    # state must mirror what would be displayed, never
                    # a hidden UNSET; a legacy value no longer offered
                    # by the pool (e.g. the pre-pool Power Yes/No
                    # cells) resets to a clean unconfigured state
                    choices = {
                        "test_point": test_point_choices(members),
                    }.get(key)
                    if choices is None:
                        choices = {k: ch for k, _l, ch in
                                   self.columns if ch}[key]
                    current = getattr(row, key)
                    if current in ("", UNSET):
                        if len(choices) == 1:
                            setattr(row, key, next(iter(choices)))
                    elif current not in choices:
                        setattr(row, key, UNSET)
        self._rendered = set()
        self._render_window()
        self.reflow()     # keep the adaptive layout after (re)fill

    # --------------------------------------------- lazy combo rendering
    def _render_window(self) -> None:
        """Render the dropdown widgets for the rows around the visible
        viewport (the data in ``_rows`` is always complete; combos only
        mirror it).  A hidden tab has a zero-height viewport - its rows
        render when the tab is shown (currentChanged hook)."""
        n = self.table.rowCount()
        if not n:
            return
        viewport_h = self.table.viewport().height()
        if viewport_h <= 0:
            return
        row_h = max(self.table.rowHeight(0), 1)
        first = max(0, self.table.verticalScrollBar().value()
                    // row_h - LAZY_MARGIN_ROWS)
        last = min(n, first + viewport_h // row_h
                   + 2 * LAZY_MARGIN_ROWS)
        for r in range(first, last):
            if r not in self._rendered:
                self._rendered.add(r)
                self._render_row(r)

    def _render_row(self, r: int) -> None:
        """Create the dropdown widgets of ONE row (mirror of the row
        object state; every change writes back via _cell_changed)."""
        row = self._rows[r]
        members = self._members_of(row.net)
        for c, (key, _label, *_rest) in enumerate(self.columns):
            if key in ("net", "status") or key in AUTO_KEYS:
                continue               # items exist for every row
            if key in NUMERIC_COLUMNS:
                spin = QDoubleSpinBox()
                spin.setRange(0.0, 1e7)
                spin.setDecimals(4 if key.endswith("_khz") else 3)
                spin.setSpecialValueText(UNSET)   # 0 shows the dash
                try:
                    spin.setValue(float(getattr(row, key) or 0))
                except (TypeError, ValueError):
                    spin.setValue(0.0)
                spin.valueChanged.connect(
                    lambda value, rr=r, kk=key:
                        self._numeric_changed(rr, kk, value))
                self.table.setCellWidget(r, c, spin)
                continue
            choices = {
                "test_point": test_point_choices(members),
            }.get(key)
            if choices is None:
                choices = {k: ch for k, _l, ch in
                           self.columns if ch}[key]
            combo = QComboBox()
            # fixed single-attribute columns (GPIO DI / DO) carry no
            # UNSET placeholder
            combo.addItems([*choices] if len(choices) == 1
                           else [UNSET, *choices])
            current = getattr(row, key)
            # M19b: the Drive level is only relevant while the row is
            # armed as DIO Write - otherwise it stays disabled + UNSET
            if key == "drive_level":
                if row.op_type != "U2355A DIO Write":
                    combo.setEnabled(False)
                    current = UNSET
            if current and current != UNSET:
                combo.setCurrentText(current)
            combo.currentTextChanged.connect(
                lambda value, rr=r, kk=key:
                    self._cell_changed(rr, kk, value))
            self.table.setCellWidget(r, c, combo)

    def _numeric_changed(self, row_index: int, key: str,
                         value: float) -> None:
        """A numeric cell changed: store the value (0 / cleared ->
        UNSET) and refresh the Status column (M19)."""
        if row_index >= len(self._rows):
            return
        row = self._rows[row_index]
        if value <= 0:
            setattr(row, key, UNSET)
        else:
            decimals = 4 if key.endswith("_khz") else 3
            setattr(row, key, f"{value:.{decimals}f}")
        self._update_status(row_index, key)

    def _cell_changed(self, row_index: int, key: str, value: str) -> None:
        """A dropdown changed: store the value + recompute Status.
        Choosing an SE Clock resource auto-fills its fixed frequency
        band (hardware mapping).  Choosing a Control-IO operation
        syncs the Drive level cell and raises ``operation_changed`` for
        the page-level DIO-write isolation preflight (M19b)."""
        if row_index >= len(self._rows):
            return
        row = self._rows[row_index]
        old = getattr(row, key, UNSET)
        setattr(row, key, value)
        if key == "se_clock_hz":
            row.band = CLOCK_BANDS.get(value, UNSET)
            keys = [k for k, _l, *_r in self.columns]
            if "band" in keys:
                band_col = keys.index("band")
                item = self.table.item(row_index, band_col)
                if item is not None:
                    item.setText(row.band)
        elif key == "op_type":
            self._sync_drive_level(row_index)
            if value != old:
                self.operation_changed.emit(row.net, old, value)
        self._update_status(row_index, key)

    def _sync_drive_level(self, row_index: int) -> None:
        """M19b: the Drive level cell is enabled (and kept) ONLY while
        the row is armed as U2355A DIO Write; otherwise it is disabled
        and reset to UNSET (High Z / Read rows carry no drive value)."""
        row = self._rows[row_index]
        keys = [k for k, _l, *_r in self.columns]
        if "drive_level" not in keys:
            return
        col = keys.index("drive_level")
        combo = self.table.cellWidget(row_index, col)
        if combo is None:
            return
        if row.op_type == "U2355A DIO Write":
            combo.setEnabled(True)
        else:
            combo.setEnabled(False)
            if str(combo.currentText()) not in ("", UNSET):
                combo.setCurrentText(UNSET)   # also clears the row value
            elif row.drive_level not in ("", UNSET):
                row.drive_level = UNSET

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

    # ------------------------------------------------------- row sorting
    def _on_header_clicked(self, col: int) -> None:
        """Header click: sort the WHOLE rows by that column, toggling
        ascending / descending on repeated clicks (the row objects are
        re-rendered via load_rows so every cell widget moves along)."""
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col, self._sort_desc = col, False
        keys = [k for k, _l, *_rest in self.columns]
        key = keys[col]

        def sort_value(row: AllocatedRow) -> str:
            if key == "net":
                return row.net
            if key == "status":
                return self.row_status(row)
            return str(getattr(row, key, ""))

        rows = list(self._rows)
        rows.sort(key=sort_value, reverse=self._sort_desc)
        header = self.table.horizontalHeader()
        header.setSortIndicator(col, Qt.SortOrder.DescendingOrder
                                if self._sort_desc
                                else Qt.SortOrder.AscendingOrder)
        self.load_rows(rows)


class ChannelAllocationPage(QWidget):
    """The embedded Channel Allocation tables (three tabs) of the
    Yaml Build page."""

    #: (level, message) Event-Log mirror (T6)
    task_log = Signal(str, str)

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
        # NOTE: the former "Auto" / "Apply to YAML" buttons are GONE
        # (user direction 2026-10-13): the Auto allocation lives on
        # the "Auto-Channel Allocation" workflow card (click -> :meth:
        # `auto_allocate`) and the persistence happens automatically
        # (card-open sync / publish sync / tab-leave hideEvent) - the
        # YAML preview's "Apply to Yaml" button owns the apply.
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
        self.tabs.addTab(self.table_gpio, "Control IO Nets")
        # M19b: arming a Control IO net as DIO Write runs the active-IO
        # isolation preflight right here in the allocation page
        self.table_gpio.operation_changed.connect(
            self._on_operation_changed)
        # cached BOM library for the isolation assessment (lazy build
        # from design_input.bom_file when not injected after a parse)
        self._isolation_library_cache: dict | None = None
        # a hidden tab has a zero-height viewport - its dropdown window
        # renders the moment the tab is shown (lazy render, 2026-10-15)
        self.tabs.currentChanged.connect(
            lambda _i: self.tabs.currentWidget()._render_window())
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

    # --------------------------------------------------- DIO-write guard
    def set_isolation_library(self, library) -> None:
        """Cache the BOM library used by the DIO-write isolation
        assessment (injected by the Parse Nets panel after a parse;
        a lazy build from ``design_input.bom_file`` fills it when the
        operator arms a Write before any parse ran)."""
        self._isolation_library_cache = dict(library or {})

    def _isolation_library(self) -> dict:
        """The BOM library for :func:`assess_net` (lazy, cached)."""
        if self._isolation_library_cache is not None:
            return self._isolation_library_cache
        bom = ""
        if self.model is not None:
            bom = str((self.model.get_params("design_input") or {})
                      .get("bom_file") or "").strip()
        cache: dict = {}
        if bom:
            try:
                from mtkgui.ict.netparse.bom import load_bom_library
                library, _report, _bom = load_bom_library(bom)
                cache = dict(library or {})
            except Exception:
                cache = {}
        self._isolation_library_cache = cache
        return cache

    def _on_operation_changed(self, net: str, old: str, new: str) -> None:
        """M19b: a Control IO row switched to U2355A DIO Write -> run
        the isolation assessment (same rules as the M7 run-time guard):

          * NOT ISOLATED (active IO found)  -> strong warning, list the
            active IO sources, Cancel reverts the row to High Z;
          * PASSIVE-ONLY                     -> review request, list all
            connections (human re-check against algorithm mistakes);
          * cannot be confirmed              -> warning, continue at the
            operator's own risk.

        Read / High Z never trigger the guard."""
        if new != "U2355A DIO Write":
            return
        members = self._net_members(net)
        library = self._isolation_library()
        try:
            isolated, drivers = assess_net(members, library)
        except Exception:
            isolated, drivers = None, []
        box = QMessageBox(self)
        if isolated is False:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("DIO Write - NOT ISOLATED")
            box.setText(
                f"Control IO '{net}' connects ACTIVE IO and is NOT "
                "isolated.")
            box.setInformativeText(
                "Driving this net may conflict / short against the "
                "active IO source(s). Active IO sources: "
                + ", ".join(str(d) for d in drivers or ["unknown"])
                + ".\n\nKeep the DIO Write only when the operator has "
                "verified the board state (e.g. MCU held in reset).")
            box.addButton("Cancel",
                          QMessageBox.ButtonRole.RejectRole)
            force = box.addButton(
                "Force-Continue", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(box.buttons()[0])
        elif isolated is True:
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("DIO Write - passive only (review)")
            box.setText(
                f"Control IO '{net}' connects only passive components "
                "- no active IO found.")
            box.setInformativeText(
                "Algorithm check only: please human-review before "
                "driving. All connections: "
                + " ".join(str(m) for m in members or ["(none)"]) + ".")
            box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(box.buttons()[0])
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("DIO Write - isolation cannot be confirmed")
            box.setText(
                f"Control IO '{net}': the isolation cannot be confirmed "
                "(components missing from the BOM / no pin info).")
            box.setInformativeText(
                "Driving an unconfirmed net is at the operator's own "
                "risk. All connections: "
                + " ".join(str(m) for m in members or ["(none)"]) + ".")
            box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(box.buttons()[0])
        box.exec()
        if isolated is not False:
            return
        clicked = box.clickedButton()
        if clicked is force:
            return
        # operator cancelled -> revert the row to High Z (not tested)
        keys = [k for k, _l, *_r in
                self.table_gpio.columns]
        op_col = keys.index("op_type")
        for r in range(self.table_gpio.table.rowCount()):
            row = self.table_gpio.rows()[r]
            if row.net != net:
                continue
            combo = self.table_gpio.table.cellWidget(r, op_col)
            if combo is not None:
                combo.setCurrentText(OP_HIGH_Z)   # re-enters _cell_changed
            else:
                row.op_type = OP_HIGH_Z
                self.table_gpio._sync_drive_level(r)
            break

    def set_edit_allowed(self, allowed: bool) -> None:
        """Permission gate (T5 matrix): operators view only.

        M19b: the Drive level cell is gated by the row's operation as
        well - it stays enabled ONLY while the operator may edit AND
        the row is armed as U2355A DIO Write (a blind enable-all would
        override the op_type linkage rendered by _render_row)."""
        self._edit_allowed = bool(allowed)
        for table in (self.table_power, self.table_clock,
                      self.table_gpio):
            keys = [k for k, _l, *_r in table.columns]
            for r in range(table.table.rowCount()):
                rows = table.rows()
                for c in range(table.table.columnCount()):
                    widget = table.table.cellWidget(r, c)
                    if widget is None:
                        continue
                    if keys[c] == "drive_level":
                        write_armed = (
                            r < len(rows)
                            and rows[r].op_type == "U2355A DIO Write")
                        widget.setEnabled(self._edit_allowed
                                          and write_armed)
                    else:
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

    # ------------------------------------------------------------ auto
    def _channel_conflicts(self) -> list[tuple[str, str, list[str]]]:
        """Fool-proofing (user direction): one instrument channel used
        by MORE THAN ONE net is a conflict.  Checked per resource pool
        - the Impedance and Voltage columns share the DAQM908A pool,
        Power rails the U2355A AI pool, SE Clock and DIO their own.
        Returns (pool, channel, [net names]) tuples."""
        conflicts: list[tuple[str, str, list[str]]] = []

        def collect(table, keys, pool):
            # per channel: the DISTINCT nets using it - one net using
            # its channel for both Impedance and Voltage is the normal
            # Auto behaviour, NOT a conflict
            usage: dict[str, list[str]] = {}
            for row in table.rows():
                for key in keys:
                    channel = getattr(row, key, UNSET)
                    if channel in ("", UNSET):
                        continue
                    if row.net not in usage.setdefault(channel, []):
                        usage[channel].append(row.net)
            for channel in sorted(usage):
                nets = usage[channel]
                if len(nets) > 1:
                    conflicts.append((pool, channel, nets))

        collect(self.table_power, ("impedance", "voltage"),
                "DAQM908A")
        collect(self.table_power, ("power_rails",), "U2355A AI")
        collect(self.table_clock, ("se_clock_hz",), "SE Clock")
        collect(self.table_gpio, ("dio_channel",), "U2355A DIO")
        return conflicts

    @staticmethod
    def _best_test_point(members: list[str]) -> str:
        """The best test point of a net (auto rule): a TP probe pin
        when the members carry one, else the first member pin."""
        members = [m for m in (members or []) if m]
        if not members:
            return UNSET
        probe = next((m for m in members
                      if m.upper().startswith("TP")), None)
        return probe or members[0]

    def auto_allocate(self) -> None:
        """Auto allocation (user direction 2026-10-13: triggered by
        the "Auto-Channel Allocation" workflow card): assign the
        Power / Clock / Control IO tables top-down - the best test
        point, then sequential channel resources.  The Impedance and
        Voltage cells share the SAME DAQM908A channel; Power rails draw
        from the U2355A AI pool; SE Clock from its pool; Control IO
        takes the top 24 nets (parse rank order) on the U2355A DIO
        pool.  Rows beyond a pool capacity stay unset (cannot be
        tested) and are adjusted manually afterwards."""
        for kind, table in (("power", self.table_power),
                            ("clock", self.table_clock),
                            ("gpio", self.table_gpio)):
            sense = iter(DAQM908A_SENSE_CHANNELS)
            rails = iter(U2355A_AI_CHANNELS)
            clocks = iter(CLOCK_CHANNELS)
            dios = iter(GPIO_DIO_CHANNELS)
            rows = table.rows()
            for row in rows:
                if row.test_point in ("", UNSET):
                    row.test_point = self._best_test_point(
                        self._net_members(row.net))
                if kind == "power":
                    # M19: R-GND / Voltage use the 80-channel DAQM908A
                    # sense pool INDEPENDENTLY of the 12-channel U2355A
                    # AI (power-rails) pool - a 55-rail board previously
                    # stopped at 12 because the rails iterator exhausted
                    try:
                        channel = next(sense)
                        row.impedance = channel
                        row.voltage = channel   # SAME channel both
                    except StopIteration:
                        row.impedance = UNSET
                        row.voltage = UNSET
                try:
                    if kind == "power":
                        row.power_rails = next(rails)
                    elif kind == "clock":
                        row.se_clock_hz = next(clocks)
                        row.band = CLOCK_BANDS.get(row.se_clock_hz,
                                                   UNSET)
                    else:
                        row.dio_channel = next(dios)
                except StopIteration:
                    # pool exhausted: this net cannot be tested
                    if kind == "power":
                        row.power_rails = UNSET
                    elif kind == "clock":
                        row.se_clock_hz = UNSET
                        row.band = UNSET
                    else:
                        row.dio_channel = UNSET
            table.load_rows(rows)
        self._update_summary()

    @staticmethod
    def _configured_ok(data: ChannelAllocationData) -> bool:
        """Capacity-aware validation: every Power / Clock row and the
        first :data:`GPIO_CHANNEL_CAPACITY` Control IO rows must be
        configured.  Later Control IO nets are EXPECTED overflow (kept
        classified, no channel - not a validation error)."""
        for kind in ("power", "clock"):
            if any(not row.is_configured(kind)
                   for row in getattr(data, kind)):
                return False
        return all(row.is_configured("gpio")
                   for row in data.gpio[:GPIO_CHANNEL_CAPACITY])

    def _update_summary(self) -> None:
        data = ChannelAllocationData.from_dict(self.collect())
        counts = {kind: len(getattr(data, kind))
                  for kind, _cols in TABLE_SPECS}
        gpio_assigned = sum(
            1 for row in data.gpio if row.dio_channel not in ("", UNSET))
        overflow = max(0, len(data.gpio) - GPIO_CHANNEL_CAPACITY)
        gpio_text = f"gpio={gpio_assigned}"
        if overflow:
            gpio_text += f" (+{overflow} over capacity)"
        rails_assigned = sum(
            1 for row in data.power
            if row.power_rails not in ("", UNSET))
        ok = self._configured_ok(data)
        text = (f"rows: power={counts['power']} "
                f"power_rails={rails_assigned}/{counts['power']} "
                f"clock={counts['clock']} {gpio_text} - "
                "validation: "
                + (STATUS_OK if ok else "NOK (incomplete rows)"))
        conflicts = self._channel_conflicts()
        if conflicts:
            detail = "; ".join(
                f"{pool} {channel} -> {', '.join(nets)}"
                for pool, channel, nets in conflicts[:5])
            more = (f" (+{len(conflicts) - 5} more)"
                    if len(conflicts) > 5 else "")
            text += f" - CONFLICT: {detail}{more}"
            self.lbl_summary.setStyleSheet("color: #b91c1c;")
        else:
            self.lbl_summary.setStyleSheet("")
        self.lbl_summary.setText(text)

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
