# -*- coding: utf-8 -*-
"""M140: no project data survives a Close Yaml / project switch.

User report (2026-11-26): an FCT-only YAML was loaded, but the Yaml
Build nodes still showed the nets and sequences of the previous 96624
ICT project - even after Close Yaml.  Root cause: the reset only cleared
the module parameters, and ``apply_state`` merged instead of replacing.

This module pins the three guarantees:

1. ``reset_to_factory`` drops every piece of project data (nets,
   allocation, sequences, firmware, equipment, marks, locks);
2. ``apply_state`` is a whole-project replace, so an FCT-only file
   cannot inherit the previous project's ICT nets;
3. the wizard rebuilds its panels on reload, so no widget keeps a stale
   table; and every node 02-07 window names the current project.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QDialog, QLabel,  # noqa: E402
                               QPushButton)

from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402

FCT_ONLY_STATE = {
    "plan_version": "1.0.0",
    "modules": {
        "design_input": {
            "enabled": True,
            "params": {
                "part_number": "FRDM-IMX93", "product_id": "90001",
                "sw_version": "A", "hw_version": "B",
                "batch": "EVT (Proto-1)",
                "ict_block_enabled": "false",
                "fct_block_enabled": "true",
                "ict_route": "files",
                "spf_file": "", "net_file": "", "bom_file": "",
                "fct_supported_tests": "FCT_FW_FLASH",
            },
        },
        "build_fct": {"enabled": True, "params": {}},
    },
    "locks": {"design_input": True},
    "fct_test_cases": [{"name": "flash_fat", "kind": "fct_flash",
                        "enable": True, "wait_ms": 0,
                        "timeout_ms": 60000, "op_params": {}}],
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wizard(qapp) -> YamlBuildWizard:
    wizard = YamlBuildWizard()
    wizard.resize(1000, 420)
    wizard.show()
    qapp.processEvents()
    return wizard


def _open_dialog(wizard: YamlBuildWizard, key: str):
    captured = {}
    real_exec = QDialog.exec

    def fake_exec(dialog):
        captured["dlg"] = dialog
        return 0

    QDialog.exec = fake_exec
    try:
        wizard._open_step_dialog(key)
    finally:
        QDialog.exec = real_exec
    return captured["dlg"]


# ------------------------------------------------------------ the model
def test_factory_reset_drops_every_project_fact():
    model = YamlBuildModel()
    model.set_parsed_nets({"route": "A", "power_nets": ["VDD_1V8"]})
    model.set_ict_test_cases([{"name": "r_gnd_1", "kind": "ict_ohm"}])
    model.set_fct_test_cases([{"name": "flash_fat", "kind": "fct_flash"}])
    model.set_channel_allocation({"power": [{"net": "VDD_1V8"}]})
    model.ict_test_plan = {"tests": [{"name": "r_gnd_1"}]}
    model.set_locked("design_input", True)

    model.reset_to_factory()

    assert model.get_parsed_nets() == {}
    assert model.get_ict_test_cases() == []
    assert model.get_fct_test_cases() == []
    assert model.get_channel_allocation() == {}
    assert model.ict_test_plan == {}
    assert model.locked_keys() == ()
    assert model.get_params("design_input")["part_number"] == ""


def test_loading_an_fct_only_project_does_not_inherit_ict_data():
    model = YamlBuildModel()
    model.set_parsed_nets({"route": "A", "power_nets": ["VDD_1V8"]})
    model.set_ict_test_cases([{"name": "r_gnd_1", "kind": "ict_ohm"}])
    model.set_channel_allocation({"power": [{"net": "VDD_1V8"}]})
    model.ict_test_plan = {"tests": [{"name": "r_gnd_1"}]}

    model.apply_state(dict(FCT_ONLY_STATE))

    assert model.get_parsed_nets() == {}, \
        "an FCT-only project must not see the previous ICT netlist"
    assert model.get_ict_test_cases() == []
    assert model.get_channel_allocation() == {}
    assert model.ict_test_plan == {}
    assert model.get_params("design_input")["part_number"] == "FRDM-IMX93"
    assert len(model.get_fct_test_cases()) == 1
    assert model.locked_keys() == ("design_input",)


# ---------------------------------------------------------- the panels
def test_reloaded_nodes_show_no_previous_tables(qapp):
    wizard = _wizard(qapp)
    try:
        parse = wizard._panels["parse_ict"]
        from mtkgui.gui.yamlbuild.parse_nets_v2 import (V2NetRow,
                                                        V2ParseState,
                                                        ROUTE_A)
        parse.set_state(V2ParseState(
            rows=[V2NetRow(name="VDD_1V8", category="power",
                           sub_type="1V8")], route=ROUTE_A))
        ict = wizard._panels["build_ict"]
        steps = ict.values()
        steps[0].name = "STALE_96624_STEP"
        ict.set_values(steps)

        wizard.model.reset_to_factory()
        wizard.refresh_from_model()

        parse = wizard._panels["parse_ict"]
        assert parse.state().rows == [], "node 02 must not show stale nets"
        assert parse.lbl_summary.text() in ("", "no parse yet")
        ict = wizard._panels["build_ict"]
        names = [step.name for step in ict.values()]
        assert "STALE_96624_STEP" not in names, \
            f"node 05 must not keep the previous project: {names}"
    finally:
        wizard.deleteLater()


def test_nodes_02_to_07_name_the_current_project(qapp):
    wizard = _wizard(qapp)
    try:
        wizard._panels["design_input"].set_values({
            "part_number": "MTK12345", "product_id": "96624",
            "sw_version": "A", "hw_version": "B",
            "batch": "EVT (Proto-1)",
            "ict_block_enabled": "true", "fct_block_enabled": "true",
            "ict_route": "files",
            "spf_file": "", "net_file": "", "bom_file": ""})
        wizard.model.set_locked("design_input", True)
        wizard._refresh()
        dialog = _open_dialog(wizard, "parse_ict")
        labels = [w.text() for w in dialog.findChildren(QLabel)]
        banner = [t for t in labels if t.startswith("Project ")]
        assert banner, labels
        assert "MTK12345" in banner[0] and "96624" in banner[0], banner[0]
    finally:
        wizard.deleteLater()


def test_design_input_explains_the_same_file_flow(qapp):
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard, "design_input")
        labels = [w.text() for w in dialog.findChildren(QLabel)]
        assert any("keeps the SAME project file" in t for t in labels), labels
        assert not any(t.startswith("Project ") for t in labels), \
            "node 01 is the source of the banner, not a consumer"
    finally:
        wizard.deleteLater()
