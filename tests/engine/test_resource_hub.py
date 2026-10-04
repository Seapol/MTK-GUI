# -*- coding: utf-8 -*-
"""P3-3 global resource hub & path hub tests."""
from __future__ import annotations

import pytest

from mtkgui.engine.project_context import (ProjectContext,
                                           TenantError,
                                           TenantRegistry)
from mtkgui.engine.resource_hub import (PathHub, ResourceManager,
                                        ResourceBusy)


@pytest.fixture(autouse=True)
def clean_ctx():
    yield
    ProjectContext.set_current(None)


@pytest.fixture()
def rm():
    return ResourceManager(default_ttl=60.0)


def test_path_hub_legacy_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hub = PathHub()                      # no active tenant -> P2 mode
    p = hub.path("config", "project.yaml")
    assert p == tmp_path / "config" / "project.yaml"
    assert p.parent.is_dir()
    with pytest.raises(TenantError):
        hub.path("nope")
    assert set(hub.snapshot()) == {"config", "cases", "outbox",
                                   "export", "archive", "audit",
                                   "logs", "metrics"}


def test_path_hub_tenant_bound(tmp_path):
    reg = TenantRegistry(tmp_path / "projects")
    ctx = reg.register("PRJ")
    hub = PathHub(ctx)
    p = hub.path("outbox", "report.zip")
    assert str(ctx.dir("outbox")) in str(p)
    assert hub.resolve(p).is_absolute()
    with pytest.raises(TenantError):
        hub.resolve("/etc/passwd")       # escape rejected


def test_acquire_release_roundtrip(rm):
    lock = rm.acquire("file", "cases.xlsx", owner="op1")
    assert rm.is_busy("file", "cases.xlsx")
    assert rm.owner_of("file", "cases.xlsx") == "op1"
    assert lock.tenant == "LEGACY"       # no active tenant
    assert rm.release(lock) is True
    assert not rm.is_busy("file", "cases.xlsx")
    assert rm.release(lock) is False, "double release rejected"


def test_busy_exclusive_and_token_guard(rm):
    l1 = rm.acquire("dev", "BURNER-1", owner="w1")
    with pytest.raises(ResourceBusy):
        rm.acquire("dev", "BURNER-1", owner="w2")
    assert rm.release_token("dev", "BURNER-1", "bad-token") is False
    assert rm.is_busy("dev", "BURNER-1"), "wrong token keeps lock"
    rm.release_token("dev", "BURNER-1", l1.token)
    assert not rm.is_busy("dev", "BURNER-1")


def test_ttl_sweep_auto_release_orphaned():
    import time
    rm = ResourceManager(default_ttl=0.05)
    lock = rm.acquire("job", "J1", owner="crashed")
    time.sleep(0.08)
    assert rm.is_busy("job", "J1") is False, "auto-released"
    assert rm.release(lock) is False
    rm2 = ResourceManager(default_ttl=60.0)
    l2 = rm2.acquire("job", "J1", owner="w")
    assert rm2.sweep() == 0, "fresh lock survives"
    rm2.release(l2)


def test_cross_tenant_penetration_blocked(tmp_path):
    reg = TenantRegistry(tmp_path / "projects")
    reg.register("A")
    reg.register("B")
    reg.switch("A")
    rm = ResourceManager()
    lock = rm.acquire("file", "x", owner="w", tenant="A")
    assert lock.tenant == "A"
    with pytest.raises(TenantError):
        rm.acquire("file", "y", owner="w", tenant="B"), \
            "foreign tenant tag rejected"
    reg.switch("B")
    with pytest.raises(ResourceBusy):
        rm.acquire("file", "x", owner="w"), \
            "A-held lock never shared with B"
    ProjectContext.set_current(None)


def test_snapshot_monitor_rows(rm):
    rm.acquire("port", "5000", owner="api")
    rm.acquire("file", "z", owner="op")
    rows = rm.snapshot()
    assert [(r["type"], r["name"]) for r in rows] == \
        [("file", "z"), ("port", "5000")], "sorted"
    assert rows[0]["owner"] == "op" and "age_s" in rows[0]
    assert len(rm.locks_view()) == 2
