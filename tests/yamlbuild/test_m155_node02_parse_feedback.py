# -*- coding: utf-8 -*-
"""M155: node 02 feedback - Parse nets button, arrows, progress, failures.

The operator could not tell whether the parse button had done anything:
the toolbar said "Re-parse", the run was silent, and a failure only
touched a small grey line at the bottom.  These tests pin the four
pieces of the fix.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QGridLayout,
    QMessageBox,
    QToolButton,
)

from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402

MINIMAL_NET = """*SIGNAL* VDD_3V3
U1.1 TP1.1
*SIGNAL* CLK_24M
U1.2 TP2.1
*SIGNAL* SOC_RST0
U1.3 TP3.1
"""


def _seed_route_a(wizard, net_path) -> None:
    wizard.model.set_params("design_input", {
        "ict_route": "files",
        "net_file": str(net_path),
        "product_id": "P001",
        "part_number": "MTK12345",
    })


def _panel(wizard):
    wizard.goto("parse_ict")
    return wizard._panels["parse_ict"]


# --------------------------------------------------------------- toolbar
def test_the_button_says_parse_nets():
    wizard = YamlBuildWizard()
    try:
        panel = _panel(wizard)
        assert panel.btn_parse.text() == "Parse nets"
        assert "Re-parse" not in panel.btn_parse.text()
    finally:
        wizard.deleteLater()


def test_the_move_controls_are_arrows_between_the_tables():
    wizard = YamlBuildWizard()
    try:
        panel = _panel(wizard)
        assert isinstance(panel.btn_up, QToolButton)
        assert isinstance(panel.btn_down, QToolButton)
        assert panel.btn_up.text() == ""
        assert panel.btn_down.text() == ""
        assert panel.btn_up.objectName() == "moveRowUp"
        assert panel.btn_down.objectName() == "moveRowDown"
        grid = next(lay for lay in panel.findChildren(QGridLayout)
                    if lay.indexOf(panel.btn_parse) >= 0
                    or lay.indexOf(panel.table) >= 0)
        left = grid.indexOf(panel.table)
        right = grid.indexOf(panel.table_other)
        up_col = grid.getItemPosition(grid.indexOf(panel.btn_up))[1]
        down_col = grid.getItemPosition(grid.indexOf(panel.btn_down))[1]
        assert up_col == down_col
        assert grid.getItemPosition(left)[1] < up_col
        assert up_col < grid.getItemPosition(right)[1]
    finally:
        wizard.deleteLater()


# -------------------------------------------------------------- progress
def test_parse_drives_a_percentage_bar(tmp_path, monkeypatch):
    from mtkgui.gui import progress_dialog

    stages: list[tuple[int, str]] = []

    class FakeBar:
        def __enter__(self):
            return lambda value, label: stages.append((int(value), label))

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(progress_dialog, "busy_progress",
                        lambda *a, **k: FakeBar())
    net_file = tmp_path / "sample.net"
    net_file.write_text(MINIMAL_NET, encoding="utf-8")
    wizard = YamlBuildWizard()
    try:
        _seed_route_a(wizard, net_file)
        panel = _panel(wizard)
        panel.btn_parse.click()
        values = [value for value, _label in stages]
        assert values, "the run must report stages"
        assert values == sorted(values), "progress never goes backwards"
        assert values[-1] == 100
        assert any("Reading" in label for _v, label in stages)
    finally:
        wizard.deleteLater()


# -------------------------------------------------------------- failures
def test_a_wrong_file_names_itself_in_a_warning(tmp_path, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(str(a[2])) or 0)
    broken = tmp_path / "broken.net"
    broken.write_text(")\nnot a netlist\n", encoding="utf-8")
    wizard = YamlBuildWizard()
    try:
        _seed_route_a(wizard, broken)
        panel = _panel(wizard)
        panel.btn_parse.click()
        assert warnings, "a failed parse must not look dead"
        assert "broken.net" in warnings[0]
        assert "no nets found" in warnings[0]
        assert panel.lbl_summary.text().startswith("Parse failed")
    finally:
        wizard.deleteLater()


def test_no_net_file_is_reported_not_swallowed(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(str(a[2])) or 0)
    wizard = YamlBuildWizard()
    try:
        wizard.model.set_params("design_input", {"ict_route": "files"})
        panel = _panel(wizard)
        panel.btn_parse.click()
        assert warnings and "No NET file" in warnings[0]
    finally:
        wizard.deleteLater()
