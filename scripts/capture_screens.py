#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture GUI screenshots for the User Guide (docs/help/images/).

Run offscreen so it works on CI and without disturbing a desktop:

    QT_QPA_PLATFORM=offscreen python scripts/capture_screens.py

GUI 改版后重跑本脚本即可一键刷新全部截图。新增页面时在
SCREENS 里加一行 (文件名, 取图函数) 即可。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# offscreen before QApplication is created (CI-safe, no window flash)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "help" / "images"

def _activate(app, window, widget):
    """Make the tab containing *widget* current so its layout gets real
    sizes (offscreen widgets never shown keep a 640x480 default)."""
    tabs = window.tabs
    node = widget
    while node is not None:
        for i in range(tabs.count()):
            if tabs.widget(i) is node:
                tabs.setCurrentIndex(i)
                break
        else:
            node = node.parentWidget()
            continue
        break
    for _ in range(5):
        app.processEvents()


def _grab(app, window, widget):
    _activate(app, window, widget)
    if widget.parentWidget() is window.tabs:
        # offscreen pages never get a real layout pass - force a
        # full-size canvas before grabbing (large enough that no
        # text is clipped)
        widget.resize(1560, 900)
    for _ in range(3):
        app.processEvents()
    return widget.grab()


SCREENS = {
    # main tabs -------------------------------------------------------
    "01_login": lambda app, w: _login(app),
    "02_test_workflow": lambda app, w: _grab(app, w, w.workflow_page),
    "03_equipment": lambda app, w: _grab(app, w, w.equipment_page),
    "04_yaml_build": lambda app, w: _grab(app, w, w.yaml_build_page),
    # test workflow details -------------------------------------------
    # 10 = the Overall Flow group: project file + the stop-policy
    # checkboxes (the Run Control group itself carries only Run / Stop
    # / Long Run and is visible in 02_test_workflow.png)
    "10_overall_flow":
        lambda app, w: _grab(app, w, w.workflow_page.overall_group),
    "11_power_rails":
        lambda app, w: _grab(app, w, _find(w.workflow_page, "Rail")),
    "12_console":
        lambda app, w: _grab(app, w, _find(w.workflow_page, "Console")),
    # instrument configuration windows (real dialogs, equipment ch.) --
    "13_inst_daq973a": lambda app, w: _instrument(app, w, "daq973a"),
    "14_inst_daqm908a": lambda app, w: _instrument(app, w, "m908a_1"),
    "15_inst_daqm907a": lambda app, w: _instrument(app, w, "m907a"),
    "16_inst_u2355a": lambda app, w: _instrument(app, w, "u2355a"),
    "17_inst_n5747a": lambda app, w: _instrument(app, w, "psu"),
    # yaml build: embedded channel allocation tables + block dialogs
    # (the 12-stage sub-stage close-ups are retired with the old flow;
    # 08/09 were unreferenced and deleted)
    "05_channel_allocation":
        lambda app, w: _grab(app, w, w.yaml_build_page.channel_alloc),
    "06_yaml_design_input":
        lambda app, w: _block_dialog(app, w, "design_input"),
    "07_yaml_parse_nets":
        lambda app, w: _block_dialog(app, w, "parse_ict"),
}

_DIALOGS = []


def _instrument(app, window, key: str):
    """Open the real instrument configuration dialog of the Equipment
    page (non-modal, offscreen) so it can be grabbed."""
    from mtkgui.equipment_page import _InstrumentDialog
    while _DIALOGS:                          # close the previous one
        _DIALOGS.pop().close()
    page = window.equipment_page
    cfg = page.configs[key]
    dlg = _InstrumentDialog(window, cfg["title"], cfg["fields"], key,
                            page.virtual_mode, manual=False, config=cfg)
    dlg.set_connected(page._instrument_connections.get(key, False))
    dlg.resize(dlg.sizeHint().expandedTo(dlg.size()))
    dlg.show()
    for _ in range(5):
        app.processEvents()
    _DIALOGS.append(dlg)
    return dlg


def _block_dialog(app, window, key: str):
    """Open one Yaml Build block config dialog (non-modal, offscreen)
    so it can be grabbed.  NOTE: BlockFlowWidget.open_dialog() runs a
    modal exec() - construct the BlockConfigDialog directly instead."""
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    while _DIALOGS:                          # close the previous one
        _DIALOGS.pop().close()
    page = window.yaml_build_page
    net = page.model.imported.get("net") or {}
    dlg = BlockConfigDialog(
        key, page.model.get_params(key) or {}, page,
        net_source=(net.get("raw", ""), Path(net.get("file", "")).name)
        if key == "parse_ict" else None,
        panel_state=None)
    dlg.resize(dlg.sizeHint().expandedTo(dlg.size()))
    dlg.show()
    for _ in range(5):
        app.processEvents()
    _DIALOGS.append(dlg)
    return dlg


def _login(app):
    from mtkgui.permissions import LoginDialog
    dlg = LoginDialog()
    dlg.resize(dlg.sizeHint().expandedTo(dlg.size()))
    return dlg


def _find(page, keyword: str):
    """First child widget whose objectName / windowTitle / QGroupBox
    title contains the keyword (case-insensitive); falls back to the
    page itself."""
    kw = keyword.lower()
    from PySide6.QtWidgets import QWidget, QGroupBox
    for child in page.findChildren(QWidget):
        titles = [child.objectName(), child.windowTitle()]
        if isinstance(child, QGroupBox):
            titles.append(child.title())
        for attr in titles:
            if attr and kw in attr.lower():
                return child
    return page


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from mtkgui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(role="Supervisor", mode="Virtual")
    # 2240px wide: the five workflow cards get ~430 px each so every
    # card title fits ONE line (the card height is locked at 46 px -
    # wrapped titles would clip, user directive 2026-10-14)
    window.resize(2240, 1750)
    window.show()
    # user directive 2026-10-14: ALL guide screenshots use the Ocean
    # theme.  Apply the stylesheet DIRECTLY - apply_gui_theme() would
    # persist the choice into the user's QSettings.
    from mtkgui.style import build_qss
    app.setStyleSheet(build_qss("Ocean"))
    MainWindow._applied_theme = "Ocean"
    # give the tab area the bulk of the vertical space (screenshots
    # should show the pages, not a squeezed strip); run twice so the
    # post-paint minimum-height locks are already in place
    for _ in range(2):
        try:
            window.splitter.setSizes([60, 100000, 140])
        except Exception:                        # noqa: BLE001 - cosmetic
            pass
        for _ in range(5):
            app.processEvents()

    OUT.mkdir(parents=True, exist_ok=True)
    tabs = window.tabs
    saved = tabs.currentIndex()

    failures = []
    for name, getter in SCREENS.items():
        try:
            widget = getter(app, window)
            app.processEvents()
            if widget is None:
                failures.append((name, "widget not found"))
                continue
            pix = widget if hasattr(widget, "save") \
                else widget.grab()
            path = OUT / f"{name}.png"
            if not pix.save(str(path), "PNG"):
                failures.append((name, "save failed"))
            else:
                print(f"captured {path.name} ({pix.width()}x{pix.height()})")
        except Exception as exc:                 # noqa: BLE001
            failures.append((name, repr(exc)))

    while _DIALOGS:                          # close the last grabbed dialog
        _DIALOGS.pop().close()
    tabs.setCurrentIndex(saved)
    app.processEvents()

    for name, why in failures:
        print(f"FAILED {name}: {why}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
