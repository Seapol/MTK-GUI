# -*- coding: utf-8 -*-
"""Report output folders (user direction 2026-10-17).

The DUT reports, DAQ CSV captures and the Event Log text files live
NEXT TO THE PROGRAM by default:

    <program dir>/DUT Report/<date>/DUT_<PASS|FAIL>_...pdf
    <program dir>/DUT Report/<date>/<SN>_<ts>.csv          (MES rows)
    <program dir>/DUT Report/DAQ CSV/power_rails_*.csv
    <program dir>/Event Report/event_<ts>.log

Both folder NAMES are modifiable (Report > Report Folder…): the
override is persisted in ``report_folders.json`` next to the program
(the file is created on first save).  The ``MTKGUI_REPORT_HOME``
environment variable replaces the whole program dir - used by the
tests to keep their output in a tmp path.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

CFG_NAME = "report_folders.json"
DEFAULT_DUT = "DUT Report"
DEFAULT_EVENT = "Event Report"
DAQ_SUBDIR = "DAQ CSV"


def program_dir() -> Path:
    """Where the reports live: the exe folder in a frozen build, the
    repo root in development, or $MTKGUI_REPORT_HOME when set."""
    env = os.environ.get("MTKGUI_REPORT_HOME")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _cfg_path() -> Path:
    return program_dir() / CFG_NAME


def _names() -> dict:
    try:
        cfg = json.loads(_cfg_path().read_text(encoding="utf-8"))
        return {"dut": str(cfg.get("dut") or DEFAULT_DUT),
                "event": str(cfg.get("event") or DEFAULT_EVENT)}
    except (OSError, ValueError):
        return {"dut": DEFAULT_DUT, "event": DEFAULT_EVENT}


def folder_names() -> tuple:
    """Current (dut_name, event_name) - for the settings dialog."""
    n = _names()
    return n["dut"], n["event"]


def set_folder_names(dut_name: str, event_name: str) -> None:
    """Persist the two folder names (Report > Report Folder…)."""
    names = {"dut": (dut_name or DEFAULT_DUT).strip() or DEFAULT_DUT,
             "event": (event_name or DEFAULT_EVENT).strip()
             or DEFAULT_EVENT}
    try:
        _cfg_path().write_text(
            json.dumps(names, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass                                  # never block the GUI


def dut_folder() -> Path:
    """<program>/DUT Report (name modifiable)."""
    return program_dir() / _names()["dut"]


def event_folder() -> Path:
    """<program>/Event Report (name modifiable)."""
    return program_dir() / _names()["event"]


def daq_folder() -> Path:
    """DAQ CSV captures live under the SAME root as the DUT reports."""
    return dut_folder() / DAQ_SUBDIR
