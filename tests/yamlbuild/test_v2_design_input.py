# -*- coding: utf-8 -*-
"""v2-3b: node 01 Design Input — three blocks, new keys, validation."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QGroupBox  # noqa: E402

from mtkgui.gui.yamlbuild.design_input_panel import DesignInputPanel  # noqa: E402
from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.gui.yamlbuild.schema import fields_for  # noqa: E402


@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


def _panel(qapp) -> DesignInputPanel:
    return DesignInputPanel()


def test_node01_blocks_in_order(qapp):
    panel = _panel(qapp)
    try:
        boxes = [b.title() for b in panel.findChildren(QGroupBox)]
        assert boxes == ["Product Information",
                         "Design Files for ICT",
                         "Pre-Configure for FCT"]
    finally:
        panel.deleteLater()


def test_node01_field_labels():
    labels = [spec.label for spec in fields_for("design_input")[:5]]
    assert labels == ["Product Part #", "Core ID", "FSW Version",
                      "HW Revision", "Batch #"]


def test_design_input_field_names():
    model = YamlBuildModel()
    design = model.to_effective_dict()["yaml_build"]["modules"]["design_input"]
    for key in ("part_number", "product_id", "sw_version", "hw_version",
                "batch", "ict_block_enabled", "ict_route", "ict_excel_file",
                "fct_block_enabled", "dut_board_software",
                "fct_supported_tests"):
        assert key in design, key


def test_node01_excel_route_disables_imports(qapp):
    panel = _panel(qapp)
    try:
        assert panel.btn_import_spf.isEnabled()
        panel.radio_excel.setChecked(True)
        assert not panel.btn_import_spf.isEnabled()
        assert not panel.btn_import_net.isEnabled()
        assert not panel.btn_import_bom.isEnabled()
        assert panel.btn_import_excel.isEnabled()
        # back to files re-enables them
        panel.radio_files.setChecked(True)
        assert panel.btn_import_spf.isEnabled()
    finally:
        panel.deleteLater()


def test_node01_requires_one_block_enabled(qapp):
    panel = _panel(qapp)
    try:
        panel.chk_ict.setChecked(False)
        panel.chk_fct.setChecked(False)
        ok, msg = panel.validate()
        assert ok is False
        assert msg == "At least one of ICT / FCT must be enabled"
    finally:
        panel.deleteLater()


def test_node01_next_creates_tree(qapp, tmp_path, monkeypatch):
    from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard
    from PySide6.QtWidgets import QDialog

    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    model = YamlBuildModel()
    model.set_params("design_input", {
        "part_number": "MTK12345", "product_id": "96317",
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "EVT (Proto-1)", "spf_file": "s.pdf",
        "net_file": "n.net", "bom_file": "b.csv",
    })
    w = YamlBuildWizard(model)
    try:
        # push the panel values into the model so validation passes
        w._panels["design_input"].set_values(model.get_params("design_input"))
        w._on_next()
        assert (tmp_path / "work" / "96317" / "sources").is_dir()
    finally:
        w.deleteLater()
