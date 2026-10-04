# -*- coding: utf-8 -*-
"""Excel -> YAML backfill sync with intelligent diffing.

The engineer edits the review Excel; :func:`sync_review_excel` diffs
it against the current ``ict_test_cases`` and applies a precise
incremental update: added rows appended, removed rows dropped,
parameter changes overwritten, untouched rows kept byte-identical.
Unknown YAML-side fields on surviving rows are preserved (no config
loss, no dirty residue).  Every sync records an audit entry (version
snapshot + change log) under ``ict_case_audit.history``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .excel_io import EDITABLE, import_review_excel

_AUDIT_KEY = "ict_case_audit"


def _norm(value):
    return "" if value is None else value


def diff_rows(yaml_rows: list[dict], excel_rows: list[dict]) -> dict:
    """Compare by case name -> added / removed / changed lists.

    changed entries carry the field name, old and new value so the
    change log is reviewable line by line."""
    by_name = {str(r.get("name")): r for r in yaml_rows}
    excel_names = {str(r.get("name")) for r in excel_rows}
    added = [r for r in excel_rows
             if str(r.get("name")) not in by_name]
    removed = [r for name, r in by_name.items() if name not in excel_names]
    changed: list[dict] = []
    for row in excel_rows:
        base = by_name.get(str(row.get("name")))
        if base is None:
            continue
        for field in EDITABLE:
            old, new = _norm(base.get(field)), _norm(row.get(field))
            if old != new and not (field not in row and not old):
                changed.append({"name": row["name"], "field": field,
                                "old": old, "new": new})
    return {"added": added, "removed": removed, "changed": changed}


def apply_diff(config: dict, diff: dict) -> dict:
    """Apply a diff result onto config in place; returns config."""
    rows = config.get("ict_test_cases") or []
    by_name = {str(r.get("name")): r for r in rows}
    for row in diff["removed"]:
        rows[:] = [r for r in rows
                   if str(r.get("name")) != str(row.get("name"))]
    for row in diff["added"]:
        clone = dict(row)
        clone.pop("ai_version", None)
        clone["ai_meta"] = {"reviewed": True}
        rows.append(clone)
    for ch in diff["changed"]:
        base = by_name.get(str(ch["name"]))
        if base is not None and ch["field"] in EDITABLE:
            base[ch["field"]] = ch["new"]
    return config


def sync_review_excel(config: dict, excel_path: str, *,
                      source: str = "review-excel",
                      actor: str = "engineer") -> dict:
    """Full backfill step: import -> diff -> apply -> audit entry.

    Returns the change report.  ``config["ict_case_audit"]`` gains one
    history snapshot per sync (traceable, comparable, roll-backable via
    the recorded previous row counts and change lists)."""
    result = import_review_excel(excel_path)
    report = diff_rows(config.get("ict_test_cases") or [], result.rows)
    report["ignored_columns"] = result.ignored_columns
    prev = config.get(_AUDIT_KEY) or {}
    history = list(prev.get("history") or [])
    history.append({
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source, "actor": actor,
        "added": [r.get("name") for r in report["added"]],
        "removed": [r.get("name") for r in report["removed"]],
        "changed": report["changed"],
        "rows_before": len(config.get("ict_test_cases") or []),
        "rows_after": (len(config.get("ict_test_cases") or [])
                       + len(report["added"]) - len(report["removed"])),
    })
    apply_diff(config, report)
    audit = dict(prev)
    audit["history"] = history
    audit["review_version"] = len(history)
    audit["final"] = {"source": source, "actor": actor,
                      "rows": len(config.get("ict_test_cases") or [])}
    config[_AUDIT_KEY] = audit
    return report
