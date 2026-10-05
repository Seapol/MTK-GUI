# -*- coding: utf-8 -*-
"""Design-Input data model: draft/committed isolation + commit gate
(spec B1-01-05 + NFR 3/4).

Two states, hard separated:

* ``draft``     - everything the parsers produce; downstream modules
  stay disabled, official export is refused;
* ``committed`` - only reachable through :meth:`DesignDataModel.commit`
  after the three blocking validations pass; freezes the official
  ``design_data`` and permanently records ``schematic_source_type``.

Nothing outside this module decides the commit gate - the GUI calls
:meth:`commit` and renders the returned errors / warnings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .components import CATEGORY_OTHER, ComponentLibrary
from .netlist import NET_TYPE_GND_REF, NET_TYPE_POWER, NetCollection
from .power_tree_draft import CandidatePowerTree
from .sources import SOURCE_NATIVE_TEXT_SPF, SOURCE_SMART_PDF_SPF

STATE_DRAFT = "draft"
STATE_COMMITTED = "committed"

SOURCE_TYPES = (SOURCE_NATIVE_TEXT_SPF, SOURCE_SMART_PDF_SPF)

# dut_board_type enum (spec B1-01-01 item 5)
BOARD_FULL_SYSTEM = "FULL_SYSTEM_BOARD"
BOARD_MAIN_CONTROLLER = "MAIN_CONTROLLER_BOARD"
BOARD_NO_MCU_SUB = "NO_MCU_INTERFACE_SUB_BOARD"
BOARD_DAUGHTER_CARD = "DAUGHTER_MODULE_CARD"
BOARD_TYPES = (BOARD_FULL_SYSTEM, BOARD_MAIN_CONTROLLER,
               BOARD_NO_MCU_SUB, BOARD_DAUGHTER_CARD)

# spec-fixed commit audit line prefix
COMMIT_LOG_PREFIX = "INFO: User performed Final Review & Commit Design-Input"

# spec-fixed Smart-PDF commit warning
SMART_PDF_COMMIT_WARNING = (
    "WARNING: Schematic source is Smart-PDF, please double-check "
    "component library and power-tree source-children links.")


@dataclass
class DesignDataModel:
    """The design_data container with the draft/committed gate.

    Attributes:
        project_info:   project_name / core_id / main_chips /
                        dut_board_type / dut_powerup_procedure_text.
        component_library:    Parsed device library.
        net_collection:       Classified nets (+ test points).
        candidate_power_tree: Draft topology (None before parsing).
        power_tree:     FORMAL tree dict ({"input_sources": [...],
                        "rails": [...]}) - empty until the user
                        accepts it in the Power-Tree Editor.
        source_type:    ``native_text_spf`` / ``smart_pdf_spf``.
        state:          ``draft`` / ``committed``.
        committed_at:   ISO timestamp of the commit (None = draft).
    """

    project_info: dict = field(default_factory=dict)
    component_library: ComponentLibrary = field(
        default_factory=ComponentLibrary)
    net_collection: NetCollection = field(default_factory=NetCollection)
    candidate_power_tree: CandidatePowerTree | None = None
    power_tree: dict | None = None
    source_type: str = SOURCE_NATIVE_TEXT_SPF
    state: str = STATE_DRAFT
    committed_at: str | None = None

    # ------------------------------------------------------------- state
    @property
    def is_committed(self) -> bool:
        """True once Final Review & Commit succeeded."""
        return self.state == STATE_COMMITTED

    def set_main_chips(self, chips: list[str]) -> None:
        """Store the (user-editable) main-chip list."""
        self.project_info["main_chips"] = list(chips)

    def infer_board_type(self) -> str:
        """Auto-infer the DUT board type from the main-chip list."""
        if self.project_info.get("main_chips"):
            return BOARD_FULL_SYSTEM
        return BOARD_NO_MCU_SUB

    # ------------------------------------------------------- commit gate
    def validate_commit(self) -> tuple[list[str], list[str]]:
        """Run the Final-Review checklist WITHOUT committing.

        Returns:
            (errors, warnings) - any error blocks the commit; warnings
            are logged only (spec B1-01-05).
        """
        errors: list[str] = []
        warnings: list[str] = []

        # blocking 1: project name
        if not (self.project_info.get("project_name") or "").strip():
            errors.append("project_name is empty")

        # blocking 2: formal power tree complete and valid
        tree = self.power_tree or {}
        rails = tree.get("rails") or []
        if not rails:
            errors.append("formal power_tree is empty (Accept & Save "
                          "Power-Tree first)")
        else:
            errors.extend(validate_power_tree(tree))
        # blocking 3: at least one bound reference ground
        if not self.reference_grounds():
            errors.append("no net is marked as reference GND "
                          "(is_reference_gnd)")

        # non-blocking warnings
        if not (self.project_info.get("core_id") or "").strip():
            warnings.append("core_id is empty (non-blocking)")
        others = [r.refdes for r in self.component_library.records
                  if r.dev_category == CATEGORY_OTHER]
        if others:
            warnings.append(
                f"{len(others)} device(s) still unclassified as "
                f"'{CATEGORY_OTHER}': {', '.join(others[:8])}")
        if self.has_alternative_testpoints():
            warnings.append(
                "alternative test points present - review probe "
                "accessibility")
        if self.source_type == SOURCE_SMART_PDF_SPF:
            warnings.append(SMART_PDF_COMMIT_WARNING)
        return errors, warnings

    def commit(self) -> tuple[list[str], list[str]]:
        """Final Review & Commit Design-Input.

        Returns:
            (errors, warnings).  With any error the state stays
            ``draft`` (blocked).  On success the state flips to
            ``committed`` and ``committed_at`` is stamped - the caller
            then logs :attr:`audit_line` into the Event-Log.
        """
        errors, warnings = self.validate_commit()
        if errors:
            return errors, warnings
        self.state = STATE_COMMITTED
        self.committed_at = datetime.now().isoformat(timespec="seconds")
        return [], warnings

    @property
    def audit_line(self) -> str:
        """Spec-fixed audit line for the Event-Log (post commit)."""
        return (f"{COMMIT_LOG_PREFIX} at {self.committed_at}, "
                f"schematic_source_type={self.source_type}")

    # ------------------------------------------------------------- views
    def reference_grounds(self) -> list[str]:
        """Nets flagged as reference ground AND having a probe."""
        return [rec.name for rec in self.net_collection.nets
                if rec.net_type == NET_TYPE_GND_REF
                and rec.is_reference_gnd]

    def has_alternative_testpoints(self) -> bool:
        """True when any auto-substituted test point exists."""
        return any(rec.is_alternative_testpoint
                   for rec in self.net_collection.nets)

    def core_id_suggestion(self) -> str:
        """``+``-joined main_mcu part numbers (core_id auto fill)."""
        parts = [rec.part_number for rec
                 in self.component_library.mains() if rec.part_number]
        return "+".join(parts)

    # -------------------------------------------------------------- bind
    def bind_power_tree_to_nets(self) -> int:
        """Bind formal rail parameters back onto power nets.

        Spec B1-01-03 item 8: after the power tree is saved, copy
        ``nominal`` / ``tolerance_pct`` / ``jumper_controlled`` onto
        the matching power nets of net_collection.

        Returns:
            Number of nets bound.
        """
        rails = (self.power_tree or {}).get("rails") or []
        by_name = {r.get("rail_name"): r for r in rails
                   if r.get("rail_name")}
        bound = 0
        for rec in self.net_collection.nets:
            rail = by_name.get(rec.name)
            if rail is None or rec.net_type != NET_TYPE_POWER:
                continue
            rec.nominal = rail.get("nominal") or None
            rec.tolerance_pct = rail.get("tolerance_pct") or None
            rec.jumper_controlled = bool(rail.get("jumper_controlled"))
            bound += 1
        return bound

    # -------------------------------------------------------------- yaml
    def to_dict(self, official: bool) -> dict:
        """Serialize to a YAML-ready payload.

        Args:
            official: True = committed engineering data; False =
                      candidate draft (debug export).

        Returns:
            Payload dict; ``official=True`` requires the committed
            state (raises otherwise - draft data must never leak).
        """
        if official and not self.is_committed:
            raise PermissionError(
                "official export requires Final Review & Commit")
        prefix = "design_data" if official else "candidate_design_data"
        return {
            "meta": {
                "kind": prefix,
                "schematic_source_type": self.source_type,
                "state": self.state,
                "committed_at": self.committed_at,
            },
            "project_info": dict(self.project_info),
            "component_library": [
                {"refdes": r.refdes, "part_number": r.part_number,
                 "dev_category": r.dev_category, "note": r.note}
                for r in self.component_library.records],
            "net_collection": [
                {"net_name": r.name, "net_type": r.net_type,
                 "members": list(r.members)}
                for r in self.net_collection.nets],
            "power_tree": self.power_tree if official else None,
        }


def _blank(value) -> bool:
    """True for None / "" / whitespace-only values."""
    if isinstance(value, str):
        return not value.strip()
    return value in (None, "")


def validate_power_tree(tree: dict) -> list[str]:
    """Structural power-tree validation (spec B1-01-03 item 4).

    Checks: circular dependencies, unknown source references and
    ``jumper_controlled`` rails without ``alt_nominal``.

    Args:
        tree: ``{"input_sources": [...], "rails": [...]}`` dict.

    Returns:
        ERROR lines (empty = valid).
    """
    errors: list[str] = []
    rails = tree.get("rails") or []
    names = [r.get("rail_name") for r in rails]
    parent: dict[str, str] = {}
    for rail in rails:
        name = rail.get("rail_name") or ""
        if _blank(rail.get("nominal")):
            errors.append(f"rail '{name}': nominal is empty")
        if _blank(rail.get("tolerance_pct")):
            errors.append(f"rail '{name}': tolerance_pct is empty")
        if rail.get("jumper_controlled") \
                and _blank(rail.get("alt_nominal")):
            errors.append(
                f"rail '{name}': jumper_controlled requires alt_nominal")
        src = rail.get("source")
        if src and src not in names:
            errors.append(
                f"rail '{name}': source '{src}' does not exist")
        if src:
            parent[name] = src
    # circular dependency walk (source chains)
    for start in parent:
        seen = {start}
        cur = parent[start]
        while cur in parent:
            if cur in seen:
                errors.append(
                    f"circular power dependency involving '{cur}'")
                break
            seen.add(cur)
            cur = parent[cur]
    return errors
