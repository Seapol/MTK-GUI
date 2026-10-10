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
        # full-size canvas before grabbing
        widget.resize(1380, 820)
    for _ in range(3):
        app.processEvents()
    return widget.grab()


SCREENS = {
    # main tabs -------------------------------------------------------
    "01_login": lambda app, w: _login(app),
    "02_test_workflow": lambda app, w: _grab(app, w, w.workflow_page),
    "03_equipment": lambda app, w: _grab(app, w, w.equipment_page),
    "04_yaml_build": lambda app, w: _grab(app, w, w.yaml_build_page),
    "05_channel_allocation":
        lambda app, w: _grab(app, w, w.channel_alloc_page),
    # yaml build sub-stages (12-stage block flow) ---------------------
    "06_yaml_design_input":
        lambda app, w: _grab(app, w, _find(w.yaml_build_page, "Design Input")),
    "07_yaml_parse_nets":
        lambda app, w: _grab(app, w, _find(w.yaml_build_page, "Parse")),
    "08_yaml_instruments":
        lambda app, w: _grab(app, w, _find(w.yaml_build_page, "Instrument")),
    "09_yaml_validate":
        lambda app, w: _grab(app, w, _find(w.yaml_build_page, "Validate")),
    # test workflow details -------------------------------------------
    "10_overall_flow":
        lambda app, w: _grab(app, w, _find(w.workflow_page, "Overall")),
    "11_power_rails":
        lambda app, w: _grab(app, w, _find(w.workflow_page, "Rail")),
    "12_console":
        lambda app, w: _grab(app, w, _find(w.workflow_page, "Console")),
}


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
    window.resize(1440, 1150)
    window.show()
    # give the tab area the bulk of the vertical space (screenshots
    # should show the pages, not a squeezed strip); run twice so the
    # post-paint minimum-height locks are already in place
    for _ in range(2):
        try:
            window.splitter.setSizes([60, 100000, 220])
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

    tabs.setCurrentIndex(saved)
    app.processEvents()

    for name, why in failures:
        print(f"FAILED {name}: {why}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
