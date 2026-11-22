# -*- coding: utf-8 -*-
"""M103a: the fresh four-sheet MTK ICT Excel Sheet writer (Route C)."""
from __future__ import annotations

import pytest

pytest.importorskip("openpyxl")

import openpyxl  # noqa: E402

from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.gui.yamlbuild.mtk_sheet_writer import (  # noqa: E402
    default_mtk_sheet_name,
    export_mtk_sheet,
)
from mtkgui.ict.netparse.route_c import parse_mtk_sheet  # noqa: E402

POWER = [
    {"net": "VDD_1V8", "test_point": "TP1.1", "r_gnd_min_ohm": "8",
     "nominal_v": "1.800", "lower_v": "1.710", "upper_v": "1.890"},
    {"net": "VDD_3V3", "test_point": "TP2.1", "r_gnd_min_ohm": "12",
     "nominal_v": "3.300", "lower_v": "3.135", "upper_v": "3.465"},
]
CLOCK = [{
    "net": "XTAL_32K", "test_point": "TP3.1", "nominal_khz": "32.768",
    "tolerance_ppm": "30.5", "lower_khz": "32.767", "upper_khz": "32.769",
}]


def _model(*, power=POWER, clock=CLOCK, gnd=("GND", "AGND"),
           clock_manual=False):
    """A minimal model carrying Route C allocation rows + GND names."""
    model = YamlBuildModel()
    model.set_params("design_input", {
        "product_id": "FRDM-IMX700",
        "part_number": "96317",
        "hw_version": "A",
    })
    clock_rows = [dict(row) for row in clock]
    if clock_manual:
        for row in clock_rows:
            row["limits_source"] = "manual"
    model.set_channel_allocation({"power": [dict(r) for r in power],
                                  "clock": clock_rows})
    model.set_parsed_nets({"gnd_nets": list(gnd)})
    return model


def _export(tmp_path, model, name="MTK_ICT_sheet.xlsx"):
    path = tmp_path / name
    export_mtk_sheet(model, str(path))
    return path


# ------------------------------------------------------------------ writer
def test_writer_produces_four_sheets(tmp_path):
    path = _export(tmp_path, _model())
    book = openpyxl.load_workbook(path)
    assert book.sheetnames == ["Info", "R-GND", "Voltage", "Clock"]


def test_writer_rejects_missing_power(tmp_path):
    with pytest.raises(ValueError, match="no power nets"):
        _export(tmp_path, _model(power=[]))


def test_writer_rejects_missing_clock(tmp_path):
    with pytest.raises(ValueError, match="no clock nets"):
        _export(tmp_path, _model(clock=[]))


def test_writer_clock_symmetric_emits_formula(tmp_path):
    book = openpyxl.load_workbook(_export(tmp_path, _model()))
    ws = book["Clock"]
    assert isinstance(ws["E6"].value, str)
    assert ws["E6"].value.startswith("=ROUND(")
    assert ws["F6"].value.startswith("=ROUND(")
    # deliberately unlocked in both cases (§1.4 deviation from the sample)
    assert ws["E6"].protection.locked is False
    assert ws["F6"].protection.locked is False


def test_writer_clock_manual_emits_constant(tmp_path):
    book = openpyxl.load_workbook(
        _export(tmp_path, _model(clock_manual=True)))
    ws = book["Clock"]
    assert ws["E6"].value == pytest.approx(32.767)
    assert ws["F6"].value == pytest.approx(32.769)
    assert ws["D6"].value == pytest.approx(30.5)


def test_writer_results_and_sn_blank(tmp_path):
    book = openpyxl.load_workbook(_export(tmp_path, _model()))
    rgnd = book["R-GND"]
    assert rgnd["D6"].value is None
    assert rgnd["M21"].value is None
    assert rgnd["D5"].value == "SN Here"
    assert book["Voltage"]["F9"].value is None
    assert book["Clock"]["G6"].value is None


def test_writer_default_filename():
    model = _model()
    assert default_mtk_sheet_name(model) == \
        "MTK_ICT_FRDM-IMX700_96317_revA.xlsx"
    model.set_params("design_input", {"hw_version": "Rev B",
                                      "part_number": "S32N-EXP",
                                      "product_id": "FRDM-IMX93"})
    assert default_mtk_sheet_name(model) == \
        "MTK_ICT_FRDM-IMX93_S32N-EXP_revB.xlsx"


def test_writer_power_on_steps_omitted_when_empty(tmp_path):
    book = openpyxl.load_workbook(_export(tmp_path, _model()))
    volt = book["Voltage"]
    assert volt["A3"].value is None
    assert volt["A4"].value is None
    assert volt["A5"].value is None
    assert book["Info"]["B32"].value == "none defined"


def test_writer_gnd_tp_is_dash_no_test_point(tmp_path):
    book = openpyxl.load_workbook(_export(tmp_path, _model()))
    info = book["Info"]
    assert info["A25"].value == "GND"
    assert info["B25"].value == "\u2014 (no test point)"


# ---------------------------------------------------- parser round-trip gaps
def test_writer_gnd_empty_tp_is_allowed(tmp_path):
    path = _export(tmp_path, _model(gnd=("GND",)))
    book = openpyxl.load_workbook(path)
    book["Info"]["B25"] = "\u2014 (no test point)"
    book.save(path)
    result = parse_mtk_sheet(str(path))
    assert [(n.name, n.test_points) for n in result.gnd] == [("GND", "")]

    book = openpyxl.load_workbook(path)
    book["Info"]["B25"] = None
    book.save(path)
    result = parse_mtk_sheet(str(path))
    assert [(n.name, n.test_points) for n in result.gnd] == [("GND", "")]


def test_writer_clock_half_override_rejected(tmp_path):
    path = _export(tmp_path, _model())
    book = openpyxl.load_workbook(path)
    book["Clock"]["E6"] = 32.767          # plain number, F6 stays a formula
    book.save(path)
    with pytest.raises(ValueError,
                       match="Clock limits must be overridden as a pair"):
        parse_mtk_sheet(str(path))
