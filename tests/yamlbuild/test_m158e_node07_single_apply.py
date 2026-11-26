# -*- coding: utf-8 -*-
"""M158e: node 07 has a single apply action.

The apply used to exist twice - the panel's ``Apply & Save Yaml`` and the
wizard footer's ``Apply_Save yaml``.  The panel button is the single save
cluster now; the footer carries ``Exit`` only.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QDialog,  # noqa: E402
                               QDialogButtonBox, QPushButton)

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


def _open_dialog(wizard: YamlBuildWizard) -> QDialog:
    captured: dict = {}
    real_exec = QDialog.exec

    def fake_exec(dialog):
        captured["dlg"] = dialog
        return 0

    QDialog.exec = fake_exec
    try:
        wizard._open_step_dialog("apply_save")
    finally:
        QDialog.exec = real_exec
    return captured["dlg"]


def test_node07_has_exactly_one_apply_button(qapp):
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard)
        panel = wizard._panels["apply_save"]
        assert panel.btn_apply.text() == "Apply & Save Yaml"
        # the footer carries no second apply action
        footer_applies = [b for b in dialog.findChildren(QPushButton)
                          if "Apply" in b.text()]
        assert footer_applies == []
    finally:
        wizard.deleteLater()


def test_node07_footer_has_exit_only(qapp):
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard)
        box = dialog.findChildren(QDialogButtonBox)[0]
        texts = [b.text() for b in box.buttons()]
        assert texts == ["Exit"]
        assert box.button(QDialogButtonBox.Ok) is None
    finally:
        wizard.deleteLater()


def test_exit_does_not_write_yaml(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        dialog = _open_dialog(wizard)
        panel = wizard._panels["apply_save"]

        def forbidden():
            raise AssertionError("Exit must not write the YAML")

        monkeypatch.setattr(panel, "apply_now", forbidden)
        exit_button = next(b for b in dialog.findChildren(QPushButton)
                           if b.text() == "Exit")
        exit_button.click()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert not wizard.model.is_locked("apply_save")
    finally:
        wizard.deleteLater()
