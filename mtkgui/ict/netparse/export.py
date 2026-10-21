# -*- coding: utf-8 -*-
"""Net-parse result export (JSON / CSV).

Stdlib only: ``json`` + ``csv``.

M2 B1-B3: every exported class is RANKED (:mod:`.priority`) and
TRUNCATED to the instrument capacity (:mod:`.capacity`); each class
gains ``selected`` / ``overflow`` and the payload carries
``resource_limits`` + ``capacity_report``.  Overflow nets are listed
under ``Others`` with ``sub_class = capacity`` (original class / rank
kept in their ``priority`` stamp).
"""
from __future__ import annotations

import csv
import io
import json

from .capacity import DEFAULT_LIMITS, ResourceLimits, capacity_reason, \
    truncate
from .model import (CATEGORY_CONTROL_IO_LABEL, CATEGORY_OTHERS,
                    ParseNetsResult)
from .priority import rank_result
from .testpoints import select_test_points

RESULT_SCHEMA = "mtkgui.ict.netparse.v3"

_CSV_HEADER = ("net", "category", "test_point", "alternatives",
               "members", "sub_class", "reason", "priority", "rank")

_CLASSES = ("power", "clock", "control_io")


def _net_entry(rec) -> dict:
    """One net -> JSON entry (test point + alternatives included)."""
    best, kept = select_test_points(rec.members)
    return {
        "net": rec.name,
        "net_type": rec.net_type,
        "members": list(rec.members),
        "test_point": best,
        "alternatives": [t for t in kept if t != best],
        "sub_class": rec.sub_class,
        "provenance": rec.provenance,
        "priority": dict(rec.priority) if rec.priority else None,
    }


def _overflow_entry(rec, class_key: str, limit: int) -> dict:
    """One capacity-overflow entry (re-labelled ``Others``/capacity)."""
    entry = _net_entry(rec)
    entry["sub_class"] = "capacity"
    entry["priority"] = dict(rec.priority or {})
    entry["priority"]["capacity_reason"] = capacity_reason(
        class_key, limit)
    return entry


def _ranked_copy(result: ParseNetsResult,
                 library: dict | None) -> ParseNetsResult:
    """Bucket-order copy of *result*, ranked per M2 B1."""
    working = ParseNetsResult(
        power=list(result.power), clock=list(result.clock),
        control_io=list(result.control_io), others=list(result.others),
        gnd=list(result.gnd), filtered=list(result.filtered),
        filtered_records=list(result.filtered_records),
        total=result.total, invalid_lines=list(result.invalid_lines),
        format=result.format, source=result.source)
    rank_result(working, library)
    return working


def result_to_dict(result: ParseNetsResult,
                   limits: ResourceLimits | None = None,
                   library: dict | None = None) -> dict:
    """Serialize a parse result to a JSON-ready dict.

    Args:
        result:  Parse result (records are not mutated - ranking
                 works on a bucket-order copy).
        limits:  Instrument capacity (default :data:`DEFAULT_LIMITS`).
        library: Optional M2 library - LOAD-role refdes count as main
                 chips for the clock importance score.
    """
    limits = limits or DEFAULT_LIMITS
    working = _ranked_copy(result, library)
    report = truncate(working, limits)

    others_entries = [_net_entry(r) for r in result.others]
    blocks = {}
    for class_key in _CLASSES:
        limit = report[class_key]["limit"]
        records = getattr(working, class_key)
        blocks[class_key] = {
            "nets": [_net_entry(r) for r in records],
            "selected": [_net_entry(r)
                         for r in report[class_key]["selected"]],
            "overflow": [_overflow_entry(r, class_key, limit)
                         for r in report[class_key]["overflow"]],
        }
        others_entries.extend(
            _overflow_entry(r, class_key, limit)
            for r in report[class_key]["overflow"])

    return {
        "schema": RESULT_SCHEMA,
        "source": result.source,
        "format": result.format,
        "total": result.total,
        "resource_limits": {
            "power_pts": limits.power_pts, "rails_up": limits.rails_up,
            "clock_lf": limits.clock_lf, "clock_hf": limits.clock_hf,
            "ctrl_io": limits.ctrl_io},
        "summary": {
            "power": len(result.power),
            "clock": len(result.clock),
            "control_io": len(result.control_io),
            "others": len(result.others),
            "gpio": len(result.gpio),
            "gnd": len(result.gnd),
            "filtered": len(result.filtered),
        },
        "nets": {
            "power": blocks["power"],
            "clock": blocks["clock"],
            "control_io": blocks["control_io"],
            "others": others_entries,
            # compatible view: control_io + others (incl. overflow)
            "gpio": blocks["control_io"]["nets"] + others_entries,
            "gnd": [_net_entry(r) for r in result.gnd],
        },
        "capacity_report": {
            class_key: {
                "limit": report[class_key]["limit"],
                "selected": blocks[class_key]["selected"],
                "overflow": blocks[class_key]["overflow"],
            }
            for class_key in _CLASSES
        },
        "rails_up": [_net_entry(r)
                     for r in working.power[:limits.rails_up]],
        "filtered": [{"net": name, "reason": reason}
                     for name, reason in result.filtered],
        "invalid_lines": list(result.invalid_lines),
    }


def result_to_json(result: ParseNetsResult,
                   limits: ResourceLimits | None = None,
                   library: dict | None = None,
                   indent: int = 2) -> str:
    """Serialize a parse result to JSON text.

    Args:
        result:  Parse result.
        limits:  Instrument capacity (default :data:`DEFAULT_LIMITS`).
        library: Optional M2 library (clock importance).
        indent:  JSON indent (0 = compact).
    """
    payload = result_to_dict(result, limits, library)
    if indent > 0:
        return json.dumps(payload, indent=indent, ensure_ascii=False)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _priority_text(rec) -> str:
    """Compact ``priority`` cell for the CSV export."""
    if not rec.priority:
        return ""
    band = rec.priority.get("band") or ""
    stage = rec.priority.get("stage")
    tag = band or (f"stage{stage}" if stage is not None else "")
    score = rec.priority.get("score", 0)
    return f"{tag}:{score}" if tag else str(score)


def result_to_csv(result: ParseNetsResult,
                  limits: ResourceLimits | None = None,
                  library: dict | None = None) -> str:
    """Serialize a parse result to CSV text.

    Row order: Power (selected, ranked), Clock (selected), Un-reused
    GPIO / EN / RST / CS / MODE (selected), Others (incl. capacity
    overflow rows with ``sub_class = capacity``), GND, Filtered.
    New M2 columns: ``priority`` + ``rank``.
    """
    limits = limits or DEFAULT_LIMITS
    working = _ranked_copy(result, library)
    report = truncate(working, limits)
    overflow = {class_key: {r.name for r in report[class_key]["overflow"]}
                for class_key in _CLASSES}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)

    def _row(rec, category, sub_class=""):
        entry = _net_entry(rec)
        writer.writerow((
            entry["net"], category, entry["test_point"],
            " ".join(entry["alternatives"]),
            " ".join(entry["members"]),
            sub_class, "", _priority_text(rec),
            str(rec.priority.get("rank", "")) if rec.priority else ""))

    for rec in working.power:
        if rec.name not in overflow["power"]:
            _row(rec, "Power")
    for rec in working.clock:
        if rec.name not in overflow["clock"]:
            _row(rec, "Clock")
    for rec in working.control_io:
        if rec.name not in overflow["control_io"]:
            _row(rec, CATEGORY_CONTROL_IO_LABEL)
    for rec in result.others:
        _row(rec, CATEGORY_OTHERS, rec.sub_class)
    for class_key in _CLASSES:
        for rec in report[class_key]["overflow"]:
            _row(rec, CATEGORY_OTHERS, "capacity")
    for rec in result.gnd:
        _row(rec, "GND")
    for name, reason in result.filtered:
        writer.writerow((name, "Filtered", "", "", "", "", reason,
                         "", ""))
    return buffer.getvalue()
