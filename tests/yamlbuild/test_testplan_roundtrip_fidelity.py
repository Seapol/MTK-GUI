# -*- coding: utf-8 -*-
"""M91-C3: the Test Plan round trip must not lose a row or a test point.

Pure engine test (no Qt, no GUI): the workbook is built by hand, imported
through the same two entry points the GUI uses (``testplan_to_yaml`` with no
parse result / ``yaml_to_testplan``), and every count is read back from the
written .xlsx, never from the Python objects used to build it.
"""
from __future__ import annotations

from openpyxl import Workbook, load_workbook

from mtkgui.gui.yamlbuild.excel_io import (
    SHEET_NAME as PARAM_SHEET,
    export_to_excel,
    import_from_excel,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.power_alloc import GPIO_DIO_CHANNELS
from mtkgui.gui.yamlbuild.testplan_sync import (
    testplan_to_yaml as import_plan,
    yaml_to_testplan as export_plan,
)
from mtkgui.ict.netparse.export_testplan import (
    CLOCK_HEADER,
    CONTROL_IO_HEADER,
    GND_HEADER,
    OTHERS_HEADER,
    POWER_HEADER,
    SHEET_CLOCK,
    SHEET_CONTROL_IO,
    SHEET_GND,
    SHEET_OTHERS,
    SHEET_POWER,
    SHEET_SUMMARY,
)

POINTS = ["TP72.1", "TP72.2", "TP72.3", "TP72.4", "TP72.5"]
NET_SHEETS = (SHEET_POWER, SHEET_CLOCK, SHEET_CONTROL_IO, SHEET_GND,
              SHEET_OTHERS)
EXPECTED_PER_SHEET = {SHEET_POWER: 10, SHEET_CLOCK: 1,
                      SHEET_CONTROL_IO: 5, SHEET_GND: 2, SHEET_OTHERS: 3}


# ---------------------------------------------------------------- fixture
def _build_workbook(path) -> str:
    """The §0 sample: 10 power rows (one with five points), 1 clock,
    5 control IO, 2 GND, 3 Others."""
    workbook = Workbook()
    summary = workbook.active
    summary.title = SHEET_SUMMARY
    summary.append(["project_name", "M91 Sample"])

    ws = workbook.create_sheet(SHEET_POWER)
    ws.append(list(POWER_HEADER))
    for index in range(1, 10):
        ws.append([f"RAIL_{index}", f"TP{index}.1", "", "3.3",
                   "", "", "", ""])
    ws.append(["DC_5V_IN", " ".join(POINTS), "", "5.0", "", "", "", ""])

    ws = workbook.create_sheet(SHEET_CLOCK)
    ws.append(list(CLOCK_HEADER))
    ws.append(["CLK_24M", "TP10.1", "24000", "23998.8", "24001.2", ""])

    ws = workbook.create_sheet(SHEET_CONTROL_IO)
    ws.append(list(CONTROL_IO_HEADER))
    for index in range(1, 6):
        ws.append([f"GPIO_{index}", f"TP2{index}.1",
                   GPIO_DIO_CHANNELS[index - 1],
                   "U2355A DIO Write", "High"])

    ws = workbook.create_sheet(SHEET_GND)
    ws.append(list(GND_HEADER))
    ws.append([0, "GND", "pcb", "TP1.2"])
    ws.append([1, "GND_DIG", "pcb", "TP9.1"])

    ws = workbook.create_sheet(SHEET_OTHERS)
    ws.append(list(OTHERS_HEADER))
    for index in range(1, 4):
        ws.append(["unclassified", f"USB_{index}",
                   "fallback:unclassified"])

    workbook.save(path)
    return str(path)


def _rows(path, sheet) -> list:
    workbook = load_workbook(path)
    try:
        return list(workbook[sheet].iter_rows(min_row=2, values_only=True))
    finally:
        workbook.close()


def _counts(path) -> dict:
    return {sheet: len(_rows(path, sheet)) for sheet in NET_SHEETS}


def _cell_of(path, sheet, net, column=0) -> str:
    for row in _rows(path, sheet):
        if str(row[0]) == net:
            return str(row[column] or "")
    raise AssertionError(f"{net} missing from {sheet}")


def _setup_model(path) -> YamlBuildModel:
    """Import the sample workbook and fill the fields the GUI would fill."""
    model = YamlBuildModel()
    import_plan(model, path)
    model.set_params("design_input", {
        "product_id": "IMXRT700", "part_number": "MTK12345",
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "MP (Production)"})
    model.set_params("instruments", {
        "psu_visa": "TCPIP0::192.168.1.20::inst0",
        "daq_visa": "GPIB0::9::INSTR", "dmm_visa": "",
        "self_test": "true"})
    return model


# ------------------------------------------------------------------ tests
def test_workbook_only_import_keeps_every_row_and_point(tmp_path):
    model = YamlBuildModel()
    import_plan(model, _build_workbook(tmp_path / "in.xlsx"))
    records = model.ict_test_plan["records"]
    assert len(records) == sum(EXPECTED_PER_SHEET.values())
    assert records["DC_5V_IN"]["test_points"] == POINTS


def test_reexport_writes_every_sheet_row_and_all_five_points(tmp_path):
    model = YamlBuildModel()
    import_plan(model, _build_workbook(tmp_path / "in.xlsx"))
    out = str(tmp_path / "out.xlsx")
    export_plan(model, out, str(tmp_path / "out.md"))
    assert _counts(out) == EXPECTED_PER_SHEET
    assert _cell_of(out, SHEET_POWER, "DC_5V_IN", column=0) == "DC_5V_IN"
    assert _cell_of(out, SHEET_POWER, "DC_5V_IN", column=1) == " ".join(POINTS)


def test_excel_numeric_edit_is_applied_without_touching_allocation(tmp_path):
    model = _setup_model(_build_workbook(tmp_path / "in.xlsx"))
    params = str(tmp_path / "params.xlsx")
    export_to_excel(model, params)
    before_allocation = model.get_channel_allocation()

    workbook = load_workbook(params)
    ws = workbook[PARAM_SHEET]
    row = next(r for r in range(2, ws.max_row + 1)
               if ws.cell(row=r, column=3).value == "on_voltage_v")
    ws.cell(row=row, column=4).value = "7.5"
    workbook.save(params)

    report = import_from_excel(model, params)
    assert report.applied, report.errors
    assert report.errors == []
    assert report.applied_changes == ["YamlBuild rails.on_voltage_v"]
    assert model.get_params("rails")["on_voltage_v"] == "7.5"
    assert model.get_channel_allocation() == before_allocation


def test_two_round_trips_keep_the_same_row_counts(tmp_path):
    model = YamlBuildModel()
    import_plan(model, _build_workbook(tmp_path / "in.xlsx"))
    first = str(tmp_path / "first.xlsx")
    export_plan(model, first, str(tmp_path / "first.md"))
    first_counts = _counts(first)

    import_plan(model, first)                 # second import, no result
    second = str(tmp_path / "second.xlsx")
    export_plan(model, second, str(tmp_path / "second.md"))
    assert _counts(second) == first_counts
    assert _cell_of(second, SHEET_POWER, "DC_5V_IN", column=1) == \
        " ".join(POINTS)
