# -*- coding: utf-8 -*-
"""Yaml Build data model - the single source of truth.

All page components (block flow, YAML preview, config dialogs, Excel
exchange, publishing) read and write through this model, which makes
the diagram <-> YAML two-way sync structurally loop-free: views never
copy data between each other, they only push into the model and
refresh from its ``changed`` signal.

Disabled modules keep their parameters silently (V4.0 rule 5.2-2)
but are excluded from the effective YAML and from sequence
validation.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime

import yaml

from mtkgui.gui.yamlbuild.schema import (
    MODULE_FIELDS,
    T_BOOL,
    T_FLOAT,
    T_INT,
    T_TEXT,
)
from mtkgui.gui.yamlbuild.stages import STAGE_KEYS, STAGE_BY_KEY

_STAGE_INDEX = {key: i for i, key in enumerate(STAGE_KEYS)}


def _coerce(field_type: str, text: str):
    """Coerce a raw string to the field type's natural value.

    Args:
        field_type: One of the schema T_* types.
        text:       Raw stripped string.

    Returns:
        bool / int / float / str.
    """
    if field_type == T_BOOL:
        return text.lower() in ("true", "1", "yes")
    if field_type == T_INT and text:
        return int(float(text))
    if field_type == T_FLOAT and text:
        return float(text)
    return text


class YamlBuildModel:
    """Parameters + enable state of the ten fixed workflow modules.

    Attributes:
        changed: set to True by every mutation (the page connects its
                 refresh hook to model changes; kept as a plain flag
                 so the model stays Qt-free and headless-testable).
    """

    def __init__(self) -> None:
        """Initialize every module disabled by default, with its
        schema defaults (a fresh project starts from the Equipment
        base template in phase B4; until then defaults apply)."""
        self._params: dict[str, dict] = {}
        self._enabled: dict[str, bool] = {}
        self._plan_version: str = "1.0.0"
        for key in STAGE_KEYS:
            self._params[key] = {
                f.name: f.default for f in MODULE_FIELDS.get(key, ())
            }
            # global default (V4.0 rule 3.2): every module starts
            # ENABLED - new projects, fresh starts and legacy imports
            # all come up fully enabled without manual switching
            self._enabled[key] = True
        # imported design data (acceptance 3.1.1): schematic metadata
        # + parsed netlist + user TP resolutions.  Shared with every
        # downstream module through the effective YAML design_data
        # section.
        self.imported: dict = {
            "schematic": {},     # file, core_id, project_name, rev
            "netlist": {"file": "", "net_count": 0,
                        "nets": {}, "missing_tp": []},
            "tp_resolutions": {},  # net -> pin | "skip"
        }
        self.changed = True

    # ------------------------------------------------------------- access
    def is_enabled(self, module_key: str) -> bool:
        """Return the Enable state of one module.

        Args:
            module_key: Stage key.

        Returns:
            True when the module participates in the flow.
        """
        return self._enabled.get(module_key, False)

    def set_enabled(self, module_key: str, enabled: bool) -> None:
        """Enable / disable one module (parameters are kept either
        way - disable is silent retention, never deletion).

        Args:
            module_key: Stage key.
            enabled:    New state.
        """
        if module_key in self._enabled:
            self._enabled[module_key] = bool(enabled)
            self.changed = True

    def get_params(self, module_key: str) -> dict:
        """Return a copy of one module's parameters.

        Args:
            module_key: Stage key.

        Returns:
            Dict of parameter name -> raw string value.
        """
        return dict(self._params.get(module_key, {}))

    def set_params(self, module_key: str, params: dict) -> None:
        """Update one module's parameters (after dialog save).

        The update merges into the schema field set, so a partial
        dict never drops fields (no field loss).

        Args:
            module_key: Stage key.
            params:     Parameter dict (name -> value); unknown names
                        are stored as-is and ignored by the schema.
        """
        if module_key in self._params:
            merged = dict(self._params[module_key])
            for name, value in (params or {}).items():
                merged[name] = value
            self._params[module_key] = merged
            self.changed = True

    @property
    def plan_version(self) -> str:
        """Plan version used in the Draft/Final file naming."""
        return self._plan_version

    def set_plan_version(self, version: str) -> None:
        """Set the plan version (validated dotted string).

        Args:
            version: e.g. ``"1.0.0"``.
        """
        if re.match(r"^\d+\.\d+\.\d+$", (version or "").strip()):
            self._plan_version = version.strip()
            self.changed = True

    def project_key(self) -> str:
        """Tenant/project identity derived from the Design Input
        module (multi-tenant isolation key).

        Returns:
            ``"<product_id>_<part_number>"`` or ``"default"`` when the
            design input is still empty.
        """
        design = self._params.get("design_input", {})
        product = str(design.get("product_id", "") or "").strip()
        part = str(design.get("part_number", "") or "").strip()
        return f"{product}_{part}" if product or part else "default"

    # ------------------------------------------------- effective YAML
    def to_effective_dict(self) -> dict:
        """Build the effective YAML section: enabled modules only, in
        the fixed workflow order, plus the imported design data that
        downstream modules consume.

        Returns:
            Dict under the ``yaml_build`` key; disabled modules are
            absent (their parameters stay retained in the model).
        """
        modules: dict[str, dict] = {}
        for key in STAGE_KEYS:
            if not self._enabled.get(key):
                continue
            raw = self._params[key]
            entry: dict = {}
            for spec in MODULE_FIELDS.get(key, ()):
                value = raw.get(spec.name, spec.default)
                text = "" if value is None else str(value).strip()
                if spec.ftype == T_TEXT:
                    lines = [ln.strip() for ln in text.splitlines()
                             if ln.strip()]
                    entry[spec.name] = lines
                else:
                    entry[spec.name] = _coerce(spec.ftype, text)
            stage = STAGE_BY_KEY[key]
            entry["stage_index"] = _STAGE_INDEX[key]
            entry["group"] = stage.group
            modules[key] = entry
        section: dict = {
            "plan_version": self._plan_version,
            "modules": modules,
        }
        # design data backfill (acceptance 3.1.1): shared with all
        # downstream flow modules
        if self.imported.get("schematic") or \
                self.imported["netlist"].get("net_count"):
            section["design_data"] = {
                "schematic": dict(self.imported["schematic"]),
                "netlist": {
                    "file": self.imported["netlist"].get("file", ""),
                    "net_count": self.imported["netlist"].get(
                        "net_count", 0),
                    "nets": dict(self.imported["netlist"].get(
                        "nets", {})),
                },
                "tp_resolutions": dict(
                    self.imported.get("tp_resolutions", {})),
            }
        return {"yaml_build": section}

    def to_effective_yaml(self) -> str:
        """Serialize the effective dict to YAML text.

        Returns:
            YAML string (stable key order).
        """
        return yaml.safe_dump(
            self.to_effective_dict(), sort_keys=False, allow_unicode=True)

    # ----------------------------------------------------- YAML import
    def apply_yaml_dict(self, data: dict) -> list[str]:
        """Apply a parsed YAML document into the model.

        Only ``yaml_build`` documents are accepted.  Missing modules
        keep their current state; unknown parameters are ignored;
        legacy files without the section enable nothing (legacy
        compatibility is handled by :meth:`enable_all` at the import
        call site per the V4.0 compatibility rule).

        Args:
            data: Parsed YAML dict.

        Returns:
            List of validation error strings (empty when the document
            was applied cleanly).
        """
        errors: list[str] = []
        if not isinstance(data, dict) or "yaml_build" not in data:
            return ["missing 'yaml_build' section"]
        section = data["yaml_build"] or {}
        modules = section.get("modules") or {}
        if not isinstance(modules, dict):
            return ["'modules' must be a mapping"]
        version = str(section.get("plan_version", "")).strip()
        if version:
            if re.match(r"^\d+\.\d+\.\d+$", version):
                self._plan_version = version
            else:
                errors.append(f"invalid plan_version {version!r}")
        # sequence check on the PRESENT enabled entries
        present = [k for k, v in modules.items()
                   if isinstance(v, dict)
                   and v.get("enabled", True)]
        order = [_STAGE_INDEX[k] for k in present if k in _STAGE_INDEX]
        if order != sorted(order):
            errors.append(
                "module sequence violates the fixed workflow order: "
                + ", ".join(present))
        for key, value in modules.items():
            if key not in _STAGE_INDEX:
                errors.append(f"unknown module {key!r} ignored")
                continue
            if not isinstance(value, dict):
                errors.append(f"module {key}: mapping expected")
                continue
            params = self._params[key]
            for spec in MODULE_FIELDS.get(key, ()):
                if spec.name not in value:
                    continue
                raw = value[spec.name]
                if spec.ftype == T_TEXT:
                    text = "\n".join(str(ln) for ln in raw) \
                        if isinstance(raw, list) else str(raw)
                else:
                    text = "" if raw is None else str(raw)
                error = spec.validate(text)
                if error:
                    errors.append(f"module {key}: {error}")
                    continue
                params[spec.name] = text
            enabled = bool(value.get("enabled", True))
            self._enabled[key] = enabled
        self.changed = True
        return errors

    def enable_all(self) -> None:
        """Enable every module (legacy YAML import default per the
        V4.0 compatibility rule: old files arrive all-enabled)."""
        for key in STAGE_KEYS:
            self._enabled[key] = True
        self.changed = True

    def disable_all(self) -> None:
        """Disable every module (batch context-menu action).

        Parameters are silently retained; re-enabling restores the
        flow without any data loss.
        """
        for key in STAGE_KEYS:
            self._enabled[key] = False
        self.changed = True

    # ---------------------------------------------------- validation
    def validate_module(self, module_key: str) -> list[str]:
        """Validate one module's current parameters against its
        schema (dialog save / pre-build check).

        Args:
            module_key: Stage key.

        Returns:
            List of error strings (empty when valid).  Disabled
            modules are NOT validated (they are skipped by the flow).
        """
        errors: list[str] = []
        if not self._enabled.get(module_key):
            return errors
        raw = self._params.get(module_key, {})
        for spec in MODULE_FIELDS.get(module_key, ()):
            errors.extend(
                [f"module {module_key}: {msg}"] if (
                    msg := spec.validate(raw.get(spec.name, ""))) else [])
        return errors

    def validate_all(self) -> list[str]:
        """Validate every ENABLED module in workflow order.

        Returns:
            Aggregated error list (disabled modules are skipped).
        """
        errors: list[str] = []
        for key in STAGE_KEYS:
            errors.extend(self.validate_module(key))
        return errors

    def missing_required_modules(self) -> list[str]:
        """Return titles of required-input modules that are disabled.

        The Design Input module feeds the file naming, so a disabled
        Design Input blocks publishing.

        Returns:
            List of stage titles.
        """
        blocked = []
        if not self._enabled.get("design_input"):
            blocked.append(STAGE_BY_KEY["design_input"].title)
        return blocked

    # -------------------------------------------------- persistence
    def to_dict(self) -> dict:
        """Serialize the full model state (enabled + retained params
        of ALL modules, including disabled ones).

        Returns:
            Plain dict for the JSON state store.
        """
        return {
            "plan_version": self._plan_version,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "imported": copy.deepcopy(self.imported),
            "modules": {
                key: {
                    "enabled": self._enabled[key],
                    "params": copy.deepcopy(self._params[key]),
                } for key in STAGE_KEYS
            },
        }

    def apply_state(self, state: dict) -> None:
        """Restore a previously persisted state.

        Args:
            state: Dict as produced by :meth:`to_dict`; tolerant of
                   missing entries (defaults stay).
        """
        if not isinstance(state, dict):
            return
        version = str(state.get("plan_version", "")).strip()
        if re.match(r"^\d+\.\d+\.\d+$", version):
            self._plan_version = version
        imported = state.get("imported") or {}
        if isinstance(imported, dict):
            self.imported = {
                "schematic": imported.get("schematic", {}),
                "netlist": imported.get(
                    "netlist",
                    {"file": "", "net_count": 0, "nets": {},
                     "missing_tp": []}),
                "tp_resolutions": imported.get("tp_resolutions", {}),
            }
        modules = state.get("modules") or {}
        for key in STAGE_KEYS:
            entry = modules.get(key) or {}
            self._enabled[key] = bool(entry.get("enabled", False))
            saved = entry.get("params") or {}
            params = self._params[key]
            for spec in MODULE_FIELDS.get(key, ()):
                if spec.name in saved:
                    params[spec.name] = saved[spec.name]
        self.changed = True
