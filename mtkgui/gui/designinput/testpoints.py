# -*- coding: utf-8 -*-
"""Automatic test-point selection (spec B1-01-01 item 1 / rule 5-6).

Priority order required by spec: ``J > JP > SJ > C > L > R``.

* EVERY net takes part - including ``gnd_ref`` (reference grounds
  join the measurement loop, they are not auto-skipped);
* the selected probe is flagged ``is_alternative_testpoint=True``
  whenever it is an auto-substitute (not a dedicated ``TP`` pin) -
  these are exactly the points the human must re-check for physical
  probe accessibility;
* a GND net without any priority hit falls back to the connector GND
  pin (the ``J`` hit - already first in priority); a net with NO
  usable member at all is flagged ``no_testpoint`` (severe WARNING
  upstream).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .netlist import NetCollection, NET_TYPE_GND_REF

# spec priority order (highest first)
TP_PRIORITY = ("J", "JP", "SJ", "C", "L", "R")

_REFDES_HEAD_RE = re.compile(r"^([A-Z]{1,2})")


def _refdes_of(pin_token: str) -> str:
    """RefDes part of a member token (``U1.5`` -> ``U1``)."""
    return re.split(r"[.\-\[]", pin_token, maxsplit=1)[0]


def _prefix_rank(refdes: str) -> int | None:
    """Priority rank of a RefDes prefix (None = not in TP_PRIORITY)."""
    head = _REFDES_HEAD_RE.match(refdes.upper())
    if head is None:
        return None
    prefix = head.group(1)
    if prefix in TP_PRIORITY:
        return TP_PRIORITY.index(prefix)
    return None


@dataclass
class TestPointAssignment:
    """Test-point selection result for one net.

    Attributes:
        tp_points:                Eligible probe pins, priority order.
        primary_tp:               The auto-selected probe ("" when none).
        is_alternative_testpoint: True = auto-substitute (review me).
        no_testpoint:             True = nothing usable (severe warn).
    """

    tp_points: list[str] = field(default_factory=list)
    primary_tp: str = ""
    is_alternative_testpoint: bool = False
    no_testpoint: bool = False


def select_test_points(collection: NetCollection) \
        -> dict[str, TestPointAssignment]:
    """Run the ``J > JP > SJ > C > L > R`` algorithm on every net.

    Args:
        collection: Classified net collection (gnd_ref included).

    Returns:
        net name -> :class:`TestPointAssignment`.
    """
    result: dict[str, TestPointAssignment] = {}
    for rec in collection.nets:
        result[rec.name] = _assign(rec.members)
    return result


def _assign(members: list[str]) -> TestPointAssignment:
    """Pick probe pins from one net's member tokens."""
    assignment = TestPointAssignment()
    # dedicated TP pins always win outright
    tp_pins = [m for m in members if m.upper().startswith("TP")]
    if tp_pins:
        assignment.tp_points = tp_pins
        assignment.primary_tp = tp_pins[0]
        return assignment

    ranked: list[tuple[int, str]] = []
    for token in members:
        rank = _prefix_rank(_refdes_of(token))
        if rank is not None:
            ranked.append((rank, token))
    ranked.sort(key=lambda pair: (pair[0], pair[1]))
    if ranked:
        assignment.tp_points = [tok for _rank, tok in ranked]
        assignment.primary_tp = ranked[0][1]
        # anything auto-substituted (not a dedicated TP pin) is an
        # "alternative test point" -> human must confirm accessibility
        assignment.is_alternative_testpoint = True
    else:
        assignment.no_testpoint = not members
    return assignment


def gnd_reference_names(collection: NetCollection,
                        assignments: dict[str, TestPointAssignment]) \
        -> list[str]:
    """GND nets WITH a usable probe (Final-Review rule: need >= 1)."""
    return [rec.name for rec in collection.nets
            if rec.net_type == NET_TYPE_GND_REF
            and assignments.get(rec.name).primary_tp]
