# -*- coding: utf-8 -*-
"""M102a: Route C (MTK ICT Excel Sheet) headless parser."""
from __future__ import annotations

import pytest

pytest.importorskip("openpyxl")

from mtkgui.ict.netparse.route_c import (  # noqa: E402
    check_power_gate,
    parse_mtk_sheet,
)


# --------------------------------------------------------------- fixture
def _make_sheet(path, *, power=None, voltage=None, clock=None, gnd=None,
                clock_limits="formula", rgnd_extra=None,
                result_columns=False):
    """Write an MTK ICT Excel Sheet at the documented absolute layout."""
    import openpyxl

    power = power if power is not None else [
        ("VDD_1V8", "TP1.1", 8), ("VDD_3V3", "TP2.1", 12)]
    voltage = voltage if voltage is not None else [
        ("VDD_1V8", "TP1.1", 1.71, 1.8, 1.89),
        ("VDD_3V3", "TP2.1", 3.135, 3.3, 3.465)]
    clock = clock if clock is not None else [
        ("CLK_32K", "TP3.1", 32.768, 30.5)]
    gnd = gnd if gnd is not None else [
        ("GND", "TP6.1 TP46.1"), ("AGND", "TP7.1")]

    book = openpyxl.Workbook()
    info = book.active
    info.title = "Info"
    rgnd = book.create_sheet("R-GND")
    volt = book.create_sheet("Voltage")
    clk = book.create_sheet("Clock")

    # Info: header row 24, data from row 25
    info["A24"] = "GND net"
    info["B24"] = "Test Point(s)"
    row = 25
    for name, points in gnd:
        info.cell(row=row, column=1, value=name)
        info.cell(row=row, column=2, value=points)
        row += 1

    # R-GND: header row 4, SN row 5, data from row 6
    rgnd["A4"] = "Net"
    rgnd["B4"] = "Test Point(s)"
    rgnd["C4"] = "R-GND Min (Ω)"
    rgnd["A5"] = "SN"
    rgnd["B5"] = "SN"
    rgnd["C5"] = "SN"
    row = 6
    for name, test_point, min_ohm in power:
        rgnd.cell(row=row, column=1, value=name)
        rgnd.cell(row=row, column=2, value=test_point)
        rgnd.cell(row=row, column=3, value=min_ohm)
        if result_columns:
            for column in range(4, 17):
                rgnd.cell(row=row, column=column, value="junk")
        row += 1
    if rgnd_extra:
        row += 1                      # one fully blank row
        for name, test_point in rgnd_extra:
            rgnd.cell(row=row, column=1, value=name)
            rgnd.cell(row=row, column=2, value=test_point)
            rgnd.cell(row=row, column=3, value=8)
            row += 1

    # Voltage: header row 7, SN row 8, data from row 9
    volt["A7"] = "Net"
    volt["B7"] = "Test Point(s)"
    volt["C7"] = "Lower (V)"
    volt["D7"] = "Nominal (V)"
    volt["E7"] = "Upper (V)"
    volt["A8"] = "SN"
    row = 9
    for name, test_point, lower, nominal, upper in voltage:
        volt.cell(row=row, column=1, value=name)
        volt.cell(row=row, column=2, value=test_point)
        volt.cell(row=row, column=3, value=lower)
        volt.cell(row=row, column=4, value=nominal)
        volt.cell(row=row, column=5, value=upper)
        if result_columns:
            for column in range(6, 17):
                volt.cell(row=row, column=column, value="junk")
        row += 1

    # Clock: header row 4, SN row 5, data from row 6
    clk["A4"] = "Net"
    clk["B4"] = "Test Point(s)"
    clk["C4"] = "Nominal (kHz)"
    clk["D4"] = "Tolerance (±ppm)"
    clk["E4"] = "Lower (auto)"
    clk["F4"] = "Upper (auto)"
    clk["A5"] = "SN"
    clk["C5"] = 999
    row = 6
    for index, (name, test_point, nominal, ppm) in enumerate(clock):
        clk.cell(row=row, column=1, value=name)
        clk.cell(row=row, column=2, value=test_point)
        clk.cell(row=row, column=3, value=nominal)
        clk.cell(row=row, column=4, value=ppm)
        if isinstance(clock_limits, str):
            clk.cell(row=row, column=5,
                     value=f"=ROUND(C{row}*(1-D{row}/1000000),3)")
            clk.cell(row=row, column=6,
                     value=f"=ROUND(C{row}*(1+D{row}/1000000),3)")
        else:
            lo, hi = clock_limits[index]
            clk.cell(row=row, column=5, value=lo)
            clk.cell(row=row, column=6, value=hi)
        if result_columns:
            for column in range(7, 17):
                clk.cell(row=row, column=column, value="junk")
        row += 1

    book.save(str(path))
    return str(path)


# --------------------------------------------------------------- parsing
def test_route_c_parses_power_clock_and_gnd(tmp_path):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    result = parse_mtk_sheet(path)
    assert [n.name for n in result.power] == ["VDD_1V8", "VDD_3V3"]
    assert [n.test_point for n in result.power] == ["TP1.1", "TP2.1"]
    assert result.power[0].r_gnd_min_ohm == 8
    assert result.power[1].nominal_v == 3.3
    assert result.power[1].lower_v == 3.135
    assert result.power[1].upper_v == 3.465
    assert [n.name for n in result.clock] == ["CLK_32K"]
    assert result.clock[0].nominal_khz == 32.768
    assert [(n.name, n.test_points) for n in result.gnd] == [
        ("GND", "TP6.1 TP46.1"), ("AGND", "TP7.1")]
    assert result.gate_ok is True
    assert result.summary() == "Power 2 · Clock 1 · GND 2 · warnings 0"
    nets = result.to_parsed_nets()
    assert nets["route"] == "mtk_sheet"
    assert nets["power_nets"] == ["VDD_1V8", "VDD_3V3"]
    assert nets["clock_nets"] == ["CLK_32K"]
    assert nets["gnd_nets"] == ["GND", "AGND"]
    assert nets["other_nets"] == []


def test_route_c_clock_limits_derived_from_ppm(tmp_path):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    clock = parse_mtk_sheet(path).to_allocation_rows()["clock"][0]
    assert clock["nominal_khz"] == "32.768"
    assert clock["lower_khz"] == "32.767"
    assert clock["upper_khz"] == "32.769"
    assert clock["tolerance_ppm"] == "30.5"
    # the symmetric path omits the source key (lean YAML)
    assert "limits_source" not in clock


def test_route_c_power_allocation_rows_are_strings(tmp_path):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    power = parse_mtk_sheet(path).to_allocation_rows()["power"][0]
    assert power == {
        "net": "VDD_1V8", "test_point": "TP1.1", "r_gnd_min_ohm": "8",
        "nominal_v": "1.800", "lower_v": "1.710", "upper_v": "1.890"}
    assert all(isinstance(value, str) for value in power.values())


# ------------------------------------------------------------------ gate
def test_route_c_gate_rejects_name_mismatch(tmp_path):
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        power=[("VDD_1V8", "TP1.1", 8), ("VDD_3V3", "TP2.1", 12),
               ("VDD_5V0", "TP4.1", 10)])
    result = parse_mtk_sheet(path)
    assert result.gate_ok is False
    assert "only in R-GND: ['VDD_5V0']" in result.gate_error
    assert "only in Voltage: []" in result.gate_error
    assert result.to_parsed_nets()["gate_ok"] is False


def test_route_c_gate_rejects_power_count_mismatch():
    ok, message = check_power_gate(
        [("VDD_1V8", "TP1.1", 8), ("VDD_1V8", "TP1.1", 9)],
        [("VDD_1V8", "TP1.1", 1.71, 1.8, 1.89)])
    assert ok is False
    assert message == "Power net count mismatch: R-GND 2 vs Voltage 1"


def test_route_c_gate_rejects_test_point_mismatch(tmp_path):
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        voltage=[("VDD_1V8", "TP9.1", 1.71, 1.8, 1.89),
                 ("VDD_3V3", "TP2.1", 3.135, 3.3, 3.465)])
    result = parse_mtk_sheet(path)
    assert result.gate_ok is False
    assert result.gate_error == (
        "Test point mismatch for VDD_1V8: R-GND TP1.1 vs Voltage TP9.1")


# ------------------------------------------------------------ rejections
def test_route_c_rejects_duplicate_power_net(tmp_path):
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        power=[("VDD_1V8", "TP1.1", 8), ("VDD_1V8", "TP1.1", 8)])
    with pytest.raises(ValueError) as exc:
        parse_mtk_sheet(path)
    assert str(exc.value) == "Duplicate power net in R-GND: VDD_1V8"


def test_route_c_rejects_non_integer_r_gnd_min(tmp_path):
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        power=[("VDD_1V8", "TP1.1", 4.5), ("VDD_3V3", "TP2.1", 12)])
    with pytest.raises(ValueError) as exc:
        parse_mtk_sheet(path)
    assert str(exc.value) == (
        "R-GND Min must be a positive integer ohm: VDD_1V8 = 4.5")


def test_route_c_rejects_bad_voltage_order(tmp_path):
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        voltage=[("VDD_1V8", "TP1.1", 3.4, 3.3, 3.5),
                 ("VDD_3V3", "TP2.1", 3.135, 3.3, 3.465)])
    with pytest.raises(ValueError) as exc:
        parse_mtk_sheet(path)
    assert str(exc.value).startswith(
        "Lower < Nominal < Upper required for VDD_1V8: ")


# ---------------------------------------------------- clock limits (ppm)
def test_route_c_symmetric_derives_min_max(tmp_path):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    clock = parse_mtk_sheet(path).clock[0]
    assert clock.min_khz == 32.767
    assert clock.max_khz == 32.769
    assert clock.limits_source == "ppm"


def test_route_c_manual_limits_kept_asymmetry(tmp_path):
    path = _make_sheet(tmp_path / "mtk.xlsx",
                       clock_limits=[(32.760, 32.775)])
    clock = parse_mtk_sheet(path).clock[0]
    assert clock.min_khz == 32.760
    assert clock.max_khz == 32.775
    assert clock.limits_source == "manual"
    assert clock.ppm == 30.5
    row = parse_mtk_sheet(path).to_allocation_rows()["clock"][0]
    assert row["tolerance_ppm"] == "30.5"
    assert row["limits_source"] == "manual"
    assert row["lower_khz"] == "32.760"
    assert row["upper_khz"] == "32.775"


def test_route_c_manual_limits_reject_wrong_order(tmp_path):
    path = _make_sheet(tmp_path / "mtk.xlsx",
                       clock_limits=[(32.790, 32.800)])
    with pytest.raises(ValueError) as exc:
        parse_mtk_sheet(path)
    assert str(exc.value).startswith(
        "Clock manual limits violate 0 < min < nominal < max: CLK_32K = ")


def test_route_c_manual_limits_reject_implied_over_1000ppm(tmp_path):
    # 1 kHz crystal with a 20 Hz window -> 10 000 ppm implied
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        clock=[("CLK_1K", "TP3.1", 1.0, 30.5)],
        clock_limits=[(0.99, 1.01)])
    with pytest.raises(ValueError) as exc:
        parse_mtk_sheet(path)
    assert str(exc.value) == (
        "Clock manual limits exceed 1000 ppm implied tolerance: CLK_1K")


# ------------------------------------------------------------- GND block
def test_route_c_gnd_block_ends_at_first_blank_row(tmp_path):
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        gnd=[("GND", "TP6.1 TP46.1"), ("AGND", "TP7.1")])
    import openpyxl
    book = openpyxl.load_workbook(path)
    book["Info"].cell(row=28, column=1, value="EXTRA")
    book["Info"].cell(row=28, column=2, value="TP9.1")
    book.save(path)
    result = parse_mtk_sheet(path)
    assert [n.name for n in result.gnd] == ["GND", "AGND"]


def test_route_c_ignores_result_columns_and_sn_row(tmp_path):
    path = _make_sheet(tmp_path / "mtk.xlsx", result_columns=True)
    result = parse_mtk_sheet(path)
    assert result.power[0].r_gnd_min_ohm == 8
    assert result.power[0].nominal_v == 1.8
    assert result.clock[0].nominal_khz == 32.768
    assert result.clock[0].max_khz == 32.769
    assert result.warnings == []


def test_route_c_warns_about_rows_below_the_blank_row(tmp_path):
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        power=[("VDD_1V8", "TP1.1", 8), ("VDD_3V3", "TP2.1", 12)],
        rgnd_extra=[("VDD_OLD", "TP8.1")])
    result = parse_mtk_sheet(path)
    assert [n.name for n in result.power] == ["VDD_1V8", "VDD_3V3"]
    assert result.warnings == [
        "Row 9 ignored after the first blank row on R-GND"]
    assert result.summary().endswith("warnings 1")
