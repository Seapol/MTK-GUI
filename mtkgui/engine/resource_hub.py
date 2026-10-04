# -*- coding: utf-8 -*-
"""P3-3 global unified resource manager & path hub (pure incremental).

Platform-wide hub layered on top of the P3-1 tenant kernel — the P1/P2
resource primitives (device locks, state machines) are untouched and
keep working exactly as before:

  PathHub         — standardized path system: every artifact category
                    (config/cases/outbox/export/archive/audit/logs/
                    metrics) resolves through ONE hub bound to the
                    active tenant workspace; escape attempts rejected
                    via the P3-1 resolve guard; legacy mode falls back
                    to the process CWD (P2 compat)

  ResourceManager — global registry for exclusive soft resources
                    (files, ports, instruments-groups, jobs...):
                      acquire -> ResourceLock (token, owner, tenant)
                      release / release_token
                      staleness TTL sweep -> auto-release orphaned
                      locks (crashed owners never deadlock the hub)
                      cross-tenant anti-penetration: acquiring with a
                      tenant tag different from the active tenant is
                      rejected; a busy resource is never shared across
                      tenants
                      snapshot() -> monitoring board rows

Thread-safe; zero changes to any producer.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .project_context import ProjectContext, TenantError

PATH_CATEGORIES = ("config", "cases", "outbox", "export", "archive",
                   "audit", "logs", "metrics")


class ResourceBusy(Exception):
    """Requested resource is exclusively held by someone else."""


@dataclass
class ResourceLock:
    rtype: str
    name: str
    owner: str
    tenant: str
    token: str
    acquired_at: float

    def as_row(self) -> dict:
        return {"type": self.rtype, "name": self.name,
                "owner": self.owner, "tenant": self.tenant,
                "token": self.token[:8], "age_s": round(
                    max(0.0, _MONO() - self.acquired_at), 3)}


def _MONO() -> float:
    import time
    return time.monotonic()


class PathHub:
    """Standardized per-tenant path resolution."""

    def __init__(self, ctx: ProjectContext | None = None):
        self.ctx = ctx if ctx is not None \
            else ProjectContext.current()

    def path(self, category: str, *parts: str) -> Path:
        if category not in PATH_CATEGORIES:
            raise TenantError(f"unknown path category: {category}")
        if self.ctx is None:                       # legacy P2 mode
            p = (Path.cwd() / category).joinpath(*parts)
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        return self.ctx.dir(category).joinpath(*parts) \
            if parts else self.ctx.dir(category)

    def resolve(self, path) -> Path:
        if self.ctx is None:
            return Path(path).resolve()
        return self.ctx.resolve(path)

    def snapshot(self) -> dict:
        return {c: str(self.path(c)) for c in PATH_CATEGORIES}


class ResourceManager:
    """Global exclusive-resource registry (per-process singleton use
    is typical; instances are independent registries)."""

    def __init__(self, now=None, default_ttl: float = 600.0):
        self.now = now or (lambda: datetime.now())
        self.default_ttl = default_ttl
        self._locks: dict[tuple[str, str], ResourceLock] = {}
        self._ttl: dict[tuple[str, str], float] = {}
        self._guard = threading.Lock()

    # --------------------------------------------------------- acquire
    def acquire(self, rtype: str, name: str, owner: str,
                tenant: str | None = None,
                ttl: float | None = None) -> ResourceLock:
        """Exclusive acquisition; raises ResourceBusy when held by
        someone else, TenantError on cross-tenant penetration."""
        active = ProjectContext.current()
        if active is not None:
            eff = tenant or active.project_id
            if eff != active.project_id:
                raise TenantError(
                    f"cross-tenant acquire: {eff!r} vs active "
                    f"{active.project_id!r}")
        key = (rtype, name)
        with self._guard:
            self._sweep_locked()
            held = self._locks.get(key)
            if held is not None:
                raise ResourceBusy(
                    f"{rtype}:{name} held by {held.owner}"
                    f"({held.tenant})")
            lock = ResourceLock(
                rtype=rtype, name=name, owner=owner,
                tenant=tenant or (active.project_id if active
                                  else "LEGACY"),
                token=secrets.token_hex(16),
                acquired_at=_MONO())
            self._locks[key] = lock
            self._ttl[key] = ttl if ttl is not None \
                else self.default_ttl
            return lock

    # --------------------------------------------------------- release
    def release(self, lock: ResourceLock) -> bool:
        """Release by lock object (token must match)."""
        return self.release_token(lock.rtype, lock.name, lock.token)

    def release_token(self, rtype: str, name: str,
                      token: str) -> bool:
        key = (rtype, name)
        with self._guard:
            held = self._locks.get(key)
            if held is None or held.token != token:
                return False
            del self._locks[key]
            self._ttl.pop(key, None)
            return True

    # ---------------------------------------------------------- status
    def owner_of(self, rtype: str, name: str) -> str | None:
        with self._guard:
            held = self._locks.get((rtype, name))
            return held.owner if held else None

    def is_busy(self, rtype: str, name: str) -> bool:
        with self._guard:
            self._sweep_locked()
            return (rtype, name) in self._locks

    def snapshot(self) -> list[dict]:
        with self._guard:
            self._sweep_locked()
            return [lk.as_row() for lk in
                    sorted(self._locks.values(),
                           key=lambda l: (l.rtype, l.name))]

    def locks_view(self) -> list[ResourceLock]:
        """Live lock objects (for token-checked release)."""
        with self._guard:
            self._sweep_locked()
            return list(self._locks.values())

    # ----------------------------------------------------------- sweep
    def sweep(self) -> int:
        """Auto-release TTL-expired locks (orphaned owners)."""
        with self._guard:
            return self._sweep_locked()

    def _sweep_locked(self) -> int:
        now = _MONO()
        dead = [k for k, lk in self._locks.items()
                if now - lk.acquired_at > self._ttl[k]]
        for k in dead:
            del self._locks[k]
            self._ttl.pop(k, None)
        return len(dead)
