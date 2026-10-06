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
from mtkgui.gui.yamlbuild.stages import LEGACY_MODULE_MAP, \
    LEGACY_ORDER_SWAP, \
    STAGE_BY_KEY, STAGE_KEYS

_STAGE_INDEX = {key: i for i, key in enumerate(STAGE_KEYS)}


def _migrate_legacy_modules(modules: dict) -> dict:
    """Migrate pre-M0 module entries into the twelve-stage list.

    Legacy ``power_dut`` (absorbed into rails by the M0 redefinition)
    hands its parameters to its successor; the successor entry stays
    FLAT (parameters at top level, the shape apply_yaml_dict
    consumes).  Item 23: projects saved with the pre-item-23 order
    (Configure Instruments before Parse nets) are swapped onto the
    canonical sequence so old files keep loading cleanly.  Returns a
    new dict; the input is untouched.

    Args:
        modules: Raw ``modules`` mapping from an incoming YAML doc.

    Returns:
        Migrated modules mapping.
    """
    out = dict(modules)
    for legacy_key, target in LEGACY_MODULE_MAP.items():
        legacy = out.pop(legacy_key, None)
        if not isinstance(legacy, dict):
            continue
        merged = dict(out.get(target) or {})
        merged.update({
            k: v for k, v in legacy.items()
            if k not in ("enabled", "stage_index", "group")})
        if target not in out:
            merged["enabled"] = bool(legacy.get("enabled", True))
        out[target] = merged
    # item 23 legacy order: files saved before the 02/03 swap carry
    # instruments BEFORE parse_ict - normalize that exact pair onto
    # the canonical sequence (any other order deviation still fails
    # the sequence check)
    first, second = LEGACY_ORDER_SWAP
    keys = list(out)
    if first in keys and second in keys \
            and keys.index(first) < keys.index(second):
        # swap the mapping POSITIONS (a plain value swap would keep
        # the old insertion order and still fail the sequence check)
        i, j = keys.index(first), keys.index(second)
        keys[i], keys[j] = keys[j], keys[i]
        out = {k: out[k] for k in keys}
    return out


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
        # imported design data (T7/T8): the NET file raw bytes loaded
        # by the Design Input panel (load only there) plus the formal
        # Parse Nets result - the single data source for the Channel
        # Allocation tables.
        self.imported: dict = {
            "net": {"file": "", "raw": ""},
            "testable_nets": {},   # name -> {category, members}
        }
        # T10 Channel Allocation configuration (three tables, the
        # parse-result data source; see channel_allocation.py)
        self.channel_allocation: dict = {}
        # item 24: net classification rules + power tree draft +
        # SE clock / GPIO channel allocations (GUI + YAML data model)
        self.net_classification_rules: dict = {}
        self.power_tree: dict = {}
        self.se_clock_allocation: list = []
        self.gpio_allocation: list = []
        # test path complexity risk (topology-based, advisory):
        # {"thresholds": {...}, "scores": {net: {...}}}
        self.path_risk: dict = {}
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

    def set_channel_allocation(self, data: dict) -> None:
        """Store the Channel Allocation table configuration (T10)."""
        if isinstance(data, dict):
            self.channel_allocation = data
            self.changed = True

    def get_channel_allocation(self) -> dict:
        """Return the stored Channel Allocation configuration."""
        return dict(self.channel_allocation or {})

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
        # T7/T8 design data: NET file reference + the formal Parse
        # Nets result (the Channel Allocation data source)
        net = self.imported.get("net") or {}
        if self.imported.get("testable_nets") or net.get("file"):
            section["design_data"] = {
                "net_file": net.get("file", ""),
                "testable_nets": dict(
                    self.imported.get("testable_nets", {})),
            }
        # T10 Channel Allocation configuration (project YAML)
        if self.channel_allocation:
            section["channel_allocation"] = self.channel_allocation
        # item 24 sections (rules / power tree / allocations)
        if self.net_classification_rules:
            section["net_classification_rules"] = \
                self.net_classification_rules
        if self.power_tree:
            section["power_tree"] = self.power_tree
        if self.se_clock_allocation:
            section["se_clock_allocation"] = self.se_clock_allocation
        if self.gpio_allocation:
            section["gpio_allocation"] = self.gpio_allocation
        if self.path_risk:
            section["path_risk"] = self.path_risk
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
        # legacy (pre-M0) YAML migration FIRST, so the sequence check
        # below sees the migrated successor instead of the absorbed key
        modules = _migrate_legacy_modules(modules)
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
        # T7/T8 design data restore (net file + parse result)
        design = section.get("design_data") or {}
        if isinstance(design, dict):
            net = self.imported.setdefault("net", {"file": "", "raw": ""})
            if design.get("net_file") is not None:
                net["file"] = str(design.get("net_file") or "")
            if isinstance(design.get("testable_nets"), dict):
                self.imported["testable_nets"] = dict(
                    design["testable_nets"])
        # T10 Channel Allocation restore (empty / legacy: no section
        # loads blank without error)
        alloc = section.get("channel_allocation")
        if isinstance(alloc, dict):
            self.channel_allocation = alloc
        # item 24 sections restore (empty / legacy: blank, no error)
        rules = section.get("net_classification_rules")
        if isinstance(rules, dict):
            self.net_classification_rules = rules
        tree = section.get("power_tree")
        if isinstance(tree, dict):
            self.power_tree = tree
        se_clock = section.get("se_clock_allocation")
        if isinstance(se_clock, list):
            self.se_clock_allocation = se_clock
        gpio = section.get("gpio_allocation")
        if isinstance(gpio, list):
            self.gpio_allocation = gpio
        risk = section.get("path_risk")
        if isinstance(risk, dict):
            self.path_risk = risk
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
            "channel_allocation": copy.deepcopy(self.channel_allocation),
            "net_classification_rules":
                copy.deepcopy(self.net_classification_rules),
            "power_tree": copy.deepcopy(self.power_tree),
            "se_clock_allocation":
                copy.deepcopy(self.se_clock_allocation),
            "gpio_allocation": copy.deepcopy(self.gpio_allocation),
            "path_risk": copy.deepcopy(self.path_risk),
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
            net = imported.get("net")
            self.imported = {
                "net": dict(net) if isinstance(net, dict)
                else {"file": "", "raw": ""},
                "testable_nets": imported.get("testable_nets", {})
                if isinstance(imported.get("testable_nets"), dict)
                else {},
            }
        # T10 Channel Allocation (legacy states: key absent -> blank)
        alloc = state.get("channel_allocation")
        self.channel_allocation = alloc if isinstance(alloc, dict) else {}
        # item 24 sections (legacy states: key absent -> blank)
        for key, default in (("net_classification_rules", {}),
                             ("power_tree", {}),
                             ("se_clock_allocation", []),
                             ("gpio_allocation", []),
                             ("path_risk", {})):
            value = state.get(key)
            if isinstance(value, type(default)):
                setattr(self, key, value)
        modules = state.get("modules") or {}
        # legacy (pre-M0) migration: the absorbed power_dut block
        # hands its retained parameters to the rails block (04)
        legacy = modules.get("power_dut")
        if isinstance(legacy, dict) and "rails" not in modules:
            modules = dict(modules)
            modules["rails"] = {
                "enabled": legacy.get("enabled", True),
                "params": dict(legacy.get("params") or {}),
            }
        for key in STAGE_KEYS:
            entry = modules.get(key) or {}
            # absent entries = keys born AFTER the state was saved
            # (new workflow blocks): they start ENABLED per rule 3.2
            self._enabled[key] = bool(entry.get("enabled", True))
            saved = entry.get("params") or {}
            params = self._params[key]
            for spec in MODULE_FIELDS.get(key, ()):
                if spec.name in saved:
                    params[spec.name] = saved[spec.name]
        self.changed = True
