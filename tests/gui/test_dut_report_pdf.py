# -*- coding: utf-8 -*-
"""Style-A DUT report certificate (user direction 2026-10-16): the
big PASS / FAIL seal + the "Authorized by MTK" sign-off row, rendered
in-app (QTextBrowser) and as the fixed-name A4 PDF export."""
from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QTextDocument  # noqa: E402

from mtkgui.engine.report import DutReport, ReportItem  # noqa: E402
from mtkgui.gui import dut_pdf  # noqa: E402

META = {"part": "FRDM-MCXL255", "core_id": "95308",
        "batch": "B20261016-01"}


def _dut(result="PASS", items=None, serial="SN95308-000123",
         console=""):
    return DutReport(
        serial_no=serial, station_id="STN-01", user="op01",
        overall_result=result, console_log=console,
        items=items or [ReportItem(
            test_name="DCDC_1V0", category="ICT", measured="1.023",
            low="0.95", high="1.05", unit="V", result="PASS")])


# ---------------------------------------------------------------- naming
def test_pdf_name_matches_fixed_pattern():
    name = dut_pdf.dut_pdf_name(_dut(), META)
    assert re.fullmatch(
        r"DUT_PASS_SN95308-000123_95308_FRDM-MCXL255_B20261016-01"
        r"_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.pdf", name)


def test_pdf_name_fail_verdict_and_sanitized_fields():
    report = _dut(result="FAIL", serial='SN/1:2')
    name = dut_pdf.dut_pdf_name(report, {"core_id": "", "part": "a/b",
                                         "batch": "x"})
    # empty fields fall back to NA, unsafe chars collapse to '-'
    assert name.startswith("DUT_FAIL_SN-1-2_NA_a-b_x_")
    assert name.count("_") == 7


def test_pdf_name_skips_missing_serial():
    """2026-10-17 user direction: an empty Serial Number is skipped -
    'DUT_PASS_DUT_...' duplicated the file-type prefix."""
    name = dut_pdf.dut_pdf_name(_dut(serial=""), META)
    assert name.startswith("DUT_PASS_95308_")
    assert "_DUT_" not in name
    html = dut_pdf.dut_report_html(_dut(serial=""), META)
    assert "DUT-PASS-2" in html          # report no skips it too
    assert "-DUT-2" not in html


# ------------------------------------------------------------------ html
def test_certificate_html_carries_seal_and_signoff():
    html = dut_pdf.dut_report_html(
        _dut(items=[
            ReportItem(test_name="DCDC_1V0", category="ICT",
                       measured="1.023", low="0.95", high="1.05",
                       unit="V", result="PASS"),
            ReportItem(test_name="WIFI RSSI", category="RF",
                       duration="1.10", result="PASS")]),
        META)
    assert "DUT TEST REPORT" in html
    assert "SN95308-000123" in html and "FRDM-MCXL255" in html
    assert "95308" in html and "B20261016-01" in html
    # the seal is an image resource, not raw text
    assert f"src='{dut_pdf.STAMP_RESOURCE}'" in html
    # the MTK-only sign-off + trace-hash footer (2026-10-17: no
    # personal Tested / Reviewed signatures - users feared liability)
    assert "AUTHORIZED SIGNATURE — MTK" in html.upper()
    assert "TESTED BY" not in html.upper()
    assert "REVIEWED BY" not in html.upper()
    assert re.search(r"sha256 · [0-9a-f]{64}", html)
    # per-item verdicts keep their green / red coding
    assert dut_pdf.GREEN in html
    # console dump appendix only when a transcript exists
    assert "Console Log" not in html


def test_certificate_html_console_appendix_and_fail():
    html = dut_pdf.dut_report_html(
        _dut(result="FAIL", console="\x1b[31mERR\x1b[0m boom"), META)
    assert "Console Log" in html
    assert "boom" in html            # ANSI escapes stripped by the appendix
    assert "\x1b[" not in html
    assert "DUT-FAIL-" in html       # report no carries the verdict
    assert dut_pdf._verdict("Virtual PASS") == "PASS"


# ----------------------------------------------------------------- seal
def test_stamp_image_renders_for_both_verdicts(qapp):
    for result in ("PASS", "FAIL"):
        img = dut_pdf.stamp_image(result)
        assert not img.isNull()
        assert img.size().width() == 340 and img.size().height() == 340


def test_stamp_resource_resolves_in_qtextdocument(qapp):
    """The preview flow: resource injection + markup -> the document
    resolves the seal image AND lays out an image fragment."""
    doc = QTextDocument()
    doc.addResource(QTextDocument.ResourceType.ImageResource,
                    QUrl(dut_pdf.STAMP_RESOURCE),
                    dut_pdf.stamp_image("PASS"))
    doc.setHtml(dut_pdf.dut_report_html(_dut(), META))
    res = doc.resource(QTextDocument.ResourceType.ImageResource,
                       QUrl(dut_pdf.STAMP_RESOURCE))
    assert not res.isNull()
    # walk the layout: at least one image fragment exists
    block, found = doc.begin(), False
    while block.isValid() and not found:
        it = block.begin()
        while not it.atEnd():
            if it.fragment().charFormat().isImageFormat():
                found = True
            it += 1
        block = block.next()
    assert found


# ------------------------------------------------------------------ pdf
def test_export_dut_pdf_smoke(tmp_path, qapp):
    path = dut_pdf.export_dut_pdf(
        _dut(items=[
            ReportItem(test_name="t", category="ICT", measured="1.0",
                       result="PASS")], console="rx line"),
        META, tmp_path / "dut.pdf")
    data = path.read_bytes()
    assert path.suffix == ".pdf"
    assert data[:4] == b"%PDF"
    assert len(data) > 1000


# ------------------------------------------------- method split + rails
def test_from_session_classifies_ict_methods_and_rails(qapp):
    """kind IS the Test Method; generic 'test' falls back to its unit.
    The rail capture is cloned for the sequence chart."""
    from mtkgui.engine.report import DutReport as DR
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    page.ict_steps = [
        ("Static Impedance", "Imp VDD_3V3", "Ω", "—", "1.0", "—"),
        ("Power Voltage", "VDD_3V3", "V", "—", "3.2", "3.4"),
        ("Clock Hz", "CLK24M", "Hz", "—", "23.9", "24.1"),
        ("DAQ AI", "Power Rails Up Sequence", "V", "—", "—", "—"),
        ("test", "Generic_Net", "V", "—", "3.1", "3.3"),
    ]
    page.ict.setRowCount(len(page.ict_steps))
    for r in range(len(page.ict_steps)):
        page.ict.item(r, 7).setText("PASS")
    rails = [("VDD_3V3", "#38bdf8", 3.3, [0.0, 0.5, 1.0, 1.0])]
    page.rail_widget.set_data(rails, 6.0, -1.0)
    report = DR.from_session(page)
    methods = [i.method for i in report.items]
    assert methods == ["Static Impedance", "Power Voltage", "Clock Hz",
                       "DAQ AI", "Power Voltage"]
    assert report.rails == rails
    assert report.rail_duration == 6.0 and report.rail_t_start == -1.0
    page.deleteLater()


def _rail_report(samples=(0.0, 0.5, 1.0, 1.0), nominal=2.0):
    r = _dut(items=[ReportItem(test_name="Power Rails Up Sequence",
                               category="ICT", method="DAQ AI",
                               result="PASS")])
    r.rails = [("VDD_3V3", "#38bdf8", nominal, list(samples))]
    r.rail_duration = 1.0
    r.rail_t_start = 0.0
    return r


def test_rail_analysis_metrics_math():
    a = dut_pdf.rail_analysis(_rail_report())[0]
    # 10% reached 0.2 samples in, 90% 1.8 samples in; step = 1/3 s
    assert a["rise"] == pytest.approx(1.6 / 3.0)
    assert a["over"] == pytest.approx(0.0)          # flat top, no peak
    # last sample outside the ±5% band is index 1 -> settle = 2 steps
    assert a["settle"] == pytest.approx(2.0 / 3.0)
    assert a["final"] == pytest.approx(2.0)
    assert "in regulation" in a["note"]


def test_rail_analysis_overshoot_and_review():
    a = dut_pdf.rail_analysis(_rail_report(
        samples=(0.0, 0.9, 1.06, 1.0), nominal=1.0))[0]
    assert a["over"] == pytest.approx(6.0)
    assert a["peak"] == pytest.approx(1.06)
    # never-sampled final droop: [0, .9, .92, .5] ends outside the band
    bad = dut_pdf.rail_analysis(_rail_report(
        samples=(0.0, 0.9, 0.92, 0.5)))[0]
    assert bad["settle"] is None and "review" in bad["note"]
    assert bad["ripple_mv"] is None          # no settled window at all


def test_rail_analysis_ripple_in_settled_window():
    """Ripple p-p counts only the settled (±5%) window: the ramp and
    the 1.06 overshoot sample are excluded."""
    a = dut_pdf.rail_analysis(_rail_report(
        samples=(0.0, 0.6, 1.06, 1.0, 0.99, 1.01, 1.0),
        nominal=3.3))[0]
    # settled window = samples 3..6 (1.0, 0.99, 1.01, 1.0) -> 0.02 frac
    assert a["ripple_mv"] == pytest.approx(0.02 * 3.3 * 1000.0)


def test_html_grouped_tables_and_sequence_chart():
    html = dut_pdf.dut_report_html(
        _dut(items=[
            ReportItem(test_name="Imp VDD_3V3", category="ICT",
                       method="Static Impedance", measured="3.21",
                       low="1.0", unit="kΩ", result="PASS"),
            ReportItem(test_name="VDD_3V3", category="ICT",
                       method="Power Voltage", measured="3.30",
                       low="3.2", high="3.4", unit="V", result="PASS"),
            ReportItem(test_name="CLK24M", category="ICT",
                       method="Clock Hz", measured="24.0", low="23.9",
                       high="24.1", unit="MHz", result="PASS"),
            ReportItem(test_name="Power Rails Up Sequence",
                       category="ICT", method="DAQ AI", result="PASS"),
            ReportItem(test_name="WIFI RSSI", category="RF",
                       duration="1.1", result="PASS"),
        ]), META)
    up = html.upper()
    assert "3.1 · IMPEDANCE (ICT)" in up
    assert "3.2 · VOLTAGE (ICT)" in up
    assert "3.3 · CLOCK (ICT)" in up
    assert "3.5 · FLASH / FCT / RF" in up
    # the sequence section exists and, without capture data, is honest
    assert "3.4 · POWER RAILS UP SEQUENCE (DAQ AI)" in up
    assert "NO CAPTURE DATA AVAILABLE" in up
    assert f"src='{dut_pdf.CHART_RESOURCE}'" not in html


def test_html_sequence_chart_with_capture():
    html = dut_pdf.dut_report_html(_rail_report(), META)
    assert f"src='{dut_pdf.CHART_RESOURCE}'" in html
    assert "RISE 10-90%" in html and "OVERSHOOT" in html
    # rail labels are zero-width-breakable at underscores (fit fix)
    assert "VDD_\u200b3V3" in html and "in regulation" in html


def test_verdict_conflict_banner():
    """Overall vs detail mismatch renders a VERDICT NOTE banner; the
    report still never re-judges (B4 §8.1).  'Done' op rows are not
    failures - a PASS session with op rows stays conflict-free."""
    ok = _dut(items=[ReportItem(test_name="t", category="ICT",
                                measured="1.0", result="PASS"),
                     ReportItem(test_name="op", category="FCT",
                                duration="1.0", result="Done")])
    assert dut_pdf.verdict_conflict(ok) is None
    assert "VERDICT NOTE" not in dut_pdf.dut_report_html(ok, META)

    fail = _dut(result="PASS", items=[
        ReportItem(test_name="bad", category="ICT", measured="7.4",
                   result="FAIL")])
    msg = dut_pdf.verdict_conflict(fail)
    assert msg and "1 item(s) did NOT pass" in msg
    html = dut_pdf.dut_report_html(fail, META)
    assert "VERDICT NOTE ·" in html and "verify the session state" in html

    # FAIL overall without any failing item is flagged as well
    odd = _dut(result="FAIL", items=[ReportItem(
        test_name="t", category="ICT", measured="1.0", result="PASS")])
    assert "No failing item found" in dut_pdf.verdict_conflict(odd)
    # a consistent FAIL session is silent
    consistent = _dut(result="FAIL", items=[ReportItem(
        test_name="bad", category="ICT", measured="7.4", result="FAIL")])
    assert dut_pdf.verdict_conflict(consistent) is None
    assert "VERDICT NOTE" not in dut_pdf.dut_report_html(consistent, META)


def test_realistic_report_fits_page_width(qapp):
    """GOLDEN regression (the 96624 report was clipped THREE times):
    the layout is measured exactly like the real pipeline — 8 pt default
    font, real-world adversarial content:
      * the chart AND seal images injected as resources (the blind spot
        that let the third clip slip through: a bare <img> sharing its
        <td> with sibling tables multiplies the image minimum width per
        nesting level - 640px chart -> 920px layout),
      * a console dump with LONG unbreakable tokens (ai_review file
        names, CSV-ish lines) — QTextDocument IGNORES zero-width
        spaces, so the transcript must be hard-wrapped by characters,
      * 37 items with long net names + the real 60-char station string,
      * a 12-rail capture (chart + per-rail analysis),
    and the document must stay inside the A4 text width (~793 px @96
    dpi minus the wrapper padding)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFont, QTextDocument

    def imp(n):
        return ReportItem(test_name=f"Static Impedance - {n}",
                          category="ICT", method="Static Impedance",
                          measured="73.36", low="30", unit="Ω",
                          result="PASS")

    def volt(n):
        return ReportItem(test_name=f"Power Voltage - {n}",
                          category="ICT", method="Power Voltage",
                          measured="12.005", low="11.400", high="12.600",
                          unit="V", result="PASS")

    nets = ["12V0_IN_PWR_EN_B", "12V_DECT_1", "1V2_RGMII_A_AVDDL",
            "1V2_RGMII_A_DVDDL", "1V8_FT4232_1", "1V8_FT4232_2",
            "1V8_FT4232_3", "1V8_RGMII_A_DVDDH", "SPI3_SENT_SEL_1V8",
            "VBAT_SENSE", "VBUS_DET", "VCC_OSC_AUXCLKIN"]
    items = ([imp(n) for n in nets] + [volt(n) for n in nets]
             + [ReportItem(test_name="Clock Hz - CLKGEN2_I2C_ADDR",
                           category="ICT", method="Clock Hz",
                           measured="32,768.3", low="32766.3616",
                           high="32769.6384", unit="Hz", result="PASS")]
             + [ReportItem(test_name=op, category="FCT", duration="0.82",
                           result="Done")
                for op in ("Init Instruments", "Fixture Clamp Down",
                           "Fixture Lock", "Power On DUT")]
             + [ReportItem(test_name="Power Rails Up Sequence",
                           category="ICT", method="DAQ AI",
                           measured="12 Power rails assigned on DAQ "
                                    "channels", result="Virtual PASS")])
    # real console shape: long unbreakable tokens (file names, dumps)
    console = "\n".join([
        "[12:01:02.345] DAQ973A AI acquisition: 12 channels @ 200Hz, "
        "3000 samples/channel, range=+-10V, aperture=0.02s",
        "[12:01:05.678] ICT DAQ AI: 12 rails captured (virtual), CSV "
        "saved (power_rails_S32N79-RDB-S_96624_EVT-(Proto-1)_DUT_"
        "virtual_20261017_120234.csv), AI review (power_rails_S32N79-"
        "RDB-S_96624_EVT-(Proto-1)_DUT_virtual_20261017_120234_ai_"
        "review.txt) -> PASS",
        "[12:01:06.000] dump:" + "A1B2C3D4E5F60718" * 25,   # 400-char wall
    ])
    report = _dut(items=items, console=console)
    report.station_id = "SeapolShenMacBook-Pro.local"   # real 60-char
    report.user = "seapolshenmacpro16"                  # station cell
    report.rails = [(n, "#38bdf8", nom,
                     [0.0, 0.5, 1.0, 0.999, 1.001, 1.0])
                    for n, nom in zip(nets, [1.2, 1.2, 1.8, 1.8, 1.8,
                                             1.8, 12.0, 12.0, 1.8, 3.3,
                                             3.3, 1.1])]
    report.rail_duration = 6.0
    report.rail_t_start = -0.5

    # EXACTLY like the real pipeline: images injected BEFORE setHtml
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Arial", 8))
    doc.addResource(QTextDocument.ResourceType.ImageResource,
                    QUrl(dut_pdf.CHART_RESOURCE),
                    dut_pdf.paint_rails_chart(list(report.rails), 6.0,
                                              -0.5, True))
    doc.addResource(QTextDocument.ResourceType.ImageResource,
                    QUrl(dut_pdf.STAMP_RESOURCE),
                    dut_pdf.stamp_image(report.overall_result))
    doc.setHtml(dut_pdf.dut_report_html(report, META))
    assert doc.idealWidth() <= 760, \
        f"layout too wide: {doc.idealWidth()} px (page ≈ 793 px)"


def test_realistic_report_pdf_never_clips(qapp, tmp_path):
    """END-TO-END with the chart: the real-shaped report (12 rails,
    chart image, 24+ items) must print a PDF whose frame right border
    is INSIDE the page and whose outermost pixel columns stay blank -
    any ink at the paper edge means the layout still overflows."""
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument

    nets = ["12V0_IN_PWR_EN_B", "12V_DECT_1", "1V2_RGMII_A_AVDDL",
            "1V2_RGMII_A_DVDDL", "1V8_FT4232_1", "1V8_FT4232_2",
            "1V8_FT4232_3", "1V8_RGMII_A_DVDDH", "SPI3_SENT_SEL_1V8",
            "VBAT_SENSE", "VBUS_DET", "VCC_OSC_AUXCLKIN"]
    items = ([ReportItem(test_name=f"Static Impedance - {n}",
                         category="ICT", method="Static Impedance",
                         measured="73.36", low="30", unit="Ω",
                         result="PASS") for n in nets]
             + [ReportItem(test_name=f"Power Voltage - {n}",
                           category="ICT", method="Power Voltage",
                           measured="12.005", low="11.400",
                           high="12.600", unit="V", result="PASS")
                for n in nets]
             + [ReportItem(test_name="Power Rails Up Sequence",
                           category="ICT", method="DAQ AI",
                           measured="12 Power rails assigned on DAQ "
                                    "channels", result="Virtual PASS")])
    report = _dut(items=items)
    report.rails = [(n, "#38bdf8", nom,
                     [0.0, 0.5, 1.0, 0.999, 1.001, 1.0])
                    for n, nom in zip(nets, [1.2, 1.2, 1.8, 1.8, 1.8,
                                             1.8, 12.0, 12.0, 1.8, 3.3,
                                             3.3, 1.1])]
    report.rail_duration = 6.0
    report.rail_t_start = -0.5

    path = dut_pdf.export_dut_pdf(report, META, tmp_path / "real.pdf")
    doc = QPdfDocument()
    doc.load(str(path))
    assert doc.pageCount() >= 2          # chart + rail table page exists
    for i in range(doc.pageCount()):
        img = doc.render(i, QSize(952, 1347))    # A4 @ ~115 dpi
        # 1. NO ink in the outermost 3 px of any page (nothing clipped)
        for x in (0, 1, 2, img.width() - 3, img.width() - 2,
                  img.width() - 1):
            for y in range(0, img.height(), 3):
                c = img.pixelColor(x, y)
                assert c.alpha() < 10 or (c.red() > 245 and
                                          c.green() > 245 and
                                          c.blue() > 245), \
                    f"page {i}: ink touches paper edge x={x} - clipped"
        # 2. the navy frame right border exists INSIDE the right half
        right_line = any(
            sum(1 for y in range(0, img.height(), 4)
                if img.pixelColor(x, y).red() < 120
                and img.pixelColor(x, y).blue() < 120) \
            > (img.height() // 4) * 0.5
            for x in range(int(img.width() * 0.75), img.width() - 4))
        assert right_line, \
            f"page {i}: frame right border missing - layout still clips"


def test_autofit_shrinks_for_pathological_content(qapp, tmp_path):
    """END-TO-END auto-fit: pathological content (a 120-char
    unbreakable test name) must shrink the body font AND produce a PDF
    whose frame right border is INSIDE the page (no clipping)."""
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtCore import QSize
    r = _dut(items=[ReportItem(
        test_name="Long-" + "X" * 120, category="ICT",
        method="Static Impedance", measured="73.36", low="30",
        unit="Ω", result="PASS")])
    path = tmp_path / "auto.pdf"
    html, images, chart_spec = dut_pdf.report_pdf_payload(r, META)
    pt = dut_pdf._render_pdf(html, images, path)
    assert pt < 8.0                      # the shrink actually engaged
    assert path.read_bytes()[:4] == b"%PDF"
    doc = QPdfDocument()
    doc.load(str(path))
    img = doc.render(0, QSize(1190, 1684))
    # a vertical frame border line must exist in the RIGHT half
    right_line = any(
        sum(1 for y in range(0, img.height(), 4)
            if img.pixelColor(x, y).red() < 120
            and img.pixelColor(x, y).blue() < 120) > (img.height() // 4) * 0.5
        for x in range(int(img.width() * 0.75), img.width()))
    assert right_line, "frame right border missing - layout still clips"


def test_console_hardwrap_bounds_line_length():
    """The twice-burned mechanism: QTextDocument ignores ZWSP, so the
    console transcript is hard-wrapped by CHARACTER COUNT - no output
    line may exceed the wrap width."""
    from mtkgui.gui.report_export import _hardwrap
    token = "power_rails_S32N79-RDB-S_96624_EVT-(Proto-1)_DUT_virtual"
    wrapped = _hardwrap(token * 5)
    assert max(len(l) for l in wrapped.split("\n")) <= 110
    assert len(wrapped.split("\n")) > 1
    # NOTE (2026-10-17): zero-width-space breaking proved UNRELIABLE in
    # practice (the 96624 report clipped even with ZWSP injected), so
    # the transcript is hard-wrapped by character count — deterministic
    # regardless of Qt's line-breaking implementation details.


def test_section_order_sequence_before_other():
    """3.4 (sequence) prints BEFORE 3.5 (flash / fct / rf)."""
    html = dut_pdf.dut_report_html(
        _dut(items=[
            ReportItem(test_name="Power Rails Up Sequence",
                       category="ICT", method="DAQ AI", result="PASS"),
            ReportItem(test_name="Init Instruments", category="FCT",
                       result="Done"),
        ]), META)
    assert html.index("3.4 · POWER RAILS UP SEQUENCE") \
        < html.index("3.5 · FLASH / FCT / RF")


def test_rails_chart_image(qapp):
    img = dut_pdf.rails_chart_image(_rail_report())
    assert not img.isNull() and img.width() == 1160
    assert dut_pdf.rails_chart_image(_dut()).isNull()


def test_pdf_render_worker_thread(qapp, tmp_path):
    """The GUI path: the worker renders the chart AND the PDF OFF the
    caller thread and reports done / failed - the user can keep
    testing the next DUT while reports render."""
    from PySide6.QtCore import QThread
    from PySide6.QtTest import QTest
    report = _rail_report()          # with rails -> chart_spec set
    html, images, chart_spec = dut_pdf.report_pdf_payload(report, META)
    assert chart_spec is not None    # chart is rendered in the worker
    assert dut_pdf.CHART_RESOURCE not in images
    worker = dut_pdf.PdfRenderWorker(html, images, tmp_path / "w.pdf",
                                     chart_spec)
    assert isinstance(worker, QThread)
    results = []
    worker.done.connect(results.append)
    worker.start()
    deadline = 15_000  # ms
    while not results and deadline > 0:
        QTest.qWait(100)
        deadline -= 100
    worker.wait()
    assert results and (tmp_path / "w.pdf").read_bytes()[:4] == b"%PDF"
    # the chart image landed in the worker's own resource dict
    assert not worker._images[dut_pdf.CHART_RESOURCE].isNull()
