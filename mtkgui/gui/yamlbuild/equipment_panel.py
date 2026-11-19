# -*- coding: utf-8 -*-
"""v2 node 04 Equipment Config — Qt panel (seven tabs).

Qt skin over :mod:`mtkgui.gui.yamlbuild.equipment_config`.  The
``Instruments`` tab gates the other six; the panel exposes
``validate()`` so the wizard can block ``[Next: 05 >]`` on the
completeness gate (§9).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.equipment_config import (
    DEFAULT_PROMPT_OFF, DEFAULT_PROMPT_ON, FIXTURE_SIGNALS,
    FIXTURE_TYPE_ATE, INSTRUMENT_KEYS, INSTRUMENT_LABEL,
    INSTRUMENT_PARENT, RESOURCE_COUNTER, RESOURCE_OUT_OF_RANGE,
    RESOURCE_TOTALIZER, SOURCE_ADAPTER, SOURCE_PSU, EquipmentConfig,
    RailRow, capacity_line, map_clock_resource, validate)

TABS_LOCKED_TEXT = "Run an instrument check first (Instruments)"


class EquipmentConfigPanel(QWidget):
    """Node 04: seven tabs, Instruments gates the rest."""

    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = EquipmentConfig()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self._build_instruments_tab()
        self._build_power_tab()
        self._build_rgnd_tab()
        self._build_clock_tab()
        self._build_rails_tab()
        self._build_fixture_tab()
        self._build_peripherals_tab()
        self._sync_gating()

    # ------------------------------------------------------------- helpers
    def _changed(self) -> None:
        self.content_changed.emit()
        self._sync_gating()

    def _sync_gating(self) -> None:
        """Tabs 2-7 unlock only after an instrument check has run."""
        unlocked = self._config.check_run
        for index in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(index, unlocked)

    # ------------------------------------------------------------- tab 1
    def _build_instruments_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self._inst_boxes: dict[str, QCheckBox] = {}
        form = QFormLayout()
        for key, label, _parent in (
                ("daq973a", "DAQ973A  mainframe", None),
                ("daqm908a_1", "DAQM908A #1  40 V/Ohm", "daq973a"),
                ("daqm908a_2", "DAQM908A #2  40 V/Ohm", "daq973a"),
                ("daqm907a", "DAQM907A  totalizer + 16 DIO", "daq973a"),
                ("u2355a", "U2355A  2 counters", None),
                ("n5747a", "N5747A  PSU 60 V / 12.5 A", None)):
            box = QCheckBox(label)
            box.setChecked(self._config.instruments.get(key, True))
            box.toggled.connect(
                lambda _=False, k=key: self._on_instrument(k))
            self._inst_boxes[key] = box
            form.addRow(box)
        lay.addLayout(form)

        self.lbl_capacity = QLabel(capacity_line(self._config.instruments))
        self.lbl_capacity.setObjectName("muted")
        lay.addWidget(self.lbl_capacity)

        self.btn_check = QPushButton("Check availability")
        self.btn_check.clicked.connect(self._on_check)
        lay.addWidget(self.btn_check)
        lay.addStretch(1)
        self.tabs.addTab(tab, "Instruments")

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

    # ------------------------------------------------------------- tab 2
    def _build_power_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.src_psu = QRadioButton("Power source: PSU N5747A")
        self.src_adapter = QRadioButton("Power source: DUT power adapter")
        self.src_psu.toggled.connect(self._on_source)
        group = QButtonGroup(self)
        group.addButton(self.src_psu)
        group.addButton(self.src_adapter)
        lay.addWidget(self.src_psu)
        lay.addWidget(self.src_adapter)

        self.relay_box = QCheckBox("Fixture Relay Control")
        self.relay_box.toggled.connect(self._on_relay)
        lay.addWidget(self.relay_box)

        form = QFormLayout()
        self.psu_voltage = QDoubleSpinBox()
        self.psu_voltage.setRange(0.0, 60.0)
        self.psu_voltage.setValue(self._config.psu_voltage)
        self.psu_voltage.valueChanged.connect(self._on_psu)
        form.addRow("Main input voltage (V)", self.psu_voltage)

        self.psu_current = QDoubleSpinBox()
        self.psu_current.setRange(0.0, 12.5)
        self.psu_current.setValue(self._config.psu_current_limit)
        self.psu_current.valueChanged.connect(self._on_psu)
        form.addRow("Current limit (A)", self.psu_current)

        self.prompt_on = QLineEdit(self._config.prompt_on)
        self.prompt_on.textChanged.connect(self._on_prompt)
        form.addRow("Power-on prompt", self.prompt_on)

        self.prompt_off = QLineEdit(self._config.prompt_off)
        self.prompt_off.textChanged.connect(self._on_prompt)
        form.addRow("Power-off prompt", self.prompt_off)
        lay.addLayout(form)

        note = QLabel("rails are derived by the DUT (LDO / DCDC / PMIC), "
                      "not set here")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        self.tabs.addTab(tab, "Power On/Off DUT")

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

    # ------------------------------------------------------------- tab 3
    def _build_rgnd_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.lbl_rgnd = QLabel("Source: no power nets")
        self.lbl_rgnd.setObjectName("muted")
        lay.addWidget(self.lbl_rgnd)
        columns = ("Net", "Test Point", "R-GND min (ohm)", "Nominal (V)",
                   "Min (V)", "Max (V)", "Channel", "Not tested")
        self.rgnd_table = QTableWidget(0, len(columns))
        self.rgnd_table.setHorizontalHeaderLabels(columns)
        self.rgnd_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rgnd_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.rgnd_table)
        self.tabs.addTab(tab, "R-GND & Voltage")

    # ------------------------------------------------------------- tab 4
    def _build_clock_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.lbl_clock = QLabel("Source: no clock nets")
        self.lbl_clock.setObjectName("muted")
        lay.addWidget(self.lbl_clock)
        form = QFormLayout()
        self.ppm_spin = QSpinBox()
        self.ppm_spin.setRange(1, 100_000)
        self.ppm_spin.setValue(50)
        self.ppm_spin.valueChanged.connect(self._on_ppm)
        form.addRow("Tolerance (ppm)", self.ppm_spin)
        self.gate_spin = QDoubleSpinBox()
        self.gate_spin.setRange(0.1, 10.0)
        self.gate_spin.setValue(1.0)
        self.gate_spin.valueChanged.connect(self._on_gate)
        form.addRow("Gate time (totalizer)", self.gate_spin)
        lay.addLayout(form)
        columns = ("Net", "Test Point", "Nominal (kHz)", "Min (kHz)",
                   "Max (kHz)", "Resource", "Not tested")
        self.clock_table = QTableWidget(0, len(columns))
        self.clock_table.setHorizontalHeaderLabels(columns)
        self.clock_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.clock_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.clock_table)
        self.tabs.addTab(tab, "Clock")

    def _on_ppm(self) -> None:
        self._refresh_clock_table()

    def _on_gate(self) -> None:
        self._refresh_clock_table()

    # ------------------------------------------------------------- tab 5
    def _build_rails_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        form = QFormLayout()
        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(1000, 250_000)
        self.rate_spin.setValue(self._config.rails.rate_hz)
        self.rate_spin.valueChanged.connect(self._on_rails_param)
        form.addRow("rate_hz", self.rate_spin)
        self.window_spin = QSpinBox()
        self.window_spin.setRange(100, 10_000)
        self.window_spin.setValue(self._config.rails.window_ms)
        self.window_spin.valueChanged.connect(self._on_rails_param)
        form.addRow("window_ms", self.window_spin)
        self.arm_spin = QSpinBox()
        self.arm_spin.setRange(0, 10_000)
        self.arm_spin.setValue(self._config.rails.arm_lead_ms)
        self.arm_spin.valueChanged.connect(self._on_rails_param)
        form.addRow("arm_lead_ms", self.arm_spin)
        lay.addLayout(form)

        columns = ("Rail", "Nominal (V)", "Min (V)", "Max (V)",
                   "AI channel (U2355A)", "Order", "Not tested")
        self.rails_table = QTableWidget(0, len(columns))
        self.rails_table.setHorizontalHeaderLabels(columns)
        self.rails_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rails_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.rails_table)

        note = QLabel("record-only: samples are recorded and plotted; "
                      "MTK judges nothing")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.tabs.addTab(tab, "Power Rails")

    def _on_rails_param(self) -> None:
        self._config.rails.rate_hz = self.rate_spin.value()
        self._config.rails.window_ms = self.window_spin.value()
        self._config.rails.arm_lead_ms = self.arm_spin.value()
        self._changed()

    # ------------------------------------------------------------- tab 6
    def _build_fixture_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        form = QFormLayout()
        self.port1 = QLineEdit(self._config.fixture.port1)
        self.port1.textChanged.connect(self._on_ports)
        form.addRow("Port 1", self.port1)
        self.port2 = QLineEdit(self._config.fixture.port2)
        self.port2.textChanged.connect(self._on_ports)
        form.addRow("Port 2", self.port2)
        lay.addLayout(form)

        self.signal_boxes: dict[str, QCheckBox] = {}
        for sig in FIXTURE_SIGNALS:
            box = QCheckBox(sig.label)
            box.setChecked(sig.enabled)
            box.toggled.connect(
                lambda _=False, k=sig.key: self._on_signal(k))
            self.signal_boxes[sig.key] = box
            lay.addWidget(box)
        lay.addStretch(1)
        self.tabs.addTab(tab, "Fixture (ATE)")

    def _on_ports(self) -> None:
        self._config.fixture.port1 = self.port1.text()
        self._config.fixture.port2 = self.port2.text()
        self._changed()

    def _on_signal(self, key: str) -> None:
        self._config.fixture.signals[key].enabled = (
            self.signal_boxes[key].isChecked())
        self._changed()

    # ------------------------------------------------------------- tab 7
    def _build_peripherals_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.periph_boxes: dict[str, QCheckBox] = {}
        for key, label in (("wifi", "Wi-Fi"), ("bt", "Bluetooth"),
                           ("router", "Router"),
                           ("dut_console", "DUT console")):
            box = QCheckBox(label)
            box.toggled.connect(
                lambda _=False, k=key: self._on_peripheral(k))
            self.periph_boxes[key] = box
            lay.addWidget(box)
        foot = QLabel(
            "Plug-and-play - no configuration required, always allowed in "
            "05/06: T1 media converter, display, microphone, headset, SD "
            "card, USB stick, RJ45 network cable, SFP module, and the like")
        foot.setObjectName("muted")
        foot.setWordWrap(True)
        lay.addWidget(foot)
        lay.addStretch(1)
        self.tabs.addTab(tab, "Peripherals")

    def _on_peripheral(self, key: str) -> None:
        setattr(self._config.peripherals, key,
                self.periph_boxes[key].isChecked())
        self._changed()

    # ------------------------------------------------------------- load
    def set_power_nets(self, nets: list[dict]) -> None:
        """Populate tab 3 from node 02's parsed power nets."""
        self._config.power_rows = []
        for i, net in enumerate(nets, start=1):
            from mtkgui.gui.yamlbuild.equipment_config import PowerRow
            self._config.power_rows.append(PowerRow(
                net=net.get("name", ""), tp=net.get("test_point", ""),
                channel=f"daqm908a_{'1' if i <= 40 else '2'}:"
                        f"{((i - 1) % 40) + 1}"))
        self._refresh_rgnd_table()

    def set_clock_nets(self, nets: list[dict]) -> None:
        """Populate tab 4 from node 02's parsed clock nets."""
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

    def values(self) -> EquipmentConfig:
        return self._config

    def validate(self) -> tuple[bool, str]:
        ok, item = validate(self._config)
        if not ok:
            return False, f"Not complete: {item}"
        return True, ""
