# -*- coding: utf-8 -*-
"""M37: unified available_ops gray-out in both step editors.

The configured resources decide which standard operations may be
added: DIO operations need the ICT Control IO nets, Init / Reset need
a configured instrument, fixture operations need a configured fixture.
``None`` = everything usable (Virtual mode).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine import (  # noqa: E402
    DIO_OPS,
    FIXTURE_OPS,
    INSTRUMENT_OPS,
    OP_STEPS,
)
from mtkgui.gui.steps_editor import StepsEditorDialog  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)
from mtkgui.gui.yamlbuild import block_flow as block_flow_module  # noqa: E402
from mtkgui.gui.yamlbuild.model import (  # noqa: E402
    YamlBuildModel,
    available_ops,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _op_actions(menu):
    """Menu actions whose label is an "Operation: <catalog name>" entry
    (the "Operation: Custom" entry is not a catalog operation)."""
    return {act.text(): act for act in menu.actions()
            if act.text().startswith("Operation: ")
            and act.text() != "Operation: Custom"}


def _editor(kind, available):
    """Minimal single-row editor for one kind (available=None -> all)."""
    if kind == "ict":
        return StepsEditorDialog(
            "ict", [("op", "Power On DUT", "—", "—", "—", "—")],
            [True], [100], [5000], available_ops=available)
    return StepsEditorDialog(
        "fct", ["Power On DUT"], [True], [100], [5000],
        kinds=["op"], available_ops=available)


# ------------------------------------------------------------ model helper
def test_available_ops_none_means_everything():
    """Virtual mode passes None: every standard operation is usable."""
    model = YamlBuildModel()
    assert available_ops(model, virtual=True) is None


def test_available_ops_empty_project_greys_every_group():
    """A blank project has no GPIO nets / instruments / fixture -> the
    three resource groups are unavailable, Power stays usable."""
    model = YamlBuildModel()
    ops = available_ops(model)
    assert "Power On DUT" in ops
    assert "Power Off DUT" in ops
    assert not set(DIO_OPS) & ops
    assert not set(INSTRUMENT_OPS) & ops
    assert not set(FIXTURE_OPS) & ops


def test_available_ops_equipment_section_restores_groups():
    """The project-file equipment section is read directly off the
    model (``_equipment_doc`` set by apply_yaml_dict)."""
    model = YamlBuildModel()
    model.apply_yaml_dict({
        "yaml_build": {"modules": {}},
        "equipment": {"u2355a": {"title": "U2355A"},
                      "fixture": {"title": "Fixture Probe Board"}}})
    assert model._equipment_doc["u2355a"]["title"] == "U2355A"
    ops = available_ops(model)
    assert set(INSTRUMENT_OPS) <= ops
    assert set(FIXTURE_OPS) <= ops
    assert not set(DIO_OPS) & ops      # still no GPIO nets
    model.gpio_allocation = [{"net": "GPIO_IN"}]
    assert set(DIO_OPS) <= available_ops(model)


# --------------------------------------------------------------- gating
def test_none_available_ops_enables_every_operation(qapp):
    """None = all available: no operation entry is grayed."""
    dlg = _editor("fct", None)
    acts = _op_actions(dlg.btn_add.menu())
    assert acts
    assert all(act.isEnabled() for act in acts.values())


@pytest.mark.parametrize("kind", ["ict", "fct"])
def test_empty_available_ops_greys_every_operation(qapp, kind):
    """An empty set = nothing usable: every "Operation: <name>" entry
    is disabled, Custom / Delay stay added-able."""
    dlg = _editor(kind, set())
    acts = _op_actions(dlg.btn_add.menu())
    assert len(acts) == len(OP_STEPS)
    assert all(not act.isEnabled() for act in acts.values())
    others = [act for act in dlg.btn_add.menu().actions()
              if not act.text().startswith("Operation: ")]
    assert others and all(act.isEnabled() for act in others)


@pytest.mark.parametrize("kind", ["ict", "fct"])
def test_subset_available_ops_enables_only_the_subset(qapp, kind):
    """Only the named operations stay usable."""
    dlg = _editor(kind, {"Power On DUT"})
    acts = _op_actions(dlg.btn_add.menu())
    assert acts["Operation: Power On DUT"].isEnabled()
    assert not acts["Operation: Init Instruments"].isEnabled()
    assert not acts["Operation: U2355A DIO Read"].isEnabled()


@pytest.mark.parametrize("kind", ["ict", "fct"])
def test_grayed_operation_tooltips_name_the_fix(qapp, kind):
    """Each grayed operation explains WHICH configuration unblocks it."""
    dlg = _editor(kind, set())
    acts = _op_actions(dlg.btn_add.menu())
    assert "Control IO Nets" in acts["Operation: U2355A DIO Read"] \
        .toolTip()
    assert "instruments (Equipment page)" in \
        acts["Operation: Init Instruments"].toolTip()
    assert "fixture (Equipment page)" in \
        acts["Operation: Fixture Clamp Down"].toolTip()


# ------------------------------------------------------------- plumbing
def test_panel_forwards_available_ops_to_row_editor(qapp, monkeypatch):
    """The Operation row editor receives the panel's available set."""
    panel = FCTTestConfigPanel()
    panel.set_available_ops({"Power On DUT"})
    seen = {}

    class FakeDialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, kind, steps, enables, waits, timeouts,
                     parent=None, kinds=None, op_params=None,
                     available_ops=None):
            seen["kind"] = kind
            seen["available_ops"] = available_ops

        def exec(self):
            return 0            # rejected -> the row is untouched

        def deleteLater(self):
            pass

    import mtkgui.gui.steps_editor as steps_editor_module
    monkeypatch.setattr(steps_editor_module, "StepsEditorDialog",
                        FakeDialog)
    panel.set_values({})
    panel._add_row_for_label("Operation")
    panel._edit_operation_row(panel.cmd_table.rowCount() - 1)
    assert seen["kind"] == "fct"
    assert seen["available_ops"] == {"Power On DUT"}


def test_block_dialog_hands_available_ops_to_the_panel(qapp):
    """BlockConfigDialog(fct_build) -> FCTTestConfigPanel."""
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    dlg = BlockConfigDialog("fct_build", {}, None,
                            available_ops={"Power On DUT"})
    assert dlg.panel._available_ops == {"Power On DUT"}
    dlg.deleteLater()


def test_block_flow_computes_from_yaml_model_and_virtual(qapp,
                                                         monkeypatch):
    """YamlBuildPage -> block_flow -> BlockConfigDialog: the model
    decides the ops unless Virtual mode is on."""
    captured = {}

    class FakeBlockDialog:
        class DialogCode:
            Accepted = 1

        def __init__(self, module_key, params, parent, **kwargs):
            captured.update(kwargs)

        def exec(self):
            return 0

        def task_log(self):
            return None

        def task_progress(self):
            return None

    monkeypatch.setattr(block_flow_module, "BlockConfigDialog",
                        FakeBlockDialog)
    flow = block_flow_module.BlockFlowWidget()
    model = YamlBuildModel()
    model.gpio_allocation = [{"net": "GPIO_IN"}]
    flow.open_dialog("fct_build", {}, None, yaml_model=model)
    assert captured["available_ops"] is not None
    assert set(DIO_OPS) <= captured["available_ops"]

    flow.open_dialog("fct_build", {}, None, yaml_model=model,
                     virtual=True)
    assert captured["available_ops"] is None


def test_yaml_build_page_threads_model_and_virtual(qapp, monkeypatch):
    """open_fct_sequence passes the model + the Virtual flag down."""
    from mtkgui import yaml_build_page as page_module
    captured = {}

    def fake_open_dialog(module_key, params, parent, **kwargs):
        captured.update(kwargs)
        return None, None

    page = page_module.YamlBuildPage()
    # M45b: 01 -> 03 must be validated before block 04 opens
    page.model.set_params("design_input", {
        "product_id": "MTK", "part_number": "P-0001",
        "spf_file": "board.spf", "net_file": "board.net",
        "bom_file": "board.csv"})
    for key in ("design_input", "parse_ict", "ict_workflow"):
        page.model.set_mark(key, "star")
    monkeypatch.setattr(page.block_flow, "open_dialog", fake_open_dialog)
    page.set_virtual(True)
    page.open_fct_sequence()
    assert captured["yaml_model"] is page.model
    assert captured["virtual"] is True


def test_ict_editor_host_accepts_available_ops(qapp):
    """The ICT sequence dialog shares the same available set."""
    from mtkgui.gui.yamlbuild.ict_sequence import (
        IctWorkFlowSequenceDialog,
    )
    dlg = IctWorkFlowSequenceDialog(lambda: {}, rail_count=0,
                                    available_ops={"Power On DUT"})
    assert dlg._available_ops == {"Power On DUT"}
    dlg.deleteLater()
