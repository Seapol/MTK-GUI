# -*- coding: utf-8 -*-
"""Offscreen GUI tests for the Yaml Build page assembly (tab
mounting, block interactions, two-way pane sync, persistence)."""

from __future__ import annotations

import pytest
import yaml

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.stages import STAGE_KEYS
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
    """Item 16: the top toolbar carries the two Excel buttons plus the
    Edit/Apply toggle (Build Draft / Release Final removed), the
    twelve M0 blocks and a live preview pane."""
    assert page.btn_import_excel.text() == "Import from Excel"
    assert page.btn_export_excel.text() == "Export to Excel"
    assert not hasattr(page, "btn_build_draft")
    assert not hasattr(page, "btn_release_final")
    assert page.yaml_preview.btn_apply in page._action_buttons
    assert len(page.block_flow._cards) == 5
    assert "ict_workflow" in page.block_flow._cards
    assert "channel_alloc" in page.block_flow._cards
    assert page.yaml_preview.editor.toPlainText().startswith(
        "yaml_build:")


def test_flow_arrows_between_cards(page):
    """User report 2026-10-14: the 01 -> 02 arrow was missing because
    each arrow was added AFTER its card (leaving the first pair
    unlinked and a stray arrow after the last card).  The layout must
    alternate card, arrow, card, ... with no trailing arrow."""
    from PySide6.QtWidgets import QLabel

    lay = page.block_flow.layout()
    seq = "".join(
        "A" if isinstance(lay.itemAt(i).widget(), QLabel) else "C"
        for i in range(lay.count()))
    assert seq == "C A C A C A C A C".replace(" ", ""), seq


def test_enable_disable_syncs_both_panes(page):
    """Disable: the card grays out AND the module leaves the effective
    YAML preview; parameters are retained in the model.  The merged
    ICT workflow card shows Enabled while ANY of rails/clocks/gpios
    is enabled."""
    page.model.enable_all()
    page._after_model_change()
    assert page.block_flow._cards["ict_workflow"].state_label.text() \
        == "Enabled"

    page._set_enabled("clocks", False)
    assert page.block_flow._cards["ict_workflow"].state_label.text() \
        == "Enabled"                       # rails / gpios still on
    preview = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    assert "clocks" not in preview["yaml_build"]["modules"]
    assert page.model.get_params("clocks")             # retained

    page._set_enabled("clocks", True)
    preview = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    assert "clocks" in preview["yaml_build"]["modules"]

    for key in ("rails", "clocks", "gpios"):
        page._set_enabled(key, False)
    assert page.block_flow._cards["ict_workflow"].state_label.text() \
        == "Disabled"


def test_config_dialog_apply_updates_preview(page):
    """Saving a block dialog updates the model and the YAML preview
    (diagram -> YAML direction)."""
    page.model.enable_all()
    page.block_flow._cards["ict_workflow"].set_enabled(True)
    # simulate the dialog's validated result
    page.model.set_params("rails", {
        "on_voltage_v": "12.0", "current_limit_a": "2.0",
        "on_delay_ms": "150", "off_delay_ms": "250",
        "off_protection": "true",
        "sequence": "VDD:0.0",
    })
    page._after_model_change()
    preview = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    assert preview["yaml_build"]["modules"]["rails"][
        "on_voltage_v"] == 12.0


def test_yaml_edit_apply_updates_blocks(page):
    """A valid hand edit of the YAML preview flows into the model
    and the block cards (YAML -> diagram direction)."""
    from tests.yamlbuild.conftest import fill_required
    page.model.enable_all()
    fill_required(page.model)   # required fields must be non-empty
    page._after_model_change()   # repaint the preview from the model
    text = page.yaml_preview.editor.toPlainText()
    doc = yaml.safe_load(text)
    doc["yaml_build"]["modules"]["rails"]["on_delay_ms"] = 555
    page.yaml_preview.editor.setPlainText(
        yaml.safe_dump(doc, sort_keys=False))
    page.yaml_preview.btn_apply.click()           # Apply: validate+persist
    # the edit was validated and applied into the model
    assert page.model.get_params("rails")["on_delay_ms"] == "555"


def test_invalid_yaml_edit_rejected(page):
    """An invalid hand edit never enters the model."""
    def semantic(model_dict: dict) -> dict:
        """Content snapshot without the volatile save timestamp."""
        return {k: v for k, v in model_dict.items() if k != "saved_at"}

    page.model.enable_all()
    before = semantic(page.model.to_dict())
    page.yaml_preview.editor.setPlainText("yaml_build: [broken")
    page.yaml_preview.btn_apply.click()           # Apply -> FAIL
    assert not page.yaml_preview.error_bar.isHidden()
    assert "broken" in page.yaml_preview.editor.toPlainText()
    assert page.yaml_preview.btn_apply.text() == "Apply to Yaml"
    assert semantic(page.model.to_dict()) == before


def test_yaml_apply_committed_forwarded(page):
    """A valid Apply on the preview forwards the committed signal -
    the main window uses it to offer the file save."""
    from tests.yamlbuild.conftest import fill_required
    page.model.enable_all()
    fill_required(page.model)
    page._after_model_change()
    seen = []
    page.yaml_apply_committed.connect(lambda: seen.append(True))
    doc = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    doc["yaml_build"]["modules"]["rails"]["on_delay_ms"] = 123
    page.yaml_preview.editor.setPlainText(
        yaml.safe_dump(doc, sort_keys=False))
    page.yaml_preview.btn_apply.click()
    assert seen == [True]
    assert page.model.get_params("rails")["on_delay_ms"] == "123"


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
    page.yaml_preview.btn_apply.click()
    doc = yaml.safe_load(page.yaml_preview.editor.toPlainText())
    doc["yaml_build"]["modules"]["clocks"]["enabled"] = False
    doc["yaml_build"]["modules"]["rails"]["enabled"] = False
    doc["yaml_build"]["modules"]["gpios"]["enabled"] = False
    page.yaml_preview.editor.setPlainText(
        yaml.safe_dump(doc, sort_keys=False))
    page.yaml_preview.btn_apply.click()
    assert page.block_flow._cards["ict_workflow"].state_label.text() \
        == "Disabled"
    assert page.model.is_enabled("clocks") is False


def test_block_cards_carry_sequence_badges(page):
    """Cards render the uniform 01..10 sequence badges (fixed order,
    unified look; the merged ICT workflow card is 04)."""
    from mtkgui.gui.yamlbuild.stages import WORKFLOW_DISPLAY_STAGES
    for index, stage in enumerate(WORKFLOW_DISPLAY_STAGES):
        card = page.block_flow._cards[stage.key]
        assert card.title_label.text().startswith(f"{index + 1:02d} ·")


def test_ict_workflow_card_opens_sequence_builder(page, monkeypatch):
    """The merged 'Build ICT Test Work Flow Sequence' card opens the
    sequence builder dialog; on accept it emits ict_sequence_ready
    with the generated test rows (no standard operations)."""
    from mtkgui.gui.yamlbuild import ict_sequence
    fired = []
    page.ict_sequence_ready.connect(lambda rows: fired.append(rows))
    page.model.imported["testable_nets"] = {
        "3V3": {"category": "Power", "members": ["U1.5"]},
        "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
    }
    # user rule: only nets WITH allocated channels enter the builder
    page.model.set_channel_allocation({
        "power": [{"net": "3V3", "impedance": "DAQM908A #1 CH101",
                   "power_rails": "U2355A AI01",
                   "voltage": "DAQM908A #1 CH101"}],
        "clock": [{"net": "CLK_24M", "se_clock_hz": "DAQM907A TOT"}],
        "gpio": [],
    })
    # the tables are EMBEDDED in the page now - a direct model
    # mutation must re-mirror into them (the _open_block quiet sync
    # pushes the TABLE state back into the model first)
    page.channel_alloc.refresh_from_model()
    monkeypatch.setattr(
        ict_sequence.IctWorkFlowSequenceDialog, "exec",
        lambda self: self.DialogCode.Accepted)
    page._open_block("ict_workflow")
    assert len(fired) == 1
    rows = fired[0]
    assert rows and all(r[0] == "test" for r in rows)   # tests only
    names = [r[1] for r in rows]
    assert any(n.startswith("Static Impedance") for n in names)
    assert any(n.startswith("Clock Hz") for n in names)
    # no navigation any more (the main window navigates on the signal)
    nav = []
    page.test_workflow_requested.connect(lambda: nav.append(1))
    monkeypatch.setattr(
        ict_sequence.IctWorkFlowSequenceDialog, "exec",
        lambda self: self.DialogCode.Rejected)
    page._open_block("ict_workflow")
    assert nav == []


def test_channel_alloc_card_runs_auto_allocation(page):
    """The 'Auto-Channel Allocation' card executes the automatic
    allocation on click (the former Auto button moved onto the
    card - user direction 2026-10-13)."""
    page.model.imported["testable_nets"] = {
        "3V3": {"category": "Power", "members": ["U1.5"]},
        "CLK_24M": {"category": "Clock", "members": ["U1.10"]},
    }
    page.channel_alloc.refresh_from_model()
    page._open_block("channel_alloc")
    power_row = page.channel_alloc.table_power.rows()[0]
    clock_row = page.channel_alloc.table_clock.rows()[0]
    assert power_row.impedance == power_row.voltage  # SAME channel
    assert power_row.impedance.startswith("DAQM908A")
    assert power_row.power_rails.startswith("U2355A")
    assert clock_row.se_clock_hz.startswith("DAQM907A")
    # the card gets a star once the allocation ran (user direction)
    assert page.block_flow._cards["channel_alloc"] \
        .mark_label.text() == "★"
    assert page.model.marks.get("channel_alloc") == "star"


def test_close_and_load_buttons_emit_requests(page):
    """The top button row carries "Close Yaml" and "Load current
    yaml" right of "Apply to Yaml"; clicking emits the request
    signals the main window routes to its File-menu slots."""
    assert page.btn_close_yaml.text() == "Close Yaml"
    assert page.btn_load_yaml.text() == "Load current yaml"
    closed, load_requested = [], []
    page.close_yaml_requested.connect(lambda: closed.append(True))
    page.load_yaml_requested.connect(lambda: load_requested.append(True))
    page.btn_close_yaml.click()
    page.btn_load_yaml.click()
    assert closed == [True]
    assert load_requested == [True]


def test_clear_preview_blanks_pane(page):
    """Close Yaml must clear the Yaml Preview (user direction)."""
    page.yaml_preview.editor.setPlainText("yaml_build: plan_version: 1.0.0")
    page.clear_preview()
    assert page.yaml_preview.editor.toPlainText() == ""


def test_standard_button_tooltips(page):
    """The top toolbar buttons carry the fixed English tooltips
    (rule 6.1, exact wording; GUI language = English)."""
    assert page.btn_import_excel.toolTip() == \
        ("Bulk-import the flow configuration workbook and fill "
         "back every module parameter and state")
    assert page.btn_export_excel.toolTip() == \
        ("Export all flow module parameters to a standard Excel "
         "archive file")


def test_module_cards_have_tooltips_even_disabled(page):
    """Every module card shows a description tooltip - also in the
    disabled state (rule 6.2)."""
    from mtkgui.gui.yamlbuild.stages import WORKFLOW_DISPLAY_STAGES
    for stage in WORKFLOW_DISPLAY_STAGES:
        card = page.block_flow._cards[stage.key]
        assert card.toolTip().strip(), stage.key
    page._set_enabled("clocks", False)
    assert page.block_flow._cards["ict_workflow"].toolTip().strip()


def test_context_menu_single_and_batch(page):
    """The right-click menu offers single Enable/Disable plus batch
    Enable All / Disable All with the standard tooltips, and the
    batch actions really flip every module."""
    card = page.block_flow._cards["ict_workflow"]
    page._disable_all()         # refresh cards to the disabled state
    menu = card._build_menu()
    actions = menu._actions_map
    assert actions["enable_all"].toolTip() == \
        ("Enable every flow module - all join the YAML "
         "generation and validation")
    assert actions["disable_all"].toolTip() == \
        ("Disable every flow module - none joins the flow "
         "compilation")
    assert actions["enable"].toolTip() == \
        "Enable / disable this module flow participation"
    assert actions["enable"].isEnabled()
    assert not actions["disable"].isEnabled()   # current state grayed

    actions["enable_all"].trigger()
    page._enable_all()          # menu signal -> page slot
    assert all(page.model.is_enabled(k) for k in STAGE_KEYS)
    page._disable_all()
    assert not any(page.model.is_enabled(k) for k in STAGE_KEYS)
    assert page.model.get_params("design_input")   # params retained


def test_dialog_fields_all_have_tooltips(page, qapp):
    """Every editor in every module config dialog carries a non-empty
    tooltip (rule 6.4: no empty / duplicate prompts)."""
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    seen = set()
    for key in STAGE_KEYS:
        dlg = BlockConfigDialog(key, page.model.get_params(key), page)
        if dlg.panel is not None:
            # embedded panels own their tooltips (T7 Design Input)
            seen.add((key, "embedded_panel"))
            dlg.deleteLater()
            continue
        for name, editor in dlg._editors.items():
            tip = editor.toolTip().strip()
            assert tip, f"{key}.{name} has an empty tooltip"
            seen.add((key, name))
        dlg.deleteLater()
    assert ("design_input", "embedded_panel") in seen


def test_default_state_is_all_enabled(page):
    """Fresh page default: every module enabled (rule 3.2).  Nav
    cards (Auto-Channel Allocation) have no module state - they
    render 'Auto assign' instead."""
    from mtkgui.gui.yamlbuild.stages import (
        NAV_CARD_KEYS,
        WORKFLOW_DISPLAY_STAGES,
    )
    assert all(page.model.is_enabled(k) for k in STAGE_KEYS)
    for stage in WORKFLOW_DISPLAY_STAGES:
        label = page.block_flow._cards[stage.key].state_label.text()
        if stage.key in NAV_CARD_KEYS:
            assert label == "Auto assign", stage.key
        else:
            assert label == "Enabled", stage.key
