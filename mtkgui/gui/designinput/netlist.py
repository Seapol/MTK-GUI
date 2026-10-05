# -*- coding: utf-8 -*-
"""Netlist parsing and net classification (spec B1-01-01 item 1).

net_collection is derived 100% from the external Allegro ``.net``
file - a PDF schematic never degrades it (boundary rule 7).

Classification rules (applied in this order):

1. ``gnd_ref``     - GND / AGND / DGND / PGND reference grounds; they
   participate in the measurement loop and are NEVER auto-skipped
   (boundary rule 5);
2. ``diff_pair``   - ``*_P`` / ``*_N`` siblings, excluded from the
   single-ended clock set;
3. ``power``       - supply nets (VDD / VCC / nVn rails / VPRE ...);
4. ``clock_single``- single-ended clock nets (CLK / XTAL ...);
5. ``signal``      - everything else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from mtkgui.gui.yamlbuild.parser import NetlistData, parse_netlist, \
    read_text_any_encoding

NET_TYPE_GND_REF = "gnd_ref"
NET_TYPE_DIFF_PAIR = "diff_pair"
NET_TYPE_POWER = "power"
NET_TYPE_CLOCK_SINGLE = "clock_single"
NET_TYPE_SIGNAL = "signal"

NET_TYPES = (NET_TYPE_GND_REF, NET_TYPE_DIFF_PAIR, NET_TYPE_POWER,
             NET_TYPE_CLOCK_SINGLE, NET_TYPE_SIGNAL)

_GND_RE = re.compile(
    r"^(GND|AGND|DGND|PGND)([_\W].*)?$", re.IGNORECASE)
_POWER_RE = re.compile(
    r"^(V(DD|CC|IN|OUT|PRE|SYS|BAT|BUS|AUX|CORE|IO|A|D|DDL|DQL)"
    r"([0-9_].*)?|[0-9]+([.][0-9]+)?V([0-9A-Z_]*)?|P[35][V_][0-9A-Z_]*)$",
    re.IGNORECASE)
_CLOCK_RE = re.compile(
    r"(CLK|XTAL|OSC|MCLK|SCKI|REFCLK)", re.IGNORECASE)
_PIN_TOKEN_RE = re.compile(r"^[\w\.\-\[\]/#]+$")


@dataclass
class NetRecord:
    """One classified net (draft state, pre test-point selection).

    Attributes:
        name:     Net name.
        members:  Member pin tokens (``U1.5``, ``J2.3``, ``TP4`` ...).
        net_type: One of :data:`NET_TYPES`.
    """

    name: str
    members: list[str]
    net_type: str = NET_TYPE_SIGNAL


@dataclass
class NetCollection:
    """Classified net collection (draft).

    Attributes:
        nets:            NetRecord list in netlist order.
        diff_pairs:      ``(_P name, _N name)`` sibling tuples.
        unclassified:    Names kept as ``signal`` (no WARNING case).
    """

    nets: list[NetRecord] = field(default_factory=list)
    diff_pairs: list[tuple[str, str]] = field(default_factory=list)

    def by_name(self, name: str) -> NetRecord | None:
        """Return the record for *name* (None when absent)."""
        for rec in self.nets:
            if rec.name == name:
                return rec
        return None

    def pins_of(self, refdes: str) -> dict[str, str]:
        """pin -> net mapping for one component (netlist ground truth).

        Used by the power-tree drafter and the Device Library Editor
        pin-net view.
        """
        pins: dict[str, str] = {}
        prefix = refdes + "."
        for rec in self.nets:
            for token in rec.members:
                if token.startswith(prefix):
                    pins[token[len(prefix):]] = rec.name
        return pins


def classify_nets(netlist: NetlistData) -> NetCollection:
    """Classify every netlist net into the fixed type set.

    Args:
        netlist: Parsed Allegro netlist (see ``parse_netlist``).

    Returns:
        :class:`NetCollection` with ``gnd_ref`` / ``diff_pair`` /
        ``power`` / ``clock_single`` / ``signal`` records.
    """
    names = list(netlist.nets)
    pair_map = _diff_pair_map(names)
    collection = NetCollection()
    for name in names:
        members = [t for t in netlist.nets[name] if _PIN_TOKEN_RE.match(t)]
        if _GND_RE.match(name):
            net_type = NET_TYPE_GND_REF
        elif name in pair_map:
            net_type = NET_TYPE_DIFF_PAIR
        elif _POWER_RE.match(name):
            net_type = NET_TYPE_POWER
        elif _CLOCK_RE.search(name):
            net_type = NET_TYPE_CLOCK_SINGLE
        else:
            net_type = NET_TYPE_SIGNAL
        collection.nets.append(
            NetRecord(name=name, members=members, net_type=net_type))
    collection.diff_pairs = _pair_tuples(pair_map)
    return collection


def parse_netlist_file(path: str) -> tuple[NetlistData, str]:
    """Read + parse a netlist file (tolerant decode chain).

    Args:
        path: Netlist file path (``.net`` / ``.net.txt``).

    Returns:
        (NetlistData, raw_text) - the raw text stays available for
        audit / re-parse without touching the file again.
    """
    text = read_text_any_encoding(path)
    return parse_netlist(text), text


def _diff_pair_map(names: list[str]) -> dict[str, str]:
    """Map ``*_P`` <-> ``*_N`` sibling names (only when BOTH exist)."""
    name_set = set(names)
    pairs: dict[str, str] = {}
    for name in names:
        if name.endswith(("_P", "_N")):
            base = name[:-2]
            sibling = f"{base}_N" if name.endswith("_P") else f"{base}_P"
            if sibling in name_set:
                pairs[name] = sibling
    return pairs


def _pair_tuples(pairs: dict[str, str]) -> list[tuple[str, str]]:
    """Ordered (positive, negative) tuples, each pair listed once."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pos, neg in pairs.items():
        if pos.endswith("_P") and neg not in seen:
            out.append((pos, neg))
            seen.add(pos)
    return out
