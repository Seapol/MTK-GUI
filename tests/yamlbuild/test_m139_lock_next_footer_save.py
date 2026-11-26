# -*- coding: utf-8 -*-
"""M139: the Yaml Build flow loses its three sharp edges.

User review (2026-11-26) named the friction points; this module pins the
fixes:

1. node 07's footer ``Apply_Save yaml`` writes the file (it only closed
   the window before);
2. ``Next`` checks + locks the node itself (no padlock-then-Next dance);
3. node 01 parses the Route A netlist when it locks, so node 02 is review
   only and keeps ``Parse nets`` for an externally edited file.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QDialog, QLabel,  # noqa: E402
                               QMessageBox, QPushButton)

from mtkgui.gui.yamlbuild.wizard_shell import LOCK_BUTTON_NAME, YamlBuildWizard  # noqa: E402

VALID_DESIGN = {
    "part_number": "MTK12345", "product_id": "96317",
    "sw_version": "A", "hw_version": "B",
    "batch": "EVT (Proto-1)", "ict_block_enabled": "true",
    "fct_block_enabled": "true",
    "ict_route": "files",
    "spf_file": "s.spf", "net_file": "n.net", "bom_file": "b.csv",
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


def _open_dialog(wizard: YamlBuildWizard, key: str, accepted: int = 0):
    captured = {}
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


def _lock_button(dialog) -> QPushButton:
    for button in dialog.findChildren(QPushButton):
        if button.objectName() == LOCK_BUTTON_NAME:
            return button
    raise AssertionError("no padlock button in the node window")


def _button(dialog, text: str) -> QPushButton:
    for button in dialog.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"{text} not found")


def test_next_offers_lock_and_next_before_locking(qapp):
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard, "design_input")
        next_btn = [b for b in dialog.findChildren(QPushButton)
                    if b.text().startswith("Lock & Next")][0]
        assert next_btn.isEnabled(), "Next must be reachable before locking"
    finally:
        wizard.deleteLater()


def test_next_locks_the_node_it_leaves(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        wizard._panels["design_input"].set_values(VALID_DESIGN)
        dialog = _open_dialog(wizard, "design_input")
        opened: list[str] = []
        monkeypatch.setattr(wizard, "_open_step_dialog", opened.append)
        wizard._advance_node("design_input", "parse_ict", dialog,
                             wizard._panels["design_input"],
                             lambda: None, QLabel())
        assert wizard.model.is_locked("design_input"), "Next must lock"
        qapp.processEvents()
        assert opened == ["parse_ict"], opened
    finally:
        wizard.deleteLater()


def test_footer_exit_does_not_write(qapp, monkeypatch):
    # M158e: the footer is Exit only - the panel owns the single apply
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard, "apply_save")
        panel = wizard._panels["apply_save"]
        calls = []

        def fake_apply():
            calls.append(True)
            return True, "Saved: /tmp/x.yaml"

        monkeypatch.setattr(panel, "apply_now", fake_apply)
        _button(dialog, "Exit").click()
        assert calls == [], "Exit must not write the YAML"
        assert dialog.result() != QDialog.DialogCode.Accepted
    finally:
        wizard.deleteLater()


def test_panel_apply_button_writes(qapp, monkeypatch):
    # M158e: node 07's panel button is the ONLY apply action
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard, "apply_save")
        panel = wizard._panels["apply_save"]
        calls = []

        def fake_apply():
            calls.append(True)
            return True, "Saved: /tmp/x.yaml"

        monkeypatch.setattr(panel, "apply_now", fake_apply)
        panel.setEnabled(True)               # the wizard disables it until locked
        panel.btn_apply.setEnabled(True)
        panel.btn_apply.click()
        assert calls == [True], "the panel must run the write"
    finally:
        wizard.deleteLater()


def test_locking_design_input_parses_route_a(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        wizard._panels["design_input"].set_values(VALID_DESIGN)
        wizard._collect_panel_values("design_input")
        parse = wizard._panels["parse_ict"]
        called: list[object] = []
        # M155: the auto parse passes notify=False (a lock never pops a
        # window), so the spy must accept the keyword
        monkeypatch.setattr(wizard, "_parse_route_a",
                            lambda panel, notify=True: called.append(panel))
        wizard._auto_parse_after_lock()
        assert called == [parse], "node 01 lock owns the parse"
    finally:
        wizard.deleteLater()


def test_auto_parse_skips_other_routes(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        wizard._panels["design_input"].set_values(
            {**VALID_DESIGN, "ict_route": "excel"})
        wizard._collect_panel_values("design_input")
        called: list[object] = []
        monkeypatch.setattr(wizard, "_parse_route_a",
                            lambda panel, notify=True: called.append(panel))
        wizard._auto_parse_after_lock()
        assert called == [], "Excel / MTK sheet routes keep their own parse"
    finally:
        wizard.deleteLater()


def _locked_wizard(qapp):
    wizard = _wizard(qapp)
    for key in ("design_input", "parse_ict", "firmware"):
        wizard.model.set_locked(key, True)
    wizard._refresh()
    return wizard


def test_unlock_without_edits_restores_the_lock_set(qapp):
    wizard = _locked_wizard(qapp)
    try:
        captured = {}
        real_exec = QDialog.exec

        def fake_exec(dialog):
            captured["dlg"] = dialog
            _lock_button(dialog).click()
            return 0

        QDialog.exec = fake_exec
        try:
            wizard._open_step_dialog("design_input")
        finally:
            QDialog.exec = real_exec
        assert wizard.model.locked_keys() == ("design_input", "parse_ict",
                                             "firmware"), \
            "a look-only Unlock must give the later locks back"
    finally:
        wizard.deleteLater()


def test_unlock_with_an_edit_keeps_the_downstream_unlocked(qapp):
    wizard = _locked_wizard(qapp)
    try:
        real_exec = QDialog.exec

        def fake_exec(dialog):
            _lock_button(dialog).click()
            dialog_panel = wizard._panels["design_input"]
            dialog_panel.set_values({**VALID_DESIGN,
                                     "product_id": "96624"})
            return 0

        QDialog.exec = fake_exec
        try:
            wizard._open_step_dialog("design_input")
        finally:
            QDialog.exec = real_exec
        assert not wizard.model.is_locked("design_input")
        assert not wizard.model.is_locked("parse_ict")
    finally:
        wizard.deleteLater()
