# -*- coding: utf-8 -*-
"""M73: Excel review-only guard.

Export: every sheet is protected (no password); the YamlBuild sheet is
fully read-only; the Power / Clock sheets unlock ONLY the whitelisted
limit columns; GPIO stays read-only.  Import: only the whitelisted
limit fields are applied - structure / module parameters / enable
flags are ignored (and reported), a structural error aborts with zero
applied changes.
"""
from __future__ import annotations

import pytest

from openpyxl import load_workbook

from mtkgui.gui.yamlbuild.excel_io import (
    ALLOC_LIMIT_KEYS,
    EDITABLE_FILL_RGB,
    EDITABLE_SUFFIX,
    READONLY_FILL_RGB,
    READONLY_SUFFIX,
    SHEET_NAME,
    export_to_excel,
    import_from_excel,
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
            dio_channel=GPIO_DIO_CHANNELS[0],
            op_type="U2355A DIO Write", drive_level="High").to_dict()],
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
        # YamlBuild: every column read-only (incl. Enabled / Remarks)
        ws = wb[SHEET_NAME]
        for idx in range(1, ws.max_column + 1):
            header = ws.cell(row=1, column=idx)
            assert str(header.value).endswith(READONLY_SUFFIX)
            assert _rgb(header) == READONLY_FILL_RGB
            cell = ws.cell(row=2, column=idx)
            assert cell.protection.locked is True
            assert _rgb(cell) == READONLY_FILL_RGB
    finally:
        wb.close()


def test_export_unlocks_only_the_limit_columns(tmp_path):
    path = str(tmp_path / "review.xlsx")
    export_to_excel(_model(), path)
    wb = load_workbook(path)
    try:
        ws = wb["Power"]
        for title in ("R-GND Min limit (ohm)", "Nominal (V)",
                      "Lower (V)", "Upper (V)"):
            idx = _header_index(ws, title)
            header = ws.cell(row=1, column=idx)
            assert header.value == title + EDITABLE_SUFFIX
            assert _rgb(header) == EDITABLE_FILL_RGB
            cell = ws.cell(row=2, column=idx)
            assert cell.protection.locked is False
            assert _rgb(cell) == EDITABLE_FILL_RGB
        for title in ("Net name", "Test point", "R-GND",
                      "Power rails", "Voltage"):
            idx = _header_index(ws, title)
            assert _rgb(ws.cell(row=2, column=idx)) == READONLY_FILL_RGB
            assert ws.cell(row=2, column=idx).protection.locked is True
        ws = wb["Clock"]
        for title in ("Nominal (kHz)", "Lower (kHz)", "Upper (kHz)"):
            idx = _header_index(ws, title)
            assert ws.cell(row=2, column=idx).protection.locked is False
        # GPIO has NO editable column (all locked)
        ws = wb["GPIO"]
        for idx in range(1, ws.max_column + 1):
            assert ws.cell(row=2, column=idx).protection.locked is True
    finally:
        wb.close()


def test_limit_whitelist_matches_the_directive():
    assert ALLOC_LIMIT_KEYS["power"] == (
        "r_gnd_min_ohm", "nominal_v", "lower_v", "upper_v")
    assert ALLOC_LIMIT_KEYS["clock"] == (
        "nominal_khz", "lower_khz", "upper_khz")
    assert ALLOC_LIMIT_KEYS["gpio"] == ()


# --------------------------------------------------------------- import
def test_import_applies_limits_and_ignores_structure(tmp_path):
    path = str(tmp_path / "review.xlsx")
    export_to_excel(_model(), path)
    wb = load_workbook(path)
    ws = wb["Power"]
    ws.cell(row=2, column=_header_index(ws, "R-GND Min limit (ohm)")).value \
        = "2.000"
    # a structural edit (test point) must never be applied
    ws.cell(row=2, column=_header_index(ws, "Test point")).value = "TP9.9"
    wb[SHEET_NAME].cell(
        row=next(r for r in range(2, wb[SHEET_NAME].max_row + 1)
                 if wb[SHEET_NAME].cell(row=r, column=3).value
                 == "on_voltage_v"),
        column=4).value = "9.0"
    wb.save(path)

    target = _model()
    before_params = target.get_params("rails")
    report = import_from_excel(target, path)
    assert report.applied, report.errors
    assert report.errors == []
    # exactly the one edited limit was applied
    assert report.applied_changes == ["Power VDD_3V3: r_gnd_min_ohm"]
    assert target.get_channel_allocation()["power"][0]["r_gnd_min_ohm"] \
        == "2.000"
    # structure unchanged (test point / resources / op type / drive level)
    power = target.get_channel_allocation()["power"][0]
    assert power["test_point"] == "TP1.1"
    assert power["impedance"] == DAQM908A_SENSE_CHANNELS[0]
    assert target.get_channel_allocation()["gpio"][0]["op_type"] \
        == "U2355A DIO Write"
    # YamlBuild review-only: the module value stays, difference ignored
    assert target.get_params("rails") == before_params
    assert any("test point" in item for item in report.ignored_changes)
    assert any("YamlBuild" in item for item in report.ignored_changes)


def test_import_missing_net_aborts_without_applying(tmp_path):
    path = str(tmp_path / "review.xlsx")
    model = _model()
    export_to_excel(model, path)
    wb = load_workbook(path)
    ws = wb["Power"]
    ws.cell(row=2,
            column=_header_index(ws, "R-GND Min limit (ohm)")).value = "8.000"
    ws.cell(row=2, column=_header_index(ws, "Net name")).value = ""
    wb.save(path)

    before = model.get_channel_allocation()
    report = import_from_excel(model, path)
    assert not report.applied
    assert any("Net name required" in e for e in report.errors)
    assert report.applied_changes == []
    assert model.get_channel_allocation() == before


def test_import_new_row_is_never_created(tmp_path):
    path = str(tmp_path / "review.xlsx")
    model = _model()
    export_to_excel(model, path)
    wb = load_workbook(path)
    ws = wb["Power"]
    ws.append(["VDD_NEW", "TP4.1", DAQM908A_SENSE_CHANNELS[1],
               U2355A_AI_CHANNELS[1], DAQM908A_SENSE_CHANNELS[1],
               "2.000", "1.100", "1.000", "1.200"])
    wb.save(path)

    before = model.get_channel_allocation()
    report = import_from_excel(model, path)
    assert report.applied
    assert model.get_channel_allocation() == before
    assert any("row not on the model" in item
               for item in report.ignored_changes)


def test_legacy_workbook_keeps_limit_values(tmp_path):
    """Pre-M70 workbook (no limit columns) still imports: nothing
    applied, the current model limits survive."""
    path = str(tmp_path / "legacy.xlsx")
    export_to_excel(_model(), path)
    wb = load_workbook(path)
    for sheet, titles in (("Power", ("R-GND Min limit (ohm)", "Nominal (V)",
                                     "Lower (V)", "Upper (V)")),
                          ("Clock", ("Nominal (kHz)", "Lower (kHz)",
                                     "Upper (kHz)"))):
        ws = wb[sheet]
        header = [cell.value for cell in ws[1]]
        for title in titles:
            idx = next(i for i, value in enumerate(header)
                       if str(value or "").startswith(title))
            ws.delete_cols(idx + 1)
            header.pop(idx)
    wb.save(path)

    target = _model()
    before = target.get_channel_allocation()
    report = import_from_excel(target, path)
    assert report.applied, report.errors
    assert report.errors == []
    assert report.applied_changes == []
    assert target.get_channel_allocation() == before
