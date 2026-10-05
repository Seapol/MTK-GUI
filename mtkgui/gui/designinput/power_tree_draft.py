# -*- coding: utf-8 -*-
"""Candidate power-tree derivation (spec B1-01-01 item 3).

DRAFT ONLY - the output carries topology facts (rail name, stage,
domain, source/children links) and marks every node
``draft_missing_param``; voltage / tolerance / jumper business
parameters are human-entered in the Power-Tree Editor (boundary
rule 4: no schematic source can supply them).

Stage model (spec):

* stage-0: top-level external input (connector-fed net);
* stage-1: PMIC pre-regulation output (VPRE);
* stage-2: Buck/DCDC first-stage output;
* stage-3: LDO / IO-analog domain second-stage output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .components import CATEGORY_DCDC, CATEGORY_LDO, \
    CATEGORY_PMIC, ComponentLibrary
from .netlist import NetCollection, NET_TYPE_POWER

DRAFT_MISSING_PARAM_TOOLTIP = (
    "草稿拓扑，需要同步至Power-Tree Editor填写电压、容差、跳线信息")

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
                          collection: NetCollection) -> CandidatePowerTree:
    """Derive the draft power tree from regulators + the netlist.

    Args:
        library:    Component library (pmic/dcdc/ldo drive the flow).
        collection: Classified net collection (netlist ground truth).

    Returns:
        :class:`CandidatePowerTree` - topology only, every node
        flagged ``draft_missing_param``; derivation warnings are
        collected for the Event-Log (never raised).
    """
    tree = CandidatePowerTree()
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
    # finalize: stage-0 for external/connector-fed power nets
    for rec in collection.nets:
        if rec.net_type != NET_TYPE_POWER:
            continue
        node = _ensure_node(tree, rec.name)
        if rec.name not in stage_of_net:
            fed_by_connector = any(
                _refdes_prefix(tok) == "J" for tok in rec.members)
            if fed_by_connector:
                node.power_stage = 0
        node.power_domain = guess_domain(rec.name)
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
    return tree


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
                    and not _is_external(node):
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
