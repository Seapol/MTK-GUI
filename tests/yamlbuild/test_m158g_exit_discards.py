# -*- coding: utf-8 -*-
"""M158g: Exit really discards the dialog's unsaved edits.

The tooltip used to promise "without changing the configuration" while
the closing dialog pushed its live values into the model.  Exit now asks
once (when something changed) and restores the pre-dialog snapshot;
``Lock & Next`` / an accepted close still collects.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QDialog,  # noqa: E402
                               QPushButton)

from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wizard(qapp) -> YamlBuildWizard:
    wizard = YamlBuildWizard()
    wizard.resize(1000, 420)
    wizard.show()
    qapp.processEvents()
    return wizard


def _run_dialog(wizard: YamlBuildWizard, key: str, action=None,
                accepted: int = 0) -> QDialog:
    """Open *key*, run *action* inside the modal loop, return the dialog."""
    captured: dict = {}
    real_exec = QDialog.exec

    def fake_exec(dialog):
        captured["dlg"] = dialog
        if action is not None:
            action(dialog)
        return accepted

    QDialog.exec = fake_exec
    try:
        wizard._open_step_dialog(key)
    finally:
        QDialog.exec = real_exec
    return captured["dlg"]


def _exit(dialog: QDialog) -> None:
    button = next(b for b in dialog.findChildren(QPushButton)
                  if b.text() == "Exit")
    button.click()


def test_node02_edit_never_reaches_the_model(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        wizard.model.set_parsed_nets({"power_nets": ["VDD_ARM"]})
        before = wizard.model.get_parsed_nets()
        panel = wizard._panels["parse_ict"]
        monkeypatch.setattr(wizard, "_confirm_discard", lambda dlg: True)

        def act(dialog):
            panel._overrides["VDD_ARM"] = "Other"   # a panel-local edit
            _exit(dialog)

        _run_dialog(wizard, "parse_ict", act)
        assert wizard.model.get_parsed_nets() == before
    finally:
        wizard.deleteLater()


def test_equipment_edit_is_discarded(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        before = wizard.model.get_equipment_config()
        assert before.source == "psu"
        panel = wizard._panels["equipment"]
        prompts: list = []

        def confirm(dlg):
            prompts.append(True)
            return True

        monkeypatch.setattr(wizard, "_confirm_discard", confirm)

        def act(dialog):
            panel.src_adapter.setChecked(True)      # writes through at once
            assert wizard.model.get_equipment_config().source == "adapter"
            _exit(dialog)

        _run_dialog(wizard, "equipment", act)
        assert prompts == [True]
        assert wizard.model.get_equipment_config().source == "psu"
        assert panel.src_psu.isChecked()
    finally:
        wizard.deleteLater()


def test_clean_exit_asks_nothing(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        prompts: list = []
        monkeypatch.setattr(wizard, "_confirm_discard",
                            lambda dlg: prompts.append(True) or True)
        before = dict(wizard.model.get_params("firmware") or {})
        _run_dialog(wizard, "firmware", _exit)
        assert prompts == []
        assert dict(wizard.model.get_params("firmware") or {}) == before
    finally:
        wizard.deleteLater()


def test_accept_still_collects_the_values(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        collected: list = []
        monkeypatch.setattr(wizard, "_collect_panel_values",
                            lambda key: collected.append(key))
        _run_dialog(wizard, "apply_save", accepted=1)
        assert collected == ["apply_save"]

        collected.clear()
        _run_dialog(wizard, "apply_save", _exit)
        assert collected == []          # Exit never collects
    finally:
        wizard.deleteLater()


def test_dict_panel_edit_is_discarded(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        panel = wizard._panels["design_input"]
        panel.set_values({"part_number": "KEEP", "product_id": "96317"})
        monkeypatch.setattr(wizard, "_confirm_discard", lambda dlg: True)

        def act(dialog):
            panel.edit_part_number.setText("CHANGED")
            _exit(dialog)

        _run_dialog(wizard, "design_input", act)
        assert (wizard.model.get_params("design_input")
                or {}).get("part_number") == "KEEP"
        assert panel.edit_part_number.text() == "KEEP"
    finally:
        wizard.deleteLater()
