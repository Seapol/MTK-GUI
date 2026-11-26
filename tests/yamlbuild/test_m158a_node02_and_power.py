# -*- coding: utf-8 -*-
"""M158a: node 02 refuses an empty Route A parse; node 04 power page.

The padlock must not report ``Completed`` on an empty netlist table, and
the power page has to name the real input source, explain the adapter
route and show a read-only availability-check ``Status``.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication,  # noqa: E402
                               QGroupBox)

from mtkgui.gui.yamlbuild.equipment_config import (  # noqa: E402
    INSTRUMENT_KEYS,
    INSTRUMENT_LABEL,
)
from mtkgui.gui.yamlbuild.equipment_panel import (  # noqa: E402
    EquipmentConfigPanel,
)
from mtkgui.gui.yamlbuild.parse_nets_v2_panel import (  # noqa: E402
    ParseNetsV2Panel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ node 02
def test_empty_route_a_parse_blocks_lock(qapp):
    panel = ParseNetsV2Panel()
    try:
        assert panel.state().rows == []
        ok, message = panel.validate()
        assert ok is False
        assert message == "Parse found no nets — press Parse nets first"
    finally:
        panel.deleteLater()


# ------------------------------------------------------------ power page
def test_power_page_uses_new_labels(qapp):
    panel = EquipmentConfigPanel()
    try:
        assert panel.src_psu.text() == "PSU N5747A"
        assert panel.src_adapter.text() == "External DC power adaptor"
    finally:
        panel.deleteLater()


def test_adapter_shows_note_and_grays_psu_settings(qapp):
    panel = EquipmentConfigPanel()
    try:
        assert panel.src_note.isHidden()
        assert panel.psu_group.isEnabled()

        panel.src_adapter.setChecked(True)
        assert not panel.src_note.isHidden()
        assert not panel.psu_group.isEnabled()
        assert "plug the DUT in and out by hand" in panel.src_note.text()

        panel.src_psu.setChecked(True)
        assert panel.src_note.isHidden()
        assert panel.psu_group.isEnabled()
    finally:
        panel.deleteLater()


def test_psu_group_is_named_settings_and_has_status(qapp):
    panel = EquipmentConfigPanel()
    try:
        titles = [box.title()
                  for box in panel.page("power").findChildren(QGroupBox)]
        assert "PSU settings" in titles
        assert "PSU limits" not in titles
        assert panel.psu_group.title() == "PSU settings"
        assert panel.lbl_psu_status.text() == "Not checked yet"
        panel._on_check()
        assert panel._check_status
        assert panel.lbl_psu_status.text() == panel._check_status
        assert panel._check_status.endswith("not probed")
    finally:
        panel.deleteLater()


def test_check_availability_reports_provider_status(qapp):
    def provider():
        node = {key: {"fields": {"Status": "Available"}}
                for key in INSTRUMENT_KEYS}
        return {"equipment": node}

    panel = EquipmentConfigPanel(equipment_provider=provider)
    try:
        panel.btn_check.click()
        status = panel._check_status
        assert "6 of 6 instruments enabled" in status
        assert f"{INSTRUMENT_LABEL['daq973a']} Available" in status
        assert f"{INSTRUMENT_LABEL['n5747a']} Available" in status
        assert panel.tiles["instruments"].badge.text() == "CHECKED"
        assert status in panel.tiles["instruments"].lbl_sub.text()
        assert panel.lbl_psu_status.text() == status
    finally:
        panel.deleteLater()
