# -*- coding: utf-8 -*-
"""v2-18: per-node dialog editing tests (flowchart click → modal dialog)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog, QScrollArea  # noqa: E402

from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402


@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


def _model() -> YamlBuildModel:
    model = YamlBuildModel()
    model.set_params("design_input", {
        "product_id": "96317", "part_number": "MTK12345",
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "EVT (Proto-1)",
    })
    return model


def _wizard(qapp, model=None):
    return YamlBuildWizard(model or _model())


def test_modal_dialog_hosts_the_node_panel_and_reparents_back(
        qapp, monkeypatch):
    w = _wizard(qapp)
    try:
        panel = w._panels["design_input"]
        assert panel.parent() is w._panel_host
        captured: dict = {}

        def fake_exec(self):
            # m106b wraps the panel in a scroll area so OK/Cancel stay visible.
            captured["panel_in_dialog"] = panel.window() is self
            captured["scroll_ancestor"] = isinstance(
                panel.parent().parent(), QScrollArea)
            return QDialog.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        w.flow.step_clicked.emit("design_input")
        assert captured.get("panel_in_dialog") is True
        assert captured.get("scroll_ancestor") is True
        assert panel.parent() is w._panel_host
        assert w.current == "design_input"
    finally:
        w.deleteLater()


def test_locked_node_dialog_disables_the_panel(qapp, monkeypatch):
    w = _wizard(qapp)
    try:
        # parse_ict is locked until node 01 validates (no SPF/NET/BoM yet)
        panel = w._panels["parse_ict"]
        captured: dict = {}

        def fake_exec(self):
            captured["enabled"] = panel.isEnabled()
            captured["panel_in_dialog"] = panel.window() is self
            return QDialog.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        w.flow.step_clicked.emit("parse_ict")
        assert captured.get("panel_in_dialog") is True
        assert captured.get("enabled") is False
        assert panel.parent() is w._panel_host
    finally:
        w.deleteLater()


def test_disabled_node_click_does_nothing(qapp):
    model = _model()
    model.set_params("design_input", {
        **model.get_params("design_input"),
        "ict_block_enabled": "false",   # ICT-only group greys out
    })
    w = _wizard(qapp, model)
    try:
        w.flow.step_clicked.emit("parse_ict")   # ICT node, now disabled
        assert w.current == "design_input"      # unchanged
    finally:
        w.deleteLater()
