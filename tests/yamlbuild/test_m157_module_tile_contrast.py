# -*- coding: utf-8 -*-
"""M157: node 04 module tiles draw as cards (badge legibility).

The theme template paints every ``QPushButton`` with the accent fill, so a
``QPushButton#moduleTile`` carried card-coloured labels on a primary-button
background (3.9:1).  The tile is a card now; the Instruments gate keeps its
emphasis through the ``gate`` property instead of the fill.
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.style import GUI_THEMES, build_qss  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _tile_block(qss: str) -> str:
    match = re.search(r"QPushButton#moduleTile \{(.*?)\}", qss, re.S)
    assert match is not None, "QPushButton#moduleTile block missing"
    return match.group(1)


def test_the_module_tiles_are_cards_in_both_themes():
    for theme in ("Light", "Dark"):
        block = _tile_block(build_qss(theme))
        assert f"background-color: {GUI_THEMES[theme]['card']}" in block, theme


def test_the_gate_tile_is_framed(qapp):
    from mtkgui.gui.yamlbuild.equipment_panel import EquipmentConfigPanel
    panel = EquipmentConfigPanel()
    try:
        assert panel.tiles["instruments"].property("gate") is True
        for key, tile in panel.tiles.items():
            if key == "instruments":
                continue
            assert not tile.property("gate"), key
        assert 'QPushButton#moduleTile[gate="true"]' in build_qss("Light")
    finally:
        panel.deleteLater()


def test_the_tile_badge_keeps_its_tone_rules():
    qss = build_qss("Light")
    for tone in ("ok", "warn", "muted"):
        assert f'QLabel[tone="{tone}"]' in qss, tone
