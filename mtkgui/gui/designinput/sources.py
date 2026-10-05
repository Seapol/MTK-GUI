# -*- coding: utf-8 -*-
"""Schematic source detection (spec B1-01-00 item 1, boundary rule 1).

Two supported schematic inputs:

* native Concept-HDL text SPF (``*.spf`` / ``*.txt``) - structured,
  ``[Component]`` / ``[Net]`` blocks, highest parsing confidence;
* Concept-HDL Publish Smart-PDF (``SPF-xxxx.pdf``) - only the
  extractable text layer is parsed; OCR is forbidden by spec.

A PDF whose text layer is empty is a scanned image and is rejected
with the exact fixed wording required by the spec.
"""
from __future__ import annotations

import os

# spec-fixed wording (do not reword; asserted verbatim in tests)
SCANNED_PDF_NOTICE = (
    "Scanned image-PDF is not supported, please use Concept-HDL "
    "Publish Smart-PDF or native text-SPF.")

SOURCE_NATIVE_TEXT_SPF = "native_text_spf"
SOURCE_SMART_PDF_SPF = "smart_pdf_spf"

_NATIVE_SUFFIXES = (".spf", ".txt")


class ScannedPdfError(ValueError):
    """The schematic PDF has no extractable text layer (scanned image).

    Carries :data:`SCANNED_PDF_NOTICE` verbatim so the GUI can show
    the spec-fixed popup directly."""

    def __init__(self) -> None:
        super().__init__(SCANNED_PDF_NOTICE)


def detect_schematic_source(path: str,
                            extract_text=None) -> str:
    """Classify a schematic file path into a source type.

    Args:
        path:         Schematic file path (.spf / .txt / .pdf).
        extract_text: Optional PDF text extractor override
                      (defaults to the bundled QtPdf extractor);
                      takes the PDF path and returns its text layer.

    Returns:
        ``SOURCE_NATIVE_TEXT_SPF`` for text SPF files, or
        ``SOURCE_SMART_PDF_SPF`` for a PDF with a non-empty text layer.

    Raises:
        ScannedPdfError: The PDF text layer is empty (scanned image).
        ValueError:      Unsupported file extension.
    """
    suffix = os.path.splitext(path)[1].lower()
    if suffix in _NATIVE_SUFFIXES:
        return SOURCE_NATIVE_TEXT_SPF
    if suffix != ".pdf":
        raise ValueError(f"unsupported schematic file type: {suffix}")
    extractor = extract_text
    if extractor is None:
        from mtkgui.gui.yamlbuild.parser import extract_pdf_text
        extractor = extract_pdf_text
    # a readable text layer on the FIRST page is enough to reject the
    # scanned-image case (title block always lives on page one)
    text = extractor(path, 1) if _takes_pages(extractor) else extractor(path)
    if not (text or "").strip():
        raise ScannedPdfError()
    return SOURCE_SMART_PDF_SPF


def _takes_pages(extractor) -> bool:
    """True when the extractor accepts a (path, max_pages) signature."""
    import inspect
    try:
        params = inspect.signature(extractor).parameters
    except (TypeError, ValueError):        # builtins / callables
        return False
    return len(params) >= 2
