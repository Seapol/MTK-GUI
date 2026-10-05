# -*- coding: utf-8 -*-
"""Offscreen GUI tests for the Yaml Build page assembly (tab
mounting, block interactions, two-way pane sync, persistence)."""

from __future__ import annotations

import pytest
import yaml

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """One offscreen QApplication for the module."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    """A fresh page per test, with the persistence store pointed at
    a temporary directory (the repo config stays untouched)."""
    from mtkgui.gui.yamlbuild import store
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "state.json")
    return YamlBuildPage()


def test_page_assembly(page):
    """The page carries the four fixed buttons, ten blocks and a
    live preview pane."""
    assert page.btn_import_excel.text() == "Import from Excel"
    assert page.btn_export_excel.text() == "Export to Excel"
    assert page.btn_build_draft.text() == "Build Draft YAML"
    assert page.btn_release_final.text() == "Release Final YAML"
    assert len(page.block_flow._cards) == 10
    assert page.yaml_preview.editor.toPlainText().startswith(
        "yaml_build:")


def test_enable_disable_syncs_both_panes(page):
    """Disable: the card grays out AND the module leaves the effective
    YAML preview; parameters are retained in the model."""
    page.model.enable_all()
    page._after_model_change()
    assert page.block_flow._cards["clocks"].state_label.text() == \
        "Enabled"

    page._set_enabled("clocks", False)
    assert page.block_flow._cards["clocks"].state_label.text() == \
        "Disabled"
    preview = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    assert "clocks" not in preview["yaml_build"]["modules"]
    assert page.model.get_params("clocks")             # retained

    page._set_enabled("clocks", True)
    preview = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    assert "clocks" in preview["yaml_build"]["modules"]


def test_config_dialog_apply_updates_preview(page):
    """Saving a block dialog updates the model and the YAML preview
    (diagram -> YAML direction)."""
    page.model.enable_all()
    page.block_flow._cards["power_dut"].set_enabled(True)
    # simulate the dialog's validated result
    page.model.set_params("power_dut", {
        "on_voltage_v": "12.0", "current_limit_a": "2.0",
        "on_delay_ms": "150", "off_delay_ms": "250", "retries": "1",
        "off_protection": "true", "self_check": "true",
    })
    page._after_model_change()
    preview = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    assert preview["yaml_build"]["modules"]["power_dut"][
        "on_voltage_v"] == 12.0


def test_yaml_edit_apply_updates_blocks(page):
    """A valid hand edit of the YAML preview flows into the model
    and the block cards (YAML -> diagram direction)."""
    from tests.yamlbuild.conftest import fill_required
    page.model.enable_all()
    fill_required(page.model)   # required fields must be non-empty
    page._after_model_change()   # repaint the preview from the model
    page.yaml_preview.btn_edit.setChecked(True)   # hand-edit mode
    text = page.yaml_preview.editor.toPlainText()
    doc = yaml.safe_load(text)
    doc["yaml_build"]["modules"]["power_dut"]["on_delay_ms"] = 555
    page.yaml_preview.editor.setPlainText(
        yaml.safe_dump(doc, sort_keys=False))
    # the preview re-validated on textChanged and applied the edit
    assert page.model.get_params("power_dut")["on_delay_ms"] == "555"


def test_invalid_yaml_edit_rejected(page):
    """An invalid hand edit never enters the model."""
    page.model.enable_all()
    before = page.model.to_dict()
    page.yaml_preview.btn_edit.setChecked(True)
    page.yaml_preview.editor.setPlainText("yaml_build: [broken")
    assert not page.yaml_preview.error_bar.isHidden()
    assert page.model.to_dict() == before


def test_persistence_round_trip(page):
    """State persists per project and reloads into a fresh page
    (restart-safe)."""
    page.model.enable_all()
    page.model.set_params("clocks", {"clocks": "CLK1:32768:0.1",
                                     "stabilize_ms": "100",
                                     "drift_check": "true",
                                     "multi_domain_check": "false"})
    page._after_model_change()

    fresh = YamlBuildPage()
    assert fresh.model.is_enabled("design_input") is True
    assert fresh.model.get_params(
        "clocks")["clocks"] == "CLK1:32768:0.1"


def test_yaml_hand_edit_disables_block_card(page):
    """YAML -> diagram: disabling a module by hand edit updates the
    block card visual (enable badge) and persists."""
    from tests.yamlbuild.conftest import fill_required
    page.model.enable_all()
    fill_required(page.model)
    page._after_model_change()
    page.yaml_preview.btn_edit.setChecked(True)
    doc = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    doc["yaml_build"]["modules"]["clocks"]["enabled"] = False
    page.yaml_preview.editor.setPlainText(
        yaml.safe_dump(doc, sort_keys=False))
    assert page.block_flow._cards["clocks"].state_label.text() == \
        "Disabled"
    assert page.model.is_enabled("clocks") is False


def test_block_cards_carry_sequence_badges(page):
    """Cards render the uniform 01..10 sequence badges (fixed order,
    unified look)."""
    from mtkgui.gui.yamlbuild.stages import WORKFLOW_STAGES
    for index, stage in enumerate(WORKFLOW_STAGES):
        card = page.block_flow._cards[stage.key]
        assert card.title_label.text().startswith(f"{index + 1:02d} ·")
