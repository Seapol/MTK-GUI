#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture the chapter 15/16 walkthrough screenshots on the CURRENT
UI, using the real 96624 and FRDM-IMX93 sources.

`capture_screens.py --examples` covers the loaded-plan pages.  This
script covers the *steps*: node 01 with the three files imported, the
Parse Nets classification result, node 05 with the built sequence, and
the FCT sequence editor of the shipped plan.

    QT_QPA_PLATFORM=offscreen python scripts/capture_walkthrough.py

Every grab is a real widget state produced by the same calls the GUI
makes; nothing is mocked except the file-picker answers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "help" / "images"
PROJ = ROOT / "projects"

SRC = {
    "spf": PROJ / "96624" / "SPF-96624_A.pdf",
    "net": PROJ / "96624" / "NET-96624_A.net",
    "bom": PROJ / "96624" / "BoM-750-96624.xlsx",
}
FCT_PLAN = (ROOT / "examples" / "fct_frdm_imx93"
            / "FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev_1.3.1.yaml")

FAILED: list[tuple[str, str]] = []


def shot(app, name: str, widget, size=None) -> None:
    if size:
        widget.resize(*size)
    for _ in range(4):
        app.processEvents()
    pix = widget.grab()
    path = OUT / f"{name}.png"
    if pix.save(str(path), "PNG"):
        print(f"captured {path.name} ({pix.width()}x{pix.height()})")
    else:
        FAILED.append((name, "save failed"))


def pump(app, seconds: float, until=None) -> bool:
    """Spin the event loop up to *seconds*; returns True as soon as
    *until()* says the background work is done."""
    import time
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        if until and until():
            for _ in range(3):
                app.processEvents()
            return True
        time.sleep(0.02)
    return bool(until and until())


def _scroll_top(dlg) -> None:
    from PySide6.QtWidgets import QScrollArea
    for area in dlg.findChildren(QScrollArea):
        area.verticalScrollBar().setValue(0)


def patch_pickers(paths: list[Path]):
    """Answer every file picker from the queue, in order."""
    from PySide6.QtWidgets import QFileDialog
    queue = list(paths)

    def _open(parent=None, caption="", directory="", filt="", *a, **k):
        return (str(queue.pop(0)) if queue else "", "")

    QFileDialog.getOpenFileName = staticmethod(_open)


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from mtkgui.main_window import MainWindow
    from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
    from mtkgui.style import build_qss

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(role="Supervisor", mode="Virtual")
    window.resize(2240, 1750)
    window.show()
    app.setStyleSheet(build_qss("Ocean"))
    MainWindow._applied_theme = "Ocean"
    for _ in range(2):
        try:
            window.splitter.setSizes([60, 100000, 140])
        except Exception:                      # noqa: BLE001
            pass
        pump(app, 0.2)

    page = window.yaml_build_page
    tabs = window.tabs
    for i in range(tabs.count()):
        if tabs.widget(i) is page:
            tabs.setCurrentIndex(i)
            break
    pump(app, 0.2)

    # ---- node 01: the three files, one at a time -------------------
    def design_dialog():
        return BlockConfigDialog("design_input", {}, page)

    dlg = design_dialog()
    dlg.resize(920, 860)
    dlg.show()
    try:
        dlg.panel.chk_enable.setChecked(True)
    except Exception:                          # noqa: BLE001
        pass
    pump(app, 0.3)
    shot(app, "15_01_design_input", dlg)

    if not SRC["spf"].exists():
        FAILED.append(("15_02_spf", f"missing {SRC['spf']}"))
    else:
        patch_pickers([SRC["spf"]])
        dlg.panel._import_spf()
        pump(app, 25.0,
             until=lambda: bool(dlg.panel.edit_product_id.text().strip())
             and "not imported" not in dlg.panel.lbl_spf.text())
        print("SPF fields:", dlg.panel.edit_product_id.text(),
              "|", dlg.panel.lbl_spf.text())
        shot(app, "15_02_spf_imported", dlg)

    patch_pickers([SRC["net"], SRC["bom"]])
    dlg.panel._import_net()
    pump(app, 1.0)
    dlg.panel._import_bom()
    pump(app, 5.0)
    print("panel values:", {k: v for k, v in dlg.panel.values().items()
                            if k in ("product_id", "part_number", "spf_file",
                                     "net_file", "bom_file")})
    shot(app, "15_03_three_files", dlg)
    dlg.close()

    # ---- node 02: real parse of the 2 231 nets --------------------
    net_text = SRC["net"].read_text(errors="ignore") \
        if SRC["net"].exists() else ""
    page.model.set_params("design_input", dlg.panel.values())
    ndlg = BlockConfigDialog("parse_ict", {}, page,
                             net_source=(net_text, SRC["net"].name),
                             yaml_model=page.model, panel_state=None)
    ndlg.resize(1320, 900)
    ndlg.show()
    pump(app, 0.3)
    ndlg.nets_panel._on_parse_clicked()
    pump(app, 120.0, until=lambda: ndlg.nets_panel.table.rowCount() > 0)
    if ndlg.nets_panel.table.rowCount() == 0:
        FAILED.append(("15_04_parse", "no rows after parse"))
    shot(app, "15_04_parse_result", ndlg)
    try:
        ndlg.nets_panel.import_to_yaml()
        pump(app, 3.0)
    except Exception as exc:                    # noqa: BLE001
        FAILED.append(("15_04_parse", f"import_to_yaml: {exc!r}"))
    ndlg.close()
    pump(app, 0.5)

    # ---- node 05: the derived ICT sequence (rails / clocks / gpios)
    from mtkgui import project_config
    ict_plan = (ROOT / "examples" / "ict_96624"
                / "A-96624_ICT_Demo_v1.0.1.yaml")
    ict_cfg = project_config.load_config(ict_plan)
    project_config.apply_config(ict_cfg, window.workflow_page,
                                window.equipment_page, page.model)
    page.refresh_all()
    pump(app, 0.5)
    bdlg = BlockConfigDialog("rails", page.model.get_params("rails") or {},
                             page)
    bdlg.resize(1000, 900)
    bdlg.show()
    pump(app, 1.0)
    _scroll_top(bdlg)
    shot(app, "15_05_build_ict", bdlg)
    bdlg.close()

    # ---- the page itself: net table + allocation -----------------


    # ---- chapter 16: the shipped FCT plan in node 06 -------------
    from mtkgui import project_config
    cfg = project_config.load_config(FCT_PLAN)
    project_config.apply_config(cfg, window.workflow_page,
                                window.equipment_page, page.model)
    page.refresh_all()
    pump(app, 1.0)
    fdlg = BlockConfigDialog("fct_build", page.model.get_params("fct_build")
                             or {}, page)
    fdlg.resize(1500, 950)
    fdlg.show()
    pump(app, 1.0)
    _scroll_top(fdlg)
    shot(app, "16_01_fct_sequence", fdlg)
    fdlg.close()

    for name, why in FAILED:
        print(f"FAILED {name}: {why}", file=sys.stderr)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
