# -*- coding: utf-8 -*-
"""P2-2 visual YAML config: field schema + validation (pure incremental).

A flat registry of dotted-path field specs drives both the GUI form and
the validation engine.  Rules:

  * registered paths map onto the EXISTING project YAML structure
    (project/product/test_workflow/firmware/equipment) — engine-consumed
    keys keep their exact names (`test_workflow.retry`,
    `firmware.<slot>_image`, ...);
  * the `sharepoint` section is NEW and additive — the engine treats it
    as pass-through until P2-8 wires the uploader;
  * saving must never drop unregistered keys (100% backward compatible).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable

# ---------------------------------------------------------------- types
STR = "str"
INT = "int"
FLOAT = "float"
BOOL = "bool"
CHOICE = "choice"
PATH = "path"          # filesystem path (existence check optional)
URL = "url"            # http(s) URL
PASSWORD = "password"  # non-empty secret
LIST_STR = "list_str"  # multiline text, one item per line

_URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
_VER_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")


@dataclass(frozen=True)
class FieldSpec:
    """One editable config leaf, addressed by dotted path."""

    path: str                       # dotted path, e.g. "test_workflow.retry"
    label: str
    ftype: str = STR
    required: bool = False
    default: Any = None
    min_value: float | None = None  # int/float bound (inclusive)
    max_value: float | None = None
    choices: tuple = ()             # CHOICE
    exists: bool = False            # PATH: file must exist on this machine
    pattern: str | None = None      # regex the string must match
    secret: bool = False            # render masked in GUI
    hint: str = ""


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    value: Any
    reason: str

    def __str__(self) -> str:  # 精准报错: 字段 + 非法值 + 原因
        return f"{self.path}: illegal value {self.value!r} ({self.reason})"


# ---------------------------------------------------------------- paths
def get_path(cfg: dict, path: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(cfg: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def iter_paths(cfg: dict, prefix: str = ""):
    """Yield every leaf (dotted path, value) — used by diff/preserve."""
    for k, v in cfg.items():
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from iter_paths(v, p)
        else:
            yield p, v


# ------------------------------------------------------------ registry
SECTIONS: dict[str, tuple[FieldSpec, ...]] = {
    "project": (
        FieldSpec("project.software", "Software version", STR),
        FieldSpec("project.revision", "Config revision", STR, required=True,
                  pattern=_VER_RE.pattern, hint="e.g. 1.0 / rev1.1"),
        FieldSpec("product.part_number", "Product part number", STR,
                  required=True),
        FieldSpec("product.core_id", "Core ID", STR),
        FieldSpec("product.batch", "Batch number", STR, required=True),
        FieldSpec("test_workflow.stop_if_failure", "Stop on failure", BOOL,
                  default=False),
        FieldSpec("test_workflow.stop_if_any_short", "Stop on short", BOOL,
                  default=True),
        FieldSpec("test_workflow.retry", "Retries", INT, min_value=0,
                  max_value=9, default=0),
        FieldSpec("test_workflow.global_timeout_s", "Global timeout (s)",
                  INT, min_value=1, max_value=86400, default=3600),
        FieldSpec("test_workflow.schedule_mode", "Schedule mode", CHOICE,
                  choices=("sequential", "parallel"), default="sequential"),
        FieldSpec("test_workflow.max_parallel", "Max parallel", INT,
                  min_value=1, max_value=16, default=1),
    ),
    "firmware": (
        FieldSpec("firmware.fat_image", "FAT image path", PATH, exists=True),
        FieldSpec("firmware.oobe_image", "OOBE image path", PATH,
                  exists=True),
        FieldSpec("firmware.connect_timeout_s", "Flash connect timeout (s)",
                  INT, min_value=1, max_value=600, default=10),
        FieldSpec("firmware.write_timeout_s", "Write timeout (s)", INT,
                  min_value=1, max_value=3600, default=120),
        FieldSpec("firmware.verify_timeout_s", "Verify timeout (s)", INT,
                  min_value=1, max_value=3600, default=60),
        FieldSpec("firmware.verify", "Verify after flash", BOOL,
                  default=True),
        FieldSpec("firmware.version_rule", "Version rule", CHOICE,
                  choices=("exact", "gte", "any"), default="exact"),
    ),
    "equipment": (
        FieldSpec("equipment.host.fields.OS", "Host OS", STR),
        FieldSpec("equipment.host.fields.Test SW", "Test software", STR),
        FieldSpec("equipment.comm.timeout_s", "Comm timeout (s)", INT,
                  min_value=1, max_value=600, default=5),
        FieldSpec("equipment.comm.alias", "Device alias", STR),
        FieldSpec("equipment.comm.channel", "Channel config", STR),
    ),
    "sharepoint": (
        FieldSpec("sharepoint.enabled", "Enable cloud archive", BOOL,
                  default=False),
        FieldSpec("sharepoint.site_url", "Project URL", URL),
        FieldSpec("sharepoint.username", "Corporate account", STR),
        FieldSpec("sharepoint.password", "Corporate password", PASSWORD,
                  secret=True),
        FieldSpec("sharepoint.token", "Token", PASSWORD, secret=True),
        FieldSpec("sharepoint.upload_retry_count", "Upload retries", INT,
                  min_value=0, max_value=9, default=3),
        FieldSpec("sharepoint.resume_on_disconnect",
                  "Resume on disconnect", BOOL, default=True),
        FieldSpec("sharepoint.overwrite_policy", "Overwrite policy", CHOICE,
                  choices=("overwrite", "keep_both", "skip"),
                  default="keep_both"),
        FieldSpec("sharepoint.project_dir", "Cloud archive dir", STR),
        FieldSpec("sharepoint.archive_whitelist", "Archive whitelist",
                  LIST_STR, hint="One glob pattern per line, e.g. *.pdf"),
    ),
}

ALL_FIELDS: tuple[FieldSpec, ...] = tuple(
    f for fields in SECTIONS.values() for f in fields)
FIELDS_BY_PATH: dict[str, FieldSpec] = {f.path: f for f in ALL_FIELDS}


# ---------------------------------------------------------- validation
def validate_value(spec: FieldSpec, value: Any) -> ValidationIssue | None:
    """Return an issue or None.  Illegal -> precise field+value+reason."""
    missing = value is None or (isinstance(value, str) and value.strip() == "")
    if spec.required and missing:
        return ValidationIssue(spec.path, value, "required but empty")
    if missing:
        return None  # optional empty is fine

    if spec.ftype in (INT, FLOAT):
        try:
            num = float(value)
        except (TypeError, ValueError):
            return ValidationIssue(spec.path, value, "not a number")
        if spec.ftype == INT and num != int(num):
            return ValidationIssue(spec.path, value, "not an integer")
        if spec.min_value is not None and num < spec.min_value:
            return ValidationIssue(spec.path, value,
                                   f"< min {spec.min_value}")
        if spec.max_value is not None and num > spec.max_value:
            return ValidationIssue(spec.path, value,
                                   f"> max {spec.max_value}")
        return None

    if spec.ftype == BOOL:
        if isinstance(value, bool):
            return None
        low = str(value).strip().lower()
        if low in ("true", "false", "yes", "no", "1", "0"):
            return None
        return ValidationIssue(spec.path, value, "not a boolean")

    if spec.ftype == CHOICE:
        if str(value) in spec.choices:
            return None
        return ValidationIssue(spec.path, value,
                               f"must be one of {list(spec.choices)}")

    if spec.ftype == PATH:
        import os
        if "\x00" in str(value):
            return ValidationIssue(spec.path, value, "contains NUL byte")
        if spec.exists and not os.path.isfile(str(value)):
            return ValidationIssue(spec.path, value, "file does not exist")
        return None

    if spec.ftype == URL:
        if not _URL_RE.match(str(value)):
            return ValidationIssue(spec.path, value, "not a valid http(s) URL")
        return None

    if spec.ftype == LIST_STR:
        if not isinstance(value, str):
            return ValidationIssue(spec.path, value, "must be multiline text")
        return None

    # plain str / password
    if spec.pattern and not re.match(spec.pattern, str(value)):
        return ValidationIssue(spec.path, value, "pattern mismatch")
    return None


def validate_config(cfg: dict) -> list[ValidationIssue]:
    """Validate every registered field against the loaded config."""
    issues: list[ValidationIssue] = []
    for spec in ALL_FIELDS:
        issue = validate_value(spec, get_path(cfg, spec.path))
        if issue:
            issues.append(issue)
    return issues


def coerce_value(spec: FieldSpec, value: Any) -> Any:
    """GUI text -> properly typed python value for YAML round-trip."""
    if spec.ftype in (INT, FLOAT) and value not in (None, ""):
        num = float(value)
        return int(num) if spec.ftype == INT else num
    if spec.ftype == BOOL:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "yes", "1")
    return value
