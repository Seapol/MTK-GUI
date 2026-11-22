# -*- coding: utf-8 -*-
"""M73/M103: Excel config workbook export guard.

Export only (M103 deleted the config-workbook import): every sheet is
protected (no password); the YamlBuild sheet is fully read-only except
its numeric ``Value`` cells; on the Power / Clock / GPIO allocation
sheets only ``net`` / ``test_point`` stay editable - the limit columns
are a read-only mirror (contract §6).
"""
from __future__ import annotations

from openpyxl import load_workbook

from mtkgui.gui.yamlbuild.excel_io import (
    ALLOC_LIMIT_KEYS,
    EDITABLE_FILL_RGB,
    EDITABLE_SUFFIX,
    MIRROR_SUFFIX,
    READONLY_FILL_RGB,
    READONLY_SUFFIX,
    SHEET_NAME,
    STRUCTURE_EDITABLE_SUFFIX,
    export_to_excel,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.channel_allocation import AllocatedRow
from mtkgui.gui.yamlbuild.power_alloc import (
    CLOCK_BANDS,
    CLOCK_CHANNELS,
    DAQM908A_SENSE_CHANNELS,
    GPIO_DIO_CHANNELS,
    U2355A_AI_CHANNELS,
)


def _model() -> YamlBuildModel:
    """Valid model with all three allocation tables configured."""
    model = YamlBuildModel()
    model.enable_all()
    model.set_params("design_input", {
        "product_id": "IMXRT700", "part_number": "MTK12345",
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "MP (Production)"})
    model.set_params("parse_ict", {"netlist_file": "design.net",
                                   "ict_test_file": ""})
    model.set_params("instruments", {
        "psu_visa": "TCPIP0::192.168.1.20::inst0",
        "daq_visa": "GPIB0::9::INSTR", "dmm_visa": "",
        "self_test": "true"})
    model.set_params("rails", {
        "on_voltage_v": "5.0", "current_limit_a": "1.0",
        "on_delay_ms": "100", "off_delay_ms": "200",
        "off_protection": "true", "sequence": "VDD:0.0\nVDDCORE:0.2",
        "voltage_tolerance_pct": "0.1", "impedance_min_ohm": "1.5",
        "sample_rate_hz": "1000", "pre_trigger_s": "-0.5",
        "post_trigger_s": "6.0", "anomaly_policy": "stop"})
    model.set_params("clocks", {"clocks": "CLK1:32768:0.1",
                                "stabilize_ms": "100",
                                "drift_check": "true",
                                "multi_domain_check": "false"})
    model.set_params("gpios", {"groups": "LED1:PA0:out:none",
                               "level_threshold_v": "1.5",
                               "exception_check": "true"})
    model.set_params("fct_build", {"flow_steps": "step1\nstep2",
                                   "yield_threshold_pct": "98.0",
                                   "exception_branch": "stop",
                                   "case_link": ""})
    band = next(iter(CLOCK_BANDS.values()))
    model.set_channel_allocation({
        "power": [AllocatedRow(
            net="VDD_3V3", test_point="TP1.1",
            impedance=DAQM908A_SENSE_CHANNELS[0],
            power_rails=U2355A_AI_CHANNELS[0],
            voltage=DAQM908A_SENSE_CHANNELS[0],
            r_gnd_min_ohm="1.500", nominal_v="3.300",
            lower_v="3.135", upper_v="3.465").to_dict()],
        "clock": [AllocatedRow(
            net="CLK_24M", test_point="TP3.1",
            se_clock_hz=CLOCK_CHANNELS[0], band=band,
            nominal_khz="24000.000", lower_khz="23998.800",
            upper_khz="24001.200").to_dict()],
        "gpio": [AllocatedRow(
            net="GPIO_RST", test_point="TP2.1",
            dio_channel=GPIO_DIO_CHANNELS[0]).to_dict()],
    })
    return model


def _rgb(cell) -> str:
    return str(cell.fill.start_color.rgb or "")[-6:]


def _header_index(ws, title: str) -> int:
    for idx, cell in enumerate(ws[1], start=1):
        if str(cell.value or "").startswith(title):
            return idx
    raise AssertionError(f"header {title!r} not found")


# --------------------------------------------------------------- export
def test_export_is_protected_and_column_locked(tmp_path):
    path = str(tmp_path / "review.xlsx")
    export_to_excel(_model(), path)
    wb = load_workbook(path)
    try:
        for sheet in (SHEET_NAME, "Power", "Clock", "GPIO"):
            ws = wb[sheet]
            assert ws.protection.sheet is True, sheet
            assert ws.protection.password is None, sheet
    finally:
        wb.close()


def test_parameter_sheet_locks_everything_but_numbers(tmp_path):
    """M91: on the YamlBuild sheet only a numeric Value cell is editable."""
    path = str(tmp_path / "numbers.xlsx")
    export_to_excel(_model(), path)
    wb = load_workbook(path)
    try:
        ws = wb[SHEET_NAME]
        value_col = _header_index(ws, "Value")
        header = ws.cell(row=1, column=value_col)
        assert header.value == "Value" + EDITABLE_SUFFIX
        assert _rgb(header) == EDITABLE_FILL_RGB
        assert header.protection.locked is False
        for idx in range(1, ws.max_column + 1):
            if idx == value_col:
                continue
            other = ws.cell(row=1, column=idx)
            assert str(other.value).endswith(READONLY_SUFFIX)
            assert _rgb(other) == READONLY_FILL_RGB
            assert other.protection.locked is True
        for ftype, editable in (("float", True), ("int", True),
                                ("text", False), ("bool", False),
                                ("choice", False), ("str", False)):
            row = next(r for r in range(2, ws.max_row + 1)
                       if str(ws.cell(row=r, column=5).value) == ftype)
            cell = ws.cell(row=row, column=value_col)
            assert cell.protection.locked is (not editable), ftype
            assert _rgb(cell) == (EDITABLE_FILL_RGB if editable
                                  else READONLY_FILL_RGB), ftype
        assert ws.protection.sheet is True
        assert ws.protection.password is None
    finally:
        wb.close()


def test_export_mirrors_the_limit_columns(tmp_path):
    """M103: the limits are a read-only mirror; only net / TP stay editable."""
    path = str(tmp_path / "review.xlsx")
    export_to_excel(_model(), path)
    wb = load_workbook(path)
    try:
        ws = wb["Power"]
        for title in ("Net name", "Test point"):
            idx = _header_index(ws, title)
            assert ws.cell(row=1, column=idx).value == \
                title + STRUCTURE_EDITABLE_SUFFIX
            assert _rgb(ws.cell(row=1, column=idx)) == EDITABLE_FILL_RGB
            assert ws.cell(row=2, column=idx).protection.locked is False
        for title in ("R-GND Min limit (ohm)", "Nominal (V)",
                      "Lower (V)", "Upper (V)"):
            idx = _header_index(ws, title)
            assert ws.cell(row=1, column=idx).value == title + MIRROR_SUFFIX
            assert _rgb(ws.cell(row=2, column=idx)) == READONLY_FILL_RGB
            assert ws.cell(row=2, column=idx).protection.locked is True
        for title in ("R-GND", "Power rails", "Voltage"):
            idx = _header_index(ws, title)
            assert ws.cell(row=1, column=idx).value == \
                title + READONLY_SUFFIX
            assert ws.cell(row=2, column=idx).protection.locked is True
        ws = wb["Clock"]
        for title in ("Nominal (kHz)", "Lower (kHz)", "Upper (kHz)"):
            idx = _header_index(ws, title)
            assert ws.cell(row=1, column=idx).value == title + MIRROR_SUFFIX
            assert ws.cell(row=2, column=idx).protection.locked is True
        for title in ("Net name", "Test point"):
            assert ws.cell(
                row=2, column=_header_index(ws, title)).protection.locked \
                is False
        ws = wb["GPIO"]
        assert ws.cell(row=2, column=_header_index(
            ws, "Net name")).protection.locked is False
        assert ws.cell(row=2, column=_header_index(
            ws, "DIO Channel")).protection.locked is True
    finally:
        wb.close()


def test_limit_whitelist_matches_the_directive():
    assert ALLOC_LIMIT_KEYS["power"] == (
        "r_gnd_min_ohm", "nominal_v", "lower_v", "upper_v")
    assert ALLOC_LIMIT_KEYS["clock"] == (
        "nominal_khz", "lower_khz", "upper_khz")
    assert ALLOC_LIMIT_KEYS["gpio"] == ()
