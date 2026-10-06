# -*- coding: utf-8 -*-
"""P3-B2 T8: Parse Nets for ICT tests.

Formal net pre-analysis: the raw NET bytes loaded by Design Input
(load only there) are parsed here - categorized into Power / Clock /
GPIO test objects, non-testable nets filtered with reasons, preview
table rendered, Event Log detail + failures with exact reasons, and
the result stored as the single data source for Channel Allocation."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog  # noqa: E402
from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.gui.yamlbuild.parse_nets import (  # noqa: E402
    CATEGORY_CLOCK,
    CATEGORY_GND,
    CATEGORY_GPIO,
    CATEGORY_POWER,
    ParseNetsPanel,
    parse_testable_nets,
)

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
    assert result.category("GPIO_LED1") == CATEGORY_GPIO
    assert result.category("GND") == CATEGORY_GND


def test_parse_no_nets_raises_clear_error():
    """No *SIGNAL* blocks -> ValueError with the exact reason."""
    with pytest.raises(ValueError, match="no nets found"):
        parse_testable_nets(NO_NETS)


def test_parse_summary_counts():
    result = parse_testable_nets(NET_SAMPLE)
    assert result.summary() == ("power=2 clock=1 gpio=1 gnd=1 "
                                "filtered=3")


# ------------------------------------------------------------ GUI panel
def test_panel_parse_renders_parsed_nets_table(panel):
    """The single PARSED NETS table (Net | Test Points | Category |
    Do Not Test) lists every parsed net; Signal / GND rows default to
    Do Not Test, the Category combo is user-changeable."""
    panel.set_net_source(NET_SAMPLE, "board.net")
    panel.parse_nets()
    assert panel.result is not None
    assert panel.table.rowCount() == 5       # 2 power + clock + signal + gnd
    assert panel.table.columnCount() == 4
    headers = [panel.table.horizontalHeaderItem(i).text()
               for i in range(4)]
    assert headers == ["Net", "Test Points", "Category", "Do Not Test"]
    names = {panel.table.item(r, 0).text(): r for r in range(5)}
    # category combos reflect the parse categories
    assert panel.table.cellWidget(names["3V3"], 2).currentText() == \
        "Power"
    assert panel.table.cellWidget(names["CLK_24M"], 2).currentText() == \
        "SE Clock"
    assert panel.table.cellWidget(names["GPIO_LED1"], 2).currentText() \
        == "Signal"
    assert panel.table.cellWidget(names["GND"], 2).currentText() == "GND"
    # DNT defaults: Signal + GND checked, Power / SE Clock unchecked
    assert panel.table.cellWidget(names["3V3"], 3).isChecked() is False
    assert panel.table.cellWidget(names["CLK_24M"], 3).isChecked() is False
    assert panel.table.cellWidget(names["GPIO_LED1"], 3).isChecked() is True
    assert panel.table.cellWidget(names["GND"], 3).isChecked() is True
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
