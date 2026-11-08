# -*- coding: utf-8 -*-
"""Per-project SharePoint config / state (M86).

SharePoint settings belong to the PROJECT, not to the application: two
projects on one station must not share a site link, an outbox or a "last
upload" light.  Everything lives under ``work/sharepoint/<PROJECT>/``:

* ``sharepoint_upload.json`` - the ``sharepoint`` config section;
* ``state.json`` - shopfloor light + last result + pending files;
* ``upload_ledger.json`` - the sha256 dedup ledger (written by the uploader).

Qt-free, atomic writes, never raises into the GUI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .gui import identity
from .report_paths import clean_name, project_key, work_dir

CONFIG_NAME = "sharepoint_upload.json"
STATE_NAME = "state.json"
LEDGER_NAME = "upload_ledger.json"

#: the shopfloor light states (mapped onto the status-bar LED palette)
LIGHTS = ("off", "ok", "busy", "fail")

#: pre-M86 location (module config dir) - migrated once, never deleted
LEGACY_CONFIG = Path(__file__).resolve().parent / "config" / CONFIG_NAME

_STATE_DEFAULTS = {"light": "off", "last_result": "", "last_url": "",
                   "last_attempt_ts": "", "pending": []}

#: Windows-forbidden characters for a folder / remote segment
_FORBIDDEN = '[]|:*?"<>'

_migration_logged = False


# ---------------------------------------------------------------- paths
def project_dir() -> Path:
    """``<work>/sharepoint/<PROJECT>/`` (created on demand)."""
    path = work_dir() / "sharepoint" / clean_name(project_key(),
                                                  "no-project")
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    """``<project dir>/sharepoint_upload.json``."""
    return project_dir() / CONFIG_NAME


def state_path() -> Path:
    """``<project dir>/state.json``."""
    return project_dir() / STATE_NAME


def ledger_path() -> Path:
    """``<project dir>/upload_ledger.json`` (the dedup ledger)."""
    return project_dir() / LEDGER_NAME


# --------------------------------------------------------------- config
def _read_json(path: Path, default: dict) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def load_config() -> dict:
    """The stored ``sharepoint`` section ({} when missing)."""
    data = _read_json(config_path(), {})
    section = data.get("sharepoint")
    return dict(section) if isinstance(section, dict) else {}


def save_config(section: dict) -> Path:
    """Write the ``sharepoint`` section (same key names as UploadConfig)."""
    path = config_path()
    payload = json.dumps({"sharepoint": dict(section or {})},
                         ensure_ascii=False, indent=2) + "\n"
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass                              # never block the GUI
    return path


def migrate_legacy_config() -> bool:
    """Copy the pre-M86 module config into this project, once.

    The old file is left untouched; nothing happens when the project already
    has its own config.
    """
    global _migration_logged
    if config_path().is_file():
        return False
    data = _read_json(LEGACY_CONFIG, {})
    section = data.get("sharepoint")
    if not isinstance(section, dict) or not section:
        return False
    save_config(section)
    if not _migration_logged:
        print(f"[SHAREPOINT] migrated {LEGACY_CONFIG} -> {config_path()}")
        _migration_logged = True
    return True


# ---------------------------------------------------------------- state
def load_state() -> dict:
    """The persisted shopfloor state (defaults when missing / corrupt)."""
    data = _read_json(state_path(), _STATE_DEFAULTS)
    state = dict(_STATE_DEFAULTS)
    state.update({key: data[key] for key in _STATE_DEFAULTS if key in data})
    if state["light"] not in LIGHTS:
        state["light"] = "off"
    if not isinstance(state["pending"], list):
        state["pending"] = []
    for key in ("last_result", "last_url", "last_attempt_ts"):
        state[key] = str(state[key] or "")
    state["pending"] = [str(name) for name in state["pending"]]
    return state


def save_state(**changes) -> Path:
    """Read-modify-write ``state.json`` atomically (tmp + os.replace)."""
    state = load_state()
    for key in ("light", "last_result", "last_url", "last_attempt_ts"):
        if key in changes:
            state[key] = str(changes[key] or "")
    if state["light"] not in LIGHTS:
        state["light"] = "off"
    if "pending" in changes:
        state["pending"] = [str(name) for name in (changes["pending"] or [])]
    path = state_path()
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass                              # never block the GUI
    return path


# ------------------------------------------------------------- identity
def _segment(text) -> str:
    """Folder-safe identity segment (Windows-forbidden chars removed)."""
    raw = str(text or "")
    for char in _FORBIDDEN:
        raw = raw.replace(char, "-")
    return clean_name(raw, "")


def identity_folder() -> str:
    """The remote identity segment - never empty, never a path separator."""
    try:
        candidates = (identity.identity_prefix(), identity.get_user(),
                      identity.get_station_id())
    except Exception:                     # noqa: BLE001 - never block upload
        candidates = ()
    for candidate in candidates:
        name = _segment(candidate)
        if name:
            return name
    return "operator"


__all__ = [
    "CONFIG_NAME",
    "LEDGER_NAME",
    "LIGHTS",
    "STATE_NAME",
    "config_path",
    "identity_folder",
    "ledger_path",
    "load_config",
    "load_state",
    "migrate_legacy_config",
    "project_dir",
    "save_config",
    "save_state",
    "state_path",
]
