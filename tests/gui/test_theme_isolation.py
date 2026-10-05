# -*- coding: utf-8 -*-
"""M0 theme-variable isolation tests (mock, no GUI render).

Guards against cross-theme QSS leakage: the workflow block cards bind
their own text colors inside the card scope, so the global light/dark
theme palettes can never bleed into the card text - and the approved
global palettes themselves stay untouched.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.block_flow import (  # noqa: E402
    STATUS_ENABLED_COLOR,
    BlockCard,
)
from mtkgui.gui.yamlbuild.stages import Stage, WORKFLOW_STAGES  # noqa: E402
from mtkgui.style import GUI_THEMES, build_qss  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _card(enabled: bool) -> BlockCard:
    stage = Stage(key="design_input", title="Design Input",
                  group="design")
    card = BlockCard(stage, 0)
    card.set_enabled(enabled)
    return card


def test_enabled_card_title_is_white(qapp):
    card = _card(True)
    assert "color: #ffffff" in card.title_label.styleSheet()
    assert "font-weight: bold" in card.title_label.styleSheet()


def test_enabled_card_status_uses_original_status_color(qapp):
    """The Enabled badge carries the original project status green -
    NOT an inherited theme text/link color."""
    card = _card(True)
    assert f"color: {STATUS_ENABLED_COLOR}" \
        in card.state_label.styleSheet()
    assert STATUS_ENABLED_COLOR == "#22c55e"      # original LED green


def test_enabled_card_scope_binds_own_text_variable(qapp):
    """The card QSS scope itself pins the label color - the isolation
    barrier that stops global-theme inheritance (M0 root-cause fix)."""
    card = _card(True)
    qss = card.styleSheet()
    assert "BlockCard QLabel { color: #ffffff; }" in qss
    # background / border keep the original design exactly
    assert "rgba(47,111,179,0.18)" in qss
    assert "border: 1px solid #2f6fb3" in qss


def test_disabled_card_keeps_original_gray(qapp):
    card = _card(False)
    qss = card.styleSheet()
    assert "rgba(128,128,128,0.15)" in qss
    assert "border: 1px dashed #9ca3af" in qss
    assert "QLabel { color: #9ca3af; }" in qss
    assert "color: #9ca3af" in card.title_label.styleSheet()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_no_theme_text_bleed_into_enabled_card(qapp, theme):
    """Under BOTH themes the enabled card's effective text colors come
    from its own scope, never from the global stylesheet: the card
    QSS must not contain any theme token (@link / @text leftovers)."""
    app_qss = build_qss(theme)
    assert "@" not in app_qss                  # tokens fully substituted
    card = _card(True)
    card_qss = card.styleSheet()
    assert "#" in card_qss and "@" not in card_qss
    # and the global QSS must not style BlockCard at all (scope split)
    assert "BlockCard" not in app_qss


# ---------------------------------------------------------- palette guard
_LIGHT_ORIGINAL = {
    "page": "#f3f5f8", "card": "#ffffff", "alt": "#eef2f7",
    "text": "#22303f", "muted": "#5b6b7a", "border": "#d0d7e0",
    "accent": "#2f6fb3", "accent_press": "#265a94",
    "accent_text": "#ffffff", "link": "#2c5fa8", "warn": "#96590f",
    "sel_bg": "#d9e7f6", "sel_text": "#1c2430",
    "danger": "#c0504d", "danger_hover": "#d3615e",
    "scroll": "#c3cddb", "scroll_hover": "#9fb0c4",
    "disabled_bg": "#eef1f5", "disabled_text": "#7a8794",
    "tab_sel_text": "#2c5fa8",
}


def test_light_theme_palette_untouched():
    """The pre-approved Light palette (login dialog etc.) is byte-for-
    byte the original - arbitrary palette drift fails this test."""
    current = {k: v for k, v in GUI_THEMES["Light"].items()
               if k != "verdicts"}
    assert current == _LIGHT_ORIGINAL


def test_light_verdicts_untouched():
    assert GUI_THEMES["Light"]["verdicts"] == {
        "ok": "#1d7a3c", "bad": "#c0392b", "run": "#2f6fb3",
        "warn": "#b35c00", "neutral": "#5b6b7a",
    }


def test_all_workflows_stages_have_cards(qapp):
    """Every workflow stage (01 DesignInput .. 10 Build Func/Interface)
    renders with the isolated card styling."""
    for stage in WORKFLOW_STAGES:
        card = BlockCard(stage, WORKFLOW_STAGES.index(stage))
        card.set_enabled(True)
        assert "color: #ffffff" in card.title_label.styleSheet()
        card.deleteLater()
