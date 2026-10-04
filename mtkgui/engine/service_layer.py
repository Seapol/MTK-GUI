# -*- coding: utf-8 -*-
"""P3-4 four-layer service architecture (UI/Service/Core/Store).

Pure WRAPPER layer — no existing module is rewritten, no external
contract changes.  Existing P1/P2/P3 objects are *classified* into
layers and their call direction is enforced by a tiny architecture
kernel, so future cluster / API / microservice work can plug into a
stable boundary:

    UI  ->  Service  ->  Core  ->  Store      (allowed direction)

    UI  may call  Service            (never Core/Store directly)
    Service may call Core + Service
    Core   may call Store + Core
    Store  may call Store only

Components:

  * LAYER / allowed_calls()  — the frozen call matrix
  * ArchError                — direction violation
  * Service (base)           — name + layer + start/stop/health
  * ServiceRegistry          — register/resolve by name, layer check,
                               lifecycle host (start_all/stop_all),
                               health report
  * RouteService             — route-key -> service-name binding so
                               GUI routes resolve through the service
                               layer (route/service decoupling) while
                               the shell contract stays untouched
  * classify()               — mapping of the shipped P2/P3 modules
                               onto the four layers (documentation
                               made executable)

Build-only services shipped here (wrapping existing objects, zero
logic duplication): MetricsService, ArchiveService, UploadService,
ClusterService, AuditService, DbService, ResourceService.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class LAYER(str, Enum):
    UI = "UI"
    SERVICE = "SERVICE"
    CORE = "CORE"
    STORE = "STORE"


_ALLOWED: dict[LAYER, set[LAYER]] = {
    LAYER.UI: {LAYER.SERVICE},
    LAYER.SERVICE: {LAYER.CORE, LAYER.SERVICE},
    LAYER.CORE: {LAYER.STORE, LAYER.CORE},
    LAYER.STORE: {LAYER.STORE},
}


def allowed_calls(layer: LAYER) -> set[LAYER]:
    return set(_ALLOWED[layer])


class ArchError(Exception):
    """Layer-direction violation."""


def check_call(caller: LAYER, target: LAYER) -> None:
    """Raise ArchError when caller may not reach target."""
    if target not in _ALLOWED[caller]:
        raise ArchError(
            f"architecture violation: {caller.value} cannot call "
            f"{target.value} directly")


# shipped-module classification (executable documentation)
CLASSIFICATION: dict[str, LAYER] = {
    # Store layer — persistence / ledgers
    "DbStore": LAYER.STORE, "AuditLog": LAYER.STORE,
    "ConfigStore": LAYER.STORE, "case_store": LAYER.STORE,
    # Core layer — engines / domain computation
    "MetricsEngine": LAYER.CORE, "ArchiveManager": LAYER.CORE,
    "SharePointUploader": LAYER.CORE, "ClusterScheduler": LAYER.CORE,
    "ResourceManager": LAYER.CORE, "AccessControl": LAYER.CORE,
    "ProjectContext": LAYER.CORE, "TenantRegistry": LAYER.CORE,
    "PathHub": LAYER.CORE,
    # Service layer — facades over core for the UI
    "MetricsService": LAYER.SERVICE, "ArchiveService": LAYER.SERVICE,
    "UploadService": LAYER.SERVICE, "ClusterService": LAYER.SERVICE,
    "AuditService": LAYER.SERVICE, "DbService": LAYER.SERVICE,
    "ResourceService": LAYER.SERVICE, "RouteService": LAYER.SERVICE,
}


def classify(name: str) -> LAYER:
    return CLASSIFICATION[name]


# ============================================================ services
@dataclass
class Service:
    name: str
    layer: LAYER = LAYER.SERVICE
    _started: bool = field(default=False, repr=False)

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    @property
    def healthy(self) -> bool:
        return self._started


class _Wrap(Service):
    """Facade over an EXISTING object (no logic duplication)."""

    def __init__(self, name: str, target, layer: LAYER):
        super().__init__(name=name, layer=layer)
        self.target = target


class ServiceRegistry:
    """Named service host with layer-aware resolution."""

    def __init__(self):
        self._services: dict[str, Service] = {}

    def register(self, service: Service) -> Service:
        if service.name in self._services:
            raise ArchError(f"service already registered: "
                            f"{service.name}")
        self._services[service.name] = service
        return service

    def wrap(self, name: str, target, layer: LAYER) -> Service:
        """Classify an existing object into a layer as a service."""
        return self.register(_Wrap(name, target, layer))

    def resolve(self, name: str, caller: LAYER) -> Service:
        svc = self._services.get(name)
        if svc is None:
            raise ArchError(f"unknown service: {name}")
        check_call(caller, svc.layer)
        return svc

    def call(self, name: str, caller: LAYER, method: str, *args,
             **kwargs):
        """Layer-checked facade invocation."""
        svc = self.resolve(name, caller)
        fn = getattr(svc.target, method)
        return fn(*args, **kwargs)

    # -------------------------------------------------------- lifecycle
    def start_all(self) -> None:
        for svc in self._services.values():
            svc.start()

    def stop_all(self) -> None:
        for svc in self._services.values():
            svc.stop()

    def health(self) -> dict[str, dict]:
        return {n: {"layer": s.layer.value, "healthy": s.healthy}
                for n, s in sorted(self._services.items())}

    def names(self, layer: LAYER | None = None) -> list[str]:
        return sorted(n for n, s in self._services.items()
                      if layer is None or s.layer is layer)


class RouteService(Service):
    """Route-key -> service-name binding (route/service decoupling).
    The shell keeps its frozen contract; this maps routes onto
    service-layer names for platform/API extensions."""

    def __init__(self, name: str = "routes"):
        super().__init__(name=name, layer=LAYER.SERVICE)
        self._routes: dict[str, str] = {}

    def bind(self, route_key: str, service_name: str) -> None:
        self._routes[route_key] = service_name

    def service_for(self, route_key: str) -> str:
        if route_key not in self._routes:
            raise ArchError(f"no service bound to route: {route_key}")
        return self._routes[route_key]

    def resolve_route(self, registry: "ServiceRegistry", route_key: str,
                      caller: LAYER = LAYER.UI):
        return registry.resolve(self.service_for(route_key),
                                caller)

    def snapshot(self) -> dict[str, str]:
        return dict(sorted(self._routes.items()))
