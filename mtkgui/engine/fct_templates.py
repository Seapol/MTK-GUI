# -*- coding: utf-8 -*-
"""fct_templates — M47 FCT Sequence reference templates.

Two reference production sequences ship with the app:

* ``Bare Metal DUT``  (``assets/templates/fct_bare_metal.yaml``, 9 rows)
* ``Linux DUT``       (``assets/templates/fct_linux.yaml``, 19 rows)

The templates are PLAIN DATA: every step is one row of the merged
"FCT test step" table, written with its public Type label and the
fields of :class:`~mtkgui.engine.fct_test_config.ConsoleCommand`.  The
loader builds ordinary rows through the SAME
``console_command_for_label`` path the Add menu uses, so a loaded row is
indistinguishable from a hand-added one (editable / removable /
reorderable - no hidden "template" state).

IRON RULE (unchanged): the app NEVER injects steps on its own.  Only the
operator pressing "Load Template" appends these rows; nothing here runs
anything (template load is configuration only).
"""
from __future__ import annotations

import dataclasses
import os
import sys

import yaml

from mtkgui.engine.fct_test_config import (
    KIND_OP,
    KIND_SERIAL_PULL,
    KIND_SERIAL_PUT,
    KIND_SFTP_GET,
    KIND_SFTP_PUT,
    STEP_TYPE_DELAY,
    STEP_TYPE_OPERATION,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_SERIAL_PUT,
    STEP_TYPE_LABELS,
    ConsoleCommand,
    console_command_for_label,
    normalize_step_type_label,
)
from mtkgui.engine.steps import OP_STEPS

#: operator-facing menu entries -> template file names
TEMPLATE_BARE_METAL = "Bare Metal DUT"
TEMPLATE_LINUX = "Linux DUT"
#: M66: operator-selectable complete Wifi_Scan sequence (never auto-loaded)
TEMPLATE_WIFI_SCAN = "Wifi_Scan (Host<->DUT)"
TEMPLATE_FILES = {TEMPLATE_BARE_METAL: "fct_bare_metal.yaml",
                  TEMPLATE_LINUX: "fct_linux.yaml",
                  TEMPLATE_WIFI_SCAN: "fct_wifi_scan.yaml"}
TEMPLATE_LABELS = (TEMPLATE_BARE_METAL, TEMPLATE_LINUX, TEMPLATE_WIFI_SCAN)

#: the Type labels a template step may carry (Delay / the two serial
#: transfers are Add-menu entries but not part of STEP_TYPE_LABELS)
_TEMPLATE_TYPES = tuple(STEP_TYPE_LABELS) + (
    STEP_TYPE_DELAY, STEP_TYPE_SERIAL_PUT, STEP_TYPE_SERIAL_PULL)

#: keys of a template step that are NOT ConsoleCommand fields
_NON_FIELD_KEYS = ("type", "op", "note")
_CMD_FIELDS = {f.name for f in dataclasses.fields(ConsoleCommand)}

#: prefill keys that map onto a stored row field
PREFILL_KEYS = ("wifi_ssid", "wifi_password", "wifi_interface",
                "wifi_driver_load_cmd", "assets_dir", "outbox_dir")


def templates_dir() -> str:
    """The ``assets/templates`` folder (frozen bundle or source tree).

    Mirrors the packaging rule of ``assets/`` (``_internal/assets`` in a
    PyInstaller build): ``sys._MEIPASS`` wins in a frozen app, the repo
    root otherwise.
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", "") or ""
        if base:
            candidate = os.path.join(base, "assets", "templates")
            if os.path.isdir(candidate):
                return candidate
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return os.path.join(repo_root, "assets", "templates")


def template_path(label: str) -> str:
    """Absolute path of one template file (raises on an unknown label)."""
    filename = TEMPLATE_FILES.get(str(label or ""))
    if not filename:
        raise ValueError(f"unknown FCT template {label!r} - expected one "
                         f"of {TEMPLATE_LABELS}")
    return os.path.join(templates_dir(), filename)


def load_template(label: str, path: str = "") -> dict:
    """Parse one template document (pure data, no Qt).

    Returns ``{"name": ..., "description": ..., "steps": [...],
    "path": ...}``; raises ``ValueError`` on an unknown label or an
    empty / malformed step list.
    """
    file_path = str(path or "") or template_path(label)
    with open(file_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    node = dict(data.get("template") or {})
    steps = list(data.get("steps") or [])
    if not steps:
        raise ValueError(f"FCT template {label!r} carries no steps "
                         f"({file_path})")
    return {"name": str(node.get("name") or label),
            "description": str(node.get("description") or ""),
            "steps": steps, "path": file_path}


def command_for_step(step: dict) -> ConsoleCommand:
    """Build the ordinary row backing one template step.

    The public Type label selects the row through
    ``console_command_for_label`` (exactly like an Add-menu click); the
    remaining keys are ConsoleCommand fields laid over the defaults, so
    the template only states what differs.
    """
    if not isinstance(step, dict):
        raise ValueError(f"FCT template step must be a mapping, got "
                         f"{type(step).__name__}")
    label = normalize_step_type_label(str(step.get("type") or ""))
    if label not in _TEMPLATE_TYPES:
        raise ValueError(f"FCT template step: unknown type {label!r}")
    unknown = set(step) - _CMD_FIELDS - set(_NON_FIELD_KEYS)
    if unknown:
        raise ValueError(f"FCT template step {label!r}: unknown key(s) "
                         f"{sorted(unknown)}")
    if label == STEP_TYPE_OPERATION:
        op_name = str(step.get("op") or "")
        if op_name not in OP_STEPS:
            raise ValueError(f"FCT template step: unknown operation "
                             f"{op_name!r}")
        cmd = console_command_for_label(label, op_name)
        cmd.op_params = dict(OP_STEPS[op_name])
    else:
        cmd = console_command_for_label(label, str(step.get("name") or ""))
    for key, value in step.items():
        if key in _NON_FIELD_KEYS:
            continue
        setattr(cmd, key, value)
    if step.get("note"):
        # M66: the note marks special prefill rows (driver probe)
        cmd._template_note = str(step.get("note"))
    return cmd


def apply_prefill(cmd: ConsoleCommand, prefill: dict) -> ConsoleCommand:
    """Pre-fill one row from the loaded project's shared parameters.

    Only parameters an operator can see on the project page are filled:
    the Wi-Fi AP SSID / password / interface (``peripherals.wifi``) and
    the Push / Pull default directories (project ``assets`` / ``outbox``).
    A missing prefill value leaves the template's own default in place;
    the operator can edit every filled value afterwards.
    """
    values = dict(prefill or {})
    params = cmd.op_params if isinstance(cmd.op_params, dict) else None
    if getattr(cmd, "_template_note", "").startswith("driver_probe"):
        # M66: the DUT Wi-Fi driver load command comes from the project
        # Wi-Fi page; the probe waits for the interface to appear
        driver = str(values.get("wifi_driver_load_cmd") or "").strip()
        if driver:
            iface = (str(values.get("wifi_interface") or "").strip()
                     or "wlan0")
            cmd.send = f"{driver}; iw dev {iface} info"
    if (cmd.kind == KIND_OP and params
            and str(params.get("type") or "") == "wifi_connect"):
        if str(values.get("wifi_ssid") or "").strip():
            params["ssid"] = str(values["wifi_ssid"]).strip()
        if str(values.get("wifi_password") or ""):
            params["password"] = str(values["wifi_password"])
        if str(values.get("wifi_interface") or "").strip():
            params["iface"] = str(values["wifi_interface"]).strip()
    if cmd.kind in (KIND_SFTP_PUT, KIND_SERIAL_PUT) \
            and str(values.get("assets_dir") or "").strip():
        cmd.local = str(values["assets_dir"]).strip()
    if cmd.kind in (KIND_SFTP_GET, KIND_SERIAL_PULL) \
            and str(values.get("outbox_dir") or "").strip():
        cmd.local = str(values["outbox_dir"]).strip()
    return cmd


def load_template_commands(label: str, prefill: dict = None,
                           path: str = "") -> list:
    """One template -> the ordered list of ordinary ConsoleCommand rows.

    Args:
        label: one of ``TEMPLATE_LABELS``.
        prefill: optional shared-parameter values (see ``apply_prefill``).
        path: optional explicit template file (tests / custom copies).
    """
    data = load_template(label, path)
    return [apply_prefill(command_for_step(step), prefill or {})
            for step in data["steps"]]
