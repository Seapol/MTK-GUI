# -*- coding: utf-8 -*-
"""Style-A DUT report (classic certificate, user direction 2026-10-16):
double-ring frame, numbered sections, the big circular PASS / FAIL
seal and the "Authorized by MTK" sign-off row.

The HTML targets the QTextDocument subset (tables + inline styles only
- no flex / absolute positioning / transform), so the SAME markup
renders in the in-app preview dialog AND in the exported PDF.  The
circular seal is pre-rendered by QPainter into a pixmap (rotation and
ring text are impossible in QTextDocument HTML) and injected as the
``mtk_stamp`` image resource.

* dut_report_html(report, meta)  - certificate markup
* stamp_pixmap(result)           - rotated circular seal (2x for crispness)
* dut_pdf_name(report, meta)     - DUT_[PASS/FAIL]_[SN]_[Core]_[Part]_[Batch]_[Date]_[Time].pdf
* export_dut_pdf(report, meta, path) - A4 PDF via QPrinter
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

NAVY = "#16324f"
GOLD = "#c9a227"
GREEN = "#1d7a3c"
RED = "#b02a2a"
INK = "#1c2e6e"
MUTED = "#5a6b7d"

STAMP_RESOURCE = "mtk_stamp"
#: cursive faces for the sign-off ink (Mac -> Windows order)
SCRIPT_FONT = "Snell Roundhand,Brush Script MT,Segoe Script,cursive"


def esc(v) -> str:
    from html import escape
    return escape("" if v is None else str(v))


def _verdict(result: str) -> str:
    return "PASS" if "PASS" in (result or "").upper() else "FAIL"


def _color(result: str) -> str:
    return GREEN if _verdict(result) == "PASS" else RED


# ------------------------------------------------------------------ seal
def stamp_pixmap(result: str) -> "QPixmap":
    """The circular seal, pre-rendered at 2x (displayed at 170 px):
    double ring + curved MTK QA text + the verdict + date, tilted -11
    like a rubber stamp.  Green for PASS, red for everything else."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

    color = QColor(_color(result))
    size = 340
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(size / 2, size / 2)
    p.rotate(-11)
    p.setOpacity(0.92)

    c = size / 2
    p.setPen(QPen(color, 14))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(0, 0), c - 12, c - 12)
    p.setPen(QPen(color, 4))
    p.drawEllipse(QPointF(0, 0), c - 48, c - 48)

    # curved text around the ring, evenly spread over the top arc
    ring = "MTK  ·  QUALITY ASSURANCE  ·  INSPECTED"
    f = QFont("Arial")
    f.setBold(True)
    f.setPixelSize(26)
    p.setFont(f)
    p.setPen(QPen(color))
    n = len(ring)
    span = 300.0
    for i, ch in enumerate(ring):
        ang = -90 - span / 2 + span * i / max(1, n - 1)
        p.save()
        p.rotate(ang)
        p.drawText(QRectF(-40, -(c - 27), 80, 34),
                   Qt.AlignmentFlag.AlignHCenter
                   | Qt.AlignmentFlag.AlignBottom, ch)
        p.restore()

    # verdict + date in the middle
    big = QFont("Arial")
    big.setBold(True)
    big.setPixelSize(84)
    p.setFont(big)
    p.drawText(QRectF(-c, -74, size, 96),
               Qt.AlignmentFlag.AlignHCenter
               | Qt.AlignmentFlag.AlignVCenter, _verdict(result))
    f2 = QFont("Arial")
    f2.setPixelSize(24)
    p.setFont(f2)
    p.drawText(QRectF(-c, 6, size, 34),
               Qt.AlignmentFlag.AlignHCenter
               | Qt.AlignmentFlag.AlignVCenter,
               f"{datetime.now():%Y-%m-%d}")
    pen = QPen(color, 4, Qt.PenStyle.DashLine)
    for x in range(-72, 73, 24):
        p.setPen(pen)
        p.drawLine(QPointF(x, 58), QPointF(x + 14, 58))
    p.end()
    return pm


# ------------------------------------------------------------------ html
def _sec(title: str) -> str:
    return (f"<table width='100%' cellspacing='0' cellpadding='0'>"
            f"<tr><td width='6' bgcolor='{GOLD}'>&nbsp;</td>"
            f"<td bgcolor='#eef2f6' style='padding:4px 8px'>"
            f"<b><font color='{NAVY}'><small>{esc(title.upper())}"
            f"</small></font></b></td></tr></table>")


def dut_report_html(report, meta=None, when: datetime | None = None) -> str:
    """Style-A certificate markup (QTextDocument-safe tables only).

    meta: part / core_id / batch (Product Information on the page).
    """
    meta = dict(meta or {})
    when = when or datetime.now()
    verdict = _verdict(report.overall_result)
    vc = _color(report.overall_result)
    sn = report.serial_no or "DUT"

    from .report_export import console_log_html, doc_hash
    digest = doc_hash({
        "serial": report.serial_no, "station": report.station_id,
        "user": report.user, "result": report.overall_result,
        "items": [i.__dict__ for i in report.items],
        "meta": meta,
    })
    report_no = (f"DUT-{verdict}-{sn}-{when:%Y%m%d-%H%M%S}")

    n_pass = sum(1 for i in report.items if "PASS" in i.result.upper())
    n_fail = len(report.items) - n_pass
    rows = "".join(
        f"<tr>"
        f"<td>{idx}</td><td>{esc(i.test_name)}</td>"
        f"<td>{esc(i.category)}</td>"
        f"<td>{esc(i.duration or i.measured)}</td>"
        f"<td>{esc(i.low)}</td><td>{esc(i.high)}</td>"
        f"<td>{esc(i.unit)}</td>"
        f"<td><b><font color='{GREEN if 'PASS' in i.result.upper() else RED}'>"
        f"{esc(i.result)}</font></b></td></tr>"
        for idx, i in enumerate(report.items, 1))

    # three-column sign-off: ink (cursive) over a rule + caption
    def _sig(ink, cap):
        return (f"<td width='33%' align='center'>"
                f"<font face='{SCRIPT_FONT}' size='5' color='{INK}'>"
                f"{esc(ink)}</font><br><hr>"
                f"<small><font color='{MUTED}'>{esc(cap.upper())}</font>"
                f"</small></td>")

    # FAIL items keep their red verdict in the table; the overall row
    # and the seal follow the report verdict
    parts = [
        # certificate double-ring frame: navy / white / navy / white
        "<table width='100%' cellspacing='0' cellpadding='5'><tr>"
        f"<td bgcolor='{NAVY}'>"
        "<table width='100%' cellspacing='0' cellpadding='2'><tr>"
        "<td bgcolor='#ffffff'>"
        "<table width='100%' cellspacing='0' cellpadding='1'><tr>"
        f"<td bgcolor='{NAVY}'>"
        "<table width='100%' cellspacing='0' cellpadding='12'><tr>"
        "<td bgcolor='#ffffff'>"
        "<table width='100%' cellspacing='0' cellpadding='0'>"
        # ---- header
        f"<tr><td><font color='{NAVY}'><b><font size='6'>MTK</font></b><br>"
        f"<small><font color='{MUTED}'>MEDIANTEK KILN · MANUFACTURING "
        f"SOLUTIONS</font></small></font></td>"
        f"<td align='right'><b><font color='{NAVY}'><font size='5'>"
        f"DUT TEST REPORT</font></font></b><br>"
        f"<small><font color='{MUTED}'>Report No.&nbsp; {esc(report_no)}"
        f"</font></small></td></tr>"
        # ---- 1 product & traceability
        f"<tr><td colspan='2'>{_sec('1 · Product & Traceability')}"
        "<table width='100%' cellspacing='0' cellpadding='4' border='0'>"
        f"<tr><td bgcolor='#eef2f6'><b><font color='{NAVY}'><small>"
        "SERIAL NO.</small></font></b></td>"
        f"<td><b>{esc(sn)}</b></td>"
        f"<td bgcolor='#eef2f6'><b><font color='{NAVY}'><small>"
        "PROJECT PART#</small></font></b></td>"
        f"<td>{esc(meta.get('part', '-') or '-')}</td></tr>"
        f"<tr><td bgcolor='#eef2f6'><b><font color='{NAVY}'><small>"
        "CORE ID</small></font></b></td>"
        f"<td>{esc(meta.get('core_id', '-') or '-')}</td>"
        f"<td bgcolor='#eef2f6'><b><font color='{NAVY}'><small>"
        "BATCH #</small></font></b></td>"
        f"<td>{esc(meta.get('batch', '-') or '-')}</td></tr>"
        f"<tr><td bgcolor='#eef2f6'><b><font color='{NAVY}'><small>"
        "STATION / OPERATOR</small></font></b></td>"
        f"<td>{esc(report.station_id)} / {esc(report.user)}</td>"
        f"<td bgcolor='#eef2f6'><b><font color='{NAVY}'><small>"
        "REPORT TIME</small></font></b></td>"
        f"<td>{esc(report.timestamp)}</td></tr>"
        "</table>"
        # ---- 2 summary
        f"{_sec('2 · Test Summary')}"
        "<table width='100%' cellspacing='0' cellpadding='6'><tr>"
        f"<td align='center' bgcolor='#f6f8fa'><b><font color='{NAVY}'>"
        f"<font size='5'>{len(report.items)}</font></b><br>"
        f"<small><font color='{MUTED}'>ITEMS</font></small></td>"
        f"<td align='center' bgcolor='#f6f8fa'><b><font color='{GREEN}'>"
        f"<font size='5'>{n_pass}</font></b><br>"
        f"<small><font color='{MUTED}'>PASS</font></small></td>"
        f"<td align='center' bgcolor='#f6f8fa'><b><font color='{RED}'>"
        f"<font size='5'>{n_fail}</font></b><br>"
        f"<small><font color='{MUTED}'>FAIL</font></small></td>"
        f"<td align='center' bgcolor='#f6f8fa'><b><font color='{vc}'>"
        f"<font size='5'>{verdict}</font></b><br>"
        f"<small><font color='{MUTED}'>OVERALL</font></small></td>"
        "</tr></table>"
        # ---- 3 detail
        f"{_sec('3 · Test Detail')}"
        "<table width='100%' cellspacing='0' cellpadding='3' border='0'>"
        f"<tr bgcolor='{NAVY}'>"
        "<td><b><font color='#ffffff'><small>#</small></font></b></td>"
        "<td><b><font color='#ffffff'><small>TEST</small></font></b></td>"
        "<td><b><font color='#ffffff'><small>CATEGORY</small></font></b></td>"
        "<td><b><font color='#ffffff'><small>MEASURED / DURATION"
        "</small></font></b></td>"
        "<td><b><font color='#ffffff'><small>LOW</small></font></b></td>"
        "<td><b><font color='#ffffff'><small>HIGH</small></font></b></td>"
        "<td><b><font color='#ffffff'><small>UNIT</small></font></b></td>"
        "<td><b><font color='#ffffff'><small>RESULT</small></font></b></td>"
        f"</tr>{rows}</table>"
        # ---- seal (right aligned, between detail and sign-off)
        f"{_sec('4 · Inspection Seal')}"
        "<table width='100%' cellspacing='0' cellpadding='4'><tr>"
        f"<td align='right'><img src='{STAMP_RESOURCE}' width='170' "
        f"height='170'></td></tr></table>"
        # ---- sign-off
        f"{_sec('5 · Sign-off')}"
        "<table width='100%' cellspacing='0' cellpadding='6'><tr>"
        + _sig(report.user or "operator", "Tested by")
        + _sig("", "Reviewed by")
        + _sig("MTK QA", "Authorized by MTK")
        + "</tr></table>"
        # ---- footer
        f"<hr><small><font color='{MUTED}'>Electronically sealed by "
        f"MTK GUI — this seal is bound to the report data by trace "
        f"hash<br>sha256 · {esc(digest)}</font></small>"
        # close the 5 nested frame tables (content -> white -> navy
        # thin -> white ring -> navy outer)
        + "</table></td></tr>" * 5]

    html = "".join(parts)
    log = report.console_log or ""
    if log.strip():
        html += "<hr>" + console_log_html(log)
    return html


# ------------------------------------------------------------------ name
def _safe(text: str) -> str:
    for ch in '/\\:*?"<>| ':
        text = text.replace(ch, "-")
    return text.strip("-") or "NA"


def dut_pdf_name(report, meta=None, when: datetime | None = None) -> str:
    """DUT_[PASS/FAIL]_[Serial#]_[Core ID]_[Project Part#]_[Batch#]_
    [Date]_[Time].pdf (the fixed naming from the spec)."""
    meta = dict(meta or {})
    when = when or datetime.now()
    sn = _safe(report.serial_no) if report.serial_no else "DUT"
    return (f"DUT_{_verdict(report.overall_result)}_{sn}"
            f"_{_safe(meta.get('core_id', ''))}"
            f"_{_safe(meta.get('part', ''))}"
            f"_{_safe(meta.get('batch', ''))}"
            f"_{when:%Y-%m-%d}_{when:%H-%M-%S}.pdf")


# ------------------------------------------------------------------ pdf
def export_dut_pdf(report, meta=None, path=None) -> Path:
    """Render the certificate into an A4 PDF (the same markup as the
    in-app preview, seal injected as an image resource)."""
    from PySide6.QtCore import QMarginsF, QUrl
    from PySide6.QtGui import QTextDocument
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtPrintSupport import QPrinter

    path = Path(path)
    doc = QTextDocument()
    doc.addResource(QTextDocument.ResourceType.ImageResource,
                    QUrl(STAMP_RESOURCE), stamp_pixmap(
                        report.overall_result))
    doc.setHtml(dut_report_html(report, meta))
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(10, 10, 10, 10),
                           QPageLayout.Unit.Millimeter)
    doc.print_(printer)
    return path
