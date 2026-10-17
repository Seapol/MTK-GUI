# -*- coding: utf-8 -*-
"""P2-9 commercial HTML/PDF report export (pure incremental).

Renders the mass-production deliverable report from the existing
bases — P1 structured records (``StepResult`` lineage) + P2-5
metrics reports + batch summaries — with zero changes to any
producer:

  * sparkline(points)          — inline SVG trend thumbnail
  * build_html_report(...)     — standardized visual HTML report:
                                 header (part/batch/station/version/
                                 revision/timestamp/trace hash), KPI
                                 summary, anomaly statistics, trend
                                 thumbnails, batch comparison, full
                                 test detail table, footer
  * export_pdf(html, path)     — QPdfWriter rendering of the same
                                 HTML (printable, archivable)
  * doc_hash(payload)          — SHA-256 provenance digest embedded
                                 in header and footer

All data is read-only: the exporter never mutates engine state.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
from datetime import datetime
from pathlib import Path

ACCENT = "#2f7fd1"
FAIL = "#c62828"
OK = "#2e7d32"

CSS = f"""
body {{ font-family: 'Helvetica','Arial','PingFang SC',sans-serif;
       margin: 28px; color: #222; }}
h1 {{ color: {ACCENT}; font-size: 22px; border-bottom: 2px solid
     {ACCENT}; padding-bottom: 6px; }}
h2 {{ font-size: 15px; color: {ACCENT}; margin: 18px 0 6px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 11px; }}
th {{ background: {ACCENT}; color: #fff; padding: 4px 6px;
     text-align: left; }}
td {{ border-bottom: 1px solid #ddd; padding: 3px 6px; }}
.kpi {{ display: inline-block; margin: 4px 10px 4px 0; padding: 6px
       12px; background: #f2f6fa; border-left: 4px solid {ACCENT};
       font-size: 12px; }}
.pass {{ color: {OK}; font-weight: bold; }}
.fail {{ color: {FAIL}; font-weight: bold; }}
.foot {{ margin-top: 22px; font-size: 10px; color: #777;
        border-top: 1px solid #ccc; padding-top: 6px; }}
"""


def esc(v) -> str:
    return _html.escape("" if v is None else str(v))


def doc_hash(payload) -> str:
    """Provenance digest over the report source data (stable)."""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   default=str).encode("utf-8")).hexdigest()


def sparkline(points, width=220, height=44, color=ACCENT) -> str:
    """Inline SVG trend thumbnail (pure string, no chart deps)."""
    vals = [p for p in points if isinstance(p, (int, float))]
    if len(vals) < 2:
        return "<i>No trend data yet</i>"
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    step = width / (len(vals) - 1)
    pts = " ".join(
        f"{i * step:.1f},{height - 4 - (v - lo) / span * (height - 8):.1f}"
        for i, v in enumerate(vals))
    return (f'<svg width="{width}" height="{height}">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="2"/></svg>')


def _yield_kpi(y) -> str:
    pct = f"{y.real_yield * 100:.2f}%" if y.real_yield is not None \
        else "N/A"
    return (f'<span class="kpi">Total {y.total}</span>'
            f'<span class="kpi">PASS {y.passed}</span>'
            f'<span class="kpi">FAIL {y.failed}</span>'
            f'<span class="kpi">Invalid {y.invalid}</span>'
            f'<span class="kpi">Real yield <b>{pct}</b></span>')


def _status_cell(status) -> str:
    s = esc(status)
    cls = "pass" if s in ("PASS", "Done") else \
        ("fail" if s in ("FAIL", "ERROR") else "")
    return f'<td class="{cls}">{s}</td>'


#: console hard-wrap width (chars) - QTextDocument does NOT honor
#: zero-width spaces, so long CLI / dump tokens must be broken by
#: inserting real newlines (110 chars ≈ 250 px at 6 pt - always well
#: inside the A4 text width)
CONSOLE_WRAP_CHARS = 110


def _hardwrap(text: str, width: int = CONSOLE_WRAP_CHARS) -> str:
    out = []
    for line in text.split("\n"):
        while len(line) > width:
            out.append(line[:width])
            line = line[width:]
        out.append(line)
    return "\n".join(out)


def console_log_html(text: str, max_chars: int = 400_000,
                     wrap: int | None = None) -> str:
    """Full DUT console transcript as a printable section appended after
    the test table.  ANSI escape sequences are stripped (QTextDocument
    cannot render them — they would pollute the PDF as garbage glyphs).

    2026-10-17 (twice-burned) fix: the transcript is HARD-WRAPPED by
    character count and rendered inside a single-cell monospace table.
    A <pre> never wraps, and QTextDocument ignores zero-width spaces
    (U+200B) — one long CLI / dump token widened the whole document
    layout past the paper edge, clipping every page (96624 reports).
    ``wrap`` overrides the default character count (the DUT certificate
    passes a dpi-derived count — on macOS the printable page is only
    ~595 doc px wide, see dut_pdf.page_body_px)."""
    from ..engine.fct_test_runner import strip_ansi
    clean = strip_ansi(text or "").replace("\r", "")
    if len(clean) > max_chars:
        clean = clean[:max_chars] + "\n... (truncated)"
    escaped = _html.escape(
        _hardwrap(clean, wrap or CONSOLE_WRAP_CHARS)).replace("\n", "<br>")
    return ("<h3>Console Log</h3>"
            "<table width='100%' cellspacing='0' cellpadding='4'>"
            "<tr><td bgcolor='#f7f7f7' style=\""
            "font-family:Menlo,Consolas,monospace; font-size:8px\">"
            f"{escaped}</td></tr></table>")


def build_html_report(*, records, yield_report, cycle_report,
                      cpk_reports, batch_summaries=None,
                      meta=None, title="Mass-production test report") -> str:
    """Standardized commercial HTML report from existing bases."""
    meta = dict(meta or {})
    records = list(records)
    batch_summaries = batch_summaries or {}
    ts = meta.get("generated_at") or f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    digest = doc_hash({
        "meta": meta,
        "records": [r.__dict__ for r in records],
        "yield": yield_report.to_dict() if yield_report else {},
        "cycle": {"mean": cycle_report.mean_s if cycle_report
                  else None},
        "cpk": {k: (v.cpk if v else None)
                for k, v in (cpk_reports or {}).items()},
    })

    # --- header ------------------------------------------------------
    parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'>"
             f"<title>{esc(title)}</title><style>{CSS}</style></head>"
             "<body>",
             f"<h1>{esc(title)}</h1>",
             "<table><tr>",
             f"<td>Part number: <b>{esc(meta.get('part_number', '-'))}"
             f"</b></td>",
             f"<td>Batch: <b>{esc(meta.get('batch', 'ALL'))}</b></td>",
             f"<td>Station: {esc(meta.get('station', '-'))}</td>",
             f"<td>Software version: {esc(meta.get('version', '-'))}</td>",
             f"<td>Config revision: {esc(meta.get('revision', '-'))}</td>",
             f"<td>Generated at: {esc(ts)}</td>",
             f"<td>Trace hash: {digest[:16]}</td>",
             "</tr></table>"]

    # --- KPI summary ---------------------------------------------------
    if yield_report:
        parts += ["<h2>KPI summary</h2>", _yield_kpi(yield_report)]
    if cycle_report and cycle_report.mean_s is not None:
        bottleneck = (cycle_report.bottlenecks[0][0]
                      if cycle_report.bottlenecks else "-")
        parts.append(f'<span class="kpi">Mean cycle time '
                     f'{cycle_report.mean_s:.2f}s</span>'
                     f'<span class="kpi">Variation CV '
                     f'{(cycle_report.cv or 0) * 100:.1f}%</span>'
                     f'<span class="kpi">Bottleneck '
                     f'{esc(bottleneck)}</span>')

    # --- anomaly statistics --------------------------------------------
    if yield_report:
        parts.append("<h2>Anomaly statistics</h2>"
                     "<table><tr><th>Anomaly category</th>"
                     "<th>Count</th></tr>")
        for kind, n in sorted(yield_report.invalid_by_kind.items()):
            parts.append(f"<tr><td>{esc(kind)}</td><td>{n}</td></tr>")
        parts.append("</table>")
        if yield_report.top_defects:
            parts.append("<h2>Defect TOP</h2><table><tr><th>Case</th>"
                         "<th>Count</th><th>Share</th></tr>")
            for name, n, ratio in yield_report.top_defects:
                parts.append(f"<tr><td>{esc(name)}</td><td>{n}</td>"
                             f"<td>{ratio * 100:.1f}%</td></tr>")
            parts.append("</table>")

    # --- trend thumbnails ------------------------------------------------
    trend = [r for r in records if r.ts is not None]
    if trend:
        trend.sort(key=lambda r: r.ts)
        bucket = max(1, len(trend) // 6)
        pts = []
        for i in range(0, len(trend), bucket):
            chunk = trend[i:i + bucket]
            p = sum(1 for r in chunk if r.status.value == "PASS")
            f = sum(1 for r in chunk if not r.is_invalid
                    and r.status.value == "FAIL")
            if p + f:
                pts.append(p / (p + f) * 100)
        parts.append("<h2>Yield trend thumbnail</h2>")
        parts.append(sparkline(pts) if len(pts) >= 2
                     else "<i>Not enough trend samples</i>")
    if cpk_reports:
        parts.append("<h2>CpK trend thumbnail</h2>"
                     "<table><tr><th>Parameter</th>"
                     "<th>Cp</th><th>CpK</th><th>Grade</th><th>Trend</th>"
                     "</tr>")
        for case, rep in cpk_reports.items():
            if rep is None:
                continue
            cp_txt = rep.cp if rep.cp is not None else "-"
            cpk_txt = rep.cpk if rep.cpk is not None else "-"
            spark = sparkline([rep.cpk] if rep.cpk is not None else [],
                              width=80)
            parts.append(f"<tr><td>{esc(case)}</td><td>{cp_txt}</td>"
                         f"<td>{cpk_txt}</td><td>{esc(rep.grade)}</td>"
                         f"<td>{spark}</td></tr>")
        parts.append("</table>")

    # --- batch comparison -------------------------------------------------
    if batch_summaries:
        parts.append("<h2>Batch summary comparison</h2>"
                     "<table><tr><th>Batch</th>"
                     "<th>Yield</th><th>Mean cycle (s)</th>"
                     "<th>Tests</th>"
                     "</tr>")
        for batch, s in batch_summaries.items():
            y, c = s.get("yield", {}), s.get("cycle", {})
            ry = y.get("real_yield")
            pct = f"{ry * 100:.2f}%" if ry is not None else "N/A"
            mean_s = (f"{c['mean_s']:.2f}"
                      if c.get("mean_s") is not None else "-")
            parts.append(f"<tr><td>{esc(batch)}</td><td>{pct}</td>"
                         f"<td>{mean_s}</td>"
                         f"<td>{y.get('total', 0)}</td></tr>")
        parts.append("</table>")

    # --- test detail ---------------------------------------------------
    parts.append("<h2>Test detail</h2><table><tr><th>#</th><th>Case</th>"
                 "<th>Result</th><th>Measured</th><th>Duration (s)</th>"
                 "<th>Time</th>"
                 "<th>Batch</th></tr>")
    for i, r in enumerate(records, 1):
        parts.append(f"<tr><td>{i}</td><td>{esc(r.name)}</td>"
                     f"{_status_cell(r.status.value)}"
                     f"<td>{esc(r.measured)}</td>"
                     f"<td>{r.duration_s:.2f}</td>"
                     f"<td>{esc(r.ts or '-')}</td>"
                     f"<td>{esc(r.batch or '-')}</td></tr>")
    parts.append("</table>")

    # --- footer ----------------------------------------------------------
    parts.append(f'<p class="foot">mtk-gui mass-production report | '
                 f'version '
                 f'{esc(meta.get("version", "-"))} | config '
                 f'{esc(meta.get("revision", "-"))} | generated '
                 f'{esc(ts)} | trace hash {digest}</p>'
                 "</body></html>")
    return "".join(parts)


def export_pdf(html_text: str, path) -> Path:
    """Render the same HTML into a standardized PDF via Qt."""
    from PySide6.QtGui import QTextDocument
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtCore import QMarginsF
    from PySide6.QtPrintSupport import QPrinter

    path = Path(path)
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(12, 14, 12, 14),
                           QPageLayout.Unit.Millimeter)
    doc = QTextDocument()
    doc.setHtml(html_text)
    doc.print_(printer)
    return path
