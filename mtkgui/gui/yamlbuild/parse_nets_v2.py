# -*- coding: utf-8 -*-
"""v2 node 02 Parse nets — headless model and collapse (Qt-free).

The v2 parse-nets node collapses every net to exactly four classes
**Power / SE Clock / GND / Other** and shows one shared column schema
``Net Name · Category · Sub-type · Test Point · Nominal · Limits ·
Confidence`` across two tables (Parsed Nets = Power/SE Clock/GND,
Other Nets = Other).

Route A (SPF + NET + BoM) collapses a :class:`ParseNetsResult`; Route B
(ICT Excel) collapses a :class:`RouteBResult` from
:mod:`mtkgui.ict.netparse.route_b`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mtkgui.ict.netparse import ParseNetsResult
from mtkgui.ict.netparse.model import (CATEGORY_GND, CATEGORY_OTHER,
                                       CATEGORY_POWER,
                                       CATEGORY_SE_CLOCK, NET_TYPE_DIFF_PAIR,
                                       NET_TYPE_GND_REF, NET_TYPE_POWER,
                                       NET_TYPE_SIGNAL)
from mtkgui.ict.netparse.route_b import RouteBResult

NA = "NA"

#: the four collapsed categories, in table order
V2_CATEGORIES = (CATEGORY_POWER, CATEGORY_SE_CLOCK, CATEGORY_GND,
                 CATEGORY_OTHER)

#: columns shared by both tables (§3.2)
V2_COLUMNS = ("Net Name", "Category", "Sub-type", "Test Point",
              "Nominal", "Limits", "Confidence")

ROUTE_A = "files"
ROUTE_B = "excel"


@dataclass
class V2NetRow:
    """One collapsed net row (single column schema, both routes)."""

    name: str
    category: str          # Power / SE Clock / GND / Other
    sub_type: str          # route A: net_type / sub_class; B: block
    test_point: str = NA
    nominal: str = NA
    limits: str = NA
    confidence: str = NA
    route: str = ROUTE_A


@dataclass
class V2ParseState:
    """The collapsed parse result backing the node 02 panel.

    Attributes:
        rows:       Every net in collapsed order (Power / SE Clock /
                    GND / Other).
        route:      ``files`` (A) or ``excel`` (B).
        gate_ok:    Route A: always True (the netlist has no impedance/
                    voltage split to contradict); Route B: the
                    impedance/voltage power-set consistency gate.
        gate_error: Named mismatch description ("" when OK).
        skipped:    ``(net name, reason)`` for Route B rejections.
    """

    rows: list[V2NetRow] = field(default_factory=list)
    route: str = ROUTE_A
    gate_ok: bool = True
    gate_error: str = ""
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def count(self, category: str) -> int:
        return sum(1 for r in self.rows if r.category == category)

    def summary(self) -> str:
        return (f"Power {self.count(CATEGORY_POWER)} · "
                f"SE Clock {self.count(CATEGORY_SE_CLOCK)} · "
                f"GND {self.count(CATEGORY_GND)} · "
                f"Other {self.count(CATEGORY_OTHER)} · "
                f"skipped {len(self.skipped)} rows")


def collapse_route_a(result: ParseNetsResult) -> V2ParseState:
    """Collapse a parsed netlist to the four v2 classes.

    ``Diff Pair`` and ``Signal`` (plus control IO / others / every
    filtered record) become **Other**; the pair partner stays recorded
    inside the record for a later pairing node.
    """
    state = V2ParseState(route=ROUTE_A, gate_ok=True)
    for rec in result.power:
        state.rows.append(V2NetRow(
            name=rec.name, category=CATEGORY_POWER,
            sub_type=NET_TYPE_POWER,
            nominal=rec.nominal or NA,
            confidence=rec.confidence or NA))
    for rec in result.clock:
        state.rows.append(V2NetRow(
            name=rec.name, category=CATEGORY_SE_CLOCK,
            sub_type="clock_single",
            nominal=rec.nominal or NA,
            confidence=rec.confidence or NA))
    for rec in result.gnd:
        state.rows.append(V2NetRow(
            name=rec.name, category=CATEGORY_GND,
            sub_type=NET_TYPE_GND_REF,
            confidence=rec.confidence or NA))
    # control IO / others / filtered (diff pair + signal) -> Other
    for rec in (*result.control_io, *result.others,
                *result.filtered_records):
        state.rows.append(V2NetRow(
            name=rec.name, category=CATEGORY_OTHER,
            sub_type=_other_sub_type(rec),
            confidence=rec.confidence or NA))
    return state


def collapse_route_b(result: RouteBResult) -> V2ParseState:
    """Collapse a Route B ICT Excel parse to the four v2 classes.

    Route B has no Confidence; the impedance/voltage consistency gate
    is carried verbatim so the node can block ``[Next >]`` on a bad
    workbook.
    """
    state = V2ParseState(route=ROUTE_B,
                         gate_ok=result.gate_ok,
                         gate_error=result.gate_error,
                         skipped=list(result.skipped))
    for net in result.nets:
        state.rows.append(V2NetRow(
            name=net.name, category=net.category, sub_type=net.block,
            test_point=net.test_point or NA,
            nominal=net.nominal or NA,
            limits=_limits(net.min_v, net.max_v),
            confidence=NA, route=ROUTE_B))
    return state


def _other_sub_type(rec) -> str:
    """Distinguish the kinds folded into Other (diff pair / signal /
    control IO / others)."""
    if rec.net_type == NET_TYPE_DIFF_PAIR:
        return NET_TYPE_DIFF_PAIR
    if rec.net_type == NET_TYPE_SIGNAL:
        return rec.sub_class or "signal"
    return rec.net_type or "signal"


def _limits(min_v: str, max_v: str) -> str:
    if min_v and max_v:
        return f"{min_v} … {max_v}"
    if min_v:
        return min_v
    if max_v:
        return max_v
    return NA
