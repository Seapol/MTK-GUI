# -*- coding: utf-8 -*-
"""Passive-bridge power rail merge (M2 B0, headless - no Qt).

Two POWER nets joined through a low-impedance passive device (0-ohm
resistor, ferrite bead, power inductor, solder jumper / jumper) are
electrically ONE rail segment: the merge keeps ONE representative net
in the power class and moves the others to ``Others`` with
``sub_class = "bridge_duplicate"``.

Library mode only (the bridge values come from the BOM-derived
library ``{refdes: {part_number, value}}``); without a library the
M1 behaviour is unchanged.

Representative rules (owner order 2026-10-22):
  1. TP test-point member wins (physical probe point);
  2. EXCEPT for a switching-converter inductor bridge: the switch
     node (square wave, not DC-measurable) is NEVER chosen even with
     a TP - the DC output side wins;
  3. higher confidence, 4. earlier power-tree stage, 5. higher
  nominal voltage, 6. stable input order.
"""
from __future__ import annotations

import re

from .model import SubClass, ParseNetsResult

#: bridge device refdes prefixes: R*, C*, L*, FB*/B*, SJ*/J*/JP*
_BRIDGE_REFDES_RE = re.compile(r"^(FB|SJ|JP|[RCLB])\d+$", re.IGNORECASE)
#: switching-node net names: never DC-representative
_SWITCH_NODE_RE = re.compile(
    r"(^|_)(SW|LX|PHASE|SWN|SWITCH|HS|LS|BOOT|BST)([0-9A-Z_]*)?$",
    re.IGNORECASE)
#: low-impedance resistor values: 0 / 0R / 0OHM / 0 ohm / 0.00
_ZERO_OHM_RE = re.compile(r"^0(\.0+)?\s*(R|OHM?|\u03a9)?$", re.IGNORECASE)
#: warning budget for the unknown-value assumption (A4 semantics)
WARNING_BUDGET = 50


def _refdes_of(token: str) -> str:
    return token.split(".", 1)[0] if "." in token else token


def _is_bridge_refdes(refdes: str) -> bool:
    return bool(_BRIDGE_REFDES_RE.match(refdes))


def _bridge_kind(refdes: str) -> str:
    head = re.match(r"^(FB|SJ|JP|[RCLB])", refdes, re.IGNORECASE)
    return head.group(1).upper() if head else ""


def _low_impedance(refdes: str, entry) -> bool | None:
    """Bridge decision from the BOM value.

    Returns True (bridge) / False (not a DC bridge) / None (value
    unknown - caller applies the assume-low-impedance rule).
    """
    kind = _bridge_kind(refdes)
    if kind in ("SJ", "JP", "J"):
        return True
    if kind == "FB":
        return True
    if kind == "L":
        return True
    if kind == "C":
        # a capacitor is NOT a DC connection (coupling / decoupling)
        return False
    value = ""
    if isinstance(entry, dict):
        value = str(entry.get("value") or "")
    if not value:
        return None
    return bool(_ZERO_OHM_RE.match(value.strip()))


class _Union:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def merge_power_bridges(result: ParseNetsResult, library: dict) -> dict:
    """Merge power nets joined by low-impedance passive bridges.

    Mutates *result*: non-representative members of a rail component
    leave the power bucket for ``Others`` / ``bridge_duplicate``.
    Returns the bridge report ``{representative: [bridged nets]}``.
    """
    if not library or len(result.power) < 2:
        return {}
    order = {rec.name: i for i, rec in enumerate(result.power)}
    members_of: dict[str, dict[str, list[str]]] = {}
    for rec in result.power:
        for token in rec.members:
            refdes = _refdes_of(token)
            if _is_bridge_refdes(refdes):
                members_of.setdefault(refdes, {}).setdefault(
                    rec.name, []).append(token)
    warned: set[str] = set()
    uf = _Union()
    for refdes, nets in members_of.items():
        names = sorted(nets, key=order.get)
        if len(names) < 2:
            continue
        decision = _low_impedance(refdes, library.get(refdes))
        if decision is None:
            if refdes not in warned and len(result.warnings) \
                    < WARNING_BUDGET:
                result.warnings.append(
                    f"bridge value unknown, assumed low-impedance: "
                    f"{refdes}")
                warned.add(refdes)
            decision = True
        if not decision:
            continue
        first = names[0]
        for other in names[1:]:
            uf.union(first, other)

    groups: dict[str, list] = {}
    for rec in result.power:
        groups.setdefault(uf.find(rec.name), []).append(rec)

    report: dict[str, list[str]] = {}
    keep: list = []
    moved: list = []
    for root, recs in groups.items():
        if len(recs) < 2:
            keep.extend(recs)
            continue
        names_in = {r.name for r in recs}
        refdeses = sorted(
            refdes for refdes, nets in members_of.items()
            if len(names_in & set(nets)) >= 2)
        rep = _representative(recs, order)
        keep.append(rep)
        report[rep.name] = [r.name for r in recs if r is not rep]
        for rec in recs:
            if rec is rep:
                continue
            rec.sub_class = SubClass.BRIDGE_DUPLICATE
            rec.provenance = (f"bridge_duplicate:"
                              f"{'+'.join(refdeses)}->{rep.name}")
            moved.append(rec)
    keep.sort(key=lambda rec: order[rec.name])
    result.power[:] = keep
    result.others.extend(moved)
    return report


def _representative(recs: list, order: dict[str, int]):
    """Owner rule order: switch-node exclusion > TP > confidence >
    stage > voltage > input order."""
    def has_tp(rec) -> bool:
        return any(t.upper().startswith("TP") for t in rec.members)

    def is_switch(rec) -> bool:
        return bool(_SWITCH_NODE_RE.search(rec.name))

    def sort_key(rec):
        from .confidence import _CONF_RANK
        conf = _CONF_RANK.get(rec.confidence or "medium", 1)
        stage = rec.priority.get("stage", 2) if rec.priority else 2
        from .priority import nominal_volts_of
        return (0 if (has_tp(rec) and not is_switch(rec)) else 1,
                0 if not is_switch(rec) else 1,
                conf, stage, -nominal_volts_of(rec.name),
                order[rec.name])

    return sorted(recs, key=sort_key)[0]
