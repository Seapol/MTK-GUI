# -*- coding: utf-8 -*-
"""M158c: node 04 module dialogs size to their page content.

The power dialog's natural hint was 374x746, but the app-wide dialog
centerer enlarged every dialog to 1.5x on first show (561x1119), leaving
~400 px of dead space under ``PSU settings``.  The module dialogs now
carry their own content-driven height and the centerer only centers
them.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.equipment_panel import (  # noqa: E402
    EquipmentConfigPanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _content_h(panel: EquipmentConfigPanel, key: str) -> int:
    page = panel.page(key)
    return max(page.minimumSizeHint().height(),
               page.minimumSize().height(),
               page.sizeHint().height())


def test_module_dialog_height_tracks_page_content(qapp):
    panel = EquipmentConfigPanel()
    try:
        panel.btn_check.click()
        for key in ("power", "fixture", "periph"):
            content = _content_h(panel, key)
            dialog = panel.open_module(key)
            # content + 130 px chrome, never the old 1.5x enlargement
            assert dialog.height() <= content + 130 + 8, (
                key, dialog.height(), content)
            assert dialog.height() >= min(content + 110, 480) - 2, key
            dialog.close()
    finally:
        panel.deleteLater()


def test_module_dialogs_are_not_enlarged_by_the_centerer(qapp):
    from mtkgui.main_window import DialogCenterer
    centerer = DialogCenterer(qapp)
    qapp.installEventFilter(centerer)
    panel = EquipmentConfigPanel()
    try:
        panel.btn_check.click()
        content = _content_h(panel, "power")
        dialog = panel.open_module("power")
        qapp.processEvents()
        assert dialog.height() <= content + 130 + 8
        assert dialog.property("_dlg_enlarged") is None
        dialog.close()
    finally:
        qapp.removeEventFilter(centerer)
        panel.deleteLater()
