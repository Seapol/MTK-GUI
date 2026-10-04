# -*- coding: utf-8 -*-
"""P3-3 resource hub & path hub demo (headless-safe, rc=0).

Closed loop: legacy path hub -> tenant path hub -> exclusive
acquire/release -> busy rejection + token guard -> TTL auto-release
of orphaned owner -> cross-tenant anti-penetration -> snapshot
monitoring -> GUI page refresh/sweep/release.  Exit 0 = passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.project_context import (ProjectContext,  # noqa: E402
                                           TenantRegistry)
from mtkgui.engine.resource_hub import (PathHub,  # noqa: E402
                                        ResourceManager, ResourceBusy)
from mtkgui.gui.resource_page import ResourcePage  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="p3_3_demo_")

    # 1. path hub: legacy mode + tenant mode
    legacy = PathHub()
    assert set(legacy.snapshot()) >= {"config", "cases"}
    reg = TenantRegistry(tmp)
    ctx = reg.register("PRJ-X")
    hub = PathHub(ctx)
    p = hub.path("archive", "batch.zip")
    assert hub.snapshot()["archive"] == str(ctx.dir("archive"))

    # 2. exclusive resource lifecycle
    rm = ResourceManager(default_ttl=60.0)
    l1 = rm.acquire("file", "cases.xlsx", owner="op1", tenant="PRJ-X")
    assert rm.is_busy("file", "cases.xlsx")
    try:
        rm.acquire("file", "cases.xlsx", owner="op2")
        raise AssertionError("busy")
    except ResourceBusy:
        pass
    assert rm.release_token("file", "cases.xlsx", "wrong") is False
    assert rm.release(l1) is True and rm.release(l1) is False

    # 3. TTL sweep auto-releases orphaned owner
    rshort = ResourceManager(default_ttl=0.05)
    ghost = rshort.acquire("job", "J1", owner="crashed")
    time.sleep(0.08)
    assert rshort.sweep() == 1 and not rshort.is_busy("job", "J1")

    # 4. cross-tenant anti-penetration
    reg.register("PRJ-Y")
    reg.switch("PRJ-X")
    rm.acquire("dev", "BURNER-1", owner="w1")   # tagged PRJ-X
    reg.switch("PRJ-Y")
    try:
        rm.acquire("dev", "BURNER-1", owner="w2")
        raise AssertionError("cross-tenant share")
    except ResourceBusy:
        pass                                    # never shared
    ProjectContext.set_current(None)

    # 5. snapshot monitoring rows
    rm2 = ResourceManager()
    a = rm2.acquire("port", "5000", owner="api")
    rm2.acquire("file", "z.zip", owner="op")
    rows = rm2.snapshot()
    assert [r["type"] for r in rows] == ["file", "port"]
    assert rows[0]["age_s"] >= 0

    # 6. GUI monitor page
    page = ResourcePage(rm2, hub)
    page.interactive = False
    assert page.refresh() == 2, "live rows"
    page.table.selectRow(0)
    assert page.on_release() is True, "token-checked release"
    assert rm2.is_busy("file", "z.zip") is False
    assert page.on_sweep() == 0
    assert page.tree.topLevelItemCount() == 8, "path categories"

    print("[P3-3 resource demo] global hub OK — path standardization, "
          "exclusive locks, token guard, TTL orphan sweep, cross-"
          "tenant anti-penetration, monitor board all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
