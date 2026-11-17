# -*- coding: utf-8 -*-
"""Application paths and the writable settings store (v2 / C3).

Roots:

* **program dir** - the exe folder (frozen) or the repo root (development).
* **work dir** - ``<exe parent>/../work`` (frozen) / ``<repo>/work``
  (development); ``MTKGUI_WORK_DIR`` overrides it.  Reports and per-project
  data live here and survive a package upgrade.
* **station root** - the ``MTK_Station`` root above the exe (frozen) or the
  repo root (development).  Logs live here, OUTSIDE the work dir.
* **config dir** - the WRITABLE settings root: ``<exe dir>/config`` (frozen,
  next to ``MTK_GUI.exe`` - not inside ``_internal``) or ``<repo>/config``
  (development); ``MTKGUI_CONFIG_DIR`` overrides it.

The package ships only FACTORY DEFAULTS (``_internal/config`` in a frozen
build).  On first launch :func:`ensure_config` copies them into the writable
config dir.  **A package upgrade replaces the whole config directory, so
every local setting returns to factory defaults** - by design, there is no
migration and no "keep my settings" path.

Qt-free on purpose (importable from the engine and from tests).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

#: files the config dir owns (factory defaults live in the same layout)
CONFIG_FILES = (
    "permissions.json",
    "report_paths.json",
    "settings.json",
    os.path.join("rules", "base.v2.json"),
)

SETTINGS_NAME = "settings.json"

#: the ONE settings schema; unknown keys in the file are ignored
SETTINGS_DEFAULTS = {
    "theme": "Light",
    "performance_timing": False,
    "slow_span_threshold_s": 0.35,
    "event_log_level": "detailed",
}


# --------------------------------------------------------------- roots
def program_dir() -> Path:
    """The program directory: exe folder (frozen) / repo root (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def work_dir() -> Path:
    """The station work folder - survives a package upgrade."""
    env = os.environ.get("MTKGUI_WORK_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return program_dir().parent / "work"
    return program_dir() / "work"


def station_root() -> Path:
    """``C:\\MTK_Station`` in the shipped layout, the repo root in dev."""
    if getattr(sys, "frozen", False):
        return program_dir().parent
    return program_dir()


def logs_dir() -> Path:
    """``<station root>/logs`` (development / station logs)."""
    return station_root() / "logs"


def event_log_dir() -> Path:
    """``<station root>/logs/event`` - never inside the work dir."""
    return logs_dir() / "event"


def config_dir() -> Path:
    """The WRITABLE config root (seeded from the factory copy).

    Frozen: ``<exe dir>/config`` - beside ``MTK_GUI.exe``, never inside
    ``_internal``.  Development: ``<repo>/config``.
    """
    env = os.environ.get("MTKGUI_CONFIG_DIR")
    if env:
        return Path(env)
    return program_dir() / "config"


def factory_config_dir() -> Path:
    """The read-only factory defaults shipped with the build."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", "") or str(program_dir() / "_internal")
        return Path(base) / "config"
    return program_dir() / "config"


def settings_path() -> Path:
    return config_dir() / SETTINGS_NAME


# --------------------------------------------------------------- seeding
def ensure_config() -> Path:
    """Create the config dir and seed every missing file from the factory
    defaults.  Idempotent; existing local values are never overwritten."""
    target = config_dir()
    target.mkdir(parents=True, exist_ok=True)
    factory = factory_config_dir()
    for name in CONFIG_FILES:
        dest = target / name
        if dest.exists():
            continue
        source = factory / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file() and source.resolve() != dest.resolve():
            try:
                shutil.copyfile(source, dest)
                continue
            except OSError:
                pass
        if name == SETTINGS_NAME:
            _write_json(dest, dict(SETTINGS_DEFAULTS))
    return target


# --------------------------------------------------------------- settings
def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_settings() -> dict:
    """Defaults merged with the saved file; unknown keys dropped."""
    data = dict(SETTINGS_DEFAULTS)
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if isinstance(raw, dict):
        for key in data:
            if key in raw and raw[key] is not None:
                data[key] = raw[key]
    return data


def save_settings(values: dict) -> Path:
    """Persist the known keys (defaults for the rest); returns the path."""
    current = load_settings()
    for key in SETTINGS_DEFAULTS:
        if key in (values or {}):
            current[key] = values[key]
    path = settings_path()
    _write_json(path, current)
    return path


def get_setting(key, default=None):
    """One saved value (the schema default when absent)."""
    return load_settings().get(key, SETTINGS_DEFAULTS.get(key, default))


def set_setting(key, value) -> Path:
    """Persist ONE known value; unknown keys are ignored."""
    if key not in SETTINGS_DEFAULTS:
        return settings_path()
    return save_settings({key: value})


# --------------------------------------------------------------- helpers
def timestamp() -> str:
    """``YYYYMMDDTHHMMSS`` - the one stamp used in runtime file names."""
    return datetime.now().strftime("%Y%m%dT%H%M%S")
