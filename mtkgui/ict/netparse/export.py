# -*- coding: utf-8 -*-
"""Net-parse result export (JSON / CSV).

Stdlib only: ``json`` + ``csv``.
"""
from __future__ import annotations

import csv
import io
import json

from .model import CATEGORY_CONTROL_IO_LABEL, ParseNetsResult
from .testpoints import select_test_points

RESULT_SCHEMA = "mtkgui.ict.netparse.v1"

_CSV_HEADER = ("net", "category", "test_point", "alternatives",
               "members", "reason")


def _net_entry(rec) -> dict:
    """One net -> JSON entry (test point + alternatives included)."""
    best, kept = select_test_points(rec.members)
    return {
        "net": rec.name,
        "net_type": rec.net_type,
        "members": list(rec.members),
        "test_point": best,
        "alternatives": [t for t in kept if t != best],
    }


def result_to_dict(result: ParseNetsResult) -> dict:
    """Serialize a parse result to a JSON-ready dict."""
    return {
        "schema": RESULT_SCHEMA,
        "source": result.source,
        "format": result.format,
        "total": result.total,
        "summary": {
            "power": len(result.power),
            "clock": len(result.clock),
            "gpio": len(result.gpio),
            "gnd": len(result.gnd),
            "filtered": len(result.filtered),
        },
        "nets": {
            "power": [_net_entry(r) for r in result.power],
            "clock": [_net_entry(r) for r in result.clock],
            "gpio": [_net_entry(r) for r in result.gpio],
            "gnd": [_net_entry(r) for r in result.gnd],
        },
        "filtered": [{"net": name, "reason": reason}
                     for name, reason in result.filtered],
        "invalid_lines": list(result.invalid_lines),
    }


def result_to_json(result: ParseNetsResult, indent: int = 2) -> str:
    """Serialize a parse result to JSON text.

    Args:
        result: Parse result.
        indent: JSON indent (0 = compact).
    """
    payload = result_to_dict(result)
    if indent > 0:
        return json.dumps(payload, indent=indent, ensure_ascii=False)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def result_to_csv(result: ParseNetsResult) -> str:
    """Serialize a parse result to CSV text.

    Row order: Power, Clock, Control IO, GND, Filtered.  ``members`` /
    ``alternatives`` are space joined; ``reason`` is set only on the
    Filtered rows.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)
    groups = ((("Power", result.power)),
              (("Clock", result.clock)),
              ((CATEGORY_CONTROL_IO_LABEL, result.gpio)),
              (("GND", result.gnd)))
    for category, records in groups:
        for rec in records:
            entry = _net_entry(rec)
            writer.writerow((
                entry["net"], category, entry["test_point"],
                " ".join(entry["alternatives"]),
                " ".join(entry["members"]), ""))
    for name, reason in result.filtered:
        writer.writerow((name, "Filtered", "", "", "", reason))
    return buffer.getvalue()
