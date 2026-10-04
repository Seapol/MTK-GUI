# -*- coding: utf-8 -*-
"""P2-11 simple RBAC + full-chain operation audit (pure incremental).

Factory-audit capability layered beside the test core (zero changes
to runners / devices / engines):

  * two roles      — ADMIN (full) vs OPERATOR (run / view / export /
                     upload only; no config, no case editing)
  * accounts       — local JSON store, salted SHA-256 passwords,
                     bootstrap admin/op accounts on first run; only
                     ADMIN may add accounts
  * login          — returns a Session or None; failed attempts are
                     audited too ([AUTH] lines)
  * require()      — permission gate: raises PermissionError and
                     records the DENY attempt for traceability
  * AuditLog       — JSONL ledger of every key operation (config
                     edit, case edit, import/export, report delete,
                     cloud upload...) with time / user / action /
                     target / before-after diff; query + filter +
                     CSV/JSON export

Pure incremental: existing pages opt in by calling audit.log/guard.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class Role(str, Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"


# what each role may do — the single source of truth for the gate
PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {"*"},
    Role.OPERATOR: {"run_test", "view", "export_report", "upload"},
}


def _hash(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


@dataclass
class Session:
    username: str
    role: Role

    def can(self, action: str) -> bool:
        allowed = PERMISSIONS[self.role]
        return "*" in allowed or action in allowed


class AccessControl:
    """Account store + login + permission gate."""

    DEFAULTS = (("admin", "admin123", Role.ADMIN),
                ("op", "op123", Role.OPERATOR))

    def __init__(self, accounts_path, audit: "AuditLog" | None = None,
                 now=None):
        self.path = Path(accounts_path)
        self.audit = audit
        self.now = now or datetime.now
        self.accounts: dict[str, dict] = {}
        self._load()

    # ---------------------------------------------------------- store
    def _load(self) -> None:
        if self.path.is_file():
            try:
                self.accounts = json.loads(
                    self.path.read_text(encoding="utf-8"))
                return
            except (json.JSONDecodeError, OSError):
                pass
        self.accounts = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.accounts,
                                        ensure_ascii=False, indent=2),
                             encoding="utf-8")

    def ensure_default_accounts(self) -> None:
        """Bootstrap the factory default pair (first run only)."""
        if not self.accounts:
            for user, pwd, role in self.DEFAULTS:
                self.add_account(user, pwd, role, actor="bootstrap")

    def add_account(self, username: str, password: str, role: Role,
                    actor: str = "system") -> None:
        salt = secrets.token_hex(8)
        self.accounts[username] = {
            "salt": salt, "hash": _hash(password, salt),
            "role": role.value,
        }
        self._save()
        if self.audit:
            self.audit.log(actor, "account_add", username,
                           detail=f"role={role.value}")

    # ---------------------------------------------------------- login
    def login(self, username: str, password: str) -> Session | None:
        row = self.accounts.get(username)
        ok = bool(row and _hash(password, row["salt"])
                  == row["hash"])
        if self.audit:
            self.audit.log(username,
                           f"login:{'GRANT' if ok else 'DENY'}",
                           username)
        if not ok:
            return None
        return Session(username=username, role=Role(row["role"]))

    # ----------------------------------------------------------- gate
    def require(self, session: Session | None, action: str,
                target: str = "") -> None:
        """Permission gate — raises PermissionError on denial and
        records the attempt in the audit trail."""
        allowed = session is not None and session.can(action)
        if self.audit:
            self.audit.log(
                session.username if session else "anonymous",
                f"{action}:{'GRANT' if allowed else 'DENY'}", target)
        if not allowed:
            who = session.username if session else "anonymous"
            raise PermissionError(
                f"[AUTH] {who} denied {action} {target}".strip())

    def role_of(self, username: str) -> Role | None:
        row = self.accounts.get(username)
        return Role(row["role"]) if row else None


# ============================================================= audit
class AuditLog:
    """Append-only JSONL operation ledger (query / filter / export)."""

    def __init__(self, path, now=None):
        self.path = Path(path)
        self.now = now or datetime.now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.is_file():
            self.path.touch()
        self._fallback: list[dict] = []   # in-memory mirror

    # ----------------------------------------------------------- write
    def log(self, user: str, action: str, target: str = "",
            before=None, after=None, detail: str = "") -> dict:
        entry = {
            "ts": f"{self.now():%Y-%m-%d %H:%M:%S}",
            "user": user,
            "action": action,
            "target": target,
            "before": _brief(before),
            "after": _brief(after),
            "detail": detail,
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fallback.append(entry)
        print(f"[AUDIT] {entry['ts']} user={user} {action} "
              f"target={target} {detail}".rstrip())
        return entry

    # ------------------------------------------------------------ read
    def entries(self) -> list[dict]:
        rows: list[dict] = []
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        except OSError:
            pass
        return rows

    def query(self, *, action: str | None = None,
              user: str | None = None, since: str | None = None,
              until: str | None = None,
              text: str | None = None) -> list[dict]:
        """Filter the ledger (all criteria AND-combined)."""
        out = []
        for e in self.entries():
            if action and action not in e["action"]:
                continue
            if user and e["user"] != user:
                continue
            if since and e["ts"] < since:
                continue
            if until and e["ts"] > until:
                continue
            if text and text.lower() not in json.dumps(
                    e, ensure_ascii=False).lower():
                continue
            out.append(e)
        return out

    # ---------------------------------------------------------- export
    def export(self, path, fmt: str = "csv") -> Path:
        path = Path(path)
        rows = self.entries()
        if fmt == "json":
            path.write_text(json.dumps(rows, ensure_ascii=False,
                                       indent=2), encoding="utf-8")
        else:                                # csv (factory-friendly)
            with open(path, "w", newline="", encoding="utf-8-sig") \
                    as fh:
                w = csv.DictWriter(fh, fieldnames=[
                    "ts", "user", "action", "target", "before",
                    "after", "detail"])
                w.writeheader()
                w.writerows(rows)
        self.log("system", "audit_export", str(path),
                 detail=f"fmt={fmt} rows={len(rows)}")
        return path


def _brief(value) -> str:
    """Compact before/after rendering for the ledger line."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      default=str)
    return text if len(text) <= 400 else text[:397] + "..."
