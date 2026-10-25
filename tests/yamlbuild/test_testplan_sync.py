# -*- coding: utf-8 -*-
"""M5 PART 2: ICT Test Plan <-> project YAML bidirectional sync."""
from __future__ import annotations

import openpyxl
import pytest

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.testplan_sync import (
    testplan_to_yaml as _import_plan,
    yaml_to_testplan as _export_plan,
)
from mtkgui.ict.netparse.capacity import DEFAULT_LIMITS
from mtkgui.ict.netparse.export_testplan import (
    SHEET_CLOCK,
    SHEET_CONTROL_IO,
    SHEET_GND,
    SHEET_NAMES,
    SHEET_OTHERS,
    SHEET_POWER,
    export_testplan_pair,
)
from mtkgui.ict.netparse.model import NetRecord, ParseNetsResult
from mtkgui.ict.netparse.priority import rank_result


def _result() -> ParseNetsResult:
    result = ParseNetsResult(source="NET-96317_A.net", total=9)
    result.power = [
        NetRecord(name="VDD_3V3", members=["TP1.1", "U1.5"],
                  net_type="power", provenance="rule:power",
                  confidence="high", input_rail=True),
        NetRecord(name="VDD_1V8", members=["U2.4"],
                  net_type="power", provenance="rule:power",
                  confidence="medium"),
    ]
    result.clock = [
        NetRecord(name="CLK_24M", members=["U1.10", "U4.1"],
                  net_type="clock_single", provenance="rule:clock",
                  confidence="high"),
    ]
    result.control_io = [
        NetRecord(name="GPIO_RST", members=["TP2.1"],
                  net_type="signal", provenance="control_io:rst",
                  confidence="high"),
    ]
    result.gnd = [
        NetRecord(name="GND", members=["J1.2", "U1.1"],
                  net_type="gnd_ref", sub_class="pcb",
                  provenance="gnd", confidence="high"),
    ]
    result.others = [
        NetRecord(name="USB_P", members=["U1.30", "J2.1"],
                  net_type="signal", sub_class="unclassified",
                  provenance="fallback:unclassified", confidence="low"),
    ]
    rank_result(result)
    result.power[0].input_rail = True
    return result


def _workbook(tmp_path, name="plan.xlsx") -> str:
    path = str(tmp_path / name)
    export_testplan_pair(_result(), DEFAULT_LIMITS, path, "96317")
    return path


def _rows(path, sheet):
    workbook = openpyxl.load_workbook(path)
    return list(workbook[sheet].iter_rows(min_row=2, values_only=True))


def test_import_populates_yaml(tmp_path):
    model = YamlBuildModel()
    xlsx = _workbook(tmp_path)
    _import_plan(model, xlsx, None, _result())
    rails = model.power_rails_up_sequence["rails"]
    assert [rail["name"] for rail in rails] == ["VDD_3V3", "VDD_1V8"]
    assert [row["net"] for row in
            model.get_channel_allocation()["power"]] == \
        ["VDD_3V3", "VDD_1V8"]
    assert [row["net"] for row in model.se_clock_allocation] == \
        ["CLK_24M"]
    assert [row["net"] for row in model.gpio_allocation] == ["GPIO_RST"]
    testable = model.imported["testable_nets"]
    assert testable["VDD_3V3"]["category"] == "Power"
    assert testable["CLK_24M"]["category"] == "Clock"
    assert testable["GPIO_RST"]["category"] == "GPIO"
    assert testable["GND"]["category"] == "GND"
    assert testable["GND"].get("is_reference_gnd") is True
    assert "USB_P" in model.get_params(
        "parse_ict")["power_dont_test"].splitlines()
    assert model.ict_test_plan["records"]["VDD_3V3"]["input_rail"] is True
    assert any(line.startswith("added power rail")
               for line in model.testplan_sync_report)
    assert model.changed is True


def test_roundtrip_keeps_every_net(tmp_path):
    model = YamlBuildModel()
    _import_plan(model, _workbook(tmp_path), None, _result())
    out = str(tmp_path / "roundtrip.xlsx")
    _export_plan(model, out,
                     str(tmp_path / "roundtrip_evidence.md"))
    workbook = openpyxl.load_workbook(out)
    assert tuple(workbook.sheetnames) == SHEET_NAMES
    assert [row[0] for row in _rows(out, SHEET_POWER)] == \
        ["VDD_3V3", "VDD_1V8"]
    assert [row[0] for row in _rows(out, SHEET_CLOCK)] == ["CLK_24M"]
    assert [row[0] for row in _rows(out, SHEET_CONTROL_IO)] == \
        ["GPIO_RST"]
    assert [row[1] for row in _rows(out, SHEET_GND)] == ["GND"]
    assert [row[1] for row in _rows(out, SHEET_OTHERS)] == ["USB_P"]
    evidence = (tmp_path / "roundtrip_evidence.md").read_text(
        encoding="utf-8")
    assert "## Power tree flows" in evidence
    assert "VDD_3V3 (INPUT)" in evidence


def test_yaml_values_win_on_reexport(tmp_path):
    model = YamlBuildModel()
    _import_plan(model, _workbook(tmp_path), None, _result())
    # human edits in the production YAML
    rails = model.power_rails_up_sequence["rails"]
    for rail in rails:
        if rail["name"] == "VDD_3V3":
            rail["nominal_v"] = 9.9
    model.set_power_rails(model.power_rails_up_sequence)
    allocation = model.get_channel_allocation()
    for row in allocation["power"]:
        if row["net"] == "VDD_3V3":
            row["test_point"] = "TPY.1"
    model.set_channel_allocation(allocation)

    out = str(tmp_path / "yaml_wins.xlsx")
    _export_plan(model, out, str(tmp_path / "yaml_wins_evidence.md"))
    power = {row[0]: row for row in _rows(out, SHEET_POWER)}
    assert float(power["VDD_3V3"][3]) == 9.9
    assert power["VDD_3V3"][1] == "TPY.1"
    assert float(power["VDD_3V3"][4]) < 9.9 < float(power["VDD_3V3"][5])
    # algorithm did not overwrite the human value
    assert float(power["VDD_1V8"][3]) == 1.8

    # a second import keeps the non-empty YAML value
    _import_plan(model, out, None, _result())
    kept = [rail for rail in model.power_rails_up_sequence["rails"]
            if rail["name"] == "VDD_3V3"][0]
    assert float(kept["nominal_v"]) == 9.9
    assert any("kept power rail VDD_3V3" in line
               for line in model.testplan_sync_report)


def test_blank_yaml_cell_is_filled(tmp_path):
    model = YamlBuildModel()
    model.set_power_rails({"rails": [{"name": "VDD_3V3",
                                      "nominal_v": "",
                                      "ramp_offset_s": 0.0,
                                      "color": "#ef4444"}]})
    _import_plan(model, _workbook(tmp_path), None, _result())
    rail = model.power_rails_up_sequence["rails"][0]
    assert float(rail["nominal_v"]) == 3.3
    assert any(line.startswith("filled power rail VDD_3V3")
               for line in model.testplan_sync_report)


def test_gui_buttons_present():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
    app = QApplication.instance() or QApplication([])
    panel = ParseNetsPanel()
    try:
        for name in ("btn_risk_thresholds", "btn_export_plan",
                     "btn_import_yaml", "btn_export_yaml"):
            assert not hasattr(panel, name)
        model = YamlBuildModel()
        panel.set_yaml_model(model)
        assert panel.yaml_model is model
        panel.mark_applied()
        assert panel._applied is True
    finally:
        panel.deleteLater()
        app.processEvents()
