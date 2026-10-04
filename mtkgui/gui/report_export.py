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
        return "<i>暂无趋势数据</i>"
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
    return (f'<span class="kpi">总测 {y.total}</span>'
            f'<span class="kpi">PASS {y.passed}</span>'
            f'<span class="kpi">FAIL {y.failed}</span>'
            f'<span class="kpi">无效 {y.invalid}</span>'
            f'<span class="kpi">真实良率 <b>{pct}</b></span>')


def _status_cell(status) -> str:
    s = esc(status)
    cls = "pass" if s in ("PASS", "Done") else \
        ("fail" if s in ("FAIL", "ERROR") else "")
    return f'<td class="{cls}">{s}</td>'


def build_html_report(*, records, yield_report, cycle_report,
                      cpk_reports, batch_summaries=None,
                      meta=None, title="量产测试成品报告") -> str:
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
             f"<td>产品料号: <b>{esc(meta.get('part_number', '-'))}"
             f"</b></td>",
             f"<td>批次: <b>{esc(meta.get('batch', 'ALL'))}</b></td>",
             f"<td>站点: {esc(meta.get('station', '-'))}</td>",
             f"<td>软件版本: {esc(meta.get('version', '-'))}</td>",
             f"<td>配置版本: {esc(meta.get('revision', '-'))}</td>",
             f"<td>生成时间: {esc(ts)}</td>",
             f"<td>溯源哈希: {digest[:16]}</td>",
             "</tr></table>"]

    # --- KPI summary ---------------------------------------------------
    if yield_report:
        parts += ["<h2>指标摘要</h2>", _yield_kpi(yield_report)]
    if cycle_report and cycle_report.mean_s is not None:
        bottleneck = (cycle_report.bottlenecks[0][0]
                      if cycle_report.bottlenecks else "-")
        parts.append(f'<span class="kpi">平均工时 '
                     f'{cycle_report.mean_s:.2f}s</span>'
                     f'<span class="kpi">波动 CV '
                     f'{(cycle_report.cv or 0) * 100:.1f}%</span>'
                     f'<span class="kpi">瓶颈 '
                     f'{esc(bottleneck)}</span>')

    # --- anomaly statistics --------------------------------------------
    if yield_report:
        parts.append("<h2>异常统计</h2><table><tr><th>异常类别</th>"
                     "<th>数量</th></tr>")
        for kind, n in sorted(yield_report.invalid_by_kind.items()):
            parts.append(f"<tr><td>{esc(kind)}</td><td>{n}</td></tr>")
        parts.append("</table>")
        if yield_report.top_defects:
            parts.append("<h2>不良 TOP</h2><table><tr><th>用例</th>"
                         "<th>次数</th><th>占比</th></tr>")
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
        parts.append("<h2>良率趋势缩略图</h2>")
        parts.append(sparkline(pts) if len(pts) >= 2
                     else "<i>趋势样本不足</i>")
    if cpk_reports:
        parts.append("<h2>CpK 趋势缩略图</h2><table><tr><th>参数</th>"
                     "<th>Cp</th><th>CpK</th><th>等级</th><th>趋势</th>"
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
        parts.append("<h2>批次汇总对比</h2><table><tr><th>批次</th>"
                     "<th>良率</th><th>平均工时s</th><th>测试数</th>"
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
    parts.append("<h2>测试明细</h2><table><tr><th>#</th><th>用例</th>"
                 "<th>结果</th><th>实测</th><th>耗时s</th><th>时间</th>"
                 "<th>批次</th></tr>")
    for i, r in enumerate(records, 1):
        parts.append(f"<tr><td>{i}</td><td>{esc(r.name)}</td>"
                     f"{_status_cell(r.status.value)}"
                     f"<td>{esc(r.measured)}</td>"
                     f"<td>{r.duration_s:.2f}</td>"
                     f"<td>{esc(r.ts or '-')}</td>"
                     f"<td>{esc(r.batch or '-')}</td></tr>")
    parts.append("</table>")

    # --- footer ----------------------------------------------------------
    parts.append(f'<p class="foot">mtk-gui 量产成品报告 | 版本 '
                 f'{esc(meta.get("version", "-"))} | 配置 '
                 f'{esc(meta.get("revision", "-"))} | 生成 '
                 f'{esc(ts)} | 溯源哈希 {digest}</p>'
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
