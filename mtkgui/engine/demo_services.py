# -*- coding: utf-8 -*-
"""P3-4 four-layer architecture demo (headless-safe, rc=0).

Closed loop: shipped modules classified into UI/Service/Core/Store ->
call matrix enforced (legal + illegal directions) -> services wrap
LIVE P2/P3 objects (no logic duplication) -> lifecycle host -> route
service decoupling -> full-stack health report.  Exit 0 = passed.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime
from pathlib import Path

from mtkgui.engine.archive import ArchiveManager
from mtkgui.engine.db_store import DbStore
from mtkgui.engine.metrics import MetricsEngine, TestRecord
from mtkgui.engine.resource_hub import ResourceManager
from mtkgui.engine.results import StepStatus
from mtkgui.engine.service_layer import (LAYER, ArchError,
                                         RouteService, ServiceRegistry,
                                         allowed_calls, check_call,
                                         classify)
from mtkgui.engine.uploader import SharePointUploader

T0 = datetime(2026, 10, 4, 8, 0, 0)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p3_4_demo_"))

    # 1. classification of shipped modules (executable architecture)
    assert classify("MetricsEngine") is LAYER.CORE
    assert classify("DbStore") is LAYER.STORE
    assert classify("MetricsService") is LAYER.SERVICE
    assert allowed_calls(LAYER.UI) == {LAYER.SERVICE}
    assert allowed_calls(LAYER.SERVICE) == {LAYER.CORE, LAYER.SERVICE}
    assert allowed_calls(LAYER.CORE) == {LAYER.STORE, LAYER.CORE}
    assert allowed_calls(LAYER.STORE) == {LAYER.STORE}

    # 2. call matrix: legal + violations
    check_call(LAYER.UI, LAYER.SERVICE)          # fine
    check_call(LAYER.CORE, LAYER.STORE)          # fine
    for bad in ((LAYER.UI, LAYER.CORE), (LAYER.UI, LAYER.STORE),
                (LAYER.SERVICE, LAYER.STORE), (LAYER.CORE, LAYER.UI),
                (LAYER.STORE, LAYER.CORE)):
        try:
            check_call(*bad)
            raise AssertionError(bad)
        except ArchError:
            pass

    # 3. wrap LIVE objects (zero logic duplication)
    eng = MetricsEngine()
    eng.add(TestRecord(name="C1", status=StepStatus.PASS,
                       duration_s=1.0, measured=3.3, ts=T0,
                       batch="B", station="S"))
    arch = ArchiveManager(tmp / "archive", station="S1",
                          version="V3", now=lambda: T0)
    db = DbStore(tmp / "t.db", project_id="P", now=lambda: T0)
    up = SharePointUploader(tmp / "outbox")
    res = ResourceManager()

    reg = ServiceRegistry()
    reg.wrap("metrics", eng, LAYER.CORE)
    reg.wrap("archive", arch, LAYER.CORE)
    reg.wrap("db", db, LAYER.STORE)
    reg.wrap("upload", up, LAYER.CORE)
    reg.wrap("resources", res, LAYER.CORE)
    assert reg.names(LAYER.CORE) == ["archive", "metrics",
                                     "resources", "upload"]
    # layer-checked invocation: UI -> CORE is refused, UI -> wrapped
    # SERVICE facade is the legal path
    try:
        reg.call("metrics", LAYER.UI, "yield_report")
        raise AssertionError("UI->CORE must be refused")
    except ArchError:
        pass
    db_svc = reg.wrap("db_facade", db, LAYER.SERVICE)  # facade rule
    reg.call("db_facade", LAYER.UI, "register_project", "P")
    assert reg.call("db_facade", LAYER.UI, "list_projects") == ["P"]

    # 4. lifecycle host
    reg.start_all()
    assert all(v["healthy"] for v in reg.health().values())
    reg.stop_all()
    assert not reg.health()["metrics"]["healthy"]

    # 5. route/service decoupling
    routes = RouteService()
    routes.bind("reports", "metrics")
    routes.bind("upload", "upload")
    assert routes.service_for("reports") == "metrics"
    assert routes.snapshot() == {"reports": "metrics",
                                 "upload": "upload"}
    reg2 = ServiceRegistry()
    reg2.wrap("metrics", eng, LAYER.SERVICE)     # service facade
    svc = routes.resolve_route(reg2, "reports")
    assert svc.target is eng
    try:
        routes.service_for("ghost")
        raise AssertionError("unbound route")
    except ArchError:
        pass

    # 6. real call through the legal chain: UI -> SERVICE -> CORE
    reg2.start_all()
    y = reg2.call("metrics", LAYER.UI, "yield_report")
    assert y.total == 1 and y.passed == 1

    print("[P3-4 layers demo] four-layer architecture OK — "
          "classification, enforced call direction, live-object "
          "wrapping, lifecycle host, route/service decoupling, "
          "health report all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
