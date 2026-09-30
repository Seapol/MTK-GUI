# -*- coding: utf-8 -*-
"""Offscreen page previews for the demo.

Renders the application to PNG files (no display needed):

    QT_QPA_PLATFORM=offscreen ./mtk_gui/bin/python scripts/capture_preview.py

Output:
    preview/equipment.png      - Equipment block diagram (Real mode)
    preview/test_workflow.png  - Test Work Flow tables (Real mode demo)
    preview/serial_console.png - virtual DUT console (Virtual mode)
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "preview"
sys.path.insert(0, str(REPO))

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from mtkgui.main_window import MainWindow
from mtkgui.project_config import load_config, apply_config
from mtkgui.style import QSS

app = QApplication(sys.argv)
app.setStyleSheet(QSS)
OUT.mkdir(exist_ok=True)

YAML = REPO / "config" / "FRDM-IMX93_12345_Dev_rev1.1.yaml"

# ------------------------------------------------------------------ Real mode
w = MainWindow()
w.resize(1680, 1000)
w.show()

# load the demo project, then simulate a full pass so the page is alive
cfg = load_config(str(YAML))
apply_config(cfg, w.workflow_page, w.equipment_page)
w.workflow_page.project_path = str(YAML)
w.workflow_page.run_demo()
app.processEvents()

# tab order: 0 = Test Work Flow, 1 = Equipment
w.tabs.setCurrentIndex(1)
app.processEvents()
w.grab().save(str(OUT / "equipment.png"))
print(f"saved {OUT / 'equipment.png'}")

w.tabs.setCurrentIndex(0)
app.processEvents()
wp = w.workflow_page
wp.ict.verticalScrollBar().setValue(0)
wp.fct.verticalScrollBar().setValue(0)
QTest.qWait(150)
wp.ict.verticalScrollBar().setValue(0)
wp.fct.verticalScrollBar().setValue(0)
app.processEvents()
w.grab().save(str(OUT / "test_workflow.png"))
print(f"saved {OUT / 'test_workflow.png'}")
w.close()

# --------------------------------------------------------------- Virtual mode
# The serial console preview shows a connected virtual DUT with its boot
# log; the console widget is grabbed directly for a clean, full-size shot.
wv = MainWindow(role="Supervisor", mode="Virtual")
wv.resize(1680, 1000)
wv.show()
mc = wv.workflow_page.multi_console
mc.add_serial()
mc.open_channel("ser1")  # fake port: connects to the simulated DUT
for _ in range(60):      # let the whole boot log stream in (~3 s)
    QTest.qWait(50)
    if "login:" in mc.console("ser1").view.toPlainText():
        QTest.qWait(400)  # drain the prompt line too
        break
# the terminal lives in a per-channel popup ConsoleWindow
mc._show_console("ser1")
QTest.qWait(300)
win = mc.channels["ser1"]["console_window"]
win.repaint()
win.grab().save(str(OUT / "serial_console.png"))
print(f"saved {OUT / 'serial_console.png'}")
wv.close()

print("PREVIEW CAPTURE DONE")
