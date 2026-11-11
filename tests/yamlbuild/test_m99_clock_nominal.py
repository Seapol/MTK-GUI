# -*- coding: utf-8 -*-
"""M99-3: a project clock nominal belongs to the project (Clock
allocation column), never to the algorithm."""
from __future__ import annotations

from openpyxl import load_workbook

from mtkgui.gui.yamlbuild.channel_allocation import AllocatedRow
from mtkgui.gui.yamlbuild.excel_io import export_to_excel, import_from_excel
from mtkgui.gui.yamlbuild.ict_sequence import auto_fill_limits
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.ict.netparse import confidence


def _model() -> YamlBuildModel:
    model = YamlBuildModel()
    model.enable_all()
    # the review workbook validates the required product fields on import
    model.set_params("design_input", {
        "product_id": "IMXRT700", "part_number": "MTK12345",
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "MP (Production)"})
    model.set_channel_allocation({
        "clock": [AllocatedRow(
            net="DMIC_CLK", test_point="SJ210.1",
            se_clock_hz="U2355A CTR0", band="0.1 Hz ~ 6 MHz",
            nominal_khz="3072.000", lower_khz="3071.846",
            upper_khz="3072.154").to_dict()],
    })
    return model


def _column(ws, title: str) -> int:
    for index, cell in enumerate(ws[1], start=1):
        if str(cell.value or "").startswith(title):
            return index
    raise AssertionError(f"column {title!r} not found")


def test_clock_nominal_column_round_trips_excel(tmp_path):
    """The Clock sheet carries the editable nominal in both directions."""
    path = str(tmp_path / "clock.xlsx")
    export_to_excel(_model(), path)
    wb = load_workbook(path)
    ws = wb["Clock"]
    column = _column(ws, "Nominal (kHz)")
    assert float(ws.cell(row=2, column=column).value) == 3072.0
    ws.cell(row=2, column=column).value = 3072.5
    wb.save(path)
    wb.close()

    model = _model()
    report = import_from_excel(model, path)
    assert report.applied is True, report.errors
    row = model.get_channel_allocation()["clock"][0]
    assert float(row["nominal_khz"]) == 3072.5


def test_auto_fill_limits_prefers_row_nominal():
    """A token-less project clock name uses the stored row nominal; no
    code-side table is consulted."""
    rows = [("test", "Clock Hz - DMIC_CLK", "Hz", "—", "—", "—")]
    testable = {"DMIC_CLK": {"category": "Clock", "nominal_khz": 3072.0}}
    _kind, _name, _unit, expected, low, high = auto_fill_limits(
        rows, testable)[0][:6]
    assert (expected, low, high) == ("3072000", "3071846", "3072154")


def test_project_net_name_not_in_algorithm():
    """DMIC_CLK is a project net - the generic parser must not know it."""
    assert confidence.clock_freq_hz("DMIC_CLK") == 0.0
    assert confidence.clock_freq_hz("CLK_24M") == 24e6
    assert confidence.clock_freq_hz("OSC32K") == 32768.0
    assert not hasattr(confidence, "_NET_NOMINAL_HZ")
