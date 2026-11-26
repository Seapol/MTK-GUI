# -*- coding: utf-8 -*-
"""M156: one page backwards, and every node explains itself.

``← Back: <previous>`` is the leftmost footer action (objectName
``nodeBackButton``): it closes the window without writing a draft and
re-opens the previous reachable node, stepping over the Route C gap.
``?`` (objectName ``nodeHelpButton``) opens that node's own step page.
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QDialog,  # noqa: E402
                               QHBoxLayout, QPushButton)

from mtkgui.gui import help_content as hc  # noqa: E402
from mtkgui.gui.yamlbuild import steps_v2 as sv  # noqa: E402
from mtkgui.gui.yamlbuild.wizard_shell import (  # noqa: E402
    BACK_BUTTON_NAME,
    HELP_BUTTON_NAME,
    YamlBuildWizard,
)

ROOT = hc.HELP_ROOT


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wizard(qapp) -> YamlBuildWizard:
    wizard = YamlBuildWizard()
    wizard.resize(1000, 420)
    wizard.show()
    qapp.processEvents()
    return wizard


def _open_dialog(wizard: YamlBuildWizard, key: str) -> QDialog:
    """Capture the node dialog without entering a nested event loop."""
    captured: dict[str, QDialog] = {}
    real_exec = QDialog.exec

    def fake_exec(dialog):
        captured["dlg"] = dialog
        return 0

    QDialog.exec = fake_exec
    try:
        wizard._open_step_dialog(key)
    finally:
        QDialog.exec = real_exec
    return captured["dlg"]


def _button(dialog: QDialog, name: str) -> QPushButton | None:
    for button in dialog.findChildren(QPushButton):
        if button.objectName() == name:
            return button
    return None


# ------------------------------------------------------------------ Back
def test_node_01_has_no_back_button(qapp):
    wizard = _wizard(qapp)
    try:
        assert wizard._prev_node_key("design_input") is None
        dialog = _open_dialog(wizard, "design_input")
        assert _button(dialog, BACK_BUTTON_NAME) is None
    finally:
        wizard.deleteLater()


def test_every_node_but_the_first_names_the_previous_step(qapp):
    wizard = _wizard(qapp)
    try:
        for key in sv.STEP_KEYS[1:]:
            previous = wizard._prev_node_key(key)
            assert previous is not None, key
            dialog = _open_dialog(wizard, key)
            back = _button(dialog, BACK_BUTTON_NAME)
            assert back is not None, key
            assert back.text() == f"← Back: {sv.step_label(previous)}"
            draft = next(b for b in dialog.findChildren(QPushButton)
                         if b.text() == "Save Draft")
            # same footer row: one layout holds both widgets
            assert any(lay.indexOf(back) >= 0 and lay.indexOf(draft) >= 0
                       for lay in dialog.findChildren(QHBoxLayout)), key
    finally:
        wizard.deleteLater()


def test_back_writes_nothing_and_opens_the_previous_node(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        monkeypatch.setattr(
            "mtkgui.gui.yamlbuild.wizard_shell.QTimer.singleShot",
            lambda ms, fn: fn())
        collected: list = []
        monkeypatch.setattr(wizard, "_collect_panel_values",
                            lambda key: collected.append(key))
        before = dict(wizard.model.get_params("firmware") or {})
        state = {"first": True}

        def fake_exec(dialog):
            if state["first"]:
                state["first"] = False
                back = _button(dialog, BACK_BUTTON_NAME)
                back.click()          # Back while the modal loop "runs"
            return dialog.result()

        real_exec = QDialog.exec
        QDialog.exec = fake_exec
        try:
            wizard._open_step_dialog("firmware")
        finally:
            QDialog.exec = real_exec

        assert wizard.current == "parse_ict"         # the previous node opened
        assert "firmware" not in collected           # no panel collect
        assert dict(wizard.model.get_params("firmware") or {}) == before
    finally:
        wizard.deleteLater()


def test_back_skips_the_route_c_gap(qapp):
    wizard = _wizard(qapp)
    try:
        wizard._panels["design_input"].set_values({
            "part_number": "LSW-409x", "product_id": "96317",
            "sw_version": "A", "hw_version": "B",
            "batch": "EVT (Proto-1)", "ict_block_enabled": "true",
            "fct_block_enabled": "false", "ict_route": "mtk_sheet"})
        assert wizard._is_skipped("parse_ict")
        assert wizard._prev_node_key("equipment") == "design_input"
        dialog = _open_dialog(wizard, "equipment")
        back = _button(dialog, BACK_BUTTON_NAME)
        assert back.text() == f"← Back: {sv.step_label('design_input')}"
    finally:
        wizard.deleteLater()


# ------------------------------------------------------------------ Help
def test_every_node_has_the_help_button(qapp):
    wizard = _wizard(qapp)
    try:
        for key in sv.STEP_KEYS:
            dialog = _open_dialog(wizard, key)
            help_btn = _button(dialog, HELP_BUTTON_NAME)
            assert help_btn is not None, key
            assert help_btn.text() == "", key
            assert help_btn.toolTip().startswith(
                "Open the step-by-step guide"), key
    finally:
        wizard.deleteLater()


def test_help_opens_the_page_of_this_node(qapp, monkeypatch):
    wizard = _wizard(qapp)
    try:
        seen: list = []
        monkeypatch.setattr(hc, "open_step_help", seen.append)
        dialog = _open_dialog(wizard, "build_fct")
        _button(dialog, HELP_BUTTON_NAME).click()
        assert seen == ["build_fct"]
    finally:
        wizard.deleteLater()


# ------------------------------------------------------------- step pages
def test_every_step_has_a_page():
    for key in sv.STEP_KEYS:
        filename = hc.STEP_TOPICS[key]
        path = ROOT / filename
        assert path.is_file(), filename
        text = path.read_text(encoding="utf-8")
        first_heading = next(line for line in text.splitlines()
                             if line.startswith("## "))
        assert first_heading == f"## {sv.step_label(key)}", filename
        assert len(re.findall(r"^\d+\.\s", text, re.M)) >= 3, filename


def test_the_step_page_walks_the_steps():
    html = hc.step_page_html("parse_ict")
    assert sv.step_label("design_input") in html
    assert sv.step_label("firmware") in html
    assert "9. Yaml Build Page" in html
