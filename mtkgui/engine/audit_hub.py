# -*- coding: utf-8 -*-
"""P3-10 full-chain audit middle platform & compliance reports
(pure additive).

A compliance layer composed ON TOP of the frozen P2-11
:class:`AuditLog` (reused as the append-only store, never modified):

  * track()          — categorized full-chain logging: every entry is
                       tagged ``category:action`` (login / config /
                       case / task / device / data / report)
  * change()         — config/data changes recorded with BEFORE and
                       AFTER snapshots -> diff_of() builds a
                       field-level comparison (前后对比)
  * stats()          — per user / category / deny counts (监控)
  * verify()         — integrity check: parseable JSONL, entry count
  * compliance_report() — ISO 审厂 report: coverage by category,
                       change records with diffs, denied attempts,
                       exported as CSV + JSON alongside a summary

Zero changes to auth_audit / AuditLog contracts.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

#: full-chain categories (ISO audit trail coverage)
CATEGORIES = ("login", "config", "case", "task", "device",
              "data", "report", "security")


def diff_of(before: dict | None, after: dict | None) -> list[dict]:
    """Field-level before/after comparison (前后对比)."""
    before = before or {}
    after = after or {}
    rows: list[dict] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            rows.append({"field": key, "old": old, "new": new})
    return rows


def _as_dict(value) -> dict | None:
    """Stored snapshots are compact JSON strings (P2-11 _brief)."""
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


class AuditHub:
    """Categorized audit trail + compliance reporting over P2-11."""

    def __init__(self, audit):          # frozen P2-11 AuditLog
        self.audit = audit

    # ------------------------------------------------------------ write
    def track(self, user: str, category: str, action: str,
              target: str = "", before=None, after=None,
              detail: str = "") -> dict:
        """Full-chain entry: action stored as ``category:action``."""
        if category not in CATEGORIES:
            category = "data"           # uncategorized -> data plane
        return self.audit.log(user, f"{category}:{action}", target,
                              before=before, after=after,
                              detail=detail)

    def change(self, user: str, category: str, action: str,
               target: str, before: dict | None,
               after: dict | None) -> dict:
        """Config/data change with before/after comparison."""
        diffs = diff_of(before, after)
        detail = "; ".join(f"{d['field']}: {d['old']}->{d['new']}"
                           for d in diffs) or "no change"
        return self.track(user, category, action, target,
                          before=before, after=after,
                          detail=detail)

    # ------------------------------------------------------------- read
    def entries(self) -> list[dict]:
        """Tolerant read: malformed lines are skipped (see verify)."""
        rows: list[dict] = []
        try:
            with open(self.audit.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue                    # flagged by verify
        except OSError:
            pass
        return rows

    def query(self, *, category: str | None = None, **kw) -> list[dict]:
        """P2-11 query plus category prefix filter."""
        rows = self.entries()
        if kw:
            rows = self.audit.query(**kw)
        if category:
            rows = [e for e in rows
                    if e["action"].startswith(f"{category}:")]
        return rows

    def changes_of(self, target: str) -> list[dict]:
        """Every before/after diff recorded for one target (溯源)."""
        out = []
        for e in self.entries():
            if e["target"] == target and \
                    (e["before"] or e["after"]):
                out.append({"ts": e["ts"], "user": e["user"],
                            "action": e["action"],
                            "diff": diff_of(_as_dict(e["before"]),
                                            _as_dict(e["after"]))})
        return out

    def stats(self) -> dict:
        """Board summary: coverage by category / user / denials."""
        rows = self.entries()
        by_cat: dict[str, int] = {}
        by_user: dict[str, int] = {}
        denied = 0
        for e in rows:
            cat = e["action"].split(":", 1)[0]
            by_cat[cat] = by_cat.get(cat, 0) + 1
            by_user[e["user"]] = by_user.get(e["user"], 0) + 1
            if e["action"].endswith(":DENY"):
                denied += 1
        return {"total": len(rows), "by_category": by_cat,
                "by_user": by_user, "denied": denied,
                "changes": sum(1 for e in rows
                               if e["before"] or e["after"])}

    # -------------------------------------------------------- integrity
    def verify(self) -> dict:
        """Tamper/parse integrity check over the JSONL ledger."""
        rows = self.entries()
        raw_lines = 0
        malformed = 0
        try:
            with open(self.audit.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    raw_lines += 1
                    try:
                        json.loads(line)
                    except json.JSONDecodeError:
                        malformed += 1
        except OSError:
            malformed = -1
        return {"raw_lines": raw_lines, "parsed": len(rows),
                "malformed": malformed,
                "ok": malformed == 0 and raw_lines == len(rows)}

    # -------------------------------------------------- compliance report
    def compliance_report(self, path, since: str | None = None,
                          until: str | None = None) -> dict:
        """ISO 审厂 report: coverage + changes + denials, CSV + JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.entries()                 # tolerant read
        if since:
            rows = [e for e in rows if e["ts"] >= since]
        if until:
            rows = [e for e in rows if e["ts"] <= until]
        by_cat: dict[str, int] = {}
        denied = []
        changes = []
        for e in rows:
            cat = e["action"].split(":", 1)[0]
            by_cat[cat] = by_cat.get(cat, 0) + 1
            if e["action"].endswith(":DENY"):
                denied.append(e)
            if e["before"] or e["after"]:
                changes.append(e)
        missing = [c for c in CATEGORIES if c not in by_cat]
        summary = {
            "period": {"since": since or "beginning",
                       "until": until or "now"},
            "total_entries": len(rows),
            "coverage": by_cat,
            "uncovered_categories": missing,
            "change_records": len(changes),
            "denied_attempts": len(denied),
            "integrity": self.verify()["ok"],
        }
        (path.with_suffix(".json")).write_text(
            json.dumps({"summary": summary, "entries": rows},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        with open(path.with_suffix(".csv"), "w", newline="",
                  encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "ts", "user", "action", "target", "before", "after",
                "detail"])
            w.writeheader()
            w.writerows(rows)
        self.audit.log("system", "report:compliance_export",
                       str(path),
                       detail=f"entries={len(rows)}")
        return summary


#: short public alias
AH = AuditHub
