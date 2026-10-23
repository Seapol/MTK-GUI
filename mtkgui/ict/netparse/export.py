# -*- coding: utf-8 -*-
"""Net-parse result export (JSON / CSV).

Stdlib only: ``json`` + ``csv``.

M2 B1-B5: every class is RANKED (:mod:`.priority`) and filled to the
instrument capacity (:mod:`.capacity`) with CONFIDENCE-aware
overflow handling - medium/low-confidence overflow nets move to
``Others`` with ``sub_class = "capacity"`` while HIGH-confidence
overflow nets STAY in their class with ``test_selected = false``.
Each entry carries ``confidence`` / ``rank`` / ``test_selected``;
the payload adds ``bridge_report`` and ``user_override``.
"""
from __future__ import annotations

import csv
import io
import json

from .capacity import DEFAULT_LIMITS, ResourceLimits, capacity_reason, \
    truncate
from .model import (CATEGORY_CONTROL_IO_LABEL, CATEGORY_OTHERS,
                    NET_TYPE_POWER, ParseNetsResult, SubClass)
from .priority import rank_result
from .rules import RULES_VERSION
from .testpoints import select_test_points

RESULT_SCHEMA = "mtkgui.ict.netparse.v4"

_CSV_HEADER = ("net", "category", "test_point", "alternatives",
               "members", "sub_class", "reason", "priority", "rank",
               "confidence", "isolated", "active_drivers")

_CLASSES = ("power", "clock", "control_io")


def _net_entry(rec, test_selected: bool | None = None) -> dict:
    """One net -> JSON entry (test point + alternatives included)."""
    best, kept = select_test_points(rec.members)
    entry = {
        "net": rec.name,
        "net_type": rec.net_type,
        "members": list(rec.members),
        "test_point": best,
        "alternatives": [t for t in kept if t != best],
        "sub_class": rec.sub_class,
        "provenance": rec.provenance,
        "priority": dict(rec.priority) if rec.priority else None,
        "confidence": rec.confidence,
        "rank": rec.priority.get("rank") if rec.priority else None,
        "test_selected": test_selected,
    }
    if rec.net_type == NET_TYPE_POWER:
        # v4: input-rail evidence + free-text note (GUI/user hint)
        entry["input_rail"] = rec.input_rail
        entry["note"] = rec.note
    if getattr(rec, "isolation_checked", False):
        # M7: DIO-write guard evidence (control-IO nets only)
        entry["isolated"] = rec.isolated
        entry["active_drivers"] = list(rec.active_drivers)
    if rec.meta:
        entry["members_meta"] = dict(rec.meta)
    return entry


def _ranked_copy(result: ParseNetsResult,
                 library: dict | None) -> ParseNetsResult:
    """Bucket-order copy of *result*, ranked per M2 B2."""
    working = ParseNetsResult(
        power=list(result.power), clock=list(result.clock),
        control_io=list(result.control_io), others=list(result.others),
        gnd=list(result.gnd), filtered=list(result.filtered),
        filtered_records=list(result.filtered_records),
        total=result.total, invalid_lines=list(result.invalid_lines),
        format=result.format, source=result.source,
        bridge_report=dict(result.bridge_report),
        warnings=list(result.warnings),
        user_override=dict(result.user_override))
    rank_result(working, library)
    return working


def _split_overflow(report: dict, class_key: str, limit: int) -> tuple:
    """Split one class overflow into (relaxed, high) record lists.

    B3 owner rule: medium/low-confidence overflow -> Others/capacity;
    high-confidence overflow STAYS in its class (test_selected=false).
    """
    relaxed, high = [], []
    for rec in report[class_key]["overflow"]:
        if (rec.confidence or "medium") == "high":
            high.append(rec)
        else:
            relaxed.append(rec)
    return relaxed, high


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
        relaxed, high = _split_overflow(report, class_key, limit)
        high_names = {r.name for r in high}
        selected_names = {r.name for r in report[class_key]["selected"]}
        records = getattr(working, class_key)

        def _ts(r):
            if r.name in selected_names:
                return True
            if r.name in high_names:
                return False      # capacity full, stays for the GUI
            return None

        blocks[class_key] = {
            "nets": [_net_entry(r, test_selected=_ts(r))
                     for r in records],
            "selected": [_net_entry(r, test_selected=True)
                         for r in report[class_key]["selected"]],
            "overflow": [],
        }
        relaxed_entries = []
        for rec in relaxed:
            entry = _net_entry(rec)
            entry["sub_class"] = SubClass.CAPACITY
            entry["priority"] = dict(rec.priority or {})
            entry["priority"]["capacity_reason"] = capacity_reason(
                class_key, limit)
            relaxed_entries.append(entry)
        blocks[class_key]["overflow"] = relaxed_entries
        blocks[class_key]["overflow_high"] = [
            _net_entry(r, test_selected=False) for r in high]
        others_entries.extend(relaxed_entries)

    high_entries = {class_key: blocks[class_key]["overflow_high"]
                    for class_key in _CLASSES}

    # M2 closeout metric (M3 1.4): "determined" = every net carrying a
    # decided verdict (candidates + others interface/muxed + high-conf
    # bridge_duplicate/capacity).  ``legacy`` = power/clock/control_io
    # only, printed alongside for comparison.
    cand = [e for class_key in _CLASSES
            for e in blocks[class_key]["nets"]]
    determined = list(cand)
    for entry in others_entries:
        sub = entry.get("sub_class")
        if sub in (SubClass.INTERFACE, SubClass.MUXED) or (
                sub in (SubClass.BRIDGE_DUPLICATE, SubClass.CAPACITY)
                and entry.get("confidence") == "high"):
            determined.append(entry)

    def _conf(entries: list[dict]) -> float:
        high = sum(1 for e in entries if e.get("confidence") == "high")
        med = sum(1 for e in entries if e.get("confidence") == "medium")
        return (high + 0.5 * med) / max(1, len(entries))

    return {
        "schema": RESULT_SCHEMA,
        "rules_version": RULES_VERSION,
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
            "overall_confidence": round(_conf(determined), 3),
            "legacy_conf": round(_conf(cand), 3),
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
                "overflow_ambiguous": blocks[class_key]["overflow"],
                "overflow_high": high_entries[class_key],
            }
            for class_key in _CLASSES
        },
        "bridge_report": dict(result.bridge_report),
        "user_override": dict(result.user_override),
        "applied_rules": list(result.applied_rules),
        "rails_up": [_net_entry(r, test_selected=True)
                     for r in working.power[:limits.rails_up]],
        "warnings": list(result.warnings),
        "filtered": [{"net": name, "reason": reason}
                     for name, reason in result.filtered],
        "invalid_lines": list(result.invalid_lines),
    }


def result_to_json(result: ParseNetsResult,
                   limits: ResourceLimits | None = None,
                   library: dict | None = None,
                   indent: int = 2) -> str:
    """Serialize a parse result to JSON text."""
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

    Row order: Power (ranked), Clock (ranked), Un-reused GPIO / EN /
    RST / CS / MODE (ranked), Others (incl. capacity-overflow rows
    with ``sub_class = capacity``), GND, Filtered.  HIGH-confidence
    overflow nets stay in their class rows (``test_selected`` is a
    JSON-only flag).
    """
    limits = limits or DEFAULT_LIMITS
    working = _ranked_copy(result, library)
    report = truncate(working, limits)
    relaxed = {}
    for class_key in _CLASSES:
        split = _split_overflow(report, class_key,
                                report[class_key]["limit"])
        relaxed[class_key] = {r.name for r in split[0]}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)

    def _row(rec, category, sub_class="", reason=""):
        entry = _net_entry(rec)
        writer.writerow((
            entry["net"], category, entry["test_point"],
            " ".join(entry["alternatives"]),
            " ".join(entry["members"]),
            sub_class, reason, _priority_text(rec),
            str(rec.priority.get("rank", "")) if rec.priority else "",
            rec.confidence,
            # M7: DIO-write guard evidence (empty for non-control nets)
            ("" if "isolated" not in entry
             else ("true" if entry["isolated"] else
                   ("false" if entry["isolated"] is False else "unknown"))),
            " ".join(entry.get("active_drivers") or [])))

    for rec in working.power:
        if rec.name not in relaxed["power"]:
            _row(rec, "Power")
    for rec in working.clock:
        if rec.name not in relaxed["clock"]:
            _row(rec, "Clock")
    for rec in working.control_io:
        if rec.name not in relaxed["control_io"]:
            _row(rec, CATEGORY_CONTROL_IO_LABEL)
    for rec in result.others:
        _row(rec, CATEGORY_OTHERS, rec.sub_class)
    for class_key in _CLASSES:
        for rec in report[class_key]["overflow"]:
            if rec.name in relaxed[class_key]:
                _row(rec, CATEGORY_OTHERS, SubClass.CAPACITY,
                     capacity_reason(class_key,
                                     report[class_key]["limit"]))
    for rec in result.gnd:
        _row(rec, "GND", rec.sub_class)
    for name, reason in result.filtered:
        writer.writerow((name, "Filtered", "", "", "", "", reason,
                         "", "", "", "", ""))
    return buffer.getvalue()
