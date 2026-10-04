# -*- coding: utf-8 -*-
"""P3-1 multi-project tenant context kernel (pure incremental base).

Breaks the P1/P2 single-project-per-instance limit by hosting many
independent projects inside ONE running program, each with a fully
partitioned workspace.  This is an upper layer only: every producer
(engine, casegen, instruments, schedulers) is untouched and keeps its
P2 contracts.

Core pieces:

  * ProjectContext  — one tenant: project_id + isolated workspace root
                      with canonical sub-directories (config / cases /
                      outbox / export / archive / audit / logs),
                      path-resolution guard (no escape, no cross-tenant
                      access) and a runtime slot cache (one isolated
                      store instance per tenant, e.g. its own
                      MetricsEngine)
  * TenantRegistry  — lifecycle hub: register / load / switch / unload
                      / reset / list, plus global activation.  When no
                      context is activated the system automatically
                      degrades to the P2 single-project compatibility
                      mode — legacy projects run unmodified
  * cross-guard     — every tenant-scoped access passes guard() so
                      resources owned by another (or unknown) project
                      are rejected, preventing data bleed

Zero changes to any P1/P2 module; everything here is additive.
"""
from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

# canonical per-tenant workspace layout (P2 layouts live INSIDE these)
TENANT_DIRS = ("config", "cases", "outbox", "export", "archive",
               "audit", "logs", "metrics")


class TenantError(Exception):
    """Cross-project violation / lifecycle misuse."""


@dataclass
class ProjectContext:
    """One isolated tenant workspace."""
    project_id: str
    root: Path
    _slots: dict = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock,
                                  repr=False)

    # ------------------------------------------------------------ paths
    def path_of(self, *parts: str) -> Path:
        """Canonical tenant path; missing dirs are created."""
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def dir(self, name: str) -> Path:
        if name not in TENANT_DIRS:
            raise TenantError(f"unknown tenant dir: {name}")
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def resolve(self, path) -> Path:
        """Guard: absolute path must live inside this tenant root."""
        p = Path(path).resolve()
        root = self.root.resolve()
        if p != root and root not in p.parents:
            raise TenantError(
                f"path escapes tenant {self.project_id}: {p}")
        return p

    # ------------------------------------------------------ runtime slots
    def slot(self, key: str, factory):
        """Isolated runtime store per tenant (lazy, cached).

        Each tenant gets its OWN instance (engine / uploader / ...) so
        runtime state never crosses projects."""
        with self._lock:
            if key not in self._slots:
                self._slots[key] = factory()
            return self._slots[key]

    def clear_slots(self) -> None:
        """Switch/reset support: drop cached runtime state."""
        with self._lock:
            self._slots.clear()

    # ------------------------------------------------------- global ctx
    _current: "ProjectContext | None" = None   # class-level pointer

    @classmethod
    def set_current(cls, ctx: "ProjectContext | None") -> None:
        cls._current = ctx

    @classmethod
    def current(cls) -> "ProjectContext | None":
        """Active tenant, or None -> legacy P2 single-project mode."""
        return cls._current


class TenantRegistry:
    """Project lifecycle hub over isolated tenant workspaces."""

    def __init__(self, base_dir):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self._tenants: dict[str, ProjectContext] = {}

    # -------------------------------------------------------- lifecycle
    def register(self, project_id: str) -> ProjectContext:
        """Create a new tenant workspace (id must be new & safe)."""
        pid = self._check_id(project_id)
        if pid in self._tenants:
            raise TenantError(f"project already registered: {pid}")
        ctx = ProjectContext(project_id=pid, root=self.base / pid)
        for d in TENANT_DIRS:
            ctx.dir(d)
        self._tenants[pid] = ctx
        return ctx

    def load(self, project_id: str) -> ProjectContext:
        """Re-open an existing tenant (must already be registered)."""
        pid = self._check_id(project_id)
        ctx = self._tenants.get(pid)
        if ctx is None:
            if (self.base / pid).is_dir():      # on-disk tenant
                ctx = ProjectContext(project_id=pid,
                                     root=self.base / pid)
                for d in TENANT_DIRS:
                    ctx.dir(d)
                self._tenants[pid] = ctx
            else:
                raise TenantError(f"unknown project: {pid}")
        return ctx

    def switch(self, project_id: str) -> ProjectContext:
        """Activate a tenant globally (context refresh + path
        redirect + runtime cache reset for the leaving tenant)."""
        prev = ProjectContext.current()
        if prev is not None and prev.project_id == project_id:
            return prev                          # already active
        if prev is not None:
            prev.clear_slots()                   # leaving: drop cache
        ctx = self.load(project_id)
        ProjectContext.set_current(ctx)
        return ctx

    def unload(self, project_id: str) -> None:
        """Detach a tenant from memory (workspace files preserved)."""
        ctx = self._tenants.pop(project_id, None)
        if ctx is None:
            raise TenantError(f"unknown project: {project_id}")
        if ProjectContext.current() is ctx:
            ProjectContext.set_current(None)     # degrade to legacy
        ctx.clear_slots()

    def reset(self, project_id: str) -> None:
        """Wipe runtime state (slots + logs/metrics), keep config and
        cases so the project stays usable."""
        ctx = self.load(project_id)
        ctx.clear_slots()
        for d in ("logs", "metrics"):
            shutil.rmtree(ctx.dir(d), ignore_errors=True)
            ctx.dir(d)

    def deactivate(self) -> None:
        """Back to the P2 single-project compatibility mode."""
        if ProjectContext.current() is not None:
            ProjectContext.current().clear_slots()
        ProjectContext.set_current(None)

    # ------------------------------------------------------------ query
    def list_projects(self) -> list[str]:
        return sorted(self._tenants)

    def get(self, project_id: str) -> ProjectContext:
        ctx = self._tenants.get(project_id)
        if ctx is None:
            raise TenantError(f"unknown project: {project_id}")
        return ctx

    # ------------------------------------------------------------ guard
    @staticmethod
    def guard(owner: str | None) -> ProjectContext:
        """Cross-project access gate.

        Legacy mode (no active tenant) always passes.  With an active
        tenant the resource must be unowned or owned by it."""
        ctx = ProjectContext.current()
        if ctx is None:
            ctx = ProjectContext(project_id="LEGACY",
                                 root=Path("."))
            return ctx                           # P2 compat mode
        if owner is not None and owner != ctx.project_id:
            raise TenantError(
                f"cross-tenant access: resource owned by "
                f"{owner!r}, active tenant {ctx.project_id!r}")
        return ctx

    # ------------------------------------------------------------ utils
    @staticmethod
    def _check_id(project_id: str) -> str:
        pid = (project_id or "").strip()
        if not pid or "/" in pid or "\\" in pid or pid in (".", ".."):
            raise TenantError(f"illegal project id: {project_id!r}")
        return pid
