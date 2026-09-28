# -*- coding: utf-8 -*-
"""Offscreen page previews for the demo.

Renders the three tabs of MTK GUI to PNG files (no display needed):

    QT_QPA_PLATFORM=offscreen ./mtk_gui/bin/python scripts/capture_preview.py

Output goes to preview/equipment.png, preview/test_workflow.png and
preview/serial_console.png.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "preview"
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication

from mtkgui.main_window import MainWindow
from mtkgui.style import QSS

app = QApplication(sys.argv)
app.setStyleSheet(QSS)
w = MainWindow()
w.resize(1680, 1000)
w.show()

# Simulate a full demo pass so the Test Work Flow page looks alive.
w.workflow_page.run_demo()
app.processEvents()

OUT.mkdir(exist_ok=True)
for index, name in enumerate(("equipment", "test_workflow", "serial_console")):
    w.tabs.setCurrentIndex(index)
    app.processEvents()
    pix = w.grab()
    path = OUT / f"{name}.png"
    pix.save(str(path))
    print(f"saved {path}")

print("PREVIEW CAPTURE DONE")
