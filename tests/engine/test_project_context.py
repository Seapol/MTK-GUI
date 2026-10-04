# -*- coding: utf-8 -*-
"""P3-1 tenant context kernel tests."""
from __future__ import annotations

import pytest

from mtkgui.engine.metrics import MetricsEngine
from mtkgui.engine.project_context import (ProjectContext,
                                           TenantError,
                                           TenantRegistry)


@pytest.fixture(autouse=True)
def clean_global_ctx():
    yield
    ProjectContext.set_current(None)


@pytest.fixture()
def reg(tmp_path):
    return TenantRegistry(tmp_path / "projects")


def test_register_creates_isolated_layout(reg):
    ctx = reg.register("PRJ-A")
    assert ctx.root.name == "PRJ-A"
    for d in ("config", "cases", "outbox", "export", "archive",
              "audit", "logs", "metrics"):
        assert ctx.dir(d).is_dir()
    assert reg.list_projects() == ["PRJ-A"]


def test_illegal_and_duplicate_ids(reg):
    with pytest.raises(TenantError):
        reg.register("")
    with pytest.raises(TenantError):
        reg.register("../escape")
    with pytest.raises(TenantError):
        reg.register("a/b")
    reg.register("A")
    with pytest.raises(TenantError):
        reg.register("A")


def test_unknown_dir_and_path_escape_guard(reg):
    ctx = reg.register("A")
    with pytest.raises(TenantError):
        ctx.dir("nope")
    inside = ctx.dir("config")
    assert ctx.resolve(inside / "x.yaml") == \
        (inside / "x.yaml").resolve()
    with pytest.raises(TenantError):
        ctx.resolve("/etc/passwd")        # escape rejected


def test_switch_activates_and_degrade_mode(reg):
    assert ProjectContext.current() is None, "legacy P2 mode default"
    a = reg.register("A")
    reg.switch("A")
    assert ProjectContext.current() is a
    b = reg.register("B")
    reg.switch("B")
    assert ProjectContext.current() is b
    reg.deactivate()
    assert ProjectContext.current() is None, "back to compat mode"


def test_switch_resets_leaving_tenant_slots(reg):
    a = reg.register("A")
    reg.switch("A")
    e1 = a.slot("metrics", MetricsEngine)
    assert a.slot("metrics", MetricsEngine) is e1, "cached"
    reg.register("B")
    reg.switch("B")
    reg.switch("A")
    assert a.slot("metrics", MetricsEngine) is not e1, \
        "leaving tenant cache cleared"


def test_load_from_disk_and_unload(reg, tmp_path):
    reg.register("A")
    reg2 = TenantRegistry(tmp_path / "projects")   # fresh registry
    ctx = reg2.load("A")                           # on-disk tenant
    assert ctx.project_id == "A"
    with pytest.raises(TenantError):
        reg2.load("GHOST")
    reg2.switch("A")
    reg2.unload("A")
    assert ProjectContext.current() is None, "unload deactivates"
    with pytest.raises(TenantError):
        reg2.get("A")


def test_reset_keeps_config_wipes_runtime(reg):
    ctx = reg.register("A")
    (ctx.dir("config") / "project.yaml").write_text("a: 1")
    (ctx.dir("logs") / "run.log").write_text("x")
    reg.reset("A")
    assert (ctx.dir("config") / "project.yaml").exists()
    assert not (ctx.dir("logs") / "run.log").exists()


def test_guard_cross_tenant_isolation(reg):
    reg.register("A")
    reg.register("B")
    # legacy mode: everything passes (P2 compat)
    assert TenantRegistry.guard(None).project_id == "LEGACY"
    assert TenantRegistry.guard("B").project_id == "LEGACY"
    reg.switch("A")
    assert TenantRegistry.guard("A").project_id == "A"
    assert TenantRegistry.guard(None).project_id == "A"
    with pytest.raises(TenantError):
        TenantRegistry.guard("B"), "cross-tenant bleed rejected"


def test_isolated_engine_slots_per_tenant(reg):
    a = reg.register("A")
    b = reg.register("B")
    ea = a.slot("metrics", MetricsEngine)
    eb = b.slot("metrics", MetricsEngine)
    assert ea is not eb, "runtime state never crosses projects"
