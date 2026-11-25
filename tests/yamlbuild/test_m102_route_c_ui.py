# -*- coding: utf-8 -*-
"""M102b: Route C import on node 01 + read-only skipped node 02."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
)

from mtkgui.gui.yamlbuild.design_input_panel import (  # noqa: E402
    DesignInputPanel,
)
from mtkgui.gui.yamlbuild.parse_nets_v2_panel import (  # noqa: E402
    ParseNetsV2Panel,
)
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402
from tests.yamlbuild.test_route_c import _make_sheet  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _patch_file_dialog(monkeypatch, path) -> None:
    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(path), "")))


def _import(wizard, monkeypatch, path):
    design = wizard._panels["design_input"]
    design.radio_mtk.setChecked(True)
    _patch_file_dialog(monkeypatch, path)
    design._import_mtk_sheet()
    return design


# ------------------------------------------------------------- node 01
def test_route_c_radio_round_trips_ict_route_key(qapp):
    panel = DesignInputPanel()
    try:
        assert panel.radio_mtk.text() == "Route C - MTK ICT Excel Sheet"
        panel.radio_mtk.setChecked(True)
        assert panel.values()["ict_route"] == "mtk_sheet"
        panel.set_values({"ict_route": "mtk_sheet"})
        assert panel.radio_mtk.isChecked()
        panel.set_values({"ict_route": "weird"})
        assert panel.radio_files.isChecked()
        assert panel.values()["ict_route"] == "files"
    finally:
        panel.deleteLater()


def test_route_c_import_is_rejected_without_touching_path(
        qapp, tmp_path, monkeypatch):
    bad = _make_sheet(
        tmp_path / "bad.xlsx",
        voltage=[("VDD_1V8", "TP9.1", 1.71, 1.8, 1.89),
                 ("VDD_3V3", "TP2.1", 3.135, 3.3, 3.465)])
    panel = DesignInputPanel()
    try:
        panel.radio_mtk.setChecked(True)
        _patch_file_dialog(monkeypatch, bad)
        monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
        panel._import_mtk_sheet()
        assert panel.values()["ict_mtk_sheet_file"] == ""
        assert panel.lbl_mtk.text() == "Sheet: (not imported)"
    finally:
        panel.deleteLater()


def test_route_c_import_emits_result(qapp, tmp_path, monkeypatch):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    panel = DesignInputPanel()
    got: list = []
    panel.mtk_sheet_imported.connect(got.append)
    try:
        panel.radio_mtk.setChecked(True)
        _patch_file_dialog(monkeypatch, path)
        panel._import_mtk_sheet()
        assert len(got) == 1
        assert got[0].summary().startswith("Power 2")
        assert panel.lbl_mtk_note.text() == got[0].summary()
        assert panel.values()["ict_mtk_sheet_file"].endswith("mtk.xlsx")
    finally:
        panel.deleteLater()


# ------------------------------------------------------------- node 02
def test_node02_loads_route_c_read_only(qapp, tmp_path):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    panel = ParseNetsV2Panel()
    try:
        ok, error = panel.load_route_c(path)
        assert ok is True and error == ""
        assert panel.state().route == "mtk_sheet"
        assert panel.lbl_summary.text().startswith("Power ")
        assert panel.table.editTriggers() == \
            QAbstractItemView.EditTrigger.NoEditTriggers
        # Route C has no editable Category combo and no Move controls
        assert panel.table.cellWidget(0, 1) is None
        assert not panel.btn_up.isEnabled()
        assert not panel.btn_down.isEnabled()
        assert not panel.table_other.isEnabled()
        # Parse / Import / Export controls are absent on Route C
        assert not panel.btn_parse.isVisible()
        assert panel.state().rows[0].sub_type == "MTK sheet"
    finally:
        panel.deleteLater()


def test_node02_is_skipped_and_opens_read_only(
        qapp, tmp_path, monkeypatch):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    wizard = YamlBuildWizard()
    try:
        _import(wizard, monkeypatch, path)
        qapp.processEvents()
        assert wizard.flow.step_state("parse_ict") == "skipped"
        assert wizard._is_complete("parse_ict") is True
        assert wizard._is_editable("parse_ict") is False
        texts: list = []

        def fake_exec(dialog):
            texts.extend(label.text() for label in
                         dialog.findChildren(QLabel))
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        wizard._open_step_dialog("parse_ict")
        assert any(text.startswith("Skipped —") for text in texts)
        assert not any(text.startswith("Prerequisites not finished")
                       for text in texts)
        assert wizard._panels["parse_ict"].isEnabled() is False
    finally:
        wizard.deleteLater()


# --------------------------------------------------------- allocation
def test_route_c_import_seeds_allocation_limits(
        qapp, tmp_path, monkeypatch):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    wizard = YamlBuildWizard()
    try:
        _import(wizard, monkeypatch, path)
        alloc = wizard.model.get_channel_allocation()
        power = {row["net"]: row for row in alloc["power"]}
        assert set(power) == {"VDD_1V8", "VDD_3V3"}
        assert power["VDD_1V8"]["test_point"] == "TP1.1"
        assert power["VDD_1V8"]["r_gnd_min_ohm"] == "8"
        assert power["VDD_1V8"]["lower_v"] == "1.710"
        assert power["VDD_1V8"]["upper_v"] == "1.890"
        clock = {row["net"]: row for row in alloc["clock"]}
        assert clock["CLK_32K"]["lower_khz"] == "32.767"
        assert clock["CLK_32K"]["upper_khz"] == "32.769"
        # Route C never seeds GPIO rows and never touches power_rails
        # (the in-memory row keeps UNSET placeholders; the YAML prunes)
        assert alloc["gpio"] == []
        assert power["VDD_1V8"]["power_rails"] == "—"
        nets = wizard.model.get_parsed_nets()
        assert nets["route"] == "mtk_sheet"
        assert nets["power_nets"] == ["VDD_1V8", "VDD_3V3"]
        assert nets["other_nets"] == []
    finally:
        wizard.deleteLater()


def test_route_c_reimport_keeps_channel_and_refreshes_limits(
        qapp, tmp_path, monkeypatch):
    path = _make_sheet(tmp_path / "mtk.xlsx")
    wizard = YamlBuildWizard()
    try:
        _import(wizard, monkeypatch, path)
        alloc = wizard.model.get_channel_allocation()
        power = {row["net"]: row for row in alloc["power"]}
        power["VDD_1V8"]["instrument"] = "DAQ973A"
        power["VDD_1V8"]["channel"] = "AI00"
        wizard.model.set_channel_allocation(alloc)

        corrected = _make_sheet(
            tmp_path / "mtk2.xlsx",
            voltage=[("VDD_1V8", "TP1.1", 1.750, 1.8, 1.850),
                     ("VDD_3V3", "TP2.1", 3.135, 3.3, 3.465)])
        _patch_file_dialog(monkeypatch, corrected)
        wizard._panels["design_input"]._import_mtk_sheet()

        power = {row["net"]: row
                 for row in wizard.model.get_channel_allocation()["power"]}
        # the operator's resource cells survive the corrected re-import
        assert power["VDD_1V8"]["instrument"] == "DAQ973A"
        assert power["VDD_1V8"]["channel"] == "AI00"
        # ... and the limits come from the new sheet
        assert power["VDD_1V8"]["lower_v"] == "1.750"
        assert power["VDD_1V8"]["upper_v"] == "1.850"
    finally:
        wizard.deleteLater()


def test_route_c_allocation_rows_carry_tolerance_and_source(
        qapp, tmp_path, monkeypatch):
    path = _make_sheet(
        tmp_path / "mtk.xlsx",
        clock=[("CLK_SYM", "TP3.1", 32.768, 30.5),
               ("CLK_MAN", "TP4.1", 32.768, 30.5)],
        clock_limits=[None, (32.760, 32.775)])
    wizard = YamlBuildWizard()
    try:
        _import(wizard, monkeypatch, path)
        clock = {row["net"]: row
                 for row in wizard.model.get_channel_allocation()["clock"]}
        assert clock["CLK_SYM"]["tolerance_ppm"] == "30.5"
        assert clock["CLK_SYM"]["limits_source"] in ("", "—")
        assert clock["CLK_MAN"]["tolerance_ppm"] == "30.5"
        assert clock["CLK_MAN"]["limits_source"] == "manual"
        assert clock["CLK_MAN"]["lower_khz"] == "32.760"
        assert clock["CLK_MAN"]["upper_khz"] == "32.775"
    finally:
        wizard.deleteLater()
