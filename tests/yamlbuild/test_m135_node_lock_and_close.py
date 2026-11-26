# -*- coding: utf-8 -*-
"""M135: the padlock names the action, and only node 07 writes the YAML.

* unlocked node  -> button reads ``Lock`` (click = validate + lock)
* locked node    -> button reads ``Unlock`` (click = release, cascade)
* nodes 01-06 close with ``Exit`` only; ``Apply_Save yaml`` sits on 07
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _open(wizard, key):
    seen = {}

    def grab():
        dialog = QApplication.activeModalWidget()
        if dialog is None:          # pragma: no cover - defensive
            return
        seen["dlg"] = dialog
        dialog.reject()

    QTimer.singleShot(0, grab)
    wizard._open_step_dialog(key)
    return seen["dlg"]


def _padlock(dialog) -> QPushButton:
    for button in dialog.findChildren(QPushButton):
        text = button.text()
        if text.endswith(" Lock") or text.endswith(" Unlock"):
            return button
    raise AssertionError("no padlock button in the node window")


def _button_texts(dialog):
    return [b.text() for b in dialog.findChildren(QPushButton)]


def test_padlock_reads_lock_while_open(qapp):
    wizard = YamlBuildWizard(model=YamlBuildModel())
    try:
        dialog = _open(wizard, "design_input")
        assert not wizard.model.is_locked("design_input")
        assert _padlock(dialog).text() == "🔒 Lock"
    finally:
        wizard.deleteLater()


def test_padlock_reads_unlock_while_locked(qapp):
    model = YamlBuildModel()
    model.set_locked("design_input", True)
    wizard = YamlBuildWizard(model=model)
    try:
        dialog = _open(wizard, "design_input")
        assert _padlock(dialog).text() == "🔓 Unlock"
    finally:
        wizard.deleteLater()


def test_nodes_01_to_06_have_no_apply_save(qapp):
    wizard = YamlBuildWizard(model=YamlBuildModel())
    try:
        for key in ("design_input", "firmware", "equipment"):
            dialog = _open(wizard, key)
            assert "Apply_Save yaml" not in _button_texts(dialog), key
            assert "Exit" in _button_texts(dialog), key
    finally:
        wizard.deleteLater()


def test_node_07_keeps_apply_save(qapp):
    wizard = YamlBuildWizard(model=YamlBuildModel())
    try:
        dialog = _open(wizard, "apply_save")
        assert "Apply_Save yaml" in _button_texts(dialog)
        assert "Exit" in _button_texts(dialog)
    finally:
        wizard.deleteLater()
