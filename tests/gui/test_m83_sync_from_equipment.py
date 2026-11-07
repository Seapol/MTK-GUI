# -*- coding: utf-8 -*-
"""M83 C15: "Sync from Equipment..." writes the profile lines the
operator ticks.

One-way only (Equipment -> script).  The review window lists the four
``AP_PROFILE_*`` values, every checkbox starts empty, passwords are
masked until "Show values" is ticked, and only the ticked lines are
rewritten - every other byte of the script stays as it was.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine import assets_config as assets  # noqa: E402
from mtkgui.gui.assets_config_dialog import (  # noqa: E402
    AssetsConfigDialog,
    SYNC_COLUMNS,
    SYNC_MASK,
    SyncFromEquipmentDialog,
)

PROJECT = "P1"
SCRIPT = ("#!/bin/sh\n"
          "# keep this comment, it must survive the sync\n"
          "AP_PROFILE_ROUTER_SSID='old-router'\n"
          "AP_PROFILE_ROUTER_PASSWORD='old-router-pw'\n"
          "AP_PROFILE_HOTSPOT_SSID='old-hotspot'\n"
          "AP_PROFILE_HOTSPOT_PASSWORD='old-hotspot-pw'\n")

EQUIPMENT = {
    "router_ap_ssid": "eq-router",
    "router_ap_password": "eq-router-pw",
    "hotspot_ssid": "eq-hotspot",
    "hotspot_password": "eq-hotspot-pw",
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _tenant(tmp_path, with_assets=True) -> str:
    base = tmp_path / "projects"
    base.mkdir(exist_ok=True)
    project = base / PROJECT
    project.mkdir(exist_ok=True)
    if with_assets:
        custom = project / f"assets_{PROJECT}" / "resources" / "scripts"
        custom.mkdir(parents=True, exist_ok=True)
        (custom / "connect_wifi.sh").write_text(SCRIPT, encoding="utf-8")
    return str(base)


def _script_path(tenant: str) -> str:
    return os.path.join(tenant, PROJECT, f"assets_{PROJECT}", "resources",
                        "scripts", "connect_wifi.sh")


def _review(tenant: str, equipment=None) -> SyncFromEquipmentDialog:
    return SyncFromEquipmentDialog(
        script_path=_script_path(tenant),
        equipment=EQUIPMENT if equipment is None else equipment)


# ---------------------------------------------------------------- button
def test_button_sits_after_recreate_from_builtin(qapp, tmp_path):
    dlg = AssetsConfigDialog(tenant_base=_tenant(tmp_path),
                             equipment_provider=lambda: {})
    dlg.refresh()
    assert dlg.btn_sync.text() == "Sync from Equipment…"
    assert dlg._action_row.indexOf(dlg.btn_sync) == \
        dlg._action_row.indexOf(dlg.btn_recreate) + 1
    dlg.deleteLater()


def test_button_disabled_without_custom_assets(qapp, tmp_path):
    dlg = AssetsConfigDialog(tenant_base=_tenant(tmp_path, with_assets=False),
                             equipment_provider=lambda: {})
    dlg.refresh()
    assert dlg.list_widget.count() == 1
    assert dlg.btn_sync.isEnabled() is False
    dlg.deleteLater()


# ----------------------------------------------------------- review window
def test_review_window_is_560_wide(qapp, tmp_path):
    dlg = _review(_tenant(tmp_path))
    assert dlg.width() == 560
    assert dlg.minimumWidth() == 560
    assert dlg.maximumWidth() == 560
    dlg.deleteLater()


def test_four_rows_three_columns(qapp, tmp_path):
    dlg = _review(_tenant(tmp_path))
    assert dlg.table.rowCount() == 4
    assert dlg.table.columnCount() == 3
    assert [dlg.table.horizontalHeaderItem(index).text()
            for index in range(3)] == list(SYNC_COLUMNS)
    assert [dlg.table.verticalHeaderItem(row).text()
            for row in range(4)] == ["Router AP SSID", "Router AP password",
                                     "Hotspot SSID", "Hotspot password"]
    dlg.deleteLater()


def test_checkboxes_default_empty_and_apply_disabled(qapp, tmp_path):
    dlg = _review(_tenant(tmp_path))
    assert all(dlg.table.item(row, 2).checkState() == Qt.CheckState.Unchecked
               for row in range(4))
    assert dlg.btn_apply.isEnabled() is False
    dlg.table.item(0, 2).setCheckState(Qt.CheckState.Checked)
    assert dlg.btn_apply.isEnabled() is True
    dlg.deleteLater()


def test_passwords_masked_until_show_values(qapp, tmp_path):
    dlg = _review(_tenant(tmp_path))
    assert dlg.table.item(1, 0).text() == SYNC_MASK
    assert dlg.table.item(1, 1).text() == SYNC_MASK
    assert dlg.table.item(3, 0).text() == SYNC_MASK
    assert dlg.table.item(0, 0).text() == "old-router"
    assert dlg.table.item(0, 1).text() == "eq-router"
    dlg.show_values.setChecked(True)
    assert dlg.table.item(1, 0).text() == "old-router-pw"
    assert dlg.table.item(1, 1).text() == "eq-router-pw"
    dlg.deleteLater()


def test_apply_writes_only_checked_lines(qapp, tmp_path):
    tenant = _tenant(tmp_path)
    dlg = _review(tenant)
    dlg.table.item(0, 2).setCheckState(Qt.CheckState.Checked)
    dlg._apply()
    text = open(_script_path(tenant), encoding="utf-8").read()
    assert "AP_PROFILE_ROUTER_SSID='eq-router'" in text
    assert "AP_PROFILE_ROUTER_PASSWORD='old-router-pw'" in text
    assert "AP_PROFILE_HOTSPOT_SSID='old-hotspot'" in text
    assert dlg.summary.text() == "1 values written, 0 already in sync"
    dlg.deleteLater()
