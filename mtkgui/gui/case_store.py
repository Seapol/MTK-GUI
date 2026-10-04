# -*- coding: utf-8 -*-
"""P2-3 case store: per-case visual edit / lock / history (pure incr).

Thin GUI-side storage over the project YAML ``ict_test_cases`` list.
Reuses the P1-16 casegen field contract (``EDITABLE`` columns, audit
key ``ict_case_audit``) verbatim — zero changes to the engine casegen
modules.  Every GUI edit:

  * validates + coerces values exactly like the review-Excel importer,
  * appends a traceable entry to ``ict_case_audit.history``,
  * prints a ``[CASE]`` structured-audit line,
  * is blocked for version-locked cases (``ict_case_audit.locks``).
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

from mtkgui.engine.casegen.excel_io import EDITABLE

AUDIT_KEY = "ict_case_audit"
SNAPSHOT_DIR = "config/case_snapshots"

# GUI-editable superset: P1-16 review columns + per-case retry/skip
# (engine keeps global test_workflow.retry as default; a per-case value
# only overrides it, absent key = inherit, 100% backward compatible)
GUI_EDITABLE = EDITABLE + ("retry", "skip_if")

# dimension toggle groups (spec P2-3 item 3)
DIMENSIONS = ("impedance", "voltage", "timing")
DIM_CN = {"impedance": "阻抗", "voltage": "电压", "timing": "上电时序"}


class LockedCaseError(RuntimeError):
    """Raised when a locked case is edited."""


@dataclass(frozen=True)
class FieldChange:
    case: str
    field: str
    old: object
    new: object

    def __str__(self) -> str:
        return f"{self.case}.{self.field}: {self.old!r} -> {self.new!r}"


def categorize(case: dict) -> str:
    """Display category for the case list (电源/时钟/信号/操作).

    Note: clock rows carry test_dim="voltage" (frequency window), so
    the name-prefix checks must take precedence over the dimension.
    """
    name = str(case.get("name") or "")
    dim = str(case.get("test_dim") or "")
    if name.startswith("CLK"):
        return "时钟网络"
    if name.startswith("SIG"):
        return "信号网络"
    if name.startswith("PWR") or dim in ("voltage", "timing") \
            or name.startswith("Impedance"):
        return "电源网络"
    return "操作流程"


def coerce_field(field: str, raw):
    """Same numeric/bool semantics as the review-Excel importer."""
    if raw is None:
        return False if field == "enable" else ""
    if field == "enable":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "是", "y")
    if field == "retry":
        if raw is None or str(raw).strip() == "":
            return None  # absent key -> inherit global retry
        return int(float(raw))  # ValueError propagates to the GUI
    if field in ("wait_ms", "timeout_ms"):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be an integer, got {raw!r}")
    if field == "priority":
        if raw is None or str(raw).strip() == "":
            return ""
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            raise ValueError(f"priority must be an integer, got {raw!r}")
    if field in ("threshold_min", "threshold_max"):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return str(raw).strip()
    return str(raw).strip()


class CaseStore:
    """File-backed case storage with lock state, snapshots and history."""

    def __init__(self, snapshot_dir: str = SNAPSHOT_DIR) -> None:
        self.snapshot_dir = snapshot_dir
        self.audit: list[tuple[str, str, str]] = []
        os.makedirs(snapshot_dir, exist_ok=True)

    # core io ----------------------------------------------------------
    @staticmethod
    def load(path: str) -> dict:
        if not os.path.exists(path):
            return {"ict_test_cases": [], AUDIT_KEY: {}}
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def save(cfg: dict, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True,
                           default_flow_style=False)
        print(f"[CASE] saved {len(cfg.get('ict_test_cases') or [])} "
              f"case(s) -> {path}")

    # snapshots --------------------------------------------------------
    def save_snapshot(self, cfg: dict, note: str = "") -> str:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        digest = json.dumps(cfg, sort_keys=True, default=str)
        snap_id = f"{ts}-{abs(hash(digest)) % 10**6:06d}"
        path = os.path.join(self.snapshot_dir, f"{snap_id}.yaml")
        self.save(cfg, path)
        self._audit("snapshot", f"{snap_id} ({note})")
        return snap_id

    def load_snapshot(self, snap_id: str) -> dict:
        return self.load(os.path.join(self.snapshot_dir,
                                      f"{snap_id}.yaml"))

    # lock state ---------------------------------------------------------
    @staticmethod
    def is_locked(cfg: dict, name: str) -> bool:
        locks = (cfg.get(AUDIT_KEY) or {}).get("locks") or {}
        return bool(locks.get(name))

    @classmethod
    def set_locked(cls, cfg: dict, name: str, locked: bool) -> None:
        audit = dict(cfg.get(AUDIT_KEY) or {})
        locks = dict(audit.get("locks") or {})
        if locked:
            locks[name] = {"time": datetime.now(timezone.utc)
                            .strftime("%Y-%m-%dT%H:%M:%SZ")}
        else:
            locks.pop(name, None)
        audit["locks"] = locks
        cfg[AUDIT_KEY] = audit

    # history ------------------------------------------------------------
    @staticmethod
    def history(cfg: dict) -> list[dict]:
        return list((cfg.get(AUDIT_KEY) or {}).get("history") or [])

    # edits ----------------------------------------------------------------
    def apply_case_edit(self, cfg: dict, name: str,
                        updates: dict) -> list[FieldChange]:
        """Apply an in-place single-case edit; returns field changes.

        Raises KeyError for unknown case, LockedCaseError when locked and
        ValueError on illegal values (GUI must intercept before save).
        """
        cases = cfg.get("ict_test_cases") or []
        target = next((c for c in cases
                       if str(c.get("name")) == name), None)
        if target is None:
            raise KeyError(f"unknown case: {name!r}")
        if self.is_locked(cfg, name):
            raise LockedCaseError(f"case {name!r} is version-locked")
        illegal = set(updates) - set(GUI_EDITABLE)
        if illegal:
            raise KeyError(f"non-editable fields: {sorted(illegal)}")
        changes: list[FieldChange] = []
        for field, raw in updates.items():
            new = coerce_field(field, raw)
            if field == "retry" and new is None:
                old = target.get("retry")
                target.pop("retry", None)
                if old is not None:
                    changes.append(FieldChange(name, field, old, None))
                continue
            old = target.get(field)
            if old != new:
                target[field] = new
                changes.append(FieldChange(name, field, old, new))
        if changes:
            self._record_history(cfg, source="gui-editor", actor="operator",
                                 changed=[ch for ch in changes],
                                 rows_delta=0)
        return changes

    def set_dimension_enabled(self, cfg: dict, dim: str,
                              enabled: bool) -> list[FieldChange]:
        """Batch toggle of one test dimension (阻抗/电压/上电时序)."""
        if dim not in DIMENSIONS:
            raise KeyError(f"unknown dimension: {dim!r}")
        changes: list[FieldChange] = []
        for case in cfg.get("ict_test_cases") or []:
            if str(case.get("test_dim")) != dim:
                continue
            if self.is_locked(cfg, str(case.get("name"))):
                continue  # locked cases are never touched by batch toggles
            old = case.get("enable")
            if bool(old) != enabled:
                case["enable"] = enabled
                changes.append(FieldChange(str(case.get("name")),
                                           "enable", old, enabled))
        if changes:
            self._record_history(
                cfg, source="gui-editor", actor="operator", changed=changes,
                rows_delta=0,
                note=f"dimension {dim} -> {'on' if enabled else 'off'}")
        return changes

    # save pipeline ---------------------------------------------------------
    def edit_and_save(self, cfg: dict, name: str, updates: dict,
                      path: str) -> tuple[dict, list[FieldChange]]:
        """snapshot -> edit -> save formatted -> audit.  Returns the new
        config (copy) and the change list."""
        self.save_snapshot(cfg, note=f"pre-edit {name}")
        new_cfg = copy.deepcopy(cfg)
        changes = self.apply_case_edit(new_cfg, name, updates)
        self.save(new_cfg, path)
        return new_cfg, changes

    # misc --------------------------------------------------------------
    def _record_history(self, cfg: dict, *, source: str, actor: str,
                        changed: list[FieldChange], rows_delta: int,
                        note: str = "") -> None:
        rows = len(cfg.get("ict_test_cases") or [])
        entry = {
            "time": datetime.now(timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": source, "actor": actor,
            "added": [], "removed": [],
            "changed": [{"name": ch.case, "field": ch.field,
                         "old": ch.old, "new": ch.new} for ch in changed],
            "rows_before": rows - rows_delta, "rows_after": rows,
        }
        if note:
            entry["note"] = note
        audit = dict(cfg.get(AUDIT_KEY) or {})
        history = list(audit.get("history") or [])
        history.append(entry)
        audit["history"] = history
        audit["review_version"] = len(history)
        cfg[AUDIT_KEY] = audit
        for ch in changed:
            self._audit("modify", str(ch))

    def _audit(self, action: str, detail: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.audit.append((stamp, action, detail))
        print(f"[CASE] {stamp} {action}: {detail}")
