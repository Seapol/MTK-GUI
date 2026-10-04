# -*- coding: utf-8 -*-
"""P3-11 open RESTful API service & MES adapter (pure additive).

A ZERO-DEPENDENCY API layer over the platform middle platforms —
P1/P2/P3 engines are called through their public contracts, nothing
is modified.  HTTP framing is pluggable (handler callables suitable
for wsgiref / any framework); the domain lives in ApiServer:

  * ApiKey auth      — hashed key store + scopes (read / write /
                       admin), per-call enforcement + audit
  * ApiServer        — route table:
                       GET  /api/v1/status            (read)
                       GET  /api/v1/devices           (read)
                       GET  /api/v1/tasks             (read)
                       POST /api/v1/tasks             (write) enqueue
                       GET  /api/v1/reports/summary   (read)
                       POST /api/v1/mes/orders        (write) MES in
                       GET  /api/v1/audit             (read)
                     request(api_key, method, path, body) -> (code,
                     json) — framework-agnostic dispatch
  * MesAdapter       — 产线对接: inbound work orders (MES -> task
                       queue) with idempotency; outbound results
                       (done batches -> MES callbacks) with retry
                       buffer; anti-pass-through validation

Zero changes to task_queue / metrics / auth_audit / any engine.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass, field

SCOPES = ("read", "write", "admin")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class ApiKey:
    key_id: str
    key_hash: str
    scopes: set = field(default_factory=set)
    enabled: bool = True


@dataclass
class MesOrder:
    order_id: str
    part_no: str
    quantity: int
    priority: int = 0
    status: str = "RECEIVED"        # RECEIVED/QUEUED/DONE/REJECTED
    result: dict | None = None


class ApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class ApiServer:
    """Zero-dependency RESTful dispatch + API-key authentication."""

    def __init__(self, audit_log=None, now=None):
        self.audit = audit_log
        self.now = now or (lambda: __import__("datetime")
                           .datetime.now())
        self._keys: dict[str, ApiKey] = {}      # key_id -> ApiKey
        self._plain: dict[str, str] = {}        # key_id -> plaintext
        self._routes: dict[tuple, dict] = {}    # (method,path) -> spec
        self._guard = threading.Lock()
        self._register_default_routes()

    # ------------------------------------------------------ key admin
    def issue_key(self, key_id: str, scopes=("read",),
                  enabled: bool = True) -> str:
        """Create an API key; returns the plaintext secret ONCE."""
        secret = f"mtk-{secrets.token_hex(16)}"
        with self._guard:
            self._keys[key_id] = ApiKey(
                key_id=key_id, key_hash=_hash(secret),
                scopes=set(scopes), enabled=enabled)
            self._plain[key_id] = secret
        return secret

    def revoke_key(self, key_id: str) -> None:
        with self._guard:
            k = self._keys.get(key_id)
            if k:
                k.enabled = False

    def _auth(self, api_key: str, needed: str) -> ApiKey:
        """Enforce scope; raises ApiError(401/403) on denial."""
        for k in self._keys.values():
            if k.key_hash == _hash(api_key or ""):
                if not k.enabled:
                    raise ApiError(403, "key disabled")
                if needed == "read" and \
                        not ({"read", "admin"} & k.scopes):
                    raise ApiError(403, "scope read required")
                if needed in ("write", "admin") and \
                        needed not in k.scopes and \
                        "admin" not in k.scopes:
                    raise ApiError(403, f"scope {needed} required")
                return k
        raise ApiError(401, "invalid api key")

    # --------------------------------------------------------- routes
    def route(self, method: str, path: str, scope: str, fn):
        self._routes[(method, path)] = {"scope": scope, "fn": fn}

    def _register_default_routes(self):
        self.route("GET", "/api/v1/status", "read", self._get_status)
        self.route("GET", "/api/v1/devices", "read",
                   self._get_devices)
        self.route("GET", "/api/v1/tasks", "read", self._get_tasks)
        self.route("POST", "/api/v1/tasks", "write", self._post_task)
        self.route("GET", "/api/v1/reports/summary", "read",
                   self._get_report)
        self.route("POST", "/api/v1/mes/orders", "write",
                   self._mes_order)
        self.route("GET", "/api/v1/audit", "read", self._get_audit)

    def bind(self, *, status_fn=None, devices=None, tasks=None,
             enqueue=None, report_fn=None, mes=None):
        """Wire platform providers (engines) into the route table."""
        self._providers = {
            "status_fn": status_fn, "devices": devices,
            "tasks": tasks, "enqueue": enqueue,
            "report_fn": report_fn, "mes": mes,
        }

    def _p(self, name):
        return getattr(self, "_providers", {}).get(name)

    # ------------------------------------------------------- dispatch
    def request(self, api_key: str, method: str, path: str,
                body: dict | None = None) -> tuple[int, dict]:
        """Framework-agnostic dispatch: returns (http_code, json)."""
        try:
            spec = self._routes.get((method, path))
            if spec is None:
                raise ApiError(404, f"no route {method} {path}")
            key = self._auth(api_key, spec["scope"])
            data = spec["fn"](body or {})
            self._audit_log(key.key_id, method, path, "OK")
            return 200, {"ok": True, "data": data}
        except ApiError as exc:
            self._audit_log("-", method, path, f"{exc.code}")
            return exc.code, {"ok": False, "error": str(exc)}
        except Exception as exc:                    # noqa: BLE001
            return 500, {"ok": False, "error": f"internal: {exc}"}

    def _audit_log(self, key_id: str, method: str, path: str,
                   result: str) -> None:
        if self.audit is not None:
            self.audit.log(f"apikey:{key_id}", f"api:{method}",
                           path, detail=result)

    # ------------------------------------------------------ handlers
    def _get_status(self, _body):
        fn = self._p("status_fn")
        return fn() if fn else {"platform": "mtk-gui", "version": "3.0"}

    def _get_devices(self, _body):
        dev = self._p("devices")
        return {"devices": dev() if dev else []}

    def _get_tasks(self, _body):
        tasks = self._p("tasks")
        return {"tasks": tasks() if tasks else []}

    def _post_task(self, body):
        enqueue = self._p("enqueue")
        if enqueue is None:
            raise ApiError(503, "task provider not bound")
        task_id = body.get("task_id") or ""
        if not task_id:
            raise ApiError(400, "task_id required")
        enqueue(body)
        return {"task_id": task_id, "queued": True}

    def _get_report(self, _body):
        fn = self._p("report_fn")
        return fn() if fn else {"yield": None}

    def _mes_order(self, body):
        mes = self._p("mes")
        if mes is None:
            raise ApiError(503, "mes adapter not bound")
        return mes.receive_order(body)

    def _get_audit(self, _body):
        rows = self.audit.query(action="api:") if self.audit else []
        return {"api_calls": rows[-50:]}


class MesAdapter:
    """产线对接: inbound orders -> enqueue; outbound results ->
    retry-buffered delivery to the MES endpoint."""

    def __init__(self, enqueue, deliver=None, log_fn=None):
        self.enqueue = enqueue              # platform task intake
        self.deliver = deliver or (lambda payload: True)
        self.log_fn = log_fn or (lambda line: None)
        self.orders: dict[str, MesOrder] = {}
        self._outbox: list[dict] = []       # retry buffer
        self._seen_orders: set = set()      # idempotency

    # ------------------------------------------------------- inbound
    def receive_order(self, body: dict) -> dict:
        oid = str(body.get("order_id") or "").strip()
        qty = body.get("quantity")
        if not oid or not isinstance(qty, int) or qty <= 0:
            return {"accepted": False, "reason": "invalid order"}
        if oid in self._seen_orders:        # idempotent re-delivery
            return {"accepted": True, "order_id": oid,
                    "duplicate": True}
        self._seen_orders.add(oid)
        order = MesOrder(order_id=oid,
                         part_no=str(body.get("part_no", "")),
                         quantity=qty,
                         priority=int(body.get("priority", 0)))
        self.orders[oid] = order
        for i in range(qty):                # one task per unit
            self.enqueue({"task_id": f"{oid}-{i + 1}",
                          "kind": body.get("kind", "*"),
                          "priority": order.priority,
                          "source": "MES", "order_id": oid})
        order.status = "QUEUED"
        self.log_fn(f"[MES] order {oid} accepted: {qty} units")
        return {"accepted": True, "order_id": oid,
                "units": qty, "duplicate": False}

    # ------------------------------------------------------ outbound
    def push_result(self, order_id: str, payload: dict) -> bool:
        """Deliver finished results; buffered on failure (retry)."""
        entry = {"order_id": order_id, "payload": payload}
        try:
            ok = bool(self.deliver(entry))
        except Exception:                   # noqa: BLE001
            ok = False
        if ok:
            order = self.orders.get(order_id)
            if order:
                order.status = "DONE"
                order.result = payload
            self.log_fn(f"[MES] result delivered for {order_id}")
            return True
        self._outbox.append(entry)          # retry buffer
        self.log_fn(f"[MES] delivery failed, buffered {order_id}")
        return False

    def retry_outbox(self) -> int:
        n = 0
        for entry in list(self._outbox):
            try:
                ok = bool(self.deliver(entry))
            except Exception:               # noqa: BLE001
                ok = False
            if ok:
                self._outbox.remove(entry)
                n += 1
        return n

    def pending_outbox(self) -> int:
        return len(self._outbox)


#: short public aliases
AS = ApiServer
MA = MesAdapter
