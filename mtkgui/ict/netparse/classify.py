# -*- coding: utf-8 -*-
"""Net classification kernel (spec B1-01-01 item 1).

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

from .model import (NET_TYPE_CLOCK_SINGLE, NET_TYPE_DIFF_PAIR,
                    NET_TYPE_GND_REF, NET_TYPE_POWER, NET_TYPE_SIGNAL,
                    NetCollection, NetlistData, NetRecord)

_GND_RE = re.compile(
    r"^(GND|AGND|DGND|PGND)([_\W].*)?$", re.IGNORECASE)
_POWER_RE = re.compile(
    r"^(?!.+INTB)(?:"
    r"V(DD|CC|IN|OUT|PRE|SYS|BAT|BUS|AUX|CORE|IO|A|D|DDL|DQL)([0-9_].*)?"
    r"|[0-9]+([.][0-9]+)?V([0-9A-Z_]*)?"
    r"|P[35][V_][0-9A-Z_]*"
    r"|(DCDC|DC)_([0-9]+([.][0-9]+)?V)([0-9A-Z_]*)?"
    r"|[0-9A-Z_]*V(OUT|REF|SW|PWR|FB)[0-9A-Z_]*"
    r"|[0-9A-Z_]+_(1V0|1V2|1V5|1V8|2V5|3V3|5V|12V|24V)([0-9A-Z_]*)?"
    r")$", re.IGNORECASE)
_CLOCK_RE = re.compile(
    r"(CLK|XTAL|OSC|MCLK|SCKI|REFCLK)", re.IGNORECASE)
_PIN_TOKEN_RE = re.compile(r"^[\w\.\-\[\]/#]+$")


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
