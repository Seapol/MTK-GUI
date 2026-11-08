# -*- coding: utf-8 -*-
"""Report output folders (user direction 2026-10-17; M96 rework).

A run writes into

    <reports root>/<PROJECT>/DUT Report/<Part#>_<CoreID>_<Batch#>_<SN>_<ts>/
        power_rails_<...>.csv          (DAQ capture, when enabled)
        DUT_PASS_<...>.pdf             (certificate, auto after the run)
        DUT_detail_<...>.csv           (MES rows)

    <reports root>/<PROJECT>/Event Report/event_<ts>.log
                                                     (one per GUI session)

``<PROJECT>`` is ``MTKGUI_PROJECT`` when the station launcher sets it, else the
loaded project's folder name (``.../projects/96317/plan.yaml`` -> ``96317``),
else ``No_Project``.

Reports ROOT resolution order:

1. the folder saved from Settings > Report Folders… (``work/report_paths.json``)
2. ``MTKGUI_REPORT_HOME`` (station launcher / tests - a default, not a lock)
3. the program directory (exe folder in a frozen build, repo root in dev)

The two sub-folder names default to ``DUT Report`` / ``Event Report`` and are
editable in the same dialog.  The settings file lives in the ``work`` folder -
never in the program directory - so a package upgrade keeps it.
``MTKGUI_WORK_DIR`` overrides that location (tests).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CFG_NAME = "report_paths.json"
ENV_PROJECT = "MTKGUI_PROJECT"
DEFAULT_DUT = "DUT Report"
DEFAULT_EVENT = "Event Report"
NO_PROJECT = "No_Project"

# project identity of the loaded document - set by main_window on load /
# close; M86 (SharePoint) keys its folders on the same value
_current_project = ""


def program_dir() -> Path:
    """The program directory: the exe folder in a frozen build, the repo
    root in development."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def work_dir() -> Path:
    """The station's work folder - survives a package upgrade.

    Frozen: ``<exe parent>/../work`` (``C:\\MTK_Station\\work``).
    Development: ``<repo>/work``.  ``MTKGUI_WORK_DIR`` overrides it.
    """
    env = os.environ.get("MTKGUI_WORK_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return program_dir().parent / "work"
    return program_dir() / "work"


def _cfg_path() -> Path:
    return work_dir() / CFG_NAME


def _raw() -> dict:
    try:
        data = json.loads(_cfg_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def clean_name(value, default: str) -> str:
    """A folder name the GUI can safely join to a path.

    Blank, a path separator or a bare ``.`` / ``..`` falls back to
    *default* - a typo must never move the output somewhere else.
    """
    name = str(value or "").strip()
    if not name:
        return default
    if any(sep in name for sep in ("/", "\\")):
        return default
    if name in (".", ".."):
        return default
    return name


def project_label_for(path) -> str:
    """Folder name that identifies the project a yaml file belongs to.

    ``.../projects/96317/plan.yaml`` -> ``96317``.  A yaml that sits
    directly in a generic folder (``config`` / ``plans`` / ``archive``)
    uses its own stem instead of that folder's name.
    """
    if not path:
        return ""
    p = Path(str(path))
    parent = p.parent.name
    if parent and parent not in ("config", "plans", "archive"):
        return parent
    return p.stem


def set_current_project(name) -> None:
    """Remember which project the GUI has loaded ('' = none)."""
    global _current_project
    _current_project = str(name or "").strip()


def project_key() -> str:
    """The per-project folder name under the reports root."""
    env = os.environ.get(ENV_PROJECT)
    if env and env.strip():
        return clean_name(env, NO_PROJECT)
    return clean_name(_current_project, NO_PROJECT)


def project_folder() -> Path:
    """<reports root>/<PROJECT>."""
    return report_root() / project_key()


def report_root() -> Path:
    """Where the report tree starts (see the module docstring)."""
    saved = str(_raw().get("root") or "").strip()
    if saved:
        return Path(saved).expanduser()
    env = os.environ.get("MTKGUI_REPORT_HOME")
    if env:
        return Path(env)
    return program_dir()


def folder_settings() -> dict:
    """Current ``{root, project, dut, event}`` - for the settings dialog."""
    data = _raw()
    return {
        "root": str(report_root()),
        "project": project_key(),
        "dut": clean_name(data.get("dut"), DEFAULT_DUT),
        "event": clean_name(data.get("event"), DEFAULT_EVENT),
    }


def set_folder_settings(root=None, dut=None, event=None) -> Path:
    """Persist the three values (Settings > Report Folders…).

    An empty *root* is stored empty, which means "unsaved" - the
    resolution order then falls back to the environment / program dir.
    """
    payload = {
        "root": str(root or "").strip(),
        "dut": clean_name(dut, DEFAULT_DUT),
        "event": clean_name(event, DEFAULT_EVENT),
    }
    path = _cfg_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def reset_folder_settings() -> None:
    """Forget the saved values (back to the defaults)."""
    try:
        _cfg_path().unlink()
    except OSError:
        pass                                  # never block the GUI


def dut_folder() -> Path:
    """<reports root>/<PROJECT>/DUT Report."""
    return project_folder() / folder_settings()["dut"]


def event_folder() -> Path:
    """<reports root>/<PROJECT>/Event Report."""
    return project_folder() / folder_settings()["event"]
