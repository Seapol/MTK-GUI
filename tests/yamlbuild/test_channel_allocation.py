# -*- coding: utf-8 -*-
"""P3-B2 T10: Channel Allocation tests.

Three dedicated dropdown-only tables (Power / Clock / GPIO), auto
Status (OK / NOK, read-only), merge from the T8 parse result as the
single data source, YAML/state persistence, empty & legacy compat."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
)

from mtkgui.gui.yamlbuild.channel_allocation import (  # noqa: E402
    AllocatedRow,
    ChannelAllocationData,
    ChannelAllocationPage,
    UNSET,
    merge_rows,
    rows_from_testable,
)

TESTABLE = {
    "3V3": {"category": "Power", "members": ["U1.5", "U2.VOUT"]},
    "1V8_CORE": {"category": "Power", "members": ["U1.2"]},
    "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
    "GPIO_LED1": {"category": "GPIO", "members": ["U1.20"]},
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    model = YamlBuildModelForTest()
    w = ChannelAllocationPage()
    w.set_model(model)
    yield w
    w.deleteLater()


class YamlBuildModelForTest:
    """Minimal model stub: imported testable nets + allocation store."""

    def __init__(self):
        self.imported = {"net": {"file": "", "raw": ""},
                         "testable_nets": dict(TESTABLE)}
        self.channel_allocation = {}

    def set_channel_allocation(self, data):
        self.channel_allocation = data


# ------------------------------------------------------ headless rules
def test_rows_from_testable_categories():
    """The parse result is the single data source: one row per
    testable net, ordered per category."""
    power = rows_from_testable(TESTABLE, "power")
    clock = rows_from_testable(TESTABLE, "clock")
    gpio = rows_from_testable(TESTABLE, "gpio")
    assert [r.net for r in power] == ["3V3", "1V8_CORE"]
    assert [r.net for r in clock] == ["CLK_24M"]
    assert [r.net for r in gpio] == ["GPIO_LED1"]


def test_row_auto_validation_ok_nok():
    """A row is OK only when every required cell is configured (the
    Power row needs NO instrument / channel / status anymore)."""
    row = AllocatedRow(net="3V3")
    assert not row.is_configured("power")           # nothing set
    row.test_point = "U1.5"
    assert not row.is_configured("power")           # pools missing
    row.impedance = "DAQM908A #1 CH101"
    row.power_rails = "U2355A AI01"
    row.voltage = "DAQM908A #2 CH201"
    assert row.is_configured("power") is True

    clock = AllocatedRow(net="CLK_24M", test_point="U1.10",
                         se_clock_hz="DAQM907A TOT",
                         band="0 ~ 100 kHz")
    assert clock.is_configured("clock") is True
    assert not AllocatedRow(
        net="CLK_24M", test_point="U1.10",
        se_clock_hz="DAQM907A TOT").is_configured("clock")

    gpio = AllocatedRow(net="GPIO_LED1", test_point="U1.20",
                        dio_channel="DAQM907A DIO01")
    # the DIO channel is the only GPIO attribute needed anymore
    assert gpio.is_configured("gpio") is True
    assert not AllocatedRow(
        net="GPIO_LED1", test_point="U1.20").is_configured("gpio")


def test_power_columns_drop_instrument_channel_status():
    """Power tab: no Instrument / Channel / Status columns; the
    Impedance / Voltage pools are the DAQM908A sense channels and the
    Power rails pool the 12 offered U2355A AI channels."""
    from mtkgui.gui.yamlbuild.channel_allocation import POWER_COLUMNS
    keys = [k for k, _l, _c in POWER_COLUMNS]
    assert keys == ["net", "test_point", "impedance",
                    "power_rails", "voltage"]
    from mtkgui.gui.yamlbuild.power_alloc import (
        DAQM908A_SENSE_CHANNELS,
        U2355A_AI_CHANNELS,
    )
    assert DAQM908A_SENSE_CHANNELS[0] == "DAQM908A #1 CH101"
    assert DAQM908A_SENSE_CHANNELS[39] == "DAQM908A #1 CH140"
    assert DAQM908A_SENSE_CHANNELS[40] == "DAQM908A #2 CH201"
    assert DAQM908A_SENSE_CHANNELS[-1] == "DAQM908A #2 CH240"
    assert len(DAQM908A_SENSE_CHANNELS) == 80
    assert len(U2355A_AI_CHANNELS) == 12            # balanced sampling
    assert U2355A_AI_CHANNELS[0] == "U2355A AI01"
    assert U2355A_AI_CHANNELS[-1] == "U2355A AI12"


def test_merge_rows_keeps_config_and_syncs_net_set():
    """Merge keeps saved configs, adds new nets, drops removed ones."""
    old = AllocatedRow(net="3V3", test_point="U2.VOUT",
                       instrument="DAQ973A", channel="CH05",
                       impedance="Yes", power_rails="Yes",
                       voltage="Yes")
    nets = rows_from_testable(TESTABLE, "power")
    merged = merge_rows([old], nets)
    assert [r.net for r in merged] == ["3V3", "1V8_CORE"]
    assert merged[0].channel == "CH05"              # config kept
    assert merged[1].channel == UNSET               # new: unconfigured


def test_persistence_round_trip():
    data = ChannelAllocationData()
    data.power = [AllocatedRow(net="3V3", test_point="U1.5",
                               instrument="DAQ973A", channel="CH01",
                               impedance="Yes", power_rails="Yes",
                               voltage="No"),
                  AllocatedRow(net="1V8_CORE")]     # unconfigured row
    data.gpio = [AllocatedRow(net="GPIO_LED1", test_point="U1.20",
                              instrument="DAQ973A", channel="CH02")]
    restored = ChannelAllocationData.from_dict(data.to_dict())
    assert restored.power[0].channel == "CH01"
    assert restored.power[0].voltage == "No"
    assert restored.gpio[0].digital_input == "HighZ"
    assert restored.gpio[0].digital_output == "No Output"
    assert restored.all_ok() is False               # 1V8_CORE is NOK


# ----------------------------------------------------------- GUI tables
def test_tables_populated_from_parse_result(page):
    """Tab refresh mirrors the parse result into the three tables."""
    assert page.table_power.table.rowCount() == 2
    assert page.table_clock.table.rowCount() == 1
    assert page.table_gpio.table.rowCount() == 1
    assert page.table_power.table.item(0, 0).text() == "3V3"


def test_config_cells_are_dropdown_only(page):
    """Every configurable cell is a QComboBox (no free text); the
    Power table has no Status column (Net stays read-only)."""
    table = page.table_power.table
    for r in range(table.rowCount()):
        for c in range(1, table.columnCount()):
            widget = table.cellWidget(r, c)
            assert isinstance(widget, QComboBox), (r, c)
    assert table.cellWidget(0, 0) is None           # net read-only
    assert table.columnCount() == 5                 # no status column


def test_no_status_instrument_channel_columns(page):
    """No table carries Instrument / Channel / Status / Digital IO
    columns anymore - the tabs pick real resource channels only."""
    banned = {"Status", "Instrument", "Channel", "Digital Input",
              "Digital Output"}
    for name in ("table_power", "table_clock", "table_gpio"):
        table = getattr(page, name).table
        keys = [table.horizontalHeaderItem(c).text()
                for c in range(table.columnCount())]
        assert not (banned & set(keys)), (name, keys)


def test_gpio_dio_pool(page):
    """The GPIO DIO Channel combo offers exactly the 16 DAQM907A DIO
    resources - the U2355A DIO is NOT offered (fixture-reserved)."""
    table = page.table_gpio.table
    assert table.columnCount() == 3
    combo = table.cellWidget(0, 2)
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == [UNSET, *(f"DAQM907A DIO{n:02d}"
                              for n in range(1, 17))]
    assert not any("U2355A" in t for t in items)


def test_clock_resource_and_band_mapping(page):
    """SE Clock Hz offers exactly the three capture resources; the
    Frequency band is read-only and hardware-derived: DAQM907A TOT
    0 ~ 100 kHz, the U2355A counters 0.1 Hz ~ 6 MHz."""
    table = page.table_clock.table
    assert table.columnCount() == 4
    combo = table.cellWidget(0, 2)
    assert [combo.itemText(i) for i in range(combo.count())] == \
        [UNSET, "DAQM907A TOT", "U2355A CTR0", "U2355A CTR1"]
    # band is a read-only item, initially unconfigured
    assert table.cellWidget(0, 3) is None
    assert table.item(0, 3).text() == UNSET
    combo.setCurrentText("DAQM907A TOT")
    assert table.item(0, 3).text() == "0 ~ 100 kHz"
    combo.setCurrentText("U2355A CTR1")
    assert table.item(0, 3).text() == "0.1 Hz ~ 6 MHz"
    # the band item is read-only
    assert not (table.item(0, 3).flags()
                & __import__("PySide6.QtCore", fromlist=["Qt"])
                .Qt.ItemFlag.ItemIsEditable)


def test_power_pool_dropdowns(page):
    """Power Impedance / Voltage combos offer the DAQM908A sense
    channels, Power rails the 12 U2355A AI channels."""
    table = page.table_power.table
    impedance = table.cellWidget(0, 2)
    rails = table.cellWidget(0, 3)
    voltage = table.cellWidget(0, 4)
    assert impedance.itemText(0) == UNSET
    assert impedance.itemText(1) == "DAQM908A #1 CH101"
    assert impedance.findText("DAQM908A #2 CH240") >= 0
    assert voltage.findText("DAQM908A #2 CH201") >= 0
    assert [rails.itemText(i) for i in range(rails.count())] == \
        [UNSET, *(f"U2355A AI{n:02d}" for n in range(1, 13))]


def test_legacy_band_value_resets(page):
    """A legacy band value (pre hardware-mapping free text) resets to
    a clean unconfigured state on reload."""
    page.model.channel_allocation = {
        "clock": [{"net": "CLK_24M", "band": "CH2 source: U2355A"}]}
    page.refresh_from_model()
    row = page.table_clock.rows()[0]
    assert row.band == UNSET
    # choosing a resource fills the hardware band
    page.table_clock.table.cellWidget(0, 2).setCurrentText(
        "U2355A CTR0")
    assert page.table_clock.rows()[0].band == "0.1 Hz ~ 6 MHz"


# -------------------------------------------------- persistence / compat
def test_save_and_model_round_trip(page):
    """collect -> model -> fresh page keeps the configuration."""
    table = page.table_power.table
    for c, value in ((1, "U1.5"), (2, "DAQM908A #1 CH101"),
                     (3, "U2355A AI01"), (4, "DAQM908A #2 CH201")):
        table.cellWidget(0, c).setCurrentText(value)
    page.save_to_model()
    assert page.model.channel_allocation["power"][0]["impedance"] == \
        "DAQM908A #1 CH101"

    fresh = ChannelAllocationPage()
    fresh.set_model(page.model)
    try:
        fresh.refresh_from_model()
        row = fresh.table_power.rows()[0]
        assert row.test_point == "U1.5"
        assert row.impedance == "DAQM908A #1 CH101"
        assert row.power_rails == "U2355A AI01"
        assert row.voltage == "DAQM908A #2 CH201"
    finally:
        fresh.deleteLater()


def test_empty_and_legacy_compat(qapp):
    """An empty model loads blank tables without error; a legacy
    state without the channel_allocation key loads blank too."""
    model = YamlBuildModelForTest()
    model.imported["testable_nets"] = {}
    page = ChannelAllocationPage()
    page.set_model(model)
    try:
        page.refresh_from_model()
        assert page.table_power.table.rowCount() == 0
        assert page.table_clock.table.rowCount() == 0
        assert page.table_gpio.table.rowCount() == 0

        from mtkgui.gui.yamlbuild.model import YamlBuildModel
        real = YamlBuildModel()
        real.apply_state({"plan_version": "1.0.0"})  # legacy: no key
        assert real.channel_allocation == {}
    finally:
        page.deleteLater()


def test_yaml_effective_section_round_trip():
    """The configuration lands in the effective YAML channel_allocation
    section and is restored by apply_yaml_dict."""
    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    model = YamlBuildModel()
    model.set_channel_allocation({
        "power": [{"net": "3V3", "channel": "CH01"}]})
    doc = model.to_effective_dict()
    assert doc["yaml_build"]["channel_allocation"]["power"][0][
        "channel"] == "CH01"

    fresh = YamlBuildModel()
    fresh.apply_yaml_dict(doc)      # unrelated modules may report
    # required-field errors (empty defaults) - the allocation data
    # itself must be restored regardless
    assert fresh.channel_allocation["power"][0]["channel"] == "CH01"
