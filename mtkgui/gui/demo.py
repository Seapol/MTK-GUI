# -*- coding: utf-8 -*-
"""P2-1 GUI shell framework demo (headless-safe, rc=0 on success).

Exercises the full framework baseline offscreen: stylesheet build,
window skeleton, routing + page cache, status bar updates, log panel
append/filter/clear, startup fallback (bad factory), and safe close.
Exit code: 0 = all framework checkpoints passed; 1 = any failure.
"""
from __future__ import annotations

import os
import sys

# Headless-safe: force offscreen before any QApplication creation.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.log_panel import LogPanelWidget  # noqa: E402
from mtkgui.gui.shell import MainWindow  # noqa: E402
from mtkgui.gui.theme import StyleSpec, build_stylesheet  # noqa: E402


class _BrokenFactory:
    """Factory that raises — verifies the shell's startup fallback path."""

    def __call__(self) -> object:
        raise RuntimeError("simulated page build failure")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # 1. style spec / stylesheet
    spec = StyleSpec()
    qss = build_stylesheet(spec)
    assert "TopNav" in qss and spec.ACCENT in qss, "stylesheet incomplete"

    # 2. window skeleton + default routes
    win = MainWindow(baseline_version="V1.0-P2-1", spec=spec)
    win.mount_default_routes()
    assert win.route_keys == ["home", "workflow", "cases", "case_io",
                              "reports", "upload", "export", "cluster", "resources", "queue", "fleet", "balance", "pipeline", "rbac", "audit", "config"], "routes wrong"
    assert win.stack.count() == 1, "home page not mounted on start"

    # 3. routing + page cache
    win.navigate("workflow")
    win.navigate("reports")
    assert win.stack.count() == 3, "pages not cached"
    assert win.cached_pages == ["home", "workflow", "reports"], "cache order"
    # P2-2: config route builds the real ConfigPage over the project YAML
    win.navigate("config")
    assert "config" in win.cached_pages and win.stack.count() == 4, \
        "config page mount"
    win.navigate("home")
    assert win.cached_pages.count("home") == 1, "home rebuilt (cache broken)"
    win.navigate("nope")  # unknown route -> logged WARN, no crash

    # 4. status bar
    win.set_engine_state("running")
    win.set_devices_online(4)
    win.set_progress(7, 10)
    chips = "".join(
        win.status.state_label.text() + win.status.devices_label.text()
        + win.status.progress_label.text())
    assert "running" in chips and "4" in chips and "70%" in chips, "status"

    # 5. log panel: append / level filter / keyword filter / clear
    lp = win.log_panel
    base = lp.entry_count  # shell init already logged its own lines
    lp.append("INFO", "alpha message")
    lp.append("ERROR", "beta fault")
    assert lp.entry_count == base + 2, "entry count"
    lp.level_combo.setCurrentText("ERROR")
    assert lp.visible_count() == 1, "level filter"
    lp.keyword_edit.setText("alpha")
    lp.level_combo.setCurrentText("ALL")
    assert lp.visible_count() == 1, "keyword filter"
    lp.keyword_edit.setText("")
    lp.clear_btn.click()
    assert lp.visible_count() == 0 and lp.entry_count == base + 2, "clear view"

    # 6. startup fallback: broken factory -> placeholder, no crash
    win.register_page("bad", _BrokenFactory(), "Broken")
    win.navigate("bad")
    assert "bad" in win.cached_pages, "fallback page missing"
    win.log_panel.append("ERROR", "fallback engaged for route: bad")
    lp.level_combo.setCurrentText("ERROR")
    assert lp.visible_count() >= 1, "fallback not visible in error view"

    print("[P2-1 GUI demo] shell framework OK — routes, cache, status, logs, "
          "fallback, style all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
