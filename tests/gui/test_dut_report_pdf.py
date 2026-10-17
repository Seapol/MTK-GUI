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
    # the MTK sign-off row + trace-hash footer
    assert "AUTHORIZED BY MTK" in html.upper()
    assert "TESTED BY" in html.upper() and "REVIEWED BY" in html.upper()
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
def test_stamp_pixmap_renders_for_both_verdicts(qapp):
    for result in ("PASS", "FAIL"):
        pm = dut_pdf.stamp_pixmap(result)
        assert not pm.isNull()
        assert pm.size().width() == 340 and pm.size().height() == 340


def test_stamp_resource_resolves_in_qtextdocument(qapp):
    """The preview flow: resource injection + markup -> the document
    resolves the seal image AND lays out an image fragment."""
    doc = QTextDocument()
    doc.addResource(QTextDocument.ResourceType.ImageResource,
                    QUrl(dut_pdf.STAMP_RESOURCE),
                    dut_pdf.stamp_pixmap("PASS"))
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


def test_realistic_report_fits_page_width(qapp):
    """Regression (user PDF 2026-10-17, 96624 run): the 9-column
    analysis table's minimum width pushed the whole document layout
    past the paper edge, clipping the right ~15% of every page.  With
    long real-world net names and a 12-rail capture the layout MUST
    stay inside the A4 text width (~793 px @96 dpi minus wrapper)."""
    from PySide6.QtGui import QTextDocument

    def mk(name, m, measured, lo, hi, unit):
        return ReportItem(test_name=name, category="ICT", method=m,
                          measured=measured, low=lo, high=hi, unit=unit,
                          result="PASS")
    report = _dut(items=[
        mk("Static Impedance - 12V0_IN_PWR_EN_B", "Static Impedance",
           "58.39", "30", "", "Ω"),
        mk("Power Voltage - 12V0_IN_PWR_EN_B", "Power Voltage",
           "12.004", "11.400", "12.600", "V"),
        mk("Clock Hz - CLKGEN2_I2C_ADDR", "Clock Hz", "32,768.3",
           "32766.3616", "32769.6384", "Hz"),
        ReportItem(test_name="Power Rails Up Sequence", category="ICT",
                   method="DAQ AI", measured="12 Power rails assigned",
                   result="Virtual PASS"),
        ReportItem(test_name="Init Instruments", category="FCT",
                   duration="", result="Done"),
    ])
    report.rails = [(f"1V2_RGMIIL_A_AVDDL{i}", "#38bdf8", 1.2,
                     [0.0, 0.5, 1.0, 1.0]) for i in range(12)]
    report.rail_duration = 6.0
    report.rail_t_start = -1.0
    doc = QTextDocument()
    doc.setHtml(dut_pdf.dut_report_html(report, META))
    assert doc.idealWidth() <= 760, \
        f"layout too wide: {doc.idealWidth()} px (page ≈ 793 px)"


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


def test_rails_chart_pixmap(qapp):
    pm = dut_pdf.rails_chart_pixmap(_rail_report())
    assert not pm.isNull() and pm.width() == 1160
    assert dut_pdf.rails_chart_pixmap(_dut()).isNull()
