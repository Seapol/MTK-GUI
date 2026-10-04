# -*- coding: utf-8 -*-
"""P3-2 structured database persistence base (pure incremental).

Standard sqlite3 persistence layered BESIDE the P2 file stores —
nothing is removed, no file logic touched (dual-storage compat):

  * per-tenant database file (default: tenant workspace
    ``metrics/tenant.db``) -> project data never crosses projects;
    legacy mode may open a standalone db path directly
  * auto schema creation + version stamp, six core tables:
    schema_version / projects / test_records / case_defs / config_kv /
    upload_records (+ audit_events mirror)
  * typed read/write wrappers: test records round-trip to the frozen
    P2-5 ``TestRecord`` contract (status / failure_kind as enum names),
    case defs as JSON field bags, config key-values as YAML strings,
    upload ledger rows
  * migration adapter: bulk-import from a live P2-5 MetricsEngine and
    export back -> file data never lost, DB and file can coexist

Pure additive: zero changes to any P1/P2 producer or store.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import fields as dc_fields
from datetime import datetime
from pathlib import Path

from .metrics import TestRecord
from .results import StepStatus

SCHEMA_VERSION = 1

_TABLES = (
    """CREATE TABLE IF NOT EXISTS schema_version (
           version INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS projects (
           project_id TEXT PRIMARY KEY,
           created_at TEXT NOT NULL,
           note TEXT DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS test_records (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           project_id TEXT NOT NULL,
           name TEXT NOT NULL,
           status TEXT NOT NULL,
           duration_s REAL NOT NULL DEFAULT 0,
           measured REAL,
           ts TEXT,
           batch TEXT DEFAULT '',
           station TEXT DEFAULT '',
           failure_kind TEXT)""",
    """CREATE TABLE IF NOT EXISTS case_defs (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           project_id TEXT NOT NULL,
           name TEXT NOT NULL,
           fields_json TEXT NOT NULL DEFAULT '{}',
           locked INTEGER NOT NULL DEFAULT 0,
           updated_at TEXT NOT NULL,
           UNIQUE(project_id, name))""",
    """CREATE TABLE IF NOT EXISTS config_kv (
           project_id TEXT NOT NULL,
           key TEXT NOT NULL,
           value TEXT NOT NULL,
           updated_at TEXT NOT NULL,
           PRIMARY KEY (project_id, key))""",
    """CREATE TABLE IF NOT EXISTS upload_records (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           project_id TEXT NOT NULL,
           file_name TEXT NOT NULL,
           sha256 TEXT DEFAULT '',
           url TEXT DEFAULT '',
           status TEXT NOT NULL,
           ts TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS audit_events (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           project_id TEXT NOT NULL,
           ts TEXT NOT NULL,
           user TEXT NOT NULL,
           action TEXT NOT NULL,
           target TEXT DEFAULT '',
           before TEXT DEFAULT '',
           after TEXT DEFAULT '',
           detail TEXT DEFAULT '')""",
)


class DbStore:
    """Per-tenant sqlite persistence (thread-safe, auto-schema)."""

    def __init__(self, path, project_id: str = "LEGACY", now=None):
        self.path = Path(path)
        self.project_id = project_id
        self.now = now or datetime.now
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path),
                                     check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.ensure_schema()

    # ----------------------------------------------------------- schema
    def ensure_schema(self) -> None:
        with self._lock:
            for ddl in _TABLES:
                self._conn.execute(ddl)
            row = self._conn.execute(
                "SELECT version FROM schema_version").fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO schema_version VALUES (?)",
                    (SCHEMA_VERSION,))
            self._conn.commit()

    @property
    def schema_version(self) -> int:
        return self._conn.execute(
            "SELECT version FROM schema_version").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --------------------------------------------------------- projects
    def register_project(self, project_id: str,
                         note: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO projects VALUES (?,?,?)",
                (project_id, f"{self.now():%Y-%m-%d %H:%M:%S}", note))
            self._conn.commit()

    def list_projects(self) -> list[str]:
        return [r[0] for r in self._conn.execute(
            "SELECT project_id FROM projects ORDER BY project_id")]

    # ----------------------------------------------------- test records
    def add_record(self, rec: TestRecord,
                   project_id: str | None = None) -> int:
        pid = project_id or self.project_id
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO test_records(project_id,name,status,"
                "duration_s,measured,ts,batch,station,failure_kind) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, rec.name, rec.status.value, rec.duration_s,
                 rec.measured,
                 rec.ts.strftime("%Y-%m-%d %H:%M:%S")
                 if rec.ts else None,
                 rec.batch, rec.station,
                 rec.failure_kind.value if rec.failure_kind else None))
            self._conn.commit()
            return cur.lastrowid

    def list_records(self, *, project_id: str | None = None,
                     batch: str | None = None,
                     name: str | None = None,
                     all_projects: bool = False) -> list[TestRecord]:
        """Typed round-trip to the frozen P2-5 TestRecord contract.

        Default scope is THIS store's project (isolation by default);
        pass all_projects=True for a cross-project report query."""
        sql = ("SELECT * FROM test_records WHERE 1=1")
        args: list = []
        if not all_projects:
            sql += " AND project_id=?"
            args.append(project_id or self.project_id)
        if batch is not None:
            sql += " AND batch=?"
            args.append(batch)
        if name is not None:
            sql += " AND name=?"
            args.append(name)
        sql += " ORDER BY id"
        out = []
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        for r in rows:
            fk = r["failure_kind"]
            out.append(TestRecord(
                name=r["name"],
                status=StepStatus(r["status"]),
                duration_s=r["duration_s"],
                measured=r["measured"],
                ts=datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
                if r["ts"] else None,
                batch=r["batch"], station=r["station"],
                failure_kind=FailureKindValue(fk) if fk else None))
        return out

    def count_records(self, project_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM test_records"
        args: tuple = ()
        if project_id is not None:
            sql += " WHERE project_id=?"
            args = (project_id,)
        return self._conn.execute(sql, args).fetchone()[0]

    # -------------------------------------------------------- case defs
    def upsert_case(self, name: str, fields: dict, locked=False,
                    project_id: str | None = None) -> None:
        pid = project_id or self.project_id
        with self._lock:
            self._conn.execute(
                "INSERT INTO case_defs(project_id,name,fields_json,"
                "locked,updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(project_id,name) DO UPDATE SET "
                "fields_json=excluded.fields_json,"
                "locked=excluded.locked,"
                "updated_at=excluded.updated_at",
                (pid, name, json.dumps(fields, ensure_ascii=False,
                                       sort_keys=True),
                 int(bool(locked)), f"{self.now():%Y-%m-%d %H:%M:%S}"))
            self._conn.commit()

    def get_case(self, name: str,
                 project_id: str | None = None) -> dict | None:
        pid = project_id or self.project_id
        row = self._conn.execute(
            "SELECT fields_json, locked FROM case_defs "
            "WHERE project_id=? AND name=?",
            (pid, name)).fetchone()
        if row is None:
            return None
        return {"fields": json.loads(row["fields_json"]),
                "locked": bool(row["locked"])}

    def list_cases(self, project_id: str | None = None) -> list[str]:
        pid = project_id or self.project_id
        return [r[0] for r in self._conn.execute(
            "SELECT name FROM case_defs WHERE project_id=? "
            "ORDER BY name", (pid,))]

    # -------------------------------------------------------- config kv
    def set_config(self, key: str, value: str,
                   project_id: str | None = None) -> None:
        pid = project_id or self.project_id
        with self._lock:
            self._conn.execute(
                "INSERT INTO config_kv VALUES (?,?,?,?) "
                "ON CONFLICT(project_id,key) DO UPDATE SET "
                "value=excluded.value, updated_at=excluded.updated_at",
                (pid, key, value, f"{self.now():%Y-%m-%d %H:%M:%S}"))
            self._conn.commit()

    def get_config(self, key: str,
                   project_id: str | None = None) -> str | None:
        pid = project_id or self.project_id
        row = self._conn.execute(
            "SELECT value FROM config_kv WHERE project_id=? AND key=?",
            (pid, key)).fetchone()
        return row[0] if row else None

    # --------------------------------------------------- upload ledger
    def add_upload(self, file_name: str, status: str, url="",
                   sha256="", project_id: str | None = None) -> int:
        pid = project_id or self.project_id
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO upload_records(project_id,file_name,"
                "sha256,url,status,ts) VALUES (?,?,?,?,?,?)",
                (pid, file_name, sha256, url, status,
                 f"{self.now():%Y-%m-%d %H:%M:%S}"))
            self._conn.commit()
            return cur.lastrowid

    def list_uploads(self, project_id: str | None = None) -> list[dict]:
        pid = project_id or self.project_id
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM upload_records WHERE project_id=? "
            "ORDER BY id", (pid,))]

    # --------------------------------------------------- audit mirror
    def add_audit(self, ts: str, user: str, action: str, target="",
                  before="", after="", detail="",
                  project_id: str | None = None) -> int:
        pid = project_id or self.project_id
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit_events(project_id,ts,user,action,"
                "target,before,after,detail) VALUES (?,?,?,?,?,?,?,?)",
                (pid, ts, user, action, target, before, after, detail))
            self._conn.commit()
            return cur.lastrowid

    def query_audits(self, *, project_id: str | None = None,
                     action: str | None = None,
                     user: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM audit_events WHERE 1=1", []
        if project_id is not None:
            sql += " AND project_id=?"
            args.append(project_id)
        if action is not None:
            sql += " AND action LIKE ?"
            args.append(f"%{action}%")
        if user is not None:
            sql += " AND user=?"
            args.append(user)
        sql += " ORDER BY id"
        return [dict(r) for r in self._conn.execute(sql, args)]

    # ---------------------------------------------- migration adapter
    def import_from_engine(self, engine, project_id: str | None = None,
                           ) -> int:
        """Bulk-import a live P2-5 MetricsEngine's file-resident
        records (data never lost when adding the DB layer)."""
        n = 0
        for rec in engine.records:
            self.add_record(rec, project_id=project_id)
            n += 1
        return n

    def export_to_engine(self, engine,
                         project_id: str | None = None) -> int:
        """Replay DB rows into a fresh MetricsEngine (dual-store
        read path / recovery)."""
        n = 0
        for rec in self.list_records(project_id=project_id):
            engine.add(rec)
            n += 1
        return n


def FailureKindValue(name: str):
    """Resolve a stored failure-kind name lazily (keeps imports thin
    and avoids any change to the frozen P1-16 taxonomy module)."""
    from .failures import FailureKind
    return FailureKind(name)


_TENANT_SLOT = "db"


def tenant_db(ctx, now=None) -> DbStore:
    """Per-tenant DB handle bound to the tenant workspace
    (``metrics/tenant.db``); cached in the tenant slot so runtime
    state stays isolated per project (P3-1 base)."""
    return ctx.slot(_TENANT_SLOT,
                    lambda: DbStore(ctx.dir("metrics") / "tenant.db",
                                    project_id=ctx.project_id,
                                    now=now))
