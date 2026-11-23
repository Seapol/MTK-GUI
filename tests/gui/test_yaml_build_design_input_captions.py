# -*- coding: utf-8 -*-
"""m106c: Design Input captions get their own band below the buttons."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from mtkgui.gui.yamlbuild.design_input_panel import DesignInputPanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_caption_rows_never_overlap_buttons():
    panel = DesignInputPanel()
    panel.show()
    _app().processEvents()

    buttons_bottom = max(
        b.geometry().bottom()
        for b in (panel.btn_import_spf, panel.btn_import_net,
                  panel.btn_import_bom)
    )
    captions_top = min(
        lbl.geometry().top()
        for lbl in (panel.lbl_spf, panel.lbl_net, panel.lbl_bom)
    )
    assert captions_top >= buttons_bottom


def test_captions_follow_route():
    panel = DesignInputPanel()
    panel.radio_excel.setChecked(True)
    panel._on_route_changed(panel.radio_excel)
    assert not panel._files_route.isEnabled()
    panel.radio_files.setChecked(True)
    panel._on_route_changed(panel.radio_files)
    assert panel._files_route.isEnabled()
