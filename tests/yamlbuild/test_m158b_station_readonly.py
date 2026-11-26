# -*- coding: utf-8 -*-
"""M158b: node 04 fixture / peripheral pages mirror the Equipment page.

Station-level wiring is configured on the Equipment page only; the node
04 pages show read-only values plus one navigation button, and their
tiles follow the same station node.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication,  # noqa: E402
                               QCheckBox, QLabel, QLineEdit, QPushButton)

from mtkgui.gui.yamlbuild.equipment_panel import (  # noqa: E402
    PERIPHERAL_LABELS,
    EquipmentConfigPanel,
)

HINT = "Station-level settings — configured on the Equipment page."


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _labels(widget) -> list[str]:
    return [label.text() for label in widget.findChildren(QLabel)]


def test_fixture_page_is_read_only_with_open_equipment_button(qapp):
    panel = EquipmentConfigPanel()
    try:
        page = panel.page("fixture")
        assert page.findChildren(QLineEdit) == []
        assert page.findChildren(QCheckBox) == []
        assert HINT in _labels(page)
        assert panel.port1.text()
        assert panel.port2.text()
        buttons = [b.text() for b in page.findChildren(QPushButton)]
        assert "Open Equipment page" in buttons
        # the eight fixed station signals are still listed, read-only
        assert len(panel.signal_labels) == 8
    finally:
        panel.deleteLater()


def test_peripheral_page_uses_host_pc_labels(qapp):
    panel = EquipmentConfigPanel()
    try:
        page = panel.page("periph")
        assert page.findChildren(QCheckBox) == []
        assert HINT in _labels(page)
        texts = [panel.periph_labels[key].text()
                 for key, _label in PERIPHERAL_LABELS]
        assert texts == [
            "Wi-Fi (Host PC Wi-Fi adapter)",
            "Bluetooth (Host PC Bluetooth adapter)",
            "Router (bench router)",
            "DUT serial console (USB on Host PC)",
        ]
        buttons = [b.text() for b in page.findChildren(QPushButton)]
        assert "Open Equipment page" in buttons
    finally:
        panel.deleteLater()


def test_open_equipment_button_emits_signal(qapp):
    panel = EquipmentConfigPanel()
    try:
        seen: list = []
        panel.equipment_page_requested.connect(lambda: seen.append(True))
        for key in ("fixture", "periph"):
            button = next(b for b in panel.page(key).findChildren(QPushButton)
                          if b.text() == "Open Equipment page")
            button.click()
        assert seen == [True, True]
    finally:
        panel.deleteLater()


def test_station_provider_values_feed_the_mirror(qapp):
    def provider():
        return {"equipment": {
            "fixture": {"port1": "901", "port2": "902",
                        "signals": {"relay": {"enabled": False}}},
            "peripherals": {"wifi": {"declared": True}},
        }}

    panel = EquipmentConfigPanel(equipment_provider=provider)
    try:
        assert panel.port1.text() == "901"
        assert panel.port2.text() == "902"
        assert panel.signal_states["relay"].text() == "off"
        assert panel.signal_states["clamped"].text() == "on"
        assert panel.periph_states["wifi"].text() == "on"
        assert panel.periph_states["bt"].text() == "off"
        panel.btn_check.click()          # badges unlock after the check
        assert panel.tiles["periph"].badge.text() == "1 ON"
        assert "901 / 902" in panel.tiles["fixture"].lbl_sub.text()
    finally:
        panel.deleteLater()
