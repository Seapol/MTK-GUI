# -*- coding: utf-8 -*-
"""v2 node 04 Equipment Config — Qt panel (launcher + seven module dialogs).

M131: the old seven-tab strip packed six checkbox rows and a wide table
into one page and left most of the node dialog empty, so the module pages
now live behind seven large tiles.  ``Instruments`` gates the other six:
until the availability check has run the remaining tiles stay grey and
cannot be opened.

The panel still exposes ``validate()`` so the wizard can block
``[Next: 05 >]`` on the completeness gate (§9).
"""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.dialog_layout import hint
from mtkgui.gui.yamlbuild.equipment_config import (
    DEFAULT_PROMPT_OFF, DEFAULT_PROMPT_ON, FIXTURE_SIGNALS,
    FIXTURE_TYPE_ATE, INSTRUMENT_KEYS, INSTRUMENT_LABEL,
    INSTRUMENT_PARENT, RESOURCE_COUNTER, RESOURCE_OUT_OF_RANGE,
    RESOURCE_TOTALIZER, SOURCE_ADAPTER, SOURCE_PSU, EquipmentConfig,
    RailRow, capacity_line, map_clock_resource, validate)

TABS_LOCKED_TEXT = "Run an instrument check first (Instruments)"

#: key, tile title, one-line purpose, dialog width, dialog height
MODULES: tuple[tuple[str, str, str, int, int], ...] = (
    ("instruments", "Instruments",
     "Rack inventory: what is installed, how much capacity is left and "
     "whether every instrument answers.", 760, 470),
    ("power", "Power On/Off DUT",
     "Main input source, current limit, fixture relay and the two operator "
     "prompts.", 700, 560),
    ("rgnd", "R-GND & Voltage",
     "80-point two-wire R-GND, then the rail voltage window per net.", 1180, 620),
    ("clock", "Clock",
     "Single-ended clock nets with ppm tolerance and counter resource.", 1180, 600),
    ("rails", "Power Rails",
     "Up-sequence capture: sample rate, window and arm lead (record-only).",
     1180, 520),
    ("fixture", "Fixture (ATE)",
     "Probe ports and the control signals the fixture exposes.", 720, 450),
    ("periph", "Peripherals",
     "Bench peripherals the flow may use: Wi-Fi, Bluetooth, router, console.",
     700, 440),
)


_TILE_QSS = "QPushButton#moduleTile {{ min-height: {h}px; }}"
_TILE_DIM_QSS = (" #tileTitle, #tileSub, #tileBadge {{ color: #6b7280; }}")


class ModuleTile(QPushButton):
    """A large clickable card: bold title, badge, muted two-line status."""

    TILE_HEIGHT = 104

    def __init__(self, title: str, subtitle: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("moduleTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(self.TILE_HEIGHT)
        # a widget-level min-height wins over an app-level button style
        # (the legacy Light QSS pins QPushButton to 26 px + padding)
        self._restyle(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.lbl_title = QLabel(title, self)
        self.lbl_title.setObjectName("tileTitle")
        self.badge = QLabel("", self)
        self.badge.setObjectName("tileBadge")
        self.badge.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for child in (self.lbl_title, self.badge):
            child.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(self.lbl_title, 1)
        row.addWidget(self.badge, 0)
        lay.addLayout(row)

        self.lbl_sub = QLabel(subtitle, self)
        self.lbl_sub.setObjectName("tileSub")
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.lbl_sub)
        lay.addStretch(1)

    def set_status(self, badge: str, subtitle: str,
                   tone: str = "muted") -> None:
        """Badge text carries the state; the subtitle carries the numbers."""
        self.badge.setText(badge)
        self.badge.setProperty("tone", tone)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.lbl_sub.setText(subtitle)

    def _restyle(self, dim: bool) -> None:
        sheet = _TILE_QSS.format(h=self.TILE_HEIGHT)
        if dim:
            sheet += _TILE_DIM_QSS
        self.setStyleSheet(sheet)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 (Qt naming)
        super().setEnabled(enabled)
        # child labels do not inherit the disabled palette - dim them here
        self._restyle(not enabled)


class EquipmentConfigPanel(QWidget):
    """Node 04: tile launcher, Instruments gates the rest."""

    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = EquipmentConfig()
        self._dialogs: dict[str, QDialog] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.lbl_intro = QLabel(
            "Click a card to configure that module.")
        self.lbl_intro.setObjectName("muted")
        self.lbl_intro.setWordWrap(True)
        root.addWidget(self.lbl_intro)

        self.setMinimumWidth(980)   # two comfortable card columns
        self.setMinimumHeight(540)  # four card rows, no inner scrollbar
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        # tiles first: a page handler may call refresh_tiles() while the
        # pages are still being built (M131 regression)
        self.tiles: dict[str, ModuleTile] = {}
        for key, title, blurb, _w, _h in MODULES:
            tile = ModuleTile(title, blurb, self)
            tile.clicked.connect(lambda _=False, k=key: self.open_module(k))
            self.tiles[key] = tile
        self._pages: dict[str, QWidget] = {
            "instruments": self._build_instruments_page(),
            "power": self._build_power_page(),
            "rgnd": self._build_rgnd_page(),
            "clock": self._build_clock_page(),
            "rails": self._build_rails_page(),
            "fixture": self._build_fixture_page(),
            "periph": self._build_peripherals_page(),
        }
        for index, (key, _title, _blurb, _w, _h) in enumerate(MODULES):
            tile = self.tiles[key]
            tile.setMinimumWidth(640 if key == "instruments" else 320)
            # Instruments is the wide banner, the rest form a 2 x 3 grid
            if key == "instruments":
                grid.addWidget(tile, 0, 0, 1, 2)
            else:
                slot = index - 1
                grid.addWidget(tile, 1 + slot // 2, slot % 2)
        root.addLayout(grid)
        root.addStretch(1)

        self._sync_gating()
        self.refresh_tiles()

    # ------------------------------------------------------------- helpers
    def _changed(self) -> None:
        self.refresh_tiles()
        self.content_changed.emit()
        self._sync_gating()

    def _sync_gating(self) -> None:
        """Every module but Instruments unlocks after the availability check."""
        for key, tile in self.tiles.items():
            if key == "instruments":
                continue
            tile.setEnabled(self._config.check_run)
            tile.setToolTip("" if self._config.check_run else TABS_LOCKED_TEXT)

    def _badge(self, key: str, text: str, tone: str) -> None:
        tile = self.tiles.get(key)
        if tile is not None:
            tile.set_status(text, tile.lbl_sub.text(), tone)

    def refresh_tiles(self) -> None:
        """Keep each tile's badge and one-line status in step with the config."""
        cfg = self._config
        if not self.tiles:
            return
        on = sum(1 for v in cfg.instruments.values() if v)
        if cfg.check_run:
            self.tiles["instruments"].set_status(
                "CHECKED", f"{on} instruments enabled · {capacity_line(cfg.instruments)}",
                "ok")
        else:
            self.tiles["instruments"].set_status(
                "NOT CHECKED",
                f"{on} instruments enabled · availability check still pending",
                "warn")

        src = ("N5747A PSU" if cfg.source == SOURCE_PSU else "DUT adapter")
        psu = (f"{cfg.psu_voltage:g} V / {cfg.psu_current_limit:g} A"
               if cfg.source == SOURCE_PSU else "PSU not used")
        relay = ("relay on" if cfg.fixture.signals["relay"].enabled
                 else "relay off")
        self.tiles["power"].set_status(src, f"{psu} · {relay}", "muted")

        self.tiles["rgnd"].set_status(
            f"{len(cfg.power_rows)} NETS",
            "2-wire R-GND across 80 points, then the rail voltage window",
            "muted")

        self.tiles["clock"].set_status(
            f"{len(cfg.clock_rows)} CLOCKS",
            f"tolerance {self.ppm_spin.value()} ppm · gate "
            f"{self.gate_spin.value():g} s",
            "muted")

        self.tiles["rails"].set_status(
            "RECORD-ONLY",
            f"rate {cfg.rails.rate_hz} Hz · window {cfg.rails.window_ms} ms "
            f"· arm lead {cfg.rails.arm_lead_ms} ms",
            "muted")

        fixture = ("ATE" if cfg.fixture.type == FIXTURE_TYPE_ATE else "manual")
        sig_on = sum(1 for s in cfg.fixture.signals.values() if s.enabled)
        ports = f"{cfg.fixture.port1 or '-'} / {cfg.fixture.port2 or '-'}"
        self.tiles["fixture"].set_status(
            fixture, f"ports {ports} · {sig_on} control signals on", "muted")

        per = cfg.peripherals
        names = [label for label, flag in (
            ("Wi-Fi", per.wifi), ("Bluetooth", per.bt),
            ("Router", per.router), ("Console", per.dut_console)) if flag]
        self.tiles["periph"].set_status(
            f"{len(names)} ON",
            " · ".join(names) if names else "no bench peripheral selected",
            "muted")

        if not cfg.check_run:
            # a locked module says so instead of showing stale numbers
            for key in self.tiles:
                if key == "instruments":
                    continue
                self.tiles[key].set_status(
                    "LOCKED", "Run the availability check in Instruments first",
                    "muted")


    # ------------------------------------------------------------- dialogs
    def page(self, key: str) -> QWidget:
        return self._pages[key]

    def open_module(self, key: str) -> QDialog | None:
        """Open (or raise) the standalone dialog for one module."""
        if key != "instruments" and not self._config.check_run:
            return None
        dlg = self._dialogs.get(key)
        if dlg is None:
            dlg = self._make_dialog(key)
            self._dialogs[key] = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def _make_dialog(self, key: str) -> QDialog:
        spec = next(m for m in MODULES if m[0] == key)
        _key, title, blurb, width, height = spec
        dlg = QDialog(self)
        dlg.setObjectName("moduleDialog")
        dlg.setWindowTitle(f"04 · Equipment Config · {title}")
        dlg.setSizeGripEnabled(True)

        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        lbl_title = QLabel(title, dlg)
        lbl_title.setObjectName("dialogTitle")
        lay.addWidget(lbl_title)
        lay.addWidget(hint(blurb, width))

        line = QFrame(dlg)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("dialogRule")
        lay.addWidget(line)

        lay.addWidget(self.page(key), 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        btn_close = QPushButton("Close", dlg)
        btn_close.setMinimumWidth(110)
        btn_close.setMinimumHeight(32)
        btn_close.clicked.connect(dlg.accept)
        foot.addWidget(btn_close)
        lay.addLayout(foot)

        dlg.resize(width, height)
        dlg.setMinimumSize(min(width, 680), min(height, 480))
        return dlg

    # ------------------------------------------------------------- page 1
    def _build_instruments_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self._inst_boxes: dict[str, QCheckBox] = {}
        main = QGroupBox("DAQ973A mainframe", page)
        main_lay = QVBoxLayout(main)
        main_lay.setSpacing(6)
        for key, label, parent_key in (
                ("daq973a", "DAQ973A  mainframe", None),
                ("daqm908a_1", "DAQM908A #1  40 V/Ohm", "daq973a"),
                ("daqm908a_2", "DAQM908A #2  40 V/Ohm", "daq973a"),
                ("daqm907a", "DAQM907A  totalizer + 16 DIO", "daq973a")):
            box = QCheckBox(label, main)
            box.setChecked(self._config.instruments.get(key, True))
            if parent_key:
                box.setContentsMargins(26, 0, 0, 0)
            box.toggled.connect(
                lambda _=False, k=key: self._on_instrument(k))
            self._inst_boxes[key] = box
            main_lay.addWidget(box)
        lay.addWidget(main)

        other = QGroupBox("Other instruments", page)
        other_lay = QVBoxLayout(other)
        other_lay.setSpacing(6)
        for key, label in (("u2355a", "U2355A  2 counters"),
                           ("n5747a", "N5747A  PSU 60 V / 12.5 A")):
            box = QCheckBox(label, other)
            box.setChecked(self._config.instruments.get(key, True))
            box.toggled.connect(
                lambda _=False, k=key: self._on_instrument(k))
            self._inst_boxes[key] = box
            other_lay.addWidget(box)
        lay.addWidget(other)

        card = QFrame(page)
        card.setObjectName("infoCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(14, 10, 14, 10)
        lbl_cap_title = QLabel("Capacity", card)
        lbl_cap_title.setObjectName("muted")
        card_lay.addWidget(lbl_cap_title)
        self.lbl_capacity = QLabel(capacity_line(self._config.instruments), card)
        self.lbl_capacity.setWordWrap(True)
        card_lay.addWidget(self.lbl_capacity)
        lay.addWidget(card)

        lay.addStretch(1)
        self.btn_check = QPushButton("Check availability", page)
        self.btn_check.setObjectName("primary")
        self.btn_check.setMinimumHeight(44)
        self.btn_check.clicked.connect(self._on_check)
        lay.addWidget(self.btn_check)
        return page

    def _on_instrument(self, key: str) -> None:
        self._config.instruments[key] = self._inst_boxes[key].isChecked()
        # cascade: mainframe off -> children off and grey out
        if key == "daq973a" and not self._config.instruments["daq973a"]:
            for child in ("daqm908a_1", "daqm908a_2", "daqm907a"):
                self._inst_boxes[child].setChecked(False)
                self._config.instruments[child] = False
        # adapter forces the PSU off
        if (key == "n5747a" and self._config.source == SOURCE_ADAPTER
                and self._config.instruments["n5747a"]):
            self._inst_boxes["n5747a"].setChecked(False)
            self._config.instruments["n5747a"] = False
        self.lbl_capacity.setText(capacity_line(self._config.instruments))
        self._changed()

    def _on_check(self) -> None:
        self._config.check_run = True
        self._changed()

    # ------------------------------------------------------------- page 2
    def _build_power_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        src = QGroupBox("Main input source", page)
        src_lay = QVBoxLayout(src)
        src_lay.setSpacing(6)
        self.src_psu = QRadioButton("PSU N5747A (ICT power)", src)
        self.src_adapter = QRadioButton("DUT power adapter", src)
        self.src_psu.toggled.connect(self._on_source)
        src_lay.addWidget(self.src_psu)
        src_lay.addWidget(self.src_adapter)
        group = QButtonGroup(self)
        group.addButton(self.src_psu)
        group.addButton(self.src_adapter)
        # mirror the loaded config right away, otherwise the page opens
        # with both radios empty while the tile already says "N5747A PSU"
        for radio, is_on in ((self.src_psu, self._config.source == SOURCE_PSU),
                             (self.src_adapter,
                              self._config.source == SOURCE_ADAPTER)):
            blocker = QSignalBlocker(radio)
            radio.setChecked(is_on)
            del blocker
        lay.addWidget(src)

        psu = QGroupBox("PSU limits", page)
        psu_form = QFormLayout(psu)
        psu_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        psu_form.setHorizontalSpacing(14)
        psu_form.setVerticalSpacing(8)
        self.psu_voltage = QDoubleSpinBox(psu)
        self.psu_voltage.setRange(0.0, 60.0)
        self.psu_voltage.setSuffix(" V")
        self.psu_voltage.setMaximumWidth(170)
        self.psu_voltage.setValue(self._config.psu_voltage)
        self.psu_voltage.valueChanged.connect(self._on_psu)
        psu_form.addRow("Main input voltage", self.psu_voltage)
        self.psu_current = QDoubleSpinBox(psu)
        self.psu_current.setRange(0.0, 12.5)
        self.psu_current.setSuffix(" A")
        self.psu_current.setMaximumWidth(170)
        self.psu_current.setValue(self._config.psu_current_limit)
        self.psu_current.valueChanged.connect(self._on_psu)
        psu_form.addRow("Current limit", self.psu_current)
        lay.addWidget(psu)

        relay = QGroupBox("Fixture relay", page)
        relay_lay = QVBoxLayout(relay)
        self.relay_box = QCheckBox("Fixture Relay Control", relay)
        blocker = QSignalBlocker(self.relay_box)
        self.relay_box.setChecked(
            self._config.fixture.signals["relay"].enabled)
        del blocker
        self.relay_box.toggled.connect(self._on_relay)
        relay_lay.addWidget(self.relay_box)
        lay.addWidget(relay)

        prompts = QGroupBox("Operator prompts", page)
        prom_form = QFormLayout(prompts)
        prom_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        prom_form.setHorizontalSpacing(14)
        prom_form.setVerticalSpacing(8)
        self.prompt_on = QLineEdit(self._config.prompt_on, prompts)
        self.prompt_on.setMaximumWidth(420)
        self.prompt_on.textChanged.connect(self._on_prompt)
        prom_form.addRow("Power-on prompt", self.prompt_on)
        self.prompt_off = QLineEdit(self._config.prompt_off, prompts)
        self.prompt_off.setMaximumWidth(420)
        self.prompt_off.textChanged.connect(self._on_prompt)
        prom_form.addRow("Power-off prompt", self.prompt_off)
        lay.addWidget(prompts)

        lay.addWidget(hint(
            "rails are derived by the DUT (LDO / DCDC / PMIC), not set here",
            660))
        lay.addStretch(1)
        return page

    def _on_source(self) -> None:
        self._config.source = (
            SOURCE_PSU if self.src_psu.isChecked() else SOURCE_ADAPTER)
        if self._config.source == SOURCE_ADAPTER:
            self._inst_boxes["n5747a"].setChecked(False)
            self._config.instruments["n5747a"] = False
        self._changed()

    def _on_relay(self) -> None:
        self._config.fixture.signals["relay"].used = (
            self.relay_box.isChecked())
        self._config.fixture.signals["relay"].enabled = (
            self.relay_box.isChecked())
        self._changed()

    def _on_psu(self) -> None:
        self._config.psu_voltage = self.psu_voltage.value()
        self._config.psu_current_limit = self.psu_current.value()
        self._changed()

    def _on_prompt(self) -> None:
        self._config.prompt_on = self.prompt_on.text()
        self._config.prompt_off = self.prompt_off.text()
        self._changed()

    # ------------------------------------------------------------- page 3
    def _build_rgnd_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.lbl_rgnd = QLabel("Source: no power nets", page)
        self.lbl_rgnd.setObjectName("muted")
        lay.addWidget(self.lbl_rgnd)
        columns = ("Net", "Test Point", "R-GND min (ohm)", "Nominal (V)",
                   "Min (V)", "Max (V)", "Channel", "Not tested")
        self.rgnd_table = self._table(page, columns)
        lay.addWidget(self.rgnd_table, 1)
        lay.addWidget(hint(
            "step 1 measures two-wire R-GND on all 80 points; step 2 applies "
            "the rail and judges the voltage window (±0.1 %)", 1140))
        return page

    def _table(self, parent: QWidget, columns: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(columns), parent)
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        table.setMinimumHeight(260)
        return table

    # ------------------------------------------------------------- page 4
    def _build_clock_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.lbl_clock = QLabel("Source: no clock nets", page)
        self.lbl_clock.setObjectName("muted")
        lay.addWidget(self.lbl_clock)

        params = QGridLayout()
        params.setHorizontalSpacing(12)
        params.setVerticalSpacing(6)
        params.addWidget(QLabel("Tolerance (ppm)", page), 0, 0)
        self.ppm_spin = QSpinBox(page)
        self.ppm_spin.setRange(1, 100_000)
        self.ppm_spin.setValue(50)
        self.ppm_spin.valueChanged.connect(self._on_ppm)
        params.addWidget(self.ppm_spin, 0, 1)
        params.addWidget(QLabel("Gate time (totalizer, s)", page), 0, 2)
        self.gate_spin = QDoubleSpinBox(page)
        self.gate_spin.setRange(0.1, 10.0)
        self.gate_spin.setValue(1.0)
        self.gate_spin.valueChanged.connect(self._on_gate)
        params.addWidget(self.gate_spin, 0, 3)
        params.setColumnStretch(4, 1)
        lay.addLayout(params)

        columns = ("Net", "Test Point", "Nominal (kHz)", "Min (kHz)",
                   "Max (kHz)", "Resource", "Not tested")
        self.clock_table = self._table(page, columns)
        lay.addWidget(self.clock_table, 1)
        lay.addWidget(hint(
            "resources map by nominal frequency: U2355A counter below 6 MHz, "
            "DAQM907A totalizer below 100 kHz", 1140))
        return page

    def _on_ppm(self) -> None:
        self._refresh_clock_table()
        self.refresh_tiles()

    def _on_gate(self) -> None:
        self._refresh_clock_table()
        self.refresh_tiles()

    # ------------------------------------------------------------- page 5
    def _build_rails_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        params = QGridLayout()
        params.setHorizontalSpacing(12)
        params.setVerticalSpacing(6)
        params.addWidget(QLabel("Sample rate (Hz)", page), 0, 0)
        self.rate_spin = QSpinBox(page)
        self.rate_spin.setRange(1000, 250_000)
        self.rate_spin.setValue(self._config.rails.rate_hz)
        self.rate_spin.valueChanged.connect(self._on_rails_param)
        params.addWidget(self.rate_spin, 0, 1)
        params.addWidget(QLabel("Window (ms)", page), 0, 2)
        self.window_spin = QSpinBox(page)
        self.window_spin.setRange(100, 10_000)
        self.window_spin.setValue(self._config.rails.window_ms)
        self.window_spin.valueChanged.connect(self._on_rails_param)
        params.addWidget(self.window_spin, 0, 3)
        params.addWidget(QLabel("Arm lead (ms)", page), 0, 4)
        self.arm_spin = QSpinBox(page)
        self.arm_spin.setRange(0, 10_000)
        self.arm_spin.setValue(self._config.rails.arm_lead_ms)
        self.arm_spin.valueChanged.connect(self._on_rails_param)
        params.addWidget(self.arm_spin, 0, 5)
        params.setColumnStretch(6, 1)
        lay.addLayout(params)

        columns = ("Rail", "Nominal (V)", "Min (V)", "Max (V)",
                   "AI channel (U2355A)", "Order", "Not tested")
        self.rails_table = self._table(page, columns)
        lay.addWidget(self.rails_table, 1)
        lay.addWidget(hint(
            "record-only: samples are written to the CSV log and plotted on "
            "the Test Work Flow page; MTK judges nothing", 1140))
        return page

    def _on_rails_param(self) -> None:
        self._config.rails.rate_hz = self.rate_spin.value()
        self._config.rails.window_ms = self.window_spin.value()
        self._config.rails.arm_lead_ms = self.arm_spin.value()
        self._changed()

    # ------------------------------------------------------------- page 6
    def _build_fixture_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        ports = QGroupBox("Probe ports", page)
        port_form = QFormLayout(ports)
        port_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        port_form.setHorizontalSpacing(14)
        port_form.setVerticalSpacing(8)
        self.port1 = QLineEdit(self._config.fixture.port1, ports)
        self.port1.setMaximumWidth(220)
        self.port1.textChanged.connect(self._on_ports)
        port_form.addRow("Port 1", self.port1)
        self.port2 = QLineEdit(self._config.fixture.port2, ports)
        self.port2.setMaximumWidth(220)
        self.port2.textChanged.connect(self._on_ports)
        port_form.addRow("Port 2", self.port2)
        lay.addWidget(ports)

        signals = QGroupBox("Control signals", page)
        sig_grid = QGridLayout(signals)
        sig_grid.setHorizontalSpacing(24)
        sig_grid.setVerticalSpacing(8)
        self.signal_boxes: dict[str, QCheckBox] = {}
        for index, sig in enumerate(FIXTURE_SIGNALS):
            box = QCheckBox(sig.label, signals)
            box.setChecked(sig.enabled)
            box.toggled.connect(
                lambda _=False, k=sig.key: self._on_signal(k))
            self.signal_boxes[sig.key] = box
            sig_grid.addWidget(box, index // 2, index % 2)
        lay.addWidget(signals)
        lay.addStretch(1)
        return page

    def _on_ports(self) -> None:
        self._config.fixture.port1 = self.port1.text()
        self._config.fixture.port2 = self.port2.text()
        self._changed()

    def _on_signal(self, key: str) -> None:
        self._config.fixture.signals[key].enabled = (
            self.signal_boxes[key].isChecked())
        self._changed()

    # ------------------------------------------------------------- page 7
    def _build_peripherals_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        found = QGroupBox("Benched peripherals", page)
        grid = QGridLayout(found)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.periph_boxes: dict[str, QCheckBox] = {}
        for index, (key, label) in enumerate((("wifi", "Wi-Fi"),
                                             ("bt", "Bluetooth"),
                                             ("router", "Router"),
                                             ("dut_console", "DUT console"))):
            box = QCheckBox(label, found)
            box.setChecked(bool(getattr(self._config.peripherals, key, False)))
            box.toggled.connect(
                lambda _=False, k=key: self._on_peripheral(k))
            self.periph_boxes[key] = box
            grid.addWidget(box, index // 2, index % 2)
        lay.addWidget(found)

        lay.addWidget(hint(
            "plug-and-play - no configuration required, always allowed in "
            "05/06: T1 media converter, display, microphone, headset, SD "
            "card, USB stick, RJ45 network cable, SFP module, and the like",
            660))
        lay.addStretch(1)
        return page

    def _on_peripheral(self, key: str) -> None:
        setattr(self._config.peripherals, key,
                self.periph_boxes[key].isChecked())
        self._changed()

    # ------------------------------------------------------------- load
    def set_power_nets(self, nets: list[dict]) -> None:
        """Populate the R-GND table from node 02's parsed power nets."""
        self._config.power_rows = []
        for i, net in enumerate(nets, start=1):
            from mtkgui.gui.yamlbuild.equipment_config import PowerRow
            self._config.power_rows.append(PowerRow(
                net=net.get("name", ""), tp=net.get("test_point", ""),
                channel=f"daqm908a_{'1' if i <= 40 else '2'}:"
                        f"{((i - 1) % 40) + 1}"))
        self._refresh_rgnd_table()

    def set_clock_nets(self, nets: list[dict]) -> None:
        """Populate the Clock table from node 02's parsed clock nets."""
        from mtkgui.gui.yamlbuild.equipment_config import ClockRow
        self._config.clock_rows = []
        for net in nets:
            self._config.clock_rows.append(ClockRow(
                net=net.get("name", ""), tp=net.get("test_point", ""),
                nominal_hz=net.get("nominal_hz", 0.0)))
        self._refresh_clock_table()

    def _refresh_rgnd_table(self) -> None:
        rows = self._config.power_rows
        self.lbl_rgnd.setText(
            f"Source: {len(rows)} power nets from 02")
        self.rgnd_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = (r.net, r.tp, str(r.r_gnd_min_ohm),
                    f"{r.nominal_v:g}", f"{r.min_v:g}", f"{r.max_v:g}",
                    r.channel or "", str(r.not_tested))
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.rgnd_table.setItem(i, col, item)
        self.refresh_tiles()

    def _refresh_clock_table(self) -> None:
        from mtkgui.gui.yamlbuild.equipment_config import (
            clock_limits_hz)
        rows = self._config.clock_rows
        self.lbl_clock.setText(
            f"Source: {len(rows)} single-ended clock nets from 02")
        ppm = self.ppm_spin.value()
        self.clock_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            r.ppm = ppm
            lo, hi = clock_limits_hz(r.nominal_hz, ppm) if r.nominal_hz \
                else (0.0, 0.0)
            if r.resource == "":
                r.resource = map_clock_resource(r.nominal_hz)
            vals = (r.net, r.tp, f"{r.nominal_hz / 1000:g}",
                    f"{lo / 1000:g}", f"{hi / 1000:g}",
                    r.resource or "", str(r.not_tested))
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.clock_table.setItem(i, col, item)

    # ------------------------------------------------------------- model io
    def set_values(self, config: EquipmentConfig) -> None:
        self._config = config
        for key, box in self._inst_boxes.items():
            box.setChecked(config.instruments.get(key, True))
        self.src_psu.setChecked(config.source == SOURCE_PSU)
        self.src_adapter.setChecked(config.source == SOURCE_ADAPTER)
        self.relay_box.setChecked(config.fixture.signals["relay"].enabled)
        self.psu_voltage.setValue(config.psu_voltage)
        self.psu_current.setValue(config.psu_current_limit)
        self.prompt_on.setText(config.prompt_on)
        self.prompt_off.setText(config.prompt_off)
        self.port1.setText(config.fixture.port1)
        self.port2.setText(config.fixture.port2)
        for sig in FIXTURE_SIGNALS:
            self.signal_boxes[sig.key].setChecked(
                config.fixture.signals[sig.key].enabled)
        self.periph_boxes["wifi"].setChecked(config.peripherals.wifi)
        self.periph_boxes["bt"].setChecked(config.peripherals.bt)
        self.periph_boxes["router"].setChecked(config.peripherals.router)
        self.periph_boxes["dut_console"].setChecked(
            config.peripherals.dut_console)
        self.lbl_capacity.setText(capacity_line(config.instruments))
        self._refresh_rgnd_table()
        self._refresh_clock_table()
        self._sync_gating()
        self.refresh_tiles()

    def values(self) -> EquipmentConfig:
        return self._config

    def validate(self) -> tuple[bool, str]:
        ok, item = validate(self._config)
        if not ok:
            return False, f"Not complete: {item}"
        return True, ""
