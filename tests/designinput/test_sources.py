# -*- coding: utf-8 -*-
"""Source-detection tests (spec: scanned-PDF rejection, native SPF)."""
from __future__ import annotations

import pytest

from mtkgui.gui.designinput.sources import (
    SCANNED_PDF_NOTICE,
    SOURCE_NATIVE_TEXT_SPF,
    SOURCE_SMART_PDF_SPF,
    ScannedPdfError,
    detect_schematic_source,
)


def test_native_spf_by_suffix():
    assert detect_schematic_source(
        "proj/spf-92722_revB.spf",
        extract_text=lambda *a: "never called") == SOURCE_NATIVE_TEXT_SPF


def test_native_txt_by_suffix():
    assert detect_schematic_source(
        "a/b/schematic.txt",
        extract_text=lambda *a: "x") == SOURCE_NATIVE_TEXT_SPF


def test_smart_pdf_with_text_layer():
    assert detect_schematic_source(
        "spf-92722_revB.pdf",
        extract_text=lambda path, pages=5: "some text") \
        == SOURCE_SMART_PDF_SPF


def test_scanned_pdf_rejected_with_fixed_wording():
    with pytest.raises(ScannedPdfError) as exc:
        detect_schematic_source("scan.pdf", extract_text=lambda *a: "")
    assert str(exc.value) == SCANNED_PDF_NOTICE


def test_scanned_pdf_whitespace_only_rejected():
    with pytest.raises(ScannedPdfError):
        detect_schematic_source("scan.pdf",
                                extract_text=lambda *a: "  \n ")


def test_unsupported_extension():
    with pytest.raises(ValueError):
        detect_schematic_source("x.dxf", extract_text=lambda *a: "t")


def test_qtpdf_default_extractor_used_when_no_override():
    """Without an override the bundled QtPdf extractor is used; a
    non-PDF garbage path yields empty text -> scanned rejection."""
    with pytest.raises(ScannedPdfError):
        detect_schematic_source("/nonexistent/x.pdf")
