# -*- coding: utf-8 -*-
"""Candidate power-tree derivation (spec B1-01-01 item 3).

DRAFT ONLY - the output carries topology facts (rail name, stage,
domain, source/children links) and marks every node
``draft_missing_param``; voltage / tolerance / jumper business
parameters are human-entered in the Power-Tree Editor (boundary
rule 4: no schematic source can supply them).

Stage model (spec):

* stage-0: top-level external input rail - ONLY the rails the headless
  parse flags ``input_rail`` (fuse / power-inlet / TVS / USB-PD input
  switch / FL input inductor evidence; M4 PART 3 replaces the old
  J-prefix connector heuristic that contradicted fix2);
* stage-1: PMIC pre-regulation output (VPRE);
* stage-2: Buck/DCDC first-stage output;
* stage-3: LDO / IO-analog domain second-stage output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from mtkgui.ict.netparse import NET_TYPE_POWER, NetCollection

from .components import CATEGORY_DCDC, CATEGORY_LDO, \
    CATEGORY_PMIC, ComponentLibrary

DRAFT_MISSING_PARAM_TOOLTIP = (
    "Draft topology: sync to the Power-Tree Editor and fill in "
    "voltage, tolerance and jumper information")

# input-pin names treated as regulator supply inputs
_VIN_PIN_RE = re.compile(r"^(VIN|IN|VCC|VDD)\d*$", re.IGNORECASE)
# output-pin names treated as regulated outputs
_OUT_PIN_RE = re.compile(r"^(OUT|VOUT|LX|SW|VO)\d*$", re.IGNORECASE)


@dataclass
class DraftNode:
    """One draft power-tree node (topology only).

    Attributes:
        rail_name:           Power net name.
        power_stage:         0..3 stage index (spec model).
        power_domain:        Guessed functional domain.
        sources:             Parent rail names (edges in).
        children:            Child rail names (edges out).
        draft_missing_param: Always True in drafts (spec: topology
                             only - business parameters come later).
        x / y:               Canvas coordinates (GUI-only payload).
    """

    rail_name: str
    power_stage: int = 0
    power_domain: str = "main"
    sources: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    draft_missing_param: bool = True
    x: float = 0.0
    y: float = 0.0
    #: M2 A2: rail served only by PDF-only RefDes (not auto-selected)
    pdf_only: bool = False
    #: M3/M4: netparse input-rail evidence (stage-0 source)
    input_rail: bool = False


@dataclass
class CandidatePowerTree:
    """Draft tree: nodes + edge list (spec output field set).

    Attributes:
        nodes:       DraftNode list (one per power net).
        edges:       (source rail, child rail) tuples.
        warnings:    Non-fatal derivation notes for the Event-Log.
    """

    nodes: list[DraftNode] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_name(self, rail: str) -> DraftNode | None:
        """Return the node for *rail* (None when absent)."""
        for node in self.nodes:
            if node.rail_name == rail:
                return node
        return None


def guess_domain(net_name: str) -> str:
    """Guess the functional domain from the rail name suffix."""
    lowered = net_name.lower()
    for key, domain in (("ddr", "ddr"), ("core", "core"),
                        ("io", "io"), ("_a", "analog"), ("avdd", "analog"),
                        ("avcc", "analog"), ("_d", "digital"),
                        ("dvdd", "digital"), ("usb", "usb"),
                        ("sd", "storage"), ("flash", "storage")):
        if key in lowered:
            return domain
    return "main"


def derive_candidate_tree(library: ComponentLibrary,
                          collection: NetCollection,
                          pdf_only: set[str] | None = None) \
        -> CandidatePowerTree:
    """Derive the draft power tree from regulators + the netlist.

    Args:
        library:    Component library (pmic/dcdc/ldo drive the flow;
                    DNP regulators never become draft nodes - M2 A1).
        collection: Classified net collection (netlist ground truth).
        pdf_only:   RefDes found only in the PDF schematic (M2 A2);
                    power nets served ONLY by such RefDes keep a
                    warning entry and are not auto-selected.

    Returns:
        :class:`CandidatePowerTree` - topology only, every node
        flagged ``draft_missing_param``; derivation warnings are
        collected for the Event-Log (never raised).
    """
    tree = CandidatePowerTree()
    # M2 A1: rails served ONLY by DNP regulators are skipped with ONE
    # warning each (a not-populated regulator cannot power a rail)
    dnp_out_rails: dict[str, str] = {}    # rail -> dnp refdes
    for rec in library.dnp_regulators():
        pins = collection.pins_of(rec.refdes)
        for pin, net in pins.items():
            if _OUT_PIN_RE.match(pin) and net not in dnp_out_rails:
                dnp_out_rails[net] = rec.refdes
    # per-component pin -> net view from the netlist
    pin_views = {rec.refdes: collection.pins_of(rec.refdes)
                 for rec in library.regulators()}
    # regulators grouped by category with their in/out nets
    stage_of_net: dict[str, int] = {}
    regulator_outputs: list[tuple[str, int, str]] = []  # (net, stage, refdes)
    for rec in library.regulators():
        pins = pin_views.get(rec.refdes, {})
        in_nets = [net for pin, net in pins.items()
                   if _VIN_PIN_RE.match(pin)]
        out_nets = [net for pin, net in pins.items()
                    if _OUT_PIN_RE.match(pin)]
        if not out_nets:
            tree.warnings.append(
                f"{rec.refdes} ({rec.dev_category}): no OUT pin found "
                "in the netlist - skipped from the draft tree")
            continue
        for net in out_nets:
            stage = _stage_for(rec.dev_category, in_nets, collection,
                               stage_of_net)
            stage_of_net[net] = stage
            regulator_outputs.append((net, stage, rec.refdes))
            dnp_out_rails.pop(net, None)
        # edges: input net -> each output net
        for in_net in in_nets:
            for out_net in out_nets:
                if in_net != out_net:
                    _add_edge(tree, in_net, out_net)
    # second pass: chain stages (a regulator fed by another regulator's
    # output sits one stage below its source)
    for net, stage, refdes in regulator_outputs:
        node = _ensure_node(tree, net)
        node.power_stage = max(node.power_stage, stage)
    # finalize: stage-0 follows the netparse input_rail evidence (M4
    # PART 3) - a plain connector pin is NOT input evidence (fix2)
    for rec in collection.nets:
        if rec.net_type != NET_TYPE_POWER:
            continue
        # M2 A1: DNP-only rails never become draft nodes
        if rec.name in dnp_out_rails:
            continue
        node = _ensure_node(tree, rec.name)
        if rec.input_rail:
            node.power_stage = 0
            node.input_rail = True
        node.power_domain = guess_domain(rec.name)
    # M2 A1: one warning per DNP-only rail (skipped, no node)
    for net, refdes in dnp_out_rails.items():
        served = any(out_net == net for out_net, _s, _r
                     in regulator_outputs)
        if not served:
            tree.warnings.append(
                f"rail {net} served by DNP part only (skipped)")
    # M2 A2: power nets whose members are ALL PDF-only RefDes keep a
    # warning and are NOT auto-selected as test candidates
    if pdf_only:
        for rec in collection.nets:
            if rec.net_type != NET_TYPE_POWER:
                continue
            refs = {_refdes_prefix(tok) + _refdes_num(tok)
                    for tok in rec.members}
            if refs and refs <= {r.upper() for r in pdf_only}:
                node = _ensure_node(tree, rec.name)
                node.pdf_only = True
                tree.warnings.append(
                    f"rail {rec.name}: PDF-only sources, not "
                    "auto-selected as a test candidate")
    # children bookkeeping from edges
    for src, child in tree.edges:
        src_node = _ensure_node(tree, src)
        child_node = _ensure_node(tree, child)
        if child not in src_node.children:
            src_node.children.append(child)
        if src not in child_node.sources:
            child_node.sources.append(src)
    # rails fed only by another rail inherit the parent stage + 1
    _propagate_stages(tree)
    # M4 PART 3: input rails render FIRST (netparse rank order), then
    # the remaining rails in discovery order
    rank_of = {rec.name: (rec.priority or {}).get("rank", 0)
               for rec in collection.nets}
    tree.nodes.sort(key=lambda node: (
        0 if node.input_rail else 1, rank_of.get(node.rail_name, 0)))
    return tree


def _refdes_num(pin_token: str) -> str:
    """RefDes number part of a member token (``U12.3`` -> ``12``)."""
    match = re.match(r"^[A-Z]+(\d+)", pin_token, re.IGNORECASE)
    return match.group(1) if match else pin_token


def _refdes_prefix(pin_token: str) -> str:
    """RefDes letter prefix of a member token (``J2.3`` -> ``J``)."""
    match = re.match(r"^([A-Z]+)", pin_token)
    return match.group(1) if match else ""


def _stage_for(category: str, in_nets: list[str],
               collection: NetCollection,
               stage_of_net: dict[str, int]) -> int:
    """Stage of a regulator output (spec stage model)."""
    if category == CATEGORY_PMIC:
        return 1                                   # VPRE pre-rail
    if category == CATEGORY_LDO:
        return 3                                   # second-stage LDO
    # DCDC: first stage (2) unless fed by another regulator output
    for net in in_nets:
        if net in stage_of_net:
            return min(3, stage_of_net[net] + 1)
    return 2


def _add_edge(tree: CandidatePowerTree, src: str, child: str) -> None:
    """Register an edge (deduplicated)."""
    if (src, child) not in tree.edges:
        tree.edges.append((src, child))


def _ensure_node(tree: CandidatePowerTree, rail: str) -> DraftNode:
    """Get-or-create a draft node ("" rails are ignored upstream)."""
    node = tree.by_name(rail)
    if node is None:
        node = DraftNode(rail_name=rail)
        tree.nodes.append(node)
    return node


def _propagate_stages(tree: CandidatePowerTree) -> None:
    """Rails fed only by rails get max(parent stage) + 1 (capped at 3)."""
    for _ in range(4):                       # depth-bounded relaxation
        changed = False
        for node in tree.nodes:
            if node.sources and node.power_stage == 0 \
                    and not node.input_rail and not _is_external(node):
                parent_stage = max(
                    (tree.by_name(s).power_stage
                     for s in node.sources
                     if tree.by_name(s) is not None),
                    default=-1)
                if parent_stage >= 0:
                    new_stage = min(3, parent_stage + 1)
                    if new_stage > node.power_stage:
                        node.power_stage = new_stage
                        changed = True
        if not changed:
            break


def _is_external(node: DraftNode) -> bool:
    """True for connector-fed stage-0 input sources."""
    return node.power_stage == 0 and bool(node.children) \
        and not node.sources
