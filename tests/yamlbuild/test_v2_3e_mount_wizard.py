# -*- coding: utf-8 -*-
"""v2-3e: mount the seven-step Yaml Build wizard in the Yaml Build tab
and share the v1 page's YamlBuildModel.

The v1 page stays alive as the owner of Excel import / export and the
ICT / FCT dialogs; the tab now hosts a top bar (Import / Export from
Excel) plus the wizard on the SAME model.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)
    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    w._ensure_secondary_ui()
    yield w
    w.close()
    w.deleteLater()


def test_wizard_is_the_yaml_build_tab(window):
    """The Yaml Build tab holds the host widget, and the wizard is the
    host's child; the v1 page is NOT the tab widget any more."""
    from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard

    idx = window.tabs.indexOf(window._yaml_build_host)
    assert idx >= 0
    assert window.tabs.tabText(idx) == "Yaml Build"
    assert window._yaml_build_host.findChildren(YamlBuildWizard) == \
        [window._yaml_wizard]
    # the v1 page survives for its dialogs / providers but is unparented
    assert window.yaml_build_page is not None


def test_design_input_reaches_the_model(window):
    """Node 01's panel writes back to the shared model on content_changed."""
    panel = window._yaml_wizard._panels["design_input"]
    panel.edit_product_id.setText("MTK-96")
    panel.content_changed.emit()
    design = window.yaml_build_page.model.get_params("design_input")
    assert design["product_id"] == "MTK-96"


def test_wizard_panel_loads_existing_params(qapp):
    """A pre-seeded model reaches the 01 panel when the wizard is built."""
    from mtkgui.gui.yamlbuild.model import YamlBuildModel
    from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard

    model = YamlBuildModel()
    model.set_params("design_input", {"product_id": "SEED-42"})
    w = YamlBuildWizard(model=model)
    try:
        panel = w._panels["design_input"]
        assert panel.edit_product_id.text() == "SEED-42"
    finally:
        w.deleteLater()


def test_build_ict_launcher_opens_the_ict_dialog(window, monkeypatch):
    """The step-05 launcher button opens the v1 page's ICT dialog owner."""
    yb = window.yaml_build_page
    calls: list = []
    monkeypatch.setattr(yb, "open_ict_sequence", lambda: calls.append(1))
    body = window._yaml_wizard._bodies["build_ict"]
    button = body.findChildren(QPushButton)[0]
    button.click()
    assert calls == [1]


def test_excel_buttons_still_call_the_v1_page(window, monkeypatch):
    """The top-row Export to Excel button calls the v1 page's slot."""
    yb = window.yaml_build_page
    calls: list = []
    monkeypatch.setattr(yb, "_export_excel", lambda: calls.append("export"))
    buttons = [b for b in window._yaml_build_host.findChildren(QPushButton)
               if b.text() == "Export to Excel"]
    assert len(buttons) == 1
    buttons[0].click()
    assert calls == ["export"]
