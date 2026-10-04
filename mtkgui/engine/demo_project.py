# -*- coding: utf-8 -*-
"""P3-1 multi-tenant base demo (headless-safe, rc=0).

Closed loop: register two tenants -> switch activates isolated
workspace -> runtime slots isolated per tenant -> cross-tenant guard
rejects bleed -> lifecycle load/unload/reset -> legacy P2 mode
degradation -> GUI shell switch rebinds stores, purges pages and
audits the move.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.metrics import MetricsEngine  # noqa: E402
from mtkgui.engine.project_context import (ProjectContext,  # noqa: E402
                                           TenantError,
                                           TenantRegistry)
from mtkgui.gui.project_switcher import LEGACY  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="p3_1_demo_")
    reg = TenantRegistry(tmp)

    # 1. lifecycle: register / duplicate / illegal
    a = reg.register("FRDM-IMX93")
    b = reg.register("RT1170-EVK")
    assert reg.list_projects() == ["FRDM-IMX93", "RT1170-EVK"]
    for bad in ("", "../x", "a/b"):
        try:
            reg.register(bad)
            raise AssertionError(bad)
        except TenantError:
            pass
    try:
        reg.register("FRDM-IMX93")
        raise AssertionError("duplicate")
    except TenantError:
        pass

    # 2. isolation layout + path guard
    for d in ("config", "cases", "outbox", "export", "archive",
              "audit", "logs", "metrics"):
        assert a.dir(d).is_dir() and b.dir(d).is_dir()
    try:
        a.resolve("/etc/passwd")
        raise AssertionError("escape")
    except TenantError:
        pass

    # 3. legacy degrade: no context -> P2 compat mode
    assert ProjectContext.current() is None
    assert TenantRegistry.guard(None).project_id == "LEGACY"

    # 4. switch + isolated runtime slots
    reg.switch("FRDM-IMX93")
    assert ProjectContext.current() is a
    ea = a.slot("metrics", MetricsEngine)
    reg.switch("RT1170-EVK")
    assert ProjectContext.current() is b
    eb = b.slot("metrics", MetricsEngine)
    assert ea is not eb, "per-tenant engine isolation"
    reg.switch("FRDM-IMX93")
    assert a.slot("metrics", MetricsEngine) is not ea, \
        "leaving tenant cache cleared on switch"

    # 5. cross-tenant guard
    try:
        TenantRegistry.guard("RT1170-EVK")
        raise AssertionError("bleed")
    except TenantError:
        pass
    assert TenantRegistry.guard("FRDM-IMX93").project_id == \
        "FRDM-IMX93"

    # 6. reset keeps config, wipes runtime; unload deactivates
    (a.dir("config") / "project.yaml").write_text("project: ok")
    (a.dir("logs") / "run.log").write_text("noise")
    reg.reset("FRDM-IMX93")
    assert (a.dir("config") / "project.yaml").exists()
    assert not (a.dir("logs") / "run.log").exists()
    reg.unload("FRDM-IMX93")
    assert ProjectContext.current() is None
    try:
        reg.get("FRDM-IMX93")
        raise AssertionError("unloaded")
    except TenantError:
        pass
    # reload from disk (workspace files preserved)
    reg.load("FRDM-IMX93")
    assert (reg.get("FRDM-IMX93").dir("config")
            / "project.yaml").exists()

    # 7. GUI shell: resident switcher rebinds + purges + audits
    from mtkgui.gui.shell import MainWindow
    os.environ["MTKGUI_TENANT_BASE"] = tmp
    win = MainWindow()
    win.interactive = False
    win.mount_default_routes()
    sw = win.project_switcher
    sw.add_project("P-A")
    sw.add_project("P-B")
    old = win.metrics_engine
    win.navigate("reports")
    sw.combo.setCurrentText("P-A")
    assert ProjectContext.current().project_id == "P-A"
    assert win.metrics_engine is not old
    assert win.cached_pages == [], "pages rebuilt in tenant"
    assert "tenant_switch" in [e["action"]
                               for e in win.audit_log.entries()]
    sw.combo.setCurrentText("P-B")
    assert win.metrics_engine is not a.slot("metrics", MetricsEngine)
    sw.combo.setCurrentText(LEGACY)
    assert ProjectContext.current() is None, "legacy restored"

    print("[P3-1 tenant demo] multi-project base OK — lifecycle, "
          "isolated workspaces, per-tenant runtime slots, cross-"
          "tenant guard, legacy degrade, shell switch rebind+audit "
          "all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
