# -*- coding: utf-8 -*-
"""P3-4 four-layer service architecture tests."""
from __future__ import annotations

from datetime import datetime

import pytest

from mtkgui.engine.db_store import DbStore
from mtkgui.engine.metrics import MetricsEngine, TestRecord
from mtkgui.engine.results import StepStatus
from mtkgui.engine.service_layer import (LAYER, ArchError,
                                         RouteService, Service,
                                         ServiceRegistry,
                                         allowed_calls, check_call,
                                         classify)

T0 = datetime(2026, 10, 4, 8, 0, 0)


def test_classification_of_shipped_modules():
    assert classify("MetricsEngine") is LAYER.CORE
    assert classify("ArchiveManager") is LAYER.CORE
    assert classify("SharePointUploader") is LAYER.CORE
    assert classify("ClusterScheduler") is LAYER.CORE
    assert classify("DbStore") is LAYER.STORE
    assert classify("AuditLog") is LAYER.STORE
    assert classify("ConfigStore") is LAYER.STORE
    assert classify("RouteService") is LAYER.SERVICE


def test_call_matrix_complete():
    assert allowed_calls(LAYER.UI) == {LAYER.SERVICE}
    assert allowed_calls(LAYER.SERVICE) == {LAYER.CORE,
                                            LAYER.SERVICE}
    assert allowed_calls(LAYER.CORE) == {LAYER.STORE, LAYER.CORE}
    assert allowed_calls(LAYER.STORE) == {LAYER.STORE}
    # every legal direction passes, every diagonal/reverse raises
    for caller in LAYER:
        for target in LAYER:
            if target in allowed_calls(caller):
                check_call(caller, target)          # no raise
            else:
                with pytest.raises(ArchError):
                    check_call(caller, target)


def test_registry_register_and_duplicate():
    reg = ServiceRegistry()
    reg.register(Service("s1"))
    with pytest.raises(ArchError):
        reg.register(Service("s1"))
    assert reg.names() == ["s1"]


def test_resolve_layer_checked():
    reg = ServiceRegistry()
    reg.register(Service("core_svc", LAYER.CORE))
    reg.register(Service("store_svc", LAYER.STORE))
    # UI may resolve the CORE-classified one? No — check_call refuses
    with pytest.raises(ArchError):
        reg.resolve("core_svc", LAYER.UI)
    reg.resolve("core_svc", LAYER.SERVICE)          # legal
    reg.resolve("store_svc", LAYER.CORE)            # legal
    with pytest.raises(ArchError):
        reg.resolve("ghost", LAYER.UI)


def test_call_wrapper_on_live_objects(tmp_path):
    eng = MetricsEngine()
    eng.add(TestRecord(name="C", status=StepStatus.PASS,
                       duration_s=1.0, ts=T0, batch="B"))
    reg = ServiceRegistry()
    reg.wrap("metrics", eng, LAYER.SERVICE)         # facade
    reg.start_all()
    y = reg.call("metrics", LAYER.UI, "yield_report")
    assert y.total == 1 and y.passed == 1
    reg.stop_all()
    assert reg.health()["metrics"] == {
        "layer": "SERVICE", "healthy": False}


def test_db_service_facade(tmp_path):
    db = DbStore(tmp_path / "x.db", project_id="P", now=lambda: T0)
    reg = ServiceRegistry()
    reg.wrap("db", db, LAYER.SERVICE)
    reg.start_all()
    reg.call("db", LAYER.UI, "set_config", "k", "v")
    assert reg.call("db", LAYER.UI, "get_config", "k") == "v"
    db.close()


def test_route_service_decoupling():
    reg = ServiceRegistry()
    eng = MetricsEngine()
    reg.wrap("metrics_facade", eng, LAYER.SERVICE)
    routes = RouteService()
    routes.bind("reports", "metrics_facade")
    routes.bind("cluster", "metrics_facade")        # rebind ok
    assert routes.snapshot() == {"cluster": "metrics_facade",
                                 "reports": "metrics_facade"}
    svc = routes.resolve_route(reg, "reports")
    assert svc.target is eng
    with pytest.raises(ArchError):
        routes.service_for("unbound")
