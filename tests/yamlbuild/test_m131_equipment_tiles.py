# -*- coding: utf-8 -*-
"""M131: node 04 is a launcher of module tiles, each opening its own dialog."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QDialog, QLabel  # noqa: E402

from mtkgui.gui.yamlbuild.equipment_panel import (  # noqa: E402
    MODULES, EquipmentConfigPanel, ModuleTile)


def _panel(provider=None) -> EquipmentConfigPanel:
    panel = EquipmentConfigPanel(equipment_provider=provider)
    panel.resize(1000, 520)
    panel.show()
    return panel


def test_launcher_has_seven_tiles_and_matching_pages():
    panel = _panel()
    try:
        assert list(panel.tiles) == [m[0] for m in MODULES]
        assert set(panel._pages) == set(panel.tiles)
        for tile in panel.tiles.values():
            assert isinstance(tile, ModuleTile)
            assert tile.minimumHeight() >= 100
    finally:
        panel.deleteLater()


def test_instruments_is_the_wide_banner():
    panel = _panel()
    try:
        width = panel.tiles["instruments"].width()
        for key, tile in panel.tiles.items():
            if key == "instruments":
                continue
            assert tile.width() < width
    finally:
        panel.deleteLater()


def test_locked_tiles_refuse_to_open_and_say_locked():
    panel = _panel()
    try:
        for key in ("power", "rgnd", "clock", "rails", "fixture", "periph"):
            assert panel.tiles[key].badge.text() == "LOCKED"
            assert panel.open_module(key) is None
        assert panel.open_module("instruments") is not None
    finally:
        panel.deleteLater()


def test_each_module_opens_its_own_dialog():
    panel = _panel()
    try:
        panel.btn_check.click()
        for key, title, _blurb, _w, _h in MODULES:
            dlg = panel.open_module(key)
            assert isinstance(dlg, QDialog)
            assert title in dlg.windowTitle()
            labels = [w.text() for w in dlg.findChildren(QLabel)]
            assert title in labels
            titles = {w.windowTitle() for w in dlg.findChildren(QDialog)}
            assert not titles  # no nested dialog
            dlg.close()
        # reopening the same module reuses one dialog instance
        first = panel.open_module("clock")
        second = panel.open_module("clock")
        assert first is second
        first.close()
    finally:
        panel.deleteLater()


def test_dialogs_carry_the_page_widgets():
    panel = _panel()
    try:
        panel.btn_check.click()
        power = panel.open_module("power")
        assert panel.src_psu.isVisible() or panel.src_psu.parent() is not None
        assert panel.src_psu.isChecked() is True
        assert panel.relay_box.isChecked() in (True, False)
        power.close()

        inst = panel.open_module("instruments")
        assert panel.btn_check.text() == "Check availability"
        assert panel.btn_check.minimumHeight() >= 40
        inst.close()
    finally:
        panel.deleteLater()


def test_dialogs_are_resizable_with_a_floor():
    panel = _panel()
    try:
        panel.btn_check.click()
        for key, _title, _blurb, width, _height in MODULES:
            page = panel.page(key)
            content_h = max(page.minimumSizeHint().height(),
                            page.minimumSize().height(),
                            page.sizeHint().height())
            dlg = panel.open_module(key)
            assert dlg.size().width() >= min(width, 680)
            # M158c: the height follows the page content, not a fixed floor
            assert dlg.size().height() >= min(content_h + 110, 480) - 2
            assert dlg.minimumWidth() <= dlg.width()
            dlg.close()
    finally:
        panel.deleteLater()


def test_badges_track_the_config():
    # M158b: fixture / peripherals are read-only station mirrors - the
    # badge follows the Equipment node, not a page checkbox
    panel = _panel(lambda: {"equipment": {
        "peripherals": {"wifi": {"declared": True}}}})
    try:
        assert panel.tiles["instruments"].badge.text() == "NOT CHECKED"
        panel.btn_check.click()
        assert panel.tiles["instruments"].badge.text() == "CHECKED"
        panel.set_power_nets([{"name": "VDD_ARM", "test_point": "TP1"}])
        assert panel.tiles["rgnd"].badge.text() == "1 NETS"
        assert panel.tiles["periph"].badge.text() == "1 ON"
    finally:
        panel.deleteLater()
