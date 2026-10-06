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
    """A row is OK only when every required cell is configured."""
    row = AllocatedRow(net="3V3")
    assert not row.is_configured("power")           # nothing set
    row.test_point = "U1.5"
    row.instrument = "DAQ973A"
    row.channel = "CH01"
    assert not row.is_configured("power")           # Yes/No missing
    row.impedance = "Yes"
    row.power_rails = "No"
    row.voltage = "Yes"
    assert row.is_configured("power") is True

    clock = AllocatedRow(net="CLK_24M", test_point="U1.10",
                         instrument="U2355A", channel="CH02")
    assert not clock.is_configured("clock")
    clock.se_clock_hz = "Yes"
    clock.band = "CH2 source: U2355A"
    assert clock.is_configured("clock") is True

    gpio = AllocatedRow(net="GPIO_LED1", test_point="U1.20",
                        instrument="DAQ973A", channel="CH03")
    # DI/DO are fixed attributes - only TP/instrument/channel needed
    assert gpio.is_configured("gpio") is True


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
    Status column is a read-only item."""
    table = page.table_power.table
    for r in range(table.rowCount()):
        for c in range(1, table.columnCount() - 1):
            widget = table.cellWidget(r, c)
            assert isinstance(widget, QComboBox), (r, c)
    for c in (0, table.columnCount() - 1):
        assert table.cellWidget(0, c) is None       # net + status


def test_status_auto_updates(page):
    """Filling every dropdown flips the Status from NOK to OK."""
    table = page.table_power.table
    assert table.item(0, 7).text() == "NOK"
    for c, value in ((1, "U1.5"), (2, "DAQ973A"), (3, "CH01"),
                     (4, "Yes"), (5, "Yes"), (6, "Yes")):
        table.cellWidget(0, c).setCurrentText(value)
    assert table.item(0, 7).text() == "OK"
    # status stays read-only: not editable by the user
    assert not (table.item(0, 7).flags()
                & __import__("PySide6.QtCore", fromlist=["Qt"])
                .Qt.ItemFlag.ItemIsEditable)


def test_gpio_fixed_attributes(page):
    """GPIO DI/DO combos carry exactly the fixed attributes."""
    combo_di = page.table_gpio.table.cellWidget(0, 4)
    combo_do = page.table_gpio.table.cellWidget(0, 5)
    assert [combo_di.itemText(i)
            for i in range(combo_di.count())] == ["HighZ"]
    assert [combo_do.itemText(i)
            for i in range(combo_do.count())] == ["No Output"]


def test_frequency_band_hardware_mapping(page):
    """Clock band dropdown: CH1 source DAQM907A / CH2 source U2355A."""
    combo = page.table_clock.table.cellWidget(0, 5)
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == ["—", "CH1 source: DAQM907A",
                     "CH2 source: U2355A"]


# -------------------------------------------------- persistence / compat
def test_save_and_model_round_trip(page):
    """collect -> model -> fresh page keeps the configuration."""
    table = page.table_power.table
    for c, value in ((1, "U1.5"), (2, "DAQ973A"), (3, "CH01"),
                     (4, "Yes"), (5, "No"), (6, "Yes")):
        table.cellWidget(0, c).setCurrentText(value)
    page.save_to_model()
    assert page.model.channel_allocation["power"][0]["channel"] == \
        "CH01"

    fresh = ChannelAllocationPage()
    fresh.set_model(page.model)
    try:
        fresh.refresh_from_model()
        row = fresh.table_power.rows()[0]
        assert row.channel == "CH01"
        assert row.impedance == "Yes"
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
