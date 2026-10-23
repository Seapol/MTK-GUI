# -*- coding: utf-8 -*-
"""ICT Test Plan output files (M5 PART 1) - headless, no Qt.

Two files share ONE owner contract (2026-10-22):

* **Excel workbook** ``ICT Test Plan for <product>.xlsx`` - exactly six
  sheets ``Summary | Power nets | SE-Clock nets | Control IO nets |
  GND nets | Others``.  The workbook is the PRODUCTION EXECUTION form:
  only the columns needed on the test floor.
* **Evidence markdown** ``ICT Test Plan for <product>_evidence.md`` -
  the FULL judgment record: every classification evidence, confidence,
  provenance and the ranked power-tree flows.

Judgment data (confidence / rank / provenance / sub_class / members)
lives ONLY in the markdown; the workbook deliberately omits it.  The
``Others`` sheet is grouped by sub-class so nets stay easy to find.

Nothing here changes classification / confidence / capacity / rules -
this module only serializes a :class:`ParseNetsResult`.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime
from pathlib import Path

from .capacity import DEFAULT_LIMITS, ResourceLimits, truncate
from .confidence import clock_freq_hz
from .model import ParseNetsResult, SubClass
from .priority import nominal_volts_of, rank_result
from .testpoints import select_test_points

#: the six sheet names (owner contract - do not rename)
SHEET_SUMMARY = "Summary"
SHEET_POWER = "Power nets"
SHEET_CLOCK = "SE-Clock nets"
SHEET_CONTROL_IO = "Control IO nets"
SHEET_GND = "GND nets"
SHEET_OTHERS = "Others"
SHEET_NAMES = (SHEET_SUMMARY, SHEET_POWER, SHEET_CLOCK,
               SHEET_CONTROL_IO, SHEET_GND, SHEET_OTHERS)

#: owner column contracts
POWER_HEADER = ("Net", "Test Point(s)", "R-GND Min limit (ohm)",
                "Nominal (V)", "Lower limit (V)", "Upper limit (V)",
                "R-V Channel", "DAQ AI Channel")
CLOCK_HEADER = ("Net", "Test Point(s)", "Nominal (kHz)",
                "Lower limit (kHz)", "Upper limit (kHz)", "FREQ Channel")
CONTROL_IO_HEADER = ("Net", "Test Point(s)")
GND_HEADER = ("rank", "net", "sub_class(pcb/chassis/shield)",
              "test_point")
OTHERS_HEADER = ("sub_class", "net", "provenance")

#: ``Others`` grouping order (owner requirement: grouped BY class)
OTHERS_ORDER = (SubClass.INTERFACE, SubClass.MUXED,
                SubClass.SYSTEM_RANDOM, SubClass.UNCLASSIFIED,
                SubClass.AMBIGUOUS, SubClass.CAPACITY,
                SubClass.BRIDGE_DUPLICATE)

NOMINAL_NOTE = ("nominal from net-name heuristic - confirm in "
                "Power-Tree Editor")

_CLASSES = ("power", "clock", "control_io")


# --------------------------------------------------------------- helpers
def _iso_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def project_name_from_path(path: str) -> str:
    """Product name derived from the netlist file name.

    ``NET-96317_A.net`` -> ``96317``; a name without the ``NET-``
    prefix falls back to the first 4-6 digit run, else the stem.
    """
    stem = Path(path).stem
    match = re.match(r"^NET[-_]?(\d{3,6})(?:[-_].*)?$", stem,
                     re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"(\d{4,6})", stem)
    if match:
        return match.group(1)
    return stem


def _fmt(value) -> str:
    """Cell text for a number ("" for None / 0 / blank)."""
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip()
    if number == 0:
        return ""
    return f"{number:g}"


def _test_points(rec, override: str = "") -> str:
    """Primary test point + space-joined alternatives."""
    if override.strip():
        return override.strip()
    best, kept = select_test_points(rec.members)
    if not best:
        return ""
    return " ".join([best] + [t for t in kept if t != best])


def _ranked(result: ParseNetsResult,
            overrides: dict | None = None,
            library: dict | None = None) -> ParseNetsResult:
    """Deep copy of *result*, ranked with the BOM *library* (never
    mutates the input).

    ``rank_result`` re-derives ``input_rail`` from the member tokens
    and the library evidence (fuse / inlet / TVS / USB-PD / FL).  The
    YAML merge hook then restores user-approved markers as a backup.
    """
    working = copy.deepcopy(result)
    rank_result(working, library)
    for rec in working.power:
        if _overrides_for(overrides, rec.name).get("input_rail"):
            rec.input_rail = True
    return working


def _limits_text(limits: ResourceLimits, working: ParseNetsResult) -> list:
    """Capacity usage lines shared by the Summary sheet and the md."""
    lf = sum(1 for r in working.clock
             if (r.priority or {}).get("band") == "LF")
    hf = len(working.clock) - lf
    return [
        ("power", f"{min(len(working.power), limits.power_pts)}/"
                  f"{limits.power_pts} (R-GND+Voltage)"),
        ("rails-up", f"{min(len(working.power), limits.rails_up)}/"
                     f"{limits.rails_up} (input_rails first)"),
        ("clock", f"LF {lf}/{limits.clock_lf}, "
                  f"HF {hf}/{limits.clock_hf}"),
        ("control_io", f"{min(len(working.control_io), limits.ctrl_io)}/"
                       f"{limits.ctrl_io}"),
        ("gnd", f"{len(working.gnd)} reference plane(s) - not counted"),
    ]


def _input_rails(working: ParseNetsResult) -> list[tuple[str, str]]:
    """``(net, evidence hint)`` for every input rail (power only)."""
    rows = []
    for rec in working.power:
        if not rec.input_rail:
            continue
        hint = rec.provenance or ""
        if rec.note:
            hint = f"{hint} ({rec.note})" if hint else rec.note
        rows.append((rec.name, hint))
    return rows


def _external_rule_ids(result: ParseNetsResult) -> list[str]:
    return [str(rule.get("id") or "?") for rule in result.applied_rules]


def _others_rows(result: ParseNetsResult, report: dict) -> list:
    """``Others`` records grouped by sub-class, netlist order inside."""
    entries = list(result.others)
    for class_key in _CLASSES:
        for rec in report[class_key]["overflow"]:
            if (rec.confidence or "medium") != "high":
                entries.append(rec)      # medium/low -> capacity
    order = {name: i for i, name in enumerate(OTHERS_ORDER)}
    index = {id(rec): i for i, rec in enumerate(entries)}

    def key(rec):
        sub = rec.sub_class or SubClass.UNCLASSIFIED
        return (order.get(sub, len(order)), index[id(rec)])

    return sorted(entries, key=key)


def _bridge_refdes(rec) -> str:
    """Passive refdes out of a ``bridge_duplicate:FB1->KEEP`` provenance."""
    text = rec.provenance or ""
    match = re.match(r"bridge_duplicate:([^>]+)->", text)
    return match.group(1) if match else ""


# ------------------------------------------------------------- plan data
def _overrides_for(overrides: dict | None, net: str) -> dict:
    return dict((overrides or {}).get(net) or {})


def _power_bounds(rec, override: dict) -> tuple[str, str]:
    """Lower / upper voltage limits (YAML tolerance or record bind)."""
    lower = _fmt(override.get("lower_v"))
    upper = _fmt(override.get("upper_v"))
    if lower or upper:
        return lower, upper
    nominal = rec.nominal
    tolerance = rec.tolerance_pct
    try:
        volts = float(str(nominal).strip())
        pct = float(str(tolerance).strip())
    except (TypeError, ValueError):
        return "", ""
    return _fmt(volts * (1 - pct / 100.0)), _fmt(volts * (1 + pct / 100.0))


def _power_nominal(rec, override: dict) -> str:
    value = override.get("nominal_v")
    if value not in (None, ""):
        return _fmt(value)
    if rec.nominal not in (None, ""):
        return _fmt(rec.nominal)
    return _fmt(nominal_volts_of(rec.name))


def _clock_nominal_khz(rec, override: dict) -> str:
    value = override.get("nominal_khz")
    if value not in (None, ""):
        return _fmt(value)
    hz = clock_freq_hz(rec.name)
    return _fmt(hz / 1000.0) if hz else ""


def _build_plan(result: ParseNetsResult, limits: ResourceLimits,
                project_name: str, overrides: dict | None = None,
                library: dict | None = None) -> dict:
    """All sheet rows + markdown blocks from one parse result."""
    limits = limits or DEFAULT_LIMITS
    working = _ranked(result, overrides, library)
    report = truncate(working, limits)
    name = project_name or Path(result.source).stem or "project"

    power_rows = []
    for rec in report["power"]["selected"]:
        override = _overrides_for(overrides, rec.name)
        lower, upper = _power_bounds(rec, override)
        power_rows.append((
            rec.name, _test_points(rec, str(override.get("test_point")
                                           or "")),
            _fmt(override.get("r_gnd_min_ohm")),
            _power_nominal(rec, override), lower, upper,
            _fmt(override.get("r_v_channel")),
            _fmt(override.get("daq_ai_channel"))))

    clock_rows = []
    for rec in report["clock"]["selected"]:
        override = _overrides_for(overrides, rec.name)
        clock_rows.append((
            rec.name, _test_points(rec, str(override.get("test_point")
                                           or "")),
            _clock_nominal_khz(rec, override),
            _fmt(override.get("lower_khz")),
            _fmt(override.get("upper_khz")),
            _fmt(override.get("freq_channel"))))

    control_rows = []
    for rec in report["control_io"]["selected"]:
        override = _overrides_for(overrides, rec.name)
        control_rows.append(
            (rec.name, _test_points(rec, str(override.get("test_point")
                                             or ""))))

    gnd_rows = []
    for rec in working.gnd:
        best, _kept = select_test_points(rec.members)
        gnd_rows.append((str((rec.priority or {}).get("rank", "")),
                         rec.name, rec.sub_class or "", best))

    others_rows = []
    for rec in _others_rows(result, report):
        others_rows.append((rec.sub_class or SubClass.UNCLASSIFIED,
                            rec.name, rec.provenance or ""))

    return {
        "project_name": name,
        "generated_at": _iso_now(),
        "source": result.source,
        "format": result.format,
        "total": result.total,
        "summary": {
            "power": len(result.power),
            "clock": len(result.clock),
            "control_io": len(result.control_io),
            "others": len(result.others),
            "gnd": len(result.gnd),
            "filtered": len(result.filtered)},
        "limits": _limits_text(limits, working),
        "input_rails": _input_rails(working),
        "bridge": dict(result.bridge_report),
        "bridge_merged": sum(len(v) for v in
                             result.bridge_report.values()),
        "external_rules": _external_rule_ids(result),
        "power_rows": power_rows,
        "clock_rows": clock_rows,
        "control_rows": control_rows,
        "gnd_rows": gnd_rows,
        "others_rows": others_rows,
        "working": working,
        "truncated": report,
    }


# ------------------------------------------------------------------ xlsx
def _new_sheet(workbook, title: str, header: tuple):
    """Add one header row (bold, frozen) + sensible column widths."""
    from openpyxl.styles import Font
    sheet = workbook.create_sheet(title)
    sheet.append(list(header))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for index, label in enumerate(header, start=1):
        sheet.column_dimensions[
            sheet.cell(row=1, column=index).column_letter].width = max(
                14, min(34, len(str(label)) + 6))
    return sheet


def _append_rows(sheet, rows: list) -> int:
    for row in rows:
        sheet.append(list(row))
    return len(rows)


def export_testplan_xlsx(result: ParseNetsResult,
                         limits: ResourceLimits,
                         path: str,
                         project_name: str = "",
                         overrides: dict | None = None,
                         library: dict | None = None) -> int:
    """Write the six-sheet ICT Test Plan workbook.

    Args:
        result:      Parse result (ranked on a copy - never mutated).
        limits:      Instrument capacity (``None`` = defaults).
        path:        Full output path (``ICT Test Plan for <p>.xlsx``).
        project_name: Product name for the Summary sheet.
        overrides:   Optional YAML merge values per net (PART 2): keys
                     ``test_point`` / ``nominal_v`` / ``lower_v`` /
                     ``upper_v`` / ``nominal_khz`` / ``lower_khz`` /
                     ``upper_khz`` / ``r_gnd_min_ohm`` / ``r_v_channel``
                     / ``daq_ai_channel`` / ``freq_channel``.
        library:     Optional BOM library ``{refdes: part info}``: input-
                     rail evidence (fuse / inlet / TVS / USB-PD / FL)
                     and the power sort then match the CLI JSON.

    Returns:
        Number of data rows written across the five net sheets.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    plan = _build_plan(result, limits or DEFAULT_LIMITS, project_name,
                       overrides, library)
    workbook = Workbook()
    workbook.remove(workbook.active)

    summary = workbook.create_sheet(SHEET_SUMMARY)
    summary_rows = [
        ("project_name", plan["project_name"]),
        ("source file", plan["source"]),
        ("netlist format", plan["format"]),
        ("generated_at", plan["generated_at"]),
        ("", ""),
        ("category counts", ""),
    ]
    summary_rows += [(f"{key} nets", str(value))
                     for key, value in plan["summary"].items()]
    summary_rows += [("", ""), ("capacity usage", "")]
    summary_rows += [(key, text) for key, text in plan["limits"]]
    summary_rows += [("", ""), ("input_rails", "evidence")]
    summary_rows += list(plan["input_rails"]) or [("", "")]
    summary_rows += [
        ("", ""),
        ("bridge merge count", str(plan["bridge_merged"])),
        ("external rules applied",
         ", ".join(plan["external_rules"])),
        ("nominal", NOMINAL_NOTE),
    ]
    for row in summary_rows:
        summary.append(list(row))
    for row in summary.iter_rows(min_col=1, max_col=1):
        cell = row[0]
        if cell.value:
            cell.font = Font(bold=True)
    summary.column_dimensions["A"].width = 26
    summary.column_dimensions["B"].width = 60

    power_sheet = _new_sheet(workbook, SHEET_POWER, POWER_HEADER)
    count = _append_rows(power_sheet, plan["power_rows"])
    clock_sheet = _new_sheet(workbook, SHEET_CLOCK, CLOCK_HEADER)
    count += _append_rows(clock_sheet, plan["clock_rows"])
    control_sheet = _new_sheet(workbook, SHEET_CONTROL_IO,
                               CONTROL_IO_HEADER)
    count += _append_rows(control_sheet, plan["control_rows"])
    gnd_sheet = _new_sheet(workbook, SHEET_GND, GND_HEADER)
    count += _append_rows(gnd_sheet, plan["gnd_rows"])
    others_sheet = _new_sheet(workbook, SHEET_OTHERS, OTHERS_HEADER)
    count += _append_rows(others_sheet, plan["others_rows"])

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return count


# -------------------------------------------------------------- markdown
def _evidence_block(rec, category: str, nominal: str,
                    test_point: str) -> list[str]:
    """One net's evidence bullet list (md contract 1.3)."""
    lines = [f"### {rec.name}",
             f"- category: {category}",
             f"- confidence: {rec.confidence or 'low'}",
             f"- sub_class: {rec.sub_class or ''}",
             f"- provenance: {rec.provenance or ''}"]
    if rec.input_rail:
        lines.append("- input_rail: true")
    if test_point:
        lines.append(f"- test_point: {test_point}")
    if nominal:
        lines.append(f"- nominal: {nominal}")
    if rec.note:
        lines.append(f"- note: {rec.note}")
    if getattr(rec, "isolation_checked", False):
        # M7: DIO-write guard evidence (control-IO nets only; the
        # Test Plan xlsx keeps its locked 2-column contract)
        iso = ("true" if rec.isolated else
               ("false" if rec.isolated is False else "unknown"))
        lines.append(f"- isolated: {iso}")
        lines.append("- active_drivers: "
                     + (", ".join(rec.active_drivers) or "(none)"))
    return lines


def build_testplan_markdown(result: ParseNetsResult,
                            limits: ResourceLimits,
                            project_name: str = "",
                            overrides: dict | None = None,
                            library: dict | None = None) -> str:
    """Render the evidence markdown (shared by file export / tests)."""
    plan = _build_plan(result, limits or DEFAULT_LIMITS, project_name,
                       overrides, library)
    working = plan["working"]
    report = plan["truncated"]
    out: list[str] = [
        f"# ICT Test Plan evidence - {plan['project_name']}",
        "",
        f"- source: {plan['source']}",
        f"- format: {plan['format']}",
        f"- generated_at: {plan['generated_at']}",
        f"- total nets: {plan['total']}",
        "",
        "## Category counts",
        "",
    ]
    out += [f"- {key}: {value}" for key, value in
            plan["summary"].items()]
    out += ["", "## Capacity usage", ""]
    out += [f"- {key}: {text}" for key, text in plan["limits"]]
    out += ["", "## Input rails", ""]
    if plan["input_rails"]:
        # one bare ``- NET`` per rail (machine-readable parity list);
        # the evidence hint follows as a non-list line
        out += [f"- {net}" for net, _hint in plan["input_rails"]]
        out += [f"  evidence: {net}: {hint}"
                for net, hint in plan["input_rails"]]
    else:
        out.append("- (none detected)")
    out += ["", "## Bridge merges", ""]
    if plan["bridge"]:
        for kept, merged in plan["bridge"].items():
            out.append(f"- {kept} <-> {', '.join(merged)}")
    else:
        out.append("- (none)")
    out += ["", "## External rules applied", ""]
    out += ([f"- {rule_id}" for rule_id in plan["external_rules"]]
            or ["- (none)"])
    out += ["", f"- nominal: {NOMINAL_NOTE}", ""]

    for title, records, category in (
            ("## Power", report["power"]["selected"], "Power"),
            ("## SE-Clock", report["clock"]["selected"], "SE-Clock"),
            ("## Control IO", report["control_io"]["selected"],
             "Control IO")):
        out += [title, ""]
        if not records:
            out += ["(no nets)", ""]
            continue
        for rec in records:
            override = _overrides_for(overrides, rec.name)
            if category == "Power":
                nominal = _power_nominal(rec, override)
                nominal = f"{nominal} V" if nominal else ""
            else:
                value = _clock_nominal_khz(rec, override)
                nominal = f"{_fmt(float(value) * 1000.0)} Hz" \
                    if value else ""
            out += _evidence_block(
                rec, category, nominal,
                _test_points(rec, str(override.get("test_point") or "")))
            out.append("")

    out += ["## GND", ""]
    out += ([f"- {rec.name} ({rec.sub_class or 'unknown'})"
             for rec in working.gnd] or ["- (no GND reference net)"])
    out += ["", "## Others", ""]
    if plan["others_rows"]:
        for sub, net, provenance in plan["others_rows"]:
            out.append(f"- {net}: {sub} ({provenance})")
    else:
        out.append("- (none)")
    # capacity overflow (high confidence) keeps its full evidence here
    high_overflow = [(class_key, rec) for class_key in _CLASSES
                     for rec in report[class_key]["overflow"]
                     if (rec.confidence or "medium") == "high"]
    if high_overflow:
        out += ["", "## Capacity overflow (high confidence, not tested)",
                ""]
        for class_key, rec in high_overflow:
            out += _evidence_block(rec, class_key, "", "")
            out.append("")
    out += ["", "## Filtered", ""]
    out += ([f"- {name}: {reason}" for name, reason in result.filtered]
            or ["- (none)"])

    out += ["", "## Power tree flows", ""]
    out += ["(rank order: input rails first)", ""]
    for rec in working.power:
        marker = " (INPUT)" if rec.input_rail else ""
        out.append(f"{rec.priority.get('rank', '?')}. {rec.name}{marker}")
    if plan["bridge"]:
        out += ["", "Bridge merges:", ""]
        moved = [rec for rec in result.others
                 if rec.sub_class == SubClass.BRIDGE_DUPLICATE]
        by_source = {rec.name: rec for rec in moved}
        for kept, merged in plan["bridge"].items():
            for name in merged:
                refdes = _bridge_refdes(by_source[name]) \
                    if name in by_source else ""
                via = f" via {refdes}" if refdes else ""
                out.append(f"- {kept} <-> {name}{via}")
    out.append("")
    return "\n".join(out)


def export_testplan_markdown(result: ParseNetsResult,
                             limits: ResourceLimits,
                             path: str,
                             project_name: str = "",
                             overrides: dict | None = None,
                             library: dict | None = None) -> int:
    """Write the evidence markdown next to the workbook.

    Returns:
        Number of evidence sections written (every classified net).
    """
    text = build_testplan_markdown(result, limits, project_name,
                                   overrides, library)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")
    return text.count("\n### ")


def export_testplan_pair(result: ParseNetsResult,
                         limits: ResourceLimits,
                         xlsx_path: str,
                         project_name: str = "",
                         overrides: dict | None = None,
                         library: dict | None = None) -> tuple[int, int]:
    """Write the workbook + the ``_evidence.md`` beside it.

    Returns:
        ``(xlsx_rows, markdown_sections)``.
    """
    md_path = str(Path(xlsx_path).with_name(
        Path(xlsx_path).stem + "_evidence.md"))
    rows = export_testplan_xlsx(result, limits, xlsx_path, project_name,
                                overrides, library)
    sections = export_testplan_markdown(result, limits, md_path,
                                        project_name, overrides, library)
    return rows, sections


__all__ = [
    "SHEET_NAMES", "SHEET_SUMMARY", "SHEET_POWER", "SHEET_CLOCK",
    "SHEET_CONTROL_IO", "SHEET_GND", "SHEET_OTHERS",
    "POWER_HEADER", "CLOCK_HEADER", "CONTROL_IO_HEADER", "GND_HEADER",
    "OTHERS_HEADER", "OTHERS_ORDER", "NOMINAL_NOTE",
    "project_name_from_path", "build_testplan_markdown",
    "export_testplan_xlsx", "export_testplan_markdown",
    "export_testplan_pair",
]
