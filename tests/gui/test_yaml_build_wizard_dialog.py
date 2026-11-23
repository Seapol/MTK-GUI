# -*- coding: utf-8 -*-
"""m106b: node dialogs must fit the screen and keep OK/Cancel visible."""
from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QScrollArea

import mtkgui.gui.yamlbuild.wizard_shell as ws


def test_step_dialog_fits_available_geometry(monkeypatch):
    seen = {}

    def fake_exec(self):
        seen["dlg"] = self
        return 0

    monkeypatch.setattr(ws.QDialog, "exec", fake_exec)
    wizard = ws.YamlBuildWizard()
    wizard._open_step_dialog("design_input")

    dlg = seen["dlg"]
    avail = dlg.screen().availableGeometry()
    assert dlg.height() <= int(avail.height() * 0.9)
    assert dlg.width() <= int(avail.width() * 0.9)


def test_step_dialog_keeps_button_box_outside_scroll(monkeypatch):
    seen = {}

    def fake_exec(self):
        seen["dlg"] = self
        return 0

    monkeypatch.setattr(ws.QDialog, "exec", fake_exec)
    wizard = ws.YamlBuildWizard()
    wizard._open_step_dialog("design_input")

    dlg = seen["dlg"]
    box = dlg.findChild(QDialogButtonBox)
    assert box is not None
    # the button box must not live inside the scrollable panel
    assert not isinstance(box.parent(), QScrollArea)
    assert dlg.findChild(QScrollArea) is not None
