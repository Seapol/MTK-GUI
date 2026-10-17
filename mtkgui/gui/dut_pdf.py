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

from PySide6.QtCore import QThread, Signal

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
def stamp_image(result: str) -> "QImage":
    """The circular seal, pre-rendered at 2x (displayed at 170 px):
    double ring + curved MTK QA text + the verdict + date, tilted -11
    like a rubber stamp.  Green for PASS, red for everything else.
    QImage (not QPixmap) so the resource can also be consumed by the
    off-GUI-thread PDF renderer."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPen, QImage

    color = QColor(_color(result))
    size = 340
    pm = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
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

    # curved ring text, rubber-stamp style: the TOP arc reads upright
    # (letter tops outward), the BOTTOM arc runs reversed (letter tops
    # toward the center) so both read left -> right, never upside down
    f = QFont("Arial")
    f.setBold(True)
    f.setPixelSize(26)
    p.setFont(f)
    p.setPen(QPen(color))
    ring_r = c - 27

    def _arc(text, span, top: bool):
        n = len(text)
        for i, ch in enumerate(text):
            if top:
                ang = -span / 2 + span * i / max(1, n - 1)
            else:                     # bottom runs right -> left in a
                ang = span / 2 - span * i / max(1, n - 1)
            p.save()
            p.rotate(ang)
            rect = QRectF(-40, ring_r - 17, 80, 34)
            if top:
                rect = QRectF(-40, -ring_r - 17, 80, 34)
            p.drawText(rect,
                       Qt.AlignmentFlag.AlignHCenter
                       | (Qt.AlignmentFlag.AlignBottom if top
                          else Qt.AlignmentFlag.AlignTop), ch)
            p.restore()

    _arc("MTK  ·  QUALITY ASSURANCE", 175.0, top=True)
    _arc("·  INSPECTED  ·", 80.0, top=False)

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


CHART_RESOURCE = "rail_chart"
#: ±5 % of nominal = the regulation band used by the rail analysis
RAIL_BAND = 0.05

# ------------------------------------------------- fixed page budget
#: QTextDocument px are laid out against the layout paint device and
#: QPrinter::print_() maps them to paper via the PLATFORM screen dpi
#: (macOS = 72, Windows/offscreen = 96): on macOS one doc px printed
#: as one POINT - 4/3 larger - and the A4 page was only ~595 doc px
#: wide instead of ~794.  That platform mapping - not the html - was
#: the real root cause of the thrice-clipped reports.  The renderer
#: therefore does NOT use print_(): it paints onto a QPdfWriter at a
#: FIXED 96 dpi (layout paint device forced to the writer), so every
#: platform lays out and prints identically.
A4_W_PX = 793.7                 # A4 width @ 96 dpi
A4_H_PX = 1122.5                # A4 height @ 96 dpi
PAGE_MARGIN_MM = 18             # paper margin around the certificate
_CONTENT_CHROME_PX = 92         # wrapper padding + 4 frame tables, measured


def page_body_px() -> float:
    """Paintable width in document pixels: A4 @ 96 dpi minus the two
    paper margins."""
    return A4_W_PX - 2 * (PAGE_MARGIN_MM * 96 / 25.4)


def content_budget_px() -> int:
    """Max width of any FIXED-px content (chart image, console line)
    inside the certificate frame."""
    return int(page_body_px() - _CONTENT_CHROME_PX - 4)


def chart_width_px() -> int:
    """Display width for the rails sequence chart."""
    return max(320, min(620, content_budget_px()))


def console_wrap_chars() -> int:
    """Hard-wrap character count for the console transcript (6 pt
    monospace ≈ 4.8 px/char + cell padding, measured)."""
    return max(48, min(110, int((content_budget_px() - 24) / 4.8)))


def screen_font_scale() -> float:
    """Font compensation for the platform screen dpi: QTextDocument
    resolves point sizes to pixels via the PLATFORM screen dpi
    (macOS 72 -> fewer px per pt, Windows 96).  Multiplying every
    point size by this factor makes the pixel layout - and therefore
    the printed physical size - identical on every platform."""
    from PySide6.QtGui import QGuiApplication
    scr = QGuiApplication.primaryScreen()
    dpi = float(scr.logicalDotsPerInch()) if scr else 96.0
    return 96.0 / dpi


def rail_analysis(report) -> list:
    """Per-rail sequence metrics computed straight from the captured
    samples (fractions of the rail nominal; linear interpolation
    between samples).  Honest math - never re-judges: the note only
    reports where the recorded curve ended relative to the ±5 % band.

    Returns dicts: label / nominal / final / rise / peak / over /
    settle / ripple_mv / note.  ``ripple_mv`` is the peak-to-peak
    swing WITHIN the settled (±5 %) window, in millivolts - None when
    the rail never settles.
    """
    out = []
    dur = report.rail_duration or 0.0
    t0 = report.rail_t_start
    for label, _c, y_max, samples in report.rails:
        n = len(samples)
        if not n:
            continue
        step = dur / max(1, n - 1)

        def _first_reach(level):
            """First capture time the fraction curve reaches level."""
            for i, s in enumerate(samples):
                if s >= level:
                    if i == 0:
                        return t0
                    s0 = samples[i - 1]
                    k = (level - s0) / ((s - s0) or 1.0)
                    return t0 + (i - 1 + k) * step
            return None

        t10, t90 = _first_reach(0.1), _first_reach(0.9)
        rise = (t90 - t10) if (t10 is not None and t90 is not None) \
            else None
        peak = max(samples)
        over = max(0.0, peak - 1.0) * 100.0
        last_out = None
        for i, s in enumerate(samples):
            if abs(s - 1.0) > RAIL_BAND:
                last_out = i
        if last_out is None:
            settle = t0                       # never left the band
            settled = samples
        elif last_out + 1 <= n - 1:
            settle = t0 + (last_out + 1) * step
            settled = samples[last_out + 1:]
        else:
            settle = None                     # never settled
            settled = []
        final_frac = samples[-1]
        ok = abs(final_frac - 1.0) <= RAIL_BAND and settle is not None
        ripple_mv = (max(settled) - min(settled)) * y_max * 1000.0 \
            if settled else None
        out.append({
            "label": label, "nominal": y_max,
            "final": final_frac * y_max, "rise": rise,
            "peak": peak * y_max, "over": over, "settle": settle,
            "ripple_mv": ripple_mv,
            "note": ("in regulation (±5%)"
                     if ok else "final outside ±5% band — review"),
        })
    return out


def _breakable(text: str) -> str:
    """Insert zero-width spaces after underscores so long net / rail
    names can wrap inside narrow table columns (QTextDocument only
    wraps at spaces by default - unbreakable tokens were widening the
    whole document layout past the paper edge)."""
    return esc(text).replace("_", "_\u200b")


def _rail_analysis_table(analysis: list) -> str:
    """The per-rail metrics table under the sequence chart.

    Compact 7-column layout: the 9-column version's minimum width
    exceeded the A4 text width and widened the whole document layout
    (everything right of ~85% was clipped on paper)."""
    if not analysis:
        return ""
    rows = ""
    for a in analysis:
        rise = "—" if a["rise"] is None else f"{a['rise']:.3f}"
        settle = "—" if a["settle"] is None else f"{a['settle']:.3f}"
        ripple = "—" if a["ripple_mv"] is None \
            else f"{a['ripple_mv']:.1f} mV"
        rows += (f"<tr><td><b>{_breakable(a['label'])}</b><br>"
                 f"<small>{a['nominal']:.3f} V nominal</small></td>"
                 f"<td>{a['final']:.3f}</td>"
                 f"<td>{rise}</td>"
                 f"<td>{a['over']:.1f}%</td>"
                 f"<td>{settle}</td>"
                 f"<td>{ripple}</td>"
                 f"<td>{esc(a['note'])}</td></tr>")
    return ("<table width='100%' cellspacing='0' cellpadding='3'"
            " border='0'>"
            f"<tr bgcolor='{NAVY}'>"
            "<td><b><font color='#ffffff'><small>RAIL</small></font></b></td>"
            "<td><b><font color='#ffffff'><small>FINAL V</small></font></b></td>"
            "<td><b><font color='#ffffff'><small>RISE 10-90% s"
            "</small></font></b></td>"
            "<td><b><font color='#ffffff'><small>OVERSHOOT"
            "</small></font></b></td>"
            "<td><b><font color='#ffffff'><small>SETTLE ±5% s"
            "</small></font></b></td>"
            "<td><b><font color='#ffffff'><small>RIPPLE P-P"
            "</small></font></b></td>"
            "<td><b><font color='#ffffff'><small>NOTE</small></font></b></td>"
            f"</tr>{rows}</table>")


def _detail_section(grp_imped, grp_volt, grp_clock, grp_seq, grp_other,
                    report, items_table) -> str:
    """Section 3: one table per ICT Test Method + the power-rails
    sequence chart with per-rail analysis (empty groups are skipped)."""
    html = _sec('3 · Test Detail')
    for title, items in (
            ("3.1 · Impedance (ICT)", grp_imped),
            ("3.2 · Voltage (ICT)", grp_volt),
            ("3.3 · Clock (ICT)", grp_clock)):
        if items:
            html += (f"<b><font color='{NAVY}'><small>"
                     f"{esc(title.upper())}</small></font></b>"
                     + items_table(items) + "<br>")
    # 3.4 power-rails sequence: judged rows + chart + metrics
    if grp_seq or report.rails:
        html += (f"<b><font color='{NAVY}'><small>"
                 "3.4 · POWER RAILS UP SEQUENCE (DAQ AI)</small></font>"
                 f"</b><br>"
                 + "".join(
                     f"<small>{esc(i.test_name)} — <b><font color='"
                     f"{GREEN if 'PASS' in i.result.upper() else RED}'>"
                     f"{esc(i.result)}</font></b></small><br>"
                     for i in grp_seq)
                 # ROOT CAUSE of the thrice-clipped 96624 report
                 # (2026-10-17): a bare <img> sharing its <td> with
                 # sibling tables makes QTextDocument count the image's
                 # minimum width once per nesting level (640px chart ->
                 # 920px layout, off the 793px page).  Isolating the img
                 # in its own single-cell table bounds the minimum to
                 # the image + cell chrome (~728px, fits).
                 + (f"<table width='100%' cellspacing='0' cellpadding='0'>"
                    f"<tr><td><img src='{CHART_RESOURCE}' "
                    f"width='{chart_width_px()}'>"
                    f"</td></tr></table><br>"
                    if report.rails else
                    f"<small><font color='{MUTED}'>No capture data "
                    f"available.</font></small><br>")
                 + _rail_analysis_table(rail_analysis(report)))
    # 3.5 everything else AFTER the sequence (numbering = print order)
    if grp_other:
        html += (f"<b><font color='{NAVY}'><small>"
                 f"{esc('3.5 · Flash / FCT / RF & Other'.upper())}"
                 f"</small></font></b>"
                 + items_table(grp_other) + "<br>")
    return html


def rails_chart_image(report, width=1160, height=480):
    """Render the captured rails chart (same painter as the live
    waveform) - widget-free, safe on any thread."""
    if not getattr(report, "rails", None):
        from PySide6.QtGui import QImage
        return QImage()
    return paint_rails_chart(report.rails, report.rail_duration or 1.0,
                             report.rail_t_start,
                             getattr(report, "virtual", False),
                             width, height)


def paint_rails_chart(data, duration: float, t_start: float,
                      virtual: bool, width=1160, height=480):
    """Widget-free rails chart render (the worker thread uses this:
    plain data in, QImage out - the GUI thread is never touched)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QImage
    from ..test_workflow_page import paint_waveform_plot
    img = QImage(int(width), int(height),
                 QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    try:
        paint_waveform_plot(p, width, height, data, duration, t_start,
                            virtual)
    finally:
        p.end()
    return img


def verdict_conflict(report) -> str | None:
    """Detect a mismatch between the session's overall verdict and the
    judged detail (2026-10-17 user direction).  The report NEVER
    re-judges (B4 §8.1 - the cells ARE the verdicts); when the overall
    and the detail disagree, the caller renders a VERDICT NOTE banner
    so the reader is warned to verify the session state.  Only real
    failures count (FAIL / TIMEOUT / ERROR - 'Done' op rows and INFO
    statuses are not failures)."""
    if not report.items:
        return None
    verdict = _verdict(report.overall_result)
    n_fail = sum(1 for i in report.items
                 if any(k in i.result.upper()
                        for k in ("FAIL", "TIMEOUT", "ERROR")))
    if verdict == "PASS" and n_fail:
        return (f"{n_fail} item(s) did NOT pass, but the session "
                f"verdict is '{report.overall_result}'.  This report "
                f"mirrors the session verdict without re-judging "
                f"(B4 §8.1) - verify the session state before "
                f"releasing this unit.")
    if verdict == "FAIL" and n_fail == 0:
        return (f"No failing item found, but the session verdict is "
                f"'{report.overall_result}'.  This report mirrors the "
                f"session verdict without re-judging (B4 §8.1) - "
                f"verify the session state.")
    return None


def _conflict_banner(message: str) -> str:
    """Amber VERDICT NOTE strip under the summary (QTextDocument-safe
    single-row table)."""
    return ("<table width='100%' cellspacing='0' cellpadding='6'>"
            f"<tr><td bgcolor='#fdecea' style='border:1px solid {RED}'>"
            f"<b><font color='{RED}'><small>VERDICT NOTE · "
            f"{esc(message)}</small></font></b></td></tr></table>")


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
        "rails": [list(r) for r in (report.rails or [])],
        "rail_window": [report.rail_t_start, report.rail_duration],
        "meta": meta,
    })
    report_no = "-".join(
        p for p in (f"DUT-{verdict}", report.serial_no,
                    f"{when:%Y%m%d-%H%M%S}") if p)

    def _items_table(items):
        """One judged-rows table (no CATEGORY column: the section
        title already names the group)."""
        rows = "".join(
            f"<tr>"
            f"<td>{idx}</td><td>{esc(i.test_name)}</td>"
            f"<td>{esc(i.duration or i.measured)}</td>"
            f"<td>{esc(i.low)}</td><td>{esc(i.high)}</td>"
            f"<td>{esc(i.unit)}</td>"
            f"<td><b><font color='{GREEN if 'PASS' in i.result.upper() else RED}'>"
            f"{esc(i.result)}</font></b></td></tr>"
            for idx, i in enumerate(items, 1))
        return ("<table width='100%' cellspacing='0' cellpadding='3'"
                " border='0'>"
                f"<tr bgcolor='{NAVY}'>"
                "<td><b><font color='#ffffff'><small>#</small></font></b></td>"
                "<td><b><font color='#ffffff'><small>TEST</small></font></b></td>"
                "<td><b><font color='#ffffff'><small>MEASURED / DURATION"
                "</small></font></b></td>"
                "<td><b><font color='#ffffff'><small>LOW</small></font></b></td>"
                "<td><b><font color='#ffffff'><small>HIGH</small></font></b></td>"
                "<td><b><font color='#ffffff'><small>UNIT</small></font></b></td>"
                "<td><b><font color='#ffffff'><small>RESULT</small></font></b></td>"
                f"</tr>{rows}</table>")

    # ICT detail split by Test Method (user direction 2026-10-16):
    # impedance / voltage / clock each get their own table, the DAQ AI
    # power-rails sequence gets chart + per-rail analysis, everything
    # else (generic ICT, Flash, FCT, RF) lands in the combined table
    ict = [i for i in report.items if i.category == "ICT"]
    grp_imped = [i for i in ict if i.method == "Static Impedance"]
    grp_volt = [i for i in ict if i.method == "Power Voltage"]
    grp_clock = [i for i in ict if i.method == "Clock Hz"]
    grp_seq = [i for i in ict if i.method == "DAQ AI"]
    claimed = {id(i) for i in grp_imped + grp_volt + grp_clock + grp_seq}
    grp_other = [i for i in report.items if id(i) not in claimed]

    # summary strip counts (strict): only real failures (FAIL /
    # TIMEOUT / ERROR) count as FAIL - 'Done' op rows and INFO rows
    # are neither (they used to inflate the FAIL count)
    n_pass = sum(1 for i in report.items if "PASS" in i.result.upper())
    n_fail = sum(1 for i in report.items
                 if any(k in i.result.upper()
                        for k in ("FAIL", "TIMEOUT", "ERROR")))
    conflict = verdict_conflict(report)

    # FAIL items keep their red verdict in the table; the overall row
    # and the seal follow the report verdict
    detail_html = _detail_section(
        grp_imped, grp_volt, grp_clock, grp_seq, grp_other, report,
        _items_table)
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
        # ---- header (fixed px sizes: legacy <font size=N> resolves
        # through the platform dpi - px keeps every platform identical)
        f"<tr><td><font color='{NAVY}'><b>"
        f"<font style='font-size:32px'>MTK</font></b><br>"
        f"<small><font color='{MUTED}'>MEDIANTEK KILN · MANUFACTURING "
        f"SOLUTIONS</font></small></font></td>"
        f"<td align='right'><b><font color='{NAVY}'><font "
        f"style='font-size:24px'>"
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
        "</table></td></tr>"
        # ---- 2 summary
        f"<tr><td colspan='2'>{_sec('2 · Test Summary')}"
        "<table width='100%' cellspacing='0' cellpadding='6'><tr>"
        f"<td align='center' bgcolor='#f6f8fa'><b><font color='{NAVY}'>"
        f"<font style='font-size:24px'>{len(report.items)}</font></b><br>"
        f"<small><font color='{MUTED}'>ITEMS</font></small></td>"
        f"<td align='center' bgcolor='#f6f8fa'><b><font color='{GREEN}'>"
        f"<font style='font-size:24px'>{n_pass}</font></b><br>"
        f"<small><font color='{MUTED}'>PASS</font></small></td>"
        f"<td align='center' bgcolor='#f6f8fa'><b><font color='{RED}'>"
        f"<font style='font-size:24px'>{n_fail}</font></b><br>"
        f"<small><font color='{MUTED}'>FAIL</font></small></td>"
        f"<td align='center' bgcolor='#f6f8fa'><b><font color='{vc}'>"
        f"<font style='font-size:24px'>{verdict}</font></b><br>"
        f"<small><font color='{MUTED}'>OVERALL</font></small></td>"
        "</tr></table>"
        # ---- verdict / detail mismatch note (never re-judges: the
        # banner only warns the reader to verify the session state)
        + (_conflict_banner(conflict) if conflict else "")
        + "</td></tr>"
        # ---- 3 detail (split per Test Method, 2026-10-16 user
        # direction: impedance / voltage / clock / sequence / other)
        f"<tr><td colspan='2'>{detail_html}</td></tr>"
        # ---- seal (right aligned, between detail and sign-off)
        f"<tr><td colspan='2'>{_sec('4 · Inspection Seal')}"
        "<table width='100%' cellspacing='0' cellpadding='4'><tr>"
        f"<td align='right'><img src='{STAMP_RESOURCE}' width='170' "
        f"height='170'></td></tr></table></td></tr>"
        # ---- sign-off (2026-10-17 user direction: ONLY the MTK
        # signature - no operator / reviewer personal sign-off, users
        # worried about taking responsibility; the tested-by identity
        # stays in section 1 Station / Operator)
        f"<tr><td colspan='2'>{_sec('5 · Sign-off')}"
        "<table width='100%' cellspacing='0' cellpadding='6'><tr>"
        "<td width='55%'>&nbsp;</td>"
        f"<td width='45%' align='center'>"
        f"<font face='{SCRIPT_FONT}' style='font-size:24px' "
        f"color='{INK}'>MTK QA</font>"
        f"<br><hr>"
        f"<small><font color='{MUTED}'>AUTHORIZED SIGNATURE — MTK · "
        f"{esc(f'{when:%Y-%m-%d}')}</font></small></td>"
        "</tr></table></td></tr>"
        # ---- footer
        f"<tr><td colspan='2'><hr><small><font color='{MUTED}'>"
        f"Electronically sealed by MTK GUI — this seal is bound to the "
        f"report data by trace hash<br>sha256 · {esc(digest)}"
        f"</small></td></tr>"
        # close the 5 nested frame tables (content -> white -> navy
        # thin -> white ring -> navy outer)
        + "</table></td></tr>" * 5]

    html = "".join(parts)
    log = report.console_log or ""
    if log.strip():
        html += ("<hr>" + console_log_html(
            log, wrap=console_wrap_chars()))
    # fullPage printing has zero page margins: this white wrapper IS
    # the paper margin (the navy ring would otherwise touch the paper
    # edge and get cut by physical printers)
    return (f"<table width='100%' cellspacing='0' cellpadding='20'>"
            f"<tr><td bgcolor='#ffffff'>{html}</td></tr></table>")


# ------------------------------------------------------------------ name
def safe_name(text: str) -> str:
    """File / folder-name safe: strip Windows-forbidden chars and
    spaces (parentheses etc. are legal on Windows and kept)."""
    for ch in '/\\:*?"<>| ':
        text = text.replace(ch, "-")
    return text.strip("-") or "NA"


# legacy alias
_safe = safe_name


def dut_pdf_name(report, meta=None, when: datetime | None = None) -> str:
    """DUT_[PASS/FAIL]_[Serial#]_[Core ID]_[Project Part#]_[Batch#]_
    [Date]_[Time].pdf (the fixed naming from the spec).  A missing
    Serial Number is SKIPPED - the leading DUT_ prefix already names
    the file type, a second DUT segment would be redundant (2026-10-17
    user direction); missing meta fields fall back to NA."""
    meta = dict(meta or {})
    when = when or datetime.now()
    parts = [f"DUT_{_verdict(report.overall_result)}"]
    if report.serial_no:
        parts.append(safe_name(report.serial_no))
    parts += [safe_name(meta.get("core_id", "")),
              safe_name(meta.get("part", "")),
              safe_name(meta.get("batch", "")),
              f"{when:%Y-%m-%d}_{when:%H-%M-%S}.pdf"]
    return "_".join(p for p in parts if p)


# ------------------------------------------------------------------ pdf
def report_pdf_payload(report, meta=None) -> tuple:
    """(html, {resource_name: QImage}, chart_spec) for one certificate
    - all cheap, GUI-thread work.  The chart_spec carries the raw rail
    data; the WORKER renders the chart + the PDF off-thread, so the
    user can immediately start testing the next DUT."""
    images = {STAMP_RESOURCE: stamp_image(report.overall_result)}
    chart_spec = None
    if getattr(report, "rails", None):
        chart_spec = (list(report.rails), report.rail_duration or 1.0,
                      report.rail_t_start,
                      getattr(report, "virtual", False))
    return dut_report_html(report, meta), images, chart_spec


def _render_pdf(html: str, images: dict, path: Path,
                font_scale: float = 1.0) -> float:
    """Lay out ``html`` and print it to an A4 PDF (safe on a worker
    thread: only QTextDocument / QPdfWriter are touched).

    The renderer does NOT use QTextDocument::print_() - that maps doc
    pixels to paper via the PLATFORM screen dpi (macOS 72 vs Windows
    96), which printed everything 4/3 larger on a Mac and clipped the
    page (the 96624/96317 reports, clipped three times).  Instead a
    QPdfWriter at a FIXED 96 dpi is painted page by page from the paged
    layout, so one doc px is ALWAYS exactly 1/96 inch.  ``font_scale``
    (= 96 / screen dpi, see :func:`screen_font_scale`) keeps the pixel
    layout identical on every platform; the returned value is the
    chosen BASE point size (8 = no shrink).

    AUTO-FIT safety net: if the unconstrained layout is wider than the
    paintable body - some table / token combination will always be able
    to exceed it - the default font shrinks in 0.5 pt steps (8 -> 6 pt)
    until it fits."""
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF, QUrl
    from PySide6.QtGui import (QAbstractTextDocumentLayout, QColor, QFont,
                               QPageLayout, QPageSize, QPainter, QPalette,
                               QTextDocument)
    from PySide6.QtGui import QPdfWriter

    writer = QPdfWriter(str(path))
    writer.setResolution(96)             # 1 doc px = exactly 1/96 inch
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(PAGE_MARGIN_MM, PAGE_MARGIN_MM,
                                    PAGE_MARGIN_MM, PAGE_MARGIN_MM),
                          QPageLayout.Unit.Millimeter)
    body_w = float(writer.width())       # paintable body in doc px
    body_h = float(writer.height())

    def _font(pt: float) -> QFont:
        f = QFont("Arial")
        f.setPointSizeF(pt * font_scale)  # platform-equal pixel size
        return f

    doc = QTextDocument()
    doc.setDefaultFont(_font(8))
    for name, img in images.items():
        doc.addResource(QTextDocument.ResourceType.ImageResource,
                        QUrl(name), img)
    doc.setHtml(html)
    # AUTO-FIT: measure UNCONSTRAINED (no page size yet) so width=100%
    # tables report their minimum, then shrink until the content fits
    chosen = 8.0
    pt = 8.0
    while doc.idealWidth() > body_w - 4 and pt > 6.0:
        pt = max(6.0, pt - 0.5)
        doc.setDefaultFont(_font(pt))
        doc.setHtml(html)
        chosen = pt
    # paged layout: the document flows into body-sized pages
    doc.setPageSize(QSizeF(body_w, body_h))
    n_pages = max(1, doc.pageCount())

    painter = QPainter(writer)
    ctx = QAbstractTextDocumentLayout.PaintContext()
    # PIN THE PRINT PALETTE.  Text in the html that carries no explicit
    # color takes its color from the paint context palette, which
    # defaults to the DESKTOP THEME: under macOS/Windows dark mode that
    # is WHITE text, so the entire table body printed white-on-white and
    # only the <font color=...> spans survived (user: "where is the
    # table content?" - the 96317 report).  QTextDocument::print_()
    # pinned this for us; the QPdfWriter path must do it explicitly.
    paper = QPalette()
    paper.setColor(QPalette.ColorRole.Text, QColor("#000000"))
    paper.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
    paper.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    paper.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    ctx.palette = paper
    layout = doc.documentLayout()
    for i in range(n_pages):
        if i:
            writer.newPage()
        painter.save()
        painter.translate(0.0, -i * body_h)
        ctx.clip = QRectF(0.0, i * body_h, body_w, body_h)
        layout.draw(painter, ctx)
        painter.restore()
    painter.end()
    return chosen


def export_dut_pdf(report, meta=None, path=None) -> Path:
    """Render the certificate into an A4 PDF (synchronous - tests and
    one-off exports; the GUI uses :class:`PdfRenderWorker` instead so
    the rasterization never freezes the UI)."""
    path = Path(path)
    html, images, chart_spec = report_pdf_payload(report, meta)
    if chart_spec:
        images[CHART_RESOURCE] = paint_rails_chart(*chart_spec)
    _render_pdf(html, images, path, font_scale=screen_font_scale())
    return path


class PdfRenderWorker(QThread):
    """Renders one certificate PDF OFF the GUI thread (2026-10-17 user
    direction: the 1200-dpi rasterization froze the UI for seconds AND
    the user must be able to test the next DUT while reports render -
    several workers may run concurrently).  Everything heavy happens
    in run(): the chart QImage and the QPrinter painting; the GUI
    thread only built the html string."""

    done = Signal(str)
    failed = Signal(str)
    #: emitted before done() with the chosen body font size (8 = fit)
    fitted = Signal(float)

    def __init__(self, html: str, images: dict, path,
                 chart_spec=None, parent=None):
        super().__init__(parent)
        self._html = html
        self._images = images
        self._chart_spec = chart_spec
        self._path = Path(path)
        # read the screen dpi on the GUI thread (QGuiApplication statics
        # are not guaranteed thread-safe off the main thread)
        self._font_scale = screen_font_scale()

    def run(self):
        try:
            if self._chart_spec:
                self._images[CHART_RESOURCE] = \
                    paint_rails_chart(*self._chart_spec)
            pt = _render_pdf(self._html, self._images, self._path,
                             font_scale=self._font_scale)
            self.fitted.emit(pt)
            self.done.emit(str(self._path))
        except Exception as e:                   # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")
