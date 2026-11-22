# -*- coding: utf-8 -*-
"""M103b: File ▸ Excel submenu + the two Import entry flows."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402

EXCEL_ITEMS = (
    "Export Config Workbook…",
    "Import Traditional ICT Test Plan…",
    "Import MTK ICT Sheet (Route C)…",
    "Export MTK ICT Sheet (Route C)…",
)


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
    # every node dialog closes immediately (offscreen)
    monkeypatch.setattr(QDialog, "exec",
                        lambda dialog: QDialog.DialogCode.Rejected)
    yield w
    w.close()
    w.deleteLater()


def test_excel_submenu_has_four_items(window):
    assert [act.text() for act in window._excel_menu.actions()] == \
        list(EXCEL_ITEMS)
    # the submenu lives in the File menu, between Close Yaml and Switch
    labels = [act.text() for act in window._file_menu.actions()]
    assert "Excel" in labels
    assert labels.index("Excel") > labels.index("Close Yaml")
    assert labels.index("Excel") < labels.index("Switch Account…")


def test_import_traditional_preselects_route_b(window):
    window._import_traditional_plan_menu()
    panel = window._yaml_wizard._design_panel
    assert panel.radio_excel.isChecked()
    assert not panel.radio_mtk.isChecked()
    assert window._yaml_wizard.current == "design_input"


def test_import_mtk_preselects_route_c(window):
    window._import_mtk_sheet_menu()
    panel = window._yaml_wizard._design_panel
    assert panel.radio_mtk.isChecked()
    assert not panel.radio_excel.isChecked()
    assert window._yaml_wizard.current == "design_input"


def test_export_mtk_gate_blocks_on_validation_error(window, monkeypatch,
                                                    tmp_path):
    warnings: list = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a) or 0)
    window._project_path = str(tmp_path / "project.yaml")
    window._refresh_excel_menu()
    # a default model fails validate_all -> the item stays disabled
    assert window.act_export_ict_plan.isEnabled() is False
    window._export_mtk_sheet_menu()
    assert warnings and warnings[0][1] == "Cannot export"


def test_open_step_and_select_route_are_public(window):
    assert callable(getattr(YamlBuildWizard, "open_step", None))
    assert callable(getattr(YamlBuildWizard, "select_route", None))
    wizard = window._yaml_wizard
    wizard.select_route("mtk_sheet")
    assert wizard._design_panel.radio_mtk.isChecked()
    wizard.select_route("not-a-route")           # no-op, no crash
    assert wizard._design_panel.radio_mtk.isChecked()
    wizard.open_step("design_input")
    assert wizard.current == "design_input"
