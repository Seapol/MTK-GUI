# -*- coding: utf-8 -*-
"""P2-2 config store: load/save/snapshot/rollback/diff/audit (pure incr).

Formatting save (``yaml.safe_dump(sort_keys=False, allow_unicode=True)``)
plus deep diff and versioned snapshots.  Saving only mutates registered
paths and never drops unregistered keys -> 100% backward compatible with
existing P1 project YAML files.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime

import yaml

from .config_spec import (FIELDS_BY_PATH, coerce_value, get_path,
                          iter_paths, set_path)

SNAPSHOT_DIR = "config/snapshots"


@dataclass(frozen=True)
class Change:
    path: str
    old: object
    new: object

    def __str__(self) -> str:
        return f"{self.path}: {self.old!r} -> {self.new!r}"


@dataclass(frozen=True)
class SnapshotInfo:
    snap_id: str      # e.g. "20261004-142530-a1b2c3"
    time: str
    note: str
    path: str         # yaml file inside the snapshot dir


def deep_diff(a: dict, b: dict) -> list[Change]:
    """Leaf-level diff of two config dicts (old=a, new=b)."""
    leaves_a = dict(iter_paths(a))
    leaves_b = dict(iter_paths(b))
    changes: list[Change] = []
    for p in sorted(set(leaves_a) | set(leaves_b)):
        old, new = leaves_a.get(p), leaves_b.get(p)
        if old != new:
            changes.append(Change(p, old, new))
    return changes


def apply_registered(cfg: dict, updates: dict[str, object]) -> list[Change]:
    """Coerce + write GUI form values into ``cfg`` IN PLACE.

    Callers pass a copy when they need the original preserved.  Unknown
    paths are rejected loudly so the GUI can never invent engine-unknown
    structure silently.
    """
    changes: list[Change] = []
    for path, raw in updates.items():
        spec = FIELDS_BY_PATH.get(path)
        if spec is None:
            raise KeyError(f"unregistered config path: {path!r}")
        # untouched empty optional fields never pollute the YAML file
        if (not spec.required and isinstance(raw, str)
                and raw.strip() == ""):
            continue
        val = coerce_value(spec, raw)
        old = get_path(cfg, path)
        if old != val:
            set_path(cfg, path, val)
            changes.append(Change(path, old, val))
    return changes


class ConfigStore:
    """File-backed config storage with snapshots + audit trail."""

    def __init__(self, snapshot_dir: str = SNAPSHOT_DIR) -> None:
        self.snapshot_dir = snapshot_dir
        self.audit: list[tuple[str, str, str]] = []  # (time, action, detail)
        os.makedirs(snapshot_dir, exist_ok=True)

    # core io ----------------------------------------------------------
    @staticmethod
    def load(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def save(cfg: dict, path: str) -> None:
        """Formatted, stable-ordered YAML write (auto-format requirement)."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True,
                           default_flow_style=False)
        # [CFG] audit line mirrors the engine's structured-log convention
        print(f"[CFG] saved {len(dict(iter_paths(cfg)))} leaves -> {path}")

    # snapshots --------------------------------------------------------
    def save_snapshot(self, cfg: dict, note: str = "") -> SnapshotInfo:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        digest = json.dumps(cfg, sort_keys=True, default=str)
        token = f"{abs(hash(digest)) % 10**6:06d}"
        snap_id = f"{ts}-{token}"
        path = os.path.join(self.snapshot_dir, f"{snap_id}.yaml")
        self.save(cfg, path)
        with open(path + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump({"id": snap_id, "time": ts, "note": note}, fh,
                      ensure_ascii=False)
        self._audit("snapshot", f"{snap_id} ({note})")
        return SnapshotInfo(snap_id, ts, note, path)

    def list_snapshots(self) -> list[SnapshotInfo]:
        out: list[SnapshotInfo] = []
        for name in sorted(os.listdir(self.snapshot_dir)):
            if not name.endswith(".meta.json"):
                continue
            with open(os.path.join(self.snapshot_dir, name),
                      "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            out.append(SnapshotInfo(meta["id"], meta["time"], meta.get("note",
                       ""), os.path.join(self.snapshot_dir,
                                         meta["id"] + ".yaml")))
        return out

    def load_snapshot(self, snap_id: str) -> dict:
        return self.load(os.path.join(self.snapshot_dir, f"{snap_id}.yaml"))

    # save pipeline ----------------------------------------------------
    def apply_and_save(self, cfg: dict, updates: dict[str, object],
                       path: str, snapshot_note: str = "before-save") -> tuple[
                           dict, list[Change]]:
        """Validate-free mechanical pipeline used by the GUI page:

        snapshot old -> apply updates -> save formatted -> audit.
        Validation is the caller's duty (page blocks on issues).
        """
        self.save_snapshot(cfg, note=snapshot_note)
        new_cfg = copy.deepcopy(cfg)
        changes = apply_registered(new_cfg, updates)
        self.save(new_cfg, path)
        for ch in changes:
            self._audit("modify", str(ch))
        return new_cfg, changes

    def rollback(self, current: dict, snap_id: str) -> tuple[
            dict, list[Change]]:
        """Restore a snapshot; diff vs current keeps the change auditable."""
        restored = self.load_snapshot(snap_id)
        self._audit("rollback", f"-> {snap_id}")
        return restored, deep_diff(current, restored)

    # misc -------------------------------------------------------------
    def diff(self, a: dict, b: dict) -> list[Change]:
        return deep_diff(a, b)

    def _audit(self, action: str, detail: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.audit.append((stamp, action, detail))
        print(f"[CFG] {stamp} {action}: {detail}")
