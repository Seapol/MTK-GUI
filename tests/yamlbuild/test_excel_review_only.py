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
from mtkgui.gui.yamlbuild.channel_allocation import AllocatedRow, UNSET
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


# ------------------------------- M75 sparser real-project row key sets
#: the 12 structure keys a REAL project row carries (no limit keys)
_STRUCT_KEYS = ("net", "test_point", "instrument", "channel",
                "impedance", "power_rails", "voltage", "se_clock_hz",
                "band", "dio_channel", "digital_input", "digital_output")
#: keys actually reaching the YAML for a sparse row (UNSET dropped)
_POWER_EFF_KEYS = {"net", "test_point", "impedance", "power_rails",
                   "voltage"}
_CLOCK_EFF_KEYS = {"net", "test_point", "se_clock_hz", "band"}
_GPIO_EFF_KEYS = {"net", "test_point", "dio_channel"}


def _sparse_real_model() -> YamlBuildModel:
    """REAL project shape: empty no-UI module fields and 12-key
    allocation rows (no limit keys at all)."""
    model = _real_project_model()
    band = next(iter(CLOCK_BANDS.values()))

    def row(**kw):
        base = {key: UNSET for key in _STRUCT_KEYS}
        base.update(kw)
        return base

    model.set_channel_allocation({
        "power": [row(net="VDD_3V3", test_point="TP1.1",
                      impedance=DAQM908A_SENSE_CHANNELS[0],
                      power_rails=U2355A_AI_CHANNELS[0],
                      voltage=DAQM908A_SENSE_CHANNELS[0])],
        "clock": [row(net="CLK_24M", test_point="TP3.1",
                      se_clock_hz=CLOCK_CHANNELS[0], band=band)],
        "gpio": [row(net="GPIO_RST", test_point="TP2.1",
                     dio_channel=GPIO_DIO_CHANNELS[0])],
    })
    return model


def _alloc_rows(model: YamlBuildModel) -> dict:
    return model.to_effective_dict()["yaml_build"]["channel_allocation"]


def test_limit_edit_adds_exactly_its_own_key(tmp_path):
    """M75: editing one Power limit adds ONE key to that row; the
    other rows keep their 12 keys and no cross-type key appears."""
    source = _sparse_real_model()
    path = str(tmp_path / "sparse.xlsx")
    export_to_excel(source, path)
    wb = load_workbook(path)
    ws = wb["Power"]
    ws.cell(row=2, column=_header_index(ws, "Nominal (V)")).value = "3.300"
    wb.save(path)

    target = _sparse_real_model()
    report = import_from_excel(target, path)
    assert report.applied, report.errors
    assert report.errors == []
    assert report.applied_changes == ["Power VDD_3V3: nominal_v"]
    assert report.ignored_changes == []
    rows = _alloc_rows(target)
    power = rows["power"][0]
    assert set(power) == _POWER_EFF_KEYS | {"nominal_v"}
    assert "nominal_khz" not in power          # no clock key in power
    assert "lower_v" not in power
    assert set(rows["clock"][0]) == _CLOCK_EFF_KEYS
    assert set(rows["gpio"][0]) == _GPIO_EFF_KEYS
    # UNSET placeholders never reach the YAML (the next save cleans
    # the legacy "—" keys - see the M75 report)
    assert UNSET not in target.to_effective_yaml()
    # the in-memory table keeps its display placeholders for the GUI /
    # Excel + exactly the one new limit key
    assert len(target.get_channel_allocation()["power"][0]) == 13
    assert len(target.get_channel_allocation()["clock"][0]) == 12
    assert len(target.get_channel_allocation()["gpio"][0]) == 12


def test_sparse_round_trip_is_zero_drift(tmp_path):
    """M75: a REAL 12-key workbook re-imported unchanged applies
    nothing, ignores nothing and keeps the effective YAML identical."""
    source = _sparse_real_model()
    path = str(tmp_path / "sparse.xlsx")
    export_to_excel(source, path)

    target = _sparse_real_model()
    before = target.to_effective_yaml()
    report = import_from_excel(target, path)
    assert report.applied, report.errors
    assert report.errors == []
    assert report.applied_changes == []
    assert report.ignored_changes == []
    assert target.to_effective_yaml() == before
    for kind in ("power", "clock", "gpio"):
        assert set(target.get_channel_allocation()[kind][0]) \
            == set(_STRUCT_KEYS)


def test_clock_limit_edit_only_adds_upper_khz(tmp_path):
    """M75: a Clock Upper edit adds only upper_khz (no power keys)."""
    source = _sparse_real_model()
    path = str(tmp_path / "sparse.xlsx")
    export_to_excel(source, path)
    wb = load_workbook(path)
    ws = wb["Clock"]
    ws.cell(row=2, column=_header_index(ws, "Upper (kHz)")).value \
        = "24009.000"
    wb.save(path)

    target = _sparse_real_model()
    report = import_from_excel(target, path)
    assert report.applied, report.errors
    assert report.applied_changes == ["Clock CLK_24M: upper_khz"]
    rows = _alloc_rows(target)
    clock = rows["clock"][0]
    assert set(clock) == _CLOCK_EFF_KEYS | {"upper_khz"}
    assert "nominal_v" not in clock
    assert set(rows["power"][0]) == _POWER_EFF_KEYS
    assert set(rows["gpio"][0]) == _GPIO_EFF_KEYS


# ------------------------------------ M74 no-UI module empty cells
def _real_project_model() -> YamlBuildModel:
    """A REAL project: the no-UI module text fields (Rail Sequence /
    Clock Definitions / Pin Groups) are EMPTY - their values live on the
    Test Work Flow page / channel allocation."""
    model = _model()
    model.set_params("rails", {**model.get_params("rails"),
                               "sequence": ""})
    model.set_params("clocks", {**model.get_params("clocks"),
                                "clocks": ""})
    model.set_params("gpios", {**model.get_params("gpios"),
                               "groups": ""})
    return model


def test_no_ui_modules_empty_round_trip_is_zero_drift(tmp_path):
    """M74: a REAL project workbook imports without the false
    "value required" abort; nothing is applied and nothing ignored."""
    source = _real_project_model()
    path = str(tmp_path / "real.xlsx")
    export_to_excel(source, path)

    target = _real_project_model()
    before_dict = target.to_effective_dict()
    before_alloc = target.get_channel_allocation()
    before_params = {key: target.get_params(key) for key in (
        "rails", "clocks", "gpios", "design_input", "parse_ict",
        "instruments", "fct_build")}
    before_states = {key: target.is_enabled(key) for key in before_params}
    report = import_from_excel(target, path)
    assert report.applied, report.errors
    assert report.errors == []
    assert report.applied_changes == []
    assert report.ignored_changes == []
    assert target.to_effective_dict() == before_dict
    assert target.get_channel_allocation() == before_alloc
    for key, params in before_params.items():
        assert target.get_params(key) == params
    for key, state in before_states.items():
        assert target.is_enabled(key) == state


def test_no_ui_modules_filled_cells_are_still_validated(tmp_path):
    """A FILLED cell of a no-UI module still goes through the normal
    schema validation - the M74 skip applies to EMPTY cells only."""
    source = _real_project_model()
    path = str(tmp_path / "real.xlsx")
    export_to_excel(source, path)
    wb = load_workbook(path)
    ws = wb[SHEET_NAME]
    for row in ws.iter_rows(min_row=2):
        if row[2].value == "stabilize_ms":     # Clocks (no-UI) int field
            row[3].value = "99999"             # above maximum 10000
    wb.save(path)

    target = _real_project_model()
    report = import_from_excel(target, path)
    assert not report.applied
    assert any("Stabilize Time" in e for e in report.errors)


def test_no_ui_empty_plus_limit_edits_applies_limits(tmp_path):
    """Zero-drift base + Power Nominal / Clock Upper edits -> exactly
    the two limit changes are applied."""
    source = _real_project_model()
    path = str(tmp_path / "real.xlsx")
    export_to_excel(source, path)
    wb = load_workbook(path)
    ws = wb["Power"]
    ws.cell(row=2, column=_header_index(ws, "Nominal (V)")).value = "3.600"
    ws = wb["Clock"]
    ws.cell(row=2, column=_header_index(ws, "Upper (kHz)")).value \
        = "24009.000"
    wb.save(path)

    target = _real_project_model()
    report = import_from_excel(target, path)
    assert report.applied, report.errors
    assert report.errors == []
    assert report.applied_changes == [
        "Power VDD_3V3: nominal_v", "Clock CLK_24M: upper_khz"]
    assert target.get_channel_allocation()["power"][0]["nominal_v"] \
        == "3.600"
    assert target.get_channel_allocation()["clock"][0]["upper_khz"] \
        == "24009.000"


def test_no_ui_empty_plus_structure_edit_is_ignored(tmp_path):
    """Zero-drift base + a structural edit -> ignored, model unchanged
    (no false abort from the empty no-UI module fields)."""
    source = _real_project_model()
    path = str(tmp_path / "real.xlsx")
    export_to_excel(source, path)
    wb = load_workbook(path)
    ws = wb["GPIO"]
    ws.cell(row=2, column=_header_index(ws, "DIO Channel")).value \
        = GPIO_DIO_CHANNELS[1]
    wb.save(path)

    target = _real_project_model()
    before = target.get_channel_allocation()
    report = import_from_excel(target, path)
    assert report.applied, report.errors
    assert report.errors == []
    assert report.applied_changes == []
    assert target.get_channel_allocation() == before
    assert any("dio channel" in item for item in report.ignored_changes)
