# -*- coding: utf-8 -*-
"""M69: project-bound customizable assets folder.

Each project may own ``projects/<Project>/assets_<Project>``, created
by copying the READ-ONLY built-in ``assets/`` template.  This module is
Qt-free so the filesystem behaviour is unit-testable; there is no GUI writer -
a project's assets folder is prepared by hand from the built-in template
(2026-11-08 user direction: assets belong to the project).
"""
from __future__ import annotations

import os
import re
import shutil
import sys

#: custom folder name prefix (assets_<Project>)
ASSETS_PREFIX = "assets_"

#: M83/C2b: the only lines the GUI reads from ``connect_wifi.sh``.
#: One name, one equals sign, one quoted value, one line.
AP_PROFILE_LINE_RE = re.compile(
    r"^AP_PROFILE_(ROUTER|HOTSPOT)_(SSID|PASSWORD)='?(.*?)'?$")


def parse_ap_profile_values(text: str) -> dict:
    """``{"AP_PROFILE_ROUTER_SSID": "...", ...}`` from connect_wifi.sh.

    Only the four declaration lines are read; a missing line is absent
    from the result (never defaulted).  The script stays the single
    owner of the values."""
    values = {}
    for line in str(text or "").splitlines():
        match = AP_PROFILE_LINE_RE.match(line)
        if not match:
            continue
        values[f"AP_PROFILE_{match.group(1)}_{match.group(2)}"] = \
            match.group(3)
    return values


#: M83/C15: the four one-way rows of the review window:
#: (label, script key, Equipment page field, is_password)
AP_PROFILE_FIELDS = (
    ("Router AP SSID", "AP_PROFILE_ROUTER_SSID", "router_ap_ssid", False),
    ("Router AP password", "AP_PROFILE_ROUTER_PASSWORD",
     "router_ap_password", True),
    ("Hotspot SSID", "AP_PROFILE_HOTSPOT_SSID", "hotspot_ssid", False),
    ("Hotspot password", "AP_PROFILE_HOTSPOT_PASSWORD",
     "hotspot_password", True),
)


def builtin_assets_dir() -> str:
    """The bundled, read-only asset template.

    Frozen build: ``<_internal>/assets``; source tree: ``<repo>/assets``.
    Mirrors :func:`mtkgui.engine.fct_templates.templates_dir`."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", "") or os.path.dirname(
            os.path.abspath(sys.executable))
        return os.path.join(base, "assets")
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "assets")


def custom_assets_dir(project: str, tenant_base: str = "projects") -> str:
    """``projects/<Project>/assets_<Project>`` (normpath)."""
    project = str(project or "").strip()
    return os.path.normpath(os.path.join(
        str(tenant_base or "projects"), project,
        ASSETS_PREFIX + project))


def legacy_assets_dir(project: str, tenant_base: str = "projects") -> str:
    """``projects/<Project>/assets`` (the pre-M69 convention)."""
    project = str(project or "").strip()
    return os.path.normpath(os.path.join(
        str(tenant_base or "projects"), project, "assets"))


def list_projects(tenant_base: str = "projects") -> list:
    """Project folders under ``tenant_base`` (skip hidden files and
    ``demo/``)."""
    try:
        entries = sorted(os.listdir(tenant_base))
    except OSError:
        return []
    projects = []
    for name in entries:
        if name.startswith(".") or name.lower() == "demo":
            continue
        if os.path.isdir(os.path.join(tenant_base, name)):
            projects.append(name)
    return projects


def assets_state(project: str, tenant_base: str = "projects") -> str:
    """``"custom"`` (assets_<Project> exists), ``"legacy"`` (old
    ``assets/`` exists) or ``"none"``."""
    if os.path.isdir(custom_assets_dir(project, tenant_base)):
        return "custom"
    if os.path.isdir(legacy_assets_dir(project, tenant_base)):
        return "legacy"
    return "none"


def status_suffix(state: str) -> str:
    """Operator-facing status suffix of a project row."""
    return {"custom": "(assets ready)",
            "legacy": "(built-in fallback)",
            "none": "(no assets yet)"}.get(state, "(no assets yet)")


def create_custom_assets(project: str, tenant_base: str = "projects",
                         source: str | None = None,
                         overwrite: bool = False) -> str:
    """Copy the built-in assets tree into ``assets_<Project>``.

    ``overwrite=True`` is the "Re-create" path: the custom folder is
    wiped first.  The built-in source is never written to.
    Returns the created folder path."""
    src = os.path.abspath(source or builtin_assets_dir())
    dst = os.path.abspath(custom_assets_dir(project, tenant_base))
    if not os.path.isdir(src):
        raise FileNotFoundError(f"built-in assets folder not found: {src}")
    if os.path.exists(dst) and not overwrite:
        raise FileExistsError(f"custom assets already exist: {dst}")
    if overwrite and os.path.isdir(dst):
        shutil.rmtree(dst)
    parent = os.path.dirname(dst)
    os.makedirs(parent, exist_ok=True)
    shutil.copytree(src, dst)
    return dst


def remove_custom_assets(project: str,
                         tenant_base: str = "projects") -> bool:
    """Delete ONLY ``assets_<Project>`` (never the project folder)."""
    dst = os.path.abspath(custom_assets_dir(project, tenant_base))
    project_dir = os.path.abspath(os.path.join(tenant_base, project))
    # hard guard: the target must be a direct child named assets_<Project>
    if os.path.dirname(dst) != project_dir or \
            os.path.basename(dst) != ASSETS_PREFIX + str(project):
        raise ValueError(f"refusing to delete outside the project: {dst}")
    if not os.path.isdir(dst):
        return False
    shutil.rmtree(dst)
    return True


def list_asset_files(root: str) -> list:
    """Relative POSIX paths under *root*, sorted (files only)."""
    out = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(base, name)
            out.append(os.path.relpath(full, root).replace(os.sep, "/"))
    return sorted(out)


def read_asset_text(path: str) -> tuple:
    """``(text, is_text)``: UTF-8 decodable and NUL-free means text.

    A binary file returns ``("", False)`` so the dialog can show the
    read-only "open in an external editor" hint."""
    try:
        data = open(path, "rb").read()
    except OSError:
        return "", False
    if b"\x00" in data:
        return "", False
    try:
        return data.decode("utf-8"), True
    except UnicodeDecodeError:
        return "", False


def write_asset_text(path: str, text: str) -> None:
    """Write UTF-8 text (never into the built-in template)."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(str(text))
