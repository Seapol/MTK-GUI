# -*- coding: utf-8 -*-
"""M127: the Yaml Build page keeps the flowchart only.

User direction (2026-11-25): the four page-level buttons
(``Export to Excel`` / ``Cancel`` / ``Save Draft`` / ``Next``) are gone,
and ``Save Draft`` - like ``Next`` - lives inside EVERY node window.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QDialog,  # noqa: E402
                               QLabel, QPushButton)

from mtkgui.gui.yamlbuild import steps_v2 as sv  # noqa: E402
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402

PAGE_ACTION_TEXTS = ("Export to Excel", "Cancel", "Save Draft", "Next")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wizard(qapp) -> YamlBuildWizard:
    wizard = YamlBuildWizard()
    wizard.resize(1000, 420)
    wizard.show()
    qapp.processEvents()
    return wizard


def _visible_button_texts(widget) -> set[str]:
    return {b.text() for b in widget.findChildren(QPushButton)
            if b.isVisibleTo(widget)}


def _dialog_buttons(dialog: QDialog) -> list[QPushButton]:
    return [b for b in dialog.findChildren(QPushButton) if b.isVisibleTo(dialog)]


def _open_dialog(wizard: YamlBuildWizard, key: str,
                 accepted: int = 0) -> QDialog:
    """Capture the node dialog without entering a nested event loop."""
    captured: dict[str, QDialog] = {}
    real_exec = QDialog.exec

    def fake_exec(dialog):
        captured["dlg"] = dialog
        return accepted

    QDialog.exec = fake_exec
    try:
        wizard._open_step_dialog(key)
    finally:
        QDialog.exec = real_exec
    return captured["dlg"]


# --------------------------------------------------------------- the page
def test_page_keeps_no_action_buttons(qapp):
    """Only the flowchart - no Export / Cancel / Save Draft / Next."""
    wizard = _wizard(qapp)
    try:
        texts = _visible_button_texts(wizard)
        assert not texts & set(PAGE_ACTION_TEXTS), texts & set(PAGE_ACTION_TEXTS)
        # the footer widgets are really gone, not just hidden
        assert not hasattr(wizard, "btn_next")
        assert not hasattr(wizard, "btn_save_draft")
        assert not hasattr(wizard, "btn_cancel")
    finally:
        wizard.deleteLater()


# --------------------------------------------------------- one node window
def test_node_window_offers_save_draft_and_next(qapp):
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard, "design_input")
        texts = [b.text() for b in _dialog_buttons(dialog)]
        assert "Save Draft" in texts
        # Next names its target node (same wording the operator knows)
        assert any(t.startswith("Next: 02") for t in texts), texts
        assert texts[-2:] == ["Apply_Save yaml", "Exit"]
        assert dialog.parent() is wizard
    finally:
        wizard.deleteLater()


def test_last_node_has_no_next(qapp):
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard, "apply_save")
        texts = [b.text() for b in _dialog_buttons(dialog)]
        assert "Save Draft" in texts
        assert not any(t.startswith("Next:") for t in texts), texts
        assert wizard._next_node_key("apply_save") is None
    finally:
        wizard.deleteLater()


def test_every_editable_node_offers_save_draft(qapp):
    """Save Draft sits on EVERY node window, exactly like Next."""
    wizard = _wizard(qapp)
    try:
        # complete node 01 so node 02 opens for editing
        wizard._panels["design_input"].set_values({
            "part_number": "MTK12345", "product_id": "96317",
            "sw_version": "A", "hw_version": "B",
            "batch": "EVT (Proto-1)", "ict_block_enabled": "true",
            "spf_file": "s.spf", "net_file": "n.net", "bom_file": "b.csv"})
        # M128: gating follows the padlock - lock 01 / 03 to open 02 / 04
        for key in ("design_input", "firmware", "parse_ict"):
            wizard.model.set_locked(key, True)
        wizard._refresh()
        editable = [k for k in sv.enabled_step_keys(True, True)
                    if wizard._is_editable(k)]
        assert {"design_input", "parse_ict", "equipment"} <= set(editable), editable
        for key in editable:
            dialog = _open_dialog(wizard, key)
            texts = [b.text() for b in _dialog_buttons(dialog)]
            assert "Save Draft" in texts, (key, texts)
    finally:
        wizard.deleteLater()


# -------------------------------------------------------------- draft write
def test_save_draft_writes_current_panel_values(qapp, monkeypatch):
    """The draft stores the LIVE panel values, not the last applied ones."""
    wizard = _wizard(qapp)
    try:
        seen: dict = {}

        def fake_save(model):
            seen["model"] = model
            return "C:/work/drafts/LSW-409x_96317_revA_draft.yaml"

        monkeypatch.setattr(sv, "save_draft", fake_save)
        monkeypatch.setattr(sv, "ensure_project_tree",
                            lambda core: seen.setdefault("tree", core))

        wizard._panels["design_input"].set_values({
            "part_number": "LSW-409x", "product_id": "96317",
            "sw_version": "A", "hw_version": "B",
            "batch": "EVT (Proto-1)", "ict_block_enabled": "true"})

        dialog = _open_dialog(wizard, "design_input")
        buttons = {b.text(): b for b in _dialog_buttons(dialog)}
        buttons["Save Draft"].click()

        assert seen["model"] is wizard.model
        assert seen["tree"] == "96317"
        assert (wizard.model.get_params("design_input") or {})[
            "part_number"] == "LSW-409x"
        # the window stays open and reports where the draft landed
        labels = [lb.text() for lb in dialog.findChildren(QLabel)]
        assert any(t.startswith("Draft saved:") for t in labels), labels
    finally:
        wizard.deleteLater()


def test_next_saves_and_opens_the_successor(qapp, monkeypatch):
    """Next = save this node, close the window, open the target node."""
    wizard = _wizard(qapp)
    try:
        saved: list = []
        monkeypatch.setattr(sv, "save_draft", lambda model: saved.append(model))
        monkeypatch.setattr(sv, "ensure_project_tree", lambda core: None)

        wizard._panels["design_input"].set_values({
            "part_number": "LSW-409x", "product_id": "96317",
            "sw_version": "A", "hw_version": "B",
            "batch": "EVT (Proto-1)", "ict_block_enabled": "true"})
        # M128: Next only unlocks once this node is locked
        wizard.model.set_locked("design_input", True)
        wizard._refresh()

        dialog = _open_dialog(wizard, "design_input", accepted=1)
        # stub AFTER the dialog exists: Next must close it and open the
        # successor instead of running the real dialog again
        opened: list = []
        monkeypatch.setattr(wizard, "_open_step_dialog", opened.append)
        monkeypatch.setattr("mtkgui.gui.yamlbuild.wizard_shell.QTimer.singleShot",
                            lambda ms, fn: fn())

        buttons = {b.text(): b for b in _dialog_buttons(dialog)}
        next_button = next(b for t, b in buttons.items() if t.startswith("Next:"))
        next_button.click()

        assert saved and saved[0] is wizard.model
        assert opened == ["parse_ict"]
        assert dialog.result() == QDialog.DialogCode.Accepted
    finally:
        wizard.deleteLater()
