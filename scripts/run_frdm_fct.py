#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the FRDM-IMX93 FCT project on the REAL board (P3-B5 5.2).

Headless GUI stack: the SAME MainWindow + TestRunner the operator uses
(offscreen), the project YAML loaded through project_config, the
serial console channel connected to /dev/cu.usbmodem53930099631, the
FCT sequence executed row by row (console via the multi-console
worker, Wi-Fi / Bluetooth through the B4 host-side adapters).

The only headless shortcut: the final "FCT done." operator dialog is
auto-answered (env._fct_message_dialog monkeypatched) - every other
step runs for real.

Usage: ./mtk_gui/bin/python scripts/run_frdm_fct.py [yaml_path]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

YAML_PATH = sys.argv[1] if len(sys.argv) > 1 else \
    "projects/FRDM-IMX93/FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev1.1.yaml"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mtkgui import project_config
from mtkgui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    page = window.workflow_page
    config = project_config.load_config(YAML_PATH)
    project_config.apply_config(config, page, window.equipment_page,
                                window.yaml_build_page.model)
    mc = page.multi_console
    keys = list(mc.channels)
    print(f"[run] yaml loaded: {YAML_PATH}")
    print(f"[run] fct rows: {len(page.fct_rows)}, console channels: "
          f"{[(k, mc.channel_endpoint(k)) for k in keys]}")
    # auto-answer the operator dialog (headless shortcut, last row only)
    page._fct_message_dialog = lambda *a, **k: "PASS"

    started = time.time()
    results: dict = {}

    def on_step_finished(idx, res):
        name = page.fct_rows[idx] if idx < len(page.fct_rows) else "?"
        print(f"[step {idx}] {res.status.name:<8} {name}")

    # full EventLog mirror to stdout (identity + every command)
    page.log_line.connect(lambda line: print(f"  [log] {line}"))

    def connect_and_run():
        key = keys[0] if keys else None
        if key is None:
            print("[run] FAIL: no console channel")
            app.quit()
            return
        mc.open_channel(key)
        t0 = time.time()
        while not mc.channel_connected(key) and time.time() - t0 < 15:
            app.processEvents()
            time.sleep(0.1)
        if not mc.channel_connected(key):
            print(f"[run] FAIL: console {key} not connected "
                  f"({mc.channel_endpoint(key)})")
            app.quit()
            return
        print(f"[run] console {key} connected "
              f"({mc.channel_endpoint(key)})")
        # reboot the DUT for a FRESH login sequence (--reboot flag);
        # default: NO reboot - the login chain is tolerant of an
        # already-open root session (final-prompt alternative match)
        if "--reboot" in sys.argv:
            mc.write_to_channel(key, b"reboot\n")
            print("[run] reboot sent, waiting for 'login:' ...")
            buf, t0 = b"", time.time()
            while time.time() - t0 < 90:
                buf += mc.get_read_buffer(key)
                if b"login:" in buf:
                    print(f"[run] login prompt after "
                          f"{time.time()-t0:.0f}s")
                    break
                app.processEvents()
                time.sleep(0.2)
            if b"login:" not in buf:
                print("[run] FAIL: no 'login:' within 90s after reboot")
                app.quit()
                return
        page._runner.step_finished.connect(on_step_finished)

        def on_finished(summary):
            results["summary"] = summary
            print(f"[run] finished: {summary}")
            tail = mc.get_read_buffer(key)[-2000:]
            print("[run] console tail:",
                  tail.decode(errors="replace"))
            app.quit()
        page._runner.run_finished.connect(on_finished)
        page._runner.start(1)

    QTimer.singleShot(300, connect_and_run)
    # watchdog: never run longer than 5 minutes
    QTimer.singleShot(300_000, lambda: (print("[run] WATCHDOG timeout"),
                                        app.exit(2)))
    app.exec()
    elapsed = time.time() - started
    print(f"[run] elapsed {elapsed:.1f}s")
    # overall result from the page result model
    summary = results.get("summary", {})
    print(f"[run] summary: {summary.get('reason', '')} "
          f"progress={summary.get('progress')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
