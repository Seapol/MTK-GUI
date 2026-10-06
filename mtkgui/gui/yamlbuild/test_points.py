# -*- coding: utf-8 -*-
"""ICT test-point auto selection (core-algorithm standard, Step 4).

Fixed selection priority (strictly locked):

    TP test point > J pin > JP pin > SJ > C > L > R

The best on-board dedicated test point wins; without a TP the pin
hierarchy picks the best reference designator automatically.  For a
net with several candidates the best one is chosen and the redundant
alternatives are dropped from the selection (they stay listed in the
net members - nothing is removed from the netlist data itself).

Pure headless functions - no Qt, no parsing-core change.
"""

from __future__ import annotations

import re

#: fixed priority (lower = better); unknown prefixes rank last
TEST_POINT_PRIORITY: tuple[str, ...] = ("TP", "J", "JP", "SJ", "C",
                                        "L", "R")
_DEFAULT_RANK = len(TEST_POINT_PRIORITY) + 1

_REFDES_RE = re.compile(r"^([A-Za-z]+)")


def _rank(token: str) -> int:
    """Priority rank of one member pin token (by its refdes prefix)."""
    head = _REFDES_RE.match(token.strip())
    if not head:
        return _DEFAULT_RANK
    prefix = head.group(1).upper()
    if prefix in TEST_POINT_PRIORITY:
        return TEST_POINT_PRIORITY.index(prefix)
    # J vs JP disambiguation: "JP1" starts with "JP", not "J"
    for candidate in TEST_POINT_PRIORITY:
        if prefix.startswith(candidate):
            return TEST_POINT_PRIORITY.index(candidate)
    return _DEFAULT_RANK


def select_test_points(members: list[str]) -> tuple[str, list[str]]:
    """Pick the best test point of one net (Step 4).

    Args:
        members: Member pin tokens of the net (``U1.5``, ``TP4`` ...).

    Returns:
        ``(best, kept)`` - the winning token ("" when the net has no
        rankable member) and the ordered non-redundant candidates
        (same rank ties keep the netlist order; only the best per
        rank prefix is kept).
    """
    ranked = sorted((( _rank(m), i, m.strip())
                     for i, m in enumerate(members or [])),
                    key=lambda t: (t[0], t[1]))
    if not ranked:
        return "", []
    best = ranked[0][2]
    kept: list[str] = []
    seen_ranks: set[int] = set()
    for rank, _i, token in ranked:
        if rank in seen_ranks:
            continue        # redundant alternative of the same class
        seen_ranks.add(rank)
        kept.append(token)
    return best, kept
