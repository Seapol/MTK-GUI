# -*- coding: utf-8 -*-
"""Review Excel I/O for the ICT case closed loop.

Export: ``ict_test_cases`` (engine YAML rows) -> one review workbook
with EVERY configurable field exposed for human editing, plus AI
provenance columns (version / timestamp).

Import: the (possibly engineer-edited) workbook -> plain row dicts,
ready for :mod:`mtkgui.engine.casegen.sync` to diff and merge back
into the project YAML.  Missing/blank cells keep their defaults; extra
unknown columns are surfaced in ``ImportResult.ignored_columns`` so
nothing is silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .generator import AI_GEN_VERSION

SHEET_NAME = "ICT_REVIEW"

# full export/import field list (spec: no missing, no masking)
COLUMNS = ("name", "kind", "enable", "wait_ms", "timeout_ms", "unit",
           "threshold_min", "threshold_max", "priority", "power_domain",
           "upstream", "downstream", "instrument", "test_dim", "notes",
           "ai_version", "gen_time")

EDITABLE = ("enable", "wait_ms", "timeout_ms", "threshold_min",
            "threshold_max", "priority", "power_domain", "upstream",
            "downstream", "instrument", "test_dim", "notes")

_HEADER_CN = {"name": "用例名称", "kind": "类型", "enable": "测试使能",
              "wait_ms": "等待ms", "timeout_ms": "超时ms",
              "unit": "单位", "threshold_min": "阈值下限",
              "threshold_max": "阈值上限", "priority": "测试优先级",
              "power_domain": "所属电源域", "upstream": "上游拓扑",
              "downstream": "下游拓扑", "instrument": "测试仪器分配",
              "test_dim": "测试维度", "notes": "备注说明",
              "ai_version": "AI生成版本", "gen_time": "生成时间戳"}


@dataclass
class ImportResult:
    rows: list[dict] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)


def export_review_excel(config: dict, path: str) -> int:
    """Project config dict -> review Excel.  Returns the row count."""
    from openpyxl import Workbook

    cases = config.get("ict_test_cases") or []
    audit = config.get("ict_case_audit") or {}
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append([_HEADER_CN[c] for c in COLUMNS])
    for case in cases:
        meta = case.get("ai_meta") or {}
        ws.append([_export_cell(case, c, meta, audit) for c in COLUMNS])
    wb.save(path)
    return len(cases)


_DEFAULTS = {"enable": True, "wait_ms": 100, "timeout_ms": 5000,
             "priority": ""}


def _export_cell(case: dict, col: str, meta: dict, audit: dict):
    if col == "ai_version":
        return meta.get("gen_version") or audit.get("ai_version") \
            or AI_GEN_VERSION
    if col == "gen_time":
        return meta.get("gen_time") or audit.get("gen_time") \
            or datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return case.get(col, _DEFAULTS.get(col, ""))


def import_review_excel(path: str) -> ImportResult:
    """Review workbook -> row dicts (values kept as strings/bools)."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        raise ValueError(f"[CASEGEN] empty review workbook {path!r}")
    header = [str(c or "").strip() for c in rows[0]]
    # accept both CN and EN headers
    key_of = {v: k for k, v in _HEADER_CN.items()}
    cols: dict[str, int] = {}
    unknown: list[str] = []
    for i, h in enumerate(header):
        key = key_of.get(h) or (h.lower() if h.lower() in COLUMNS else None)
        if key is None:
            if h:
                unknown.append(h)
            continue
        cols[key] = i
    for required in ("name", "kind"):
        if required not in cols:
            raise ValueError(f"[CASEGEN] review excel missing required "
                             f"column {required!r} (header {header})")
    result = ImportResult(ignored_columns=unknown)
    for raw in rows[1:]:
        if raw is None or all(c is None for c in raw):
            continue
        row: dict = {}
        for key, i in cols.items():
            val = raw[i] if i < len(raw) else None
            row[key] = _coerce(key, val)
        if not str(row.get("name") or "").strip():
            continue
        if "enable" not in row:
            row["enable"] = True
        result.rows.append(row)
    return result


def _coerce(key: str, val):
    if val is None:
        return False if key == "enable" else ""
    if key == "enable":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "是",
                                            "y", "enabled")
    if key in ("wait_ms", "timeout_ms"):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return _DEFAULTS[key]
    if key == "priority":
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return ""
    if key in ("threshold_min", "threshold_max"):
        try:
            return float(val)
        except (TypeError, ValueError):
            return str(val).strip()
    return str(val).strip()
