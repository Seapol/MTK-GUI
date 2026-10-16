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
