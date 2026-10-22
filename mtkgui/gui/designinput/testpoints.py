# -*- coding: utf-8 -*-
"""GUI view helpers for test points (M4 PART 2).

The TEST-POINT RANKING lives in exactly ONE place:
``mtkgui.ict.netparse.testpoints.select_test_points`` (TP > J > JP >
SJ > C > L > R).  The GUI renders that result - it never re-derives
it, so GUI == CLI by construction.

This module keeps only the GUI-only view concepts.
"""
from __future__ import annotations

from mtkgui.ict.netparse import (NET_TYPE_GND_REF, NetCollection,
                                 select_test_points)


def probe_of(members: list[str]) -> tuple[str, list[str]]:
    """``(best, alternatives)`` of one net - thin netparse view."""
    best, kept = select_test_points(members)
    return best, [t for t in kept if t != best]


def gnd_reference_names(collection: NetCollection) -> list[str]:
    """GND nets WITH a usable probe, pcb-plane first (rank order).

    Reference grounds are a GUI interaction concept: every GND record
    defaults ON (see ``model.net_collection_from_result``); this view
    lists the ones a probe can actually reach, in netparse rank order
    (pcb rank 0 first, then chassis, then shield).
    """
    records = [rec for rec in collection.nets
               if rec.net_type == NET_TYPE_GND_REF]
    records.sort(key=lambda rec: (rec.priority or {}).get("rank", 0))
    return [rec.name for rec in records
            if select_test_points(rec.members)[0]]
