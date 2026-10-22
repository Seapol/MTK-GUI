# -*- coding: utf-8 -*-
"""P3-B2 T8: Parse Nets for ICT tests.

Formal net pre-analysis: the raw NET bytes loaded by Design Input
(load only there) are parsed here - categorized into Power / Clock /
GPIO test objects, non-testable nets filtered with reasons, preview
table rendered, Event Log detail + failures with exact reasons, and
the result stored as the single data source for Channel Allocation."""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QMessageBox,
)

from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog  # noqa: E402
from mtkgui.gui.yamlbuild.channel_allocation import (  # noqa: E402
    rows_from_testable,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.ict.netparse import (  # noqa: E402
    CATEGORY_CLOCK,
    CATEGORY_GND,
    CATEGORY_OTHERS,
    CATEGORY_POWER,
    parse_testable_nets,
    rank_result,
)
from mtkgui.ict.netparse.capacity import DEFAULT_LIMITS  # noqa: E402
from mtkgui.ict.netparse.export_testplan import (  # noqa: E402
    SHEET_POWER,
    export_testplan_pair,
)
from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel  # noqa: E402

FIXTURE_96317 = Path(__file__).parent / "fixtures" / "NET-96317_A.net"

NET_SAMPLE = """*SIGNAL* 3V3
U1.5 U2.VOUT
*SIGNAL* 1V8_CORE
U1.2 U3.4
*SIGNAL* CLK_24M
U1.10 U4.1
*SIGNAL* GPIO_LED1
U1.20 R5.2
*SIGNAL* GND
U1.1 J1.2
*SIGNAL* USB_P
U1.30 J2.1
*SIGNAL* USB_N
U1.31 J2.2
*SIGNAL* NO_PINS
PAD1
"""

NO_NETS = "garbage without signal blocks"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    w = ParseNetsPanel()
    yield w
    w.deleteLater()


# ------------------------------------------------------- headless core
def test_parse_categorizes_testable_nets():
    """Power / Clock / GPIO / GND categories extracted; diff pairs and
    pin-less nets filtered with documented reasons."""
    result = parse_testable_nets(NET_SAMPLE)
    assert [r.name for r in result.power] == ["3V3", "1V8_CORE"]
    assert [r.name for r in result.clock] == ["CLK_24M"]
    assert [r.name for r in result.gpio] == ["GPIO_LED1"]
    assert [r.name for r in result.gnd] == ["GND"]
    filtered = dict(result.filtered)
    assert "USB_P" in filtered and "USB_N" in filtered
    assert filtered["NO_PINS"] == \
        "no valid member pin (no test point)"
    assert result.total == 8


def test_parse_result_category_lookup():
    result = parse_testable_nets(NET_SAMPLE)
    assert result.category("3V3") == CATEGORY_POWER
    assert result.category("CLK_24M") == CATEGORY_CLOCK
    assert result.category("GPIO_LED1") == CATEGORY_OTHERS
    assert result.category("GND") == CATEGORY_GND


def test_parse_no_nets_raises_clear_error():
    """No *SIGNAL* blocks -> ValueError with the exact reason."""
    with pytest.raises(ValueError, match="no nets found"):
        parse_testable_nets(NO_NETS)


def test_parse_summary_counts():
    result = parse_testable_nets(NET_SAMPLE)
    assert result.summary() == ("power=2 clock=1 control_io=0 others=1 "
                                "gnd=1 filtered=3")


def test_exclude_regex_drops_signal_nets():
    """The Exclude Parse Nets regex (factory default: DIFF / RESET /
    ENABLE / UART / WAKE / I2C / SPI / JTAG / DBGIF / DATA / ADC and
    system random numeric names) drops matching SIGNAL nets from the
    parse result; Power / Clock / GND rows are never excluded and an
    explicit empty user value disables the exclusion."""
    sample = NET_SAMPLE + """*SIGNAL* DEBUG_UART_TX
U1.40 J9.1
*SIGNAL* BT_WAKE_OUT
U1.41 J9.2
*SIGNAL* DBG_RESET_REQ
U1.42 J9.3
*SIGNAL* SENSOR_I2C_SCL
U1.43 J9.4
*SIGNAL* FLASH_SPI_MOSI
U1.44 J9.5
*SIGNAL* CPU_JTAG_TDI
U1.45 J9.6
*SIGNAL* N12345
U1.46 J9.7
*SIGNAL* ADC0_IN
U1.47 J9.8
*SIGNAL* LCD_DATA01
U1.48 J9.9
"""
    result = parse_testable_nets(sample)
    excluded = {n for n, _r in result.filtered}
    assert {"DEBUG_UART_TX", "BT_WAKE_OUT", "DBG_RESET_REQ",
            "SENSOR_I2C_SCL", "FLASH_SPI_MOSI", "CPU_JTAG_TDI",
            "N12345", "ADC0_IN", "LCD_DATA01"} <= excluded
    # power nets never excluded even on a name hit
    result2 = parse_testable_nets(
        sample, rules={"power": r"^DBG_",
                       "exclude": r"RESET"})
    assert [r.name for r in result2.power] == ["3V3", "1V8_CORE",
                                               "DBG_RESET_REQ"]
    # empty user value disables the exclusion entirely
    result3 = parse_testable_nets(sample, rules={"exclude": ""})
    assert "DEBUG_UART_TX" in [r.name for r in result3.gpio]
    assert "N12345" in [r.name for r in result3.gpio]


# ------------------------------------------------- Filtered Nets table
def test_kernel_keeps_filtered_records():
    """The kernel keeps the dropped NetRecords so the Filtered Nets
    table can move a net back into the parsed set."""
    result = parse_testable_nets(NET_SAMPLE)
    rec_names = {r.name for r in result.filtered_records}
    assert rec_names == {n for n, _r in result.filtered}


def test_panel_filtered_table_and_moves(panel):
    """Filtered Nets table (Net | Reason | Category, default
    "Filtered"): picking "Filtered" in the Parsed Nets table moves a
    net down; picking a real category in the Filtered table moves it
    back up (both are whole-row moves)."""
    panel.set_net_source(NET_SAMPLE, "board.net")
    panel.parse_nets()
    # the filtered table shows the 3 dropped nets with their reasons
    assert panel.table_filtered.rowCount() == 3
    names = {panel.table_filtered.item(r, 0).text(): r
             for r in range(3)}
    assert set(names) == {"USB_P", "USB_N", "NO_PINS"}
    assert panel.table_filtered.cellWidget(names["USB_P"], 2) \
        .currentText() == "Filtered"
    # parsed -> filtered: pick "Filtered" on GPIO_LED1
    parsed = {panel.table.item(r, 0).text(): r
              for r in range(panel.table.rowCount())}
    panel.table.cellWidget(parsed["GPIO_LED1"], 2).setCurrentText(
        "Filtered")
    assert panel.table_filtered.rowCount() == 4
    assert panel.table.rowCount() == 4        # moved out of parsed
    filtered_names = {panel.table_filtered.item(r, 0).text()
                      for r in range(4)}
    assert "GPIO_LED1" in filtered_names
    # filtered -> parsed: restore USB_P as Power
    panel.table_filtered.cellWidget(names["USB_P"], 2) \
        .setCurrentText("Power")
    assert panel.table_filtered.rowCount() == 3
    assert panel.table.rowCount() == 5
    restored = {panel.table.item(r, 0).text(): r
                for r in range(panel.table.rowCount())}
    assert "USB_P" in restored
    assert panel.table.cellWidget(restored["USB_P"], 2) \
        .currentText() == "Power"
    assert panel.table.cellWidget(restored["USB_P"], 3) \
        .isChecked() is False                 # Power DNT default


# ------------------------------------------------------------ GUI panel
def test_panel_parse_renders_parsed_nets_table(panel):
    """The single PARSED NETS table (Net | Test Points | Category |
    Do Not Test) lists every parsed net; Signal / GND rows default to
    Do Not Test, the Category combo is user-changeable."""
    panel.set_net_source(NET_SAMPLE, "board.net")
    panel.parse_nets()
    assert panel.result is not None
    assert panel.table.rowCount() == 5       # 2 power + clock + signal + gnd
    assert panel.table.columnCount() == 7
    headers = [panel.table.horizontalHeaderItem(i).text()
               for i in range(7)]
    assert headers == ["Net", "Test Points", "Category", "Do Not Test",
                       "Confidence", "Input Rail", "Sub-class"]
    names = {panel.table.item(r, 0).text(): r for r in range(5)}
    # category combos reflect the parse categories
    assert panel.table.cellWidget(names["3V3"], 2).currentText() == \
        "Power"
    assert panel.table.cellWidget(names["CLK_24M"], 2).currentText() == \
        "SE Clock"
    assert panel.table.cellWidget(names["GPIO_LED1"], 2).currentText() \
        == CATEGORY_OTHERS
    assert panel.table.cellWidget(names["GND"], 2).currentText() == "GND"
    # DNT defaults: Signal + GND checked, Power / SE Clock unchecked
    assert panel.table.cellWidget(names["3V3"], 3).isChecked() is False
    assert panel.table.cellWidget(names["CLK_24M"], 3).isChecked() is False
    assert panel.table.cellWidget(names["GPIO_LED1"], 3).isChecked() is True
    assert panel.table.cellWidget(names["GND"], 3).isChecked() is True
    # M4 PART 6: read-only facts (confidence / input_rail / sub_class)
    assert panel.table.item(names["3V3"], 4).text() in (
        "high", "medium", "low")
    assert panel.table.item(names["3V3"], 5).text() == ""
    assert panel.table.item(names["GND"], 6).text() == "pcb"
    assert "power=2" in panel.lbl_summary.text()


def test_panel_category_change_updates_dnt_default(panel):
    """Re-categorizing a net applies the new category DNT default and
    survives re-parses."""
    panel.set_net_source(NET_SAMPLE, "board.net")
    panel.parse_nets()
    names = {panel.table.item(r, 0).text(): r for r in range(5)}
    combo = panel.table.cellWidget(names["GPIO_LED1"], 2)
    combo.setCurrentText("Power")
    assert panel.table.cellWidget(names["GPIO_LED1"], 3).isChecked() \
        is False
    panel.parse_nets()                        # re-parse keeps the override
    names = {panel.table.item(r, 0).text(): r for r in range(5)}
    assert panel.table.cellWidget(names["GPIO_LED1"], 2).currentText() \
        == "Power"


def test_panel_parse_progress_and_log(panel):
    """Parse emits staged progress (0 -> 100) and Event-Log detail:
    start / done with counts / per-net filtered warnings."""
    progress = []
    logs = []
    panel.task_progress.connect(lambda p, l: progress.append(p))
    panel.task_log.connect(lambda l, m: logs.append((l, m)))
    panel.set_net_source(NET_SAMPLE, "board.net")
    panel.parse_nets()
    assert progress[0] == 0 and progress[-1] == 100
    assert any("parse nets started" in m for _l, m in logs)
    assert any("parse nets done" in m and "power=2" in m
               for _l, m in logs)
    # GND integrity advisory: single reference ground -> OK hint
    assert "single global reference" in panel.lbl_gnd_risk.text()


def test_panel_without_net_reports_reason(panel, monkeypatch):
    """No NET loaded: clear prompt + ERROR log, no progress hang."""
    shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a) or 0)
    logs = []
    panel.task_log.connect(lambda l, m: logs.append((l, m)))
    panel.parse_nets()
    assert shown and "no NET file loaded" in shown[0][2]
    assert any(l == "ERROR" for l, _m in logs)


def test_panel_invalid_net_reports_reason(panel, monkeypatch):
    """A NET without *SIGNAL* blocks fails with the exact reason."""
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)
    panel.set_net_source(NO_NETS, "bad.net")
    panel.parse_nets()
    assert shown and "no nets found" in shown[0][2]


# ------------------------------------------- block03 dialog integration
def test_block03_dialog_embeds_parse_panel(qapp):
    """The parse_ict dialog hosts the Parse Nets panel; the raw NET
    source travels from the Design Input import."""
    dlg = BlockConfigDialog("parse_ict", {},
                            net_source=(NET_SAMPLE, "board.net"))
    try:
        assert dlg.nets_panel is not None
        dlg.nets_panel.set_net_source(NET_SAMPLE, "board.net")
        dlg.nets_panel.parse_nets()
        assert dlg.nets_panel.result is not None
        assert dlg.nets_panel.table.rowCount() == 5
    finally:
        dlg.deleteLater()


# ------------------------------------ model persistence (T10 data source)
def test_testable_nets_persist_round_trip():
    """The parse result stored on the model survives to_dict /
    apply_state and the effective YAML design_data section."""
    model = YamlBuildModel()
    model.imported["net"] = {"file": "board.net", "raw": NET_SAMPLE}
    model.imported["testable_nets"] = {
        "3V3": {"category": "Power", "members": ["U1.5", "U2.VOUT"]},
        "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
        "GPIO_LED1": {"category": "GPIO", "members": ["U1.20"]},
    }
    state = model.to_dict()
    fresh = YamlBuildModel()
    fresh.apply_state(state)
    assert fresh.imported["net"]["file"] == "board.net"
    assert fresh.imported["testable_nets"]["3V3"]["category"] == \
        "Power"

    doc = model.to_effective_dict()
    design = doc["yaml_build"]["design_data"]
    assert design["net_file"] == "board.net"
    assert design["testable_nets"]["CLK_24M"]["category"] == "Clock"

    # YAML import side: apply_yaml_dict restores the design data
    fresh2 = YamlBuildModel()
    fresh2.apply_yaml_dict(doc)
    assert fresh2.imported["net"]["file"] == "board.net"
    assert fresh2.imported["testable_nets"]["GPIO_LED1"][
        "category"] == "GPIO"


def test_old_model_state_without_net_key():
    """Legacy persisted states (pre-T8 imported dict) load without
    error and default to an empty net source."""
    model = YamlBuildModel()
    model.apply_state({"plan_version": "1.0.0", "imported": {
        "schematic": {}, "netlist": {}, "tp_resolutions": {}}})
    assert model.imported["net"] == {"file": "", "raw": ""}
    assert model.imported["testable_nets"] == {}


# ------------------------------------------- GUI-FIX2 F1: sync gate
def test_sync_gate_opens_on_applied_model(panel):
    """A REOPENED dialog (no instance 'applied' flag) may sync when
    the model already holds an applied parse result - the former
    gate could never be satisfied (GUI-FIX2 F1)."""
    model = YamlBuildModel()
    model.imported["testable_nets"] = {
        "3V3": {"category": "Power", "members": ["U1.5"]}}
    panel.set_yaml_model(model)
    assert panel._applied is False
    assert panel._sync_allowed("Export from YAML") is True


def test_sync_gate_opens_on_channel_allocation_only(panel):
    """A filled channel allocation counts as an applied plan too."""
    model = YamlBuildModel()
    model.set_channel_allocation({
        "power": [{"net": "3V3"}], "clock": [], "gpio": []})
    panel.set_yaml_model(model)
    assert panel._sync_allowed("Import to YAML") is True


def test_sync_gate_warns_without_parse_data(panel, monkeypatch):
    """No project YAML data and no parse: one warning, WITHOUT the
    retired 'Apply this block (OK)' instruction."""
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a) or 0)
    panel.set_yaml_model(YamlBuildModel())
    assert panel._sync_allowed("Import to YAML") is False
    assert warnings and "No parsed ICT data yet" in warnings[0][2]
    assert "Apply this block" not in warnings[0][2]


def test_sync_gate_warns_without_project_yaml(panel, monkeypatch):
    """No project YAML loaded -> explicit message (never a crash)."""
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a) or 0)
    assert panel._sync_allowed("Export from YAML") is False
    assert warnings and warnings[0][2] == "No project YAML is loaded."


def test_import_to_yaml_lazy_parses_and_syncs(panel, tmp_path,
                                              monkeypatch):
    """Clicking Import to YAML in a dialog that never called Parse
    runs the same headless pipeline, then syncs immediately - no
    apply-first round-trip, no file dialog for a missing precondition."""
    source = parse_testable_nets(NET_SAMPLE)
    rank_result(source)
    xlsx = str(tmp_path / "plan.xlsx")
    export_testplan_pair(source, DEFAULT_LIMITS, xlsx, "board")

    model = YamlBuildModel()
    panel.set_yaml_model(model)
    panel.set_net_source(NET_SAMPLE, "board.net")
    warnings, logs = [], []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a) or 0)
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *a, **k: (xlsx, ""))
    panel.task_log.connect(lambda _lvl, msg: logs.append(msg))

    panel.import_to_yaml()

    assert warnings == []
    assert not any("Apply this block" in str(w) for w in warnings)
    assert panel.result is not None          # lazy parse ran
    assert "3V3" in model.imported["testable_nets"]
    assert any("import to YAML" in msg for msg in logs)


def test_export_from_yaml_reopened_dialog(panel, tmp_path, monkeypatch):
    """Reopened dialog (model applied earlier, no parse inside this
    instance): Export from YAML writes the workbook + evidence md."""
    model = YamlBuildModel()
    model.imported["testable_nets"] = {
        "3V3": {"category": "Power", "members": ["U1.5", "U2.VOUT"]}}
    panel.set_yaml_model(model)
    out = str(tmp_path / "out.xlsx")
    warnings, logs = [], []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a) or 0)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (out, ""))
    panel.task_log.connect(lambda _lvl, msg: logs.append(msg))

    panel.export_from_yaml()

    assert warnings == []
    assert Path(out).exists()
    assert Path(out).with_name("out_evidence.md").exists()
    assert any("export from YAML" in msg for msg in logs)


# ---------------------------------------- GUI-FIX2 F2: rank ordering
def test_96317_power_order_input_rail_first(panel, tmp_path):
    """96317 must materialise DC_5V_IN (the only input rail) FIRST in
    the panel preview, the Channel Allocation row order AND the
    exported workbook - CLI / export_testplan share one ranking."""
    panel.set_net_source(FIXTURE_96317.read_text(encoding="utf-8"),
                         "NET-96317_A.net")
    panel.parse_nets()
    names = [rec.name for rec in panel.result.power]
    assert names[0] == "DC_5V_IN"
    assert panel.result.power[0].input_rail is True
    assert panel.table.item(0, 0).text() == "DC_5V_IN"

    # Channel Allocation rows follow the same order (the GUI
    # materialises testable_nets in the parse order -> dict order)
    testable = {rec.name: {"category": "Power",
                           "members": list(rec.members)}
                for rec in panel.result.power}
    assert [row.net for row in rows_from_testable(testable, "power")] \
        == names

    # the exported Test Plan Power sheet keeps the identical order
    xlsx = str(tmp_path / "plan.xlsx")
    export_testplan_pair(panel.result, DEFAULT_LIMITS, xlsx, "96317")
    rows = list(openpyxl.load_workbook(xlsx)[SHEET_POWER]
                .iter_rows(min_row=2, values_only=True))
    assert [row[0] for row in rows] == names
