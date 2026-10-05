# -*- coding: utf-8 -*-
"""Smart-PDF text-stream parser tests (no OCR, regex recovery)."""
from __future__ import annotations

from mtkgui.gui.designinput.pdf_schematic import parse_pdf_schematic

PDF_TEXT_SAMPLE = """NXP Semiconductor
Drawing Title: FRDM-MW30-S Sensor Board
U1 MIMXRT798S
U2 PF1500
R2 10K
TP1
"""


def test_recovers_refdes_and_parts():
    data = parse_pdf_schematic(PDF_TEXT_SAMPLE)
    refdes = [r for r, _p in data.components]
    assert "U1" in refdes and "U2" in refdes and "TP1" in refdes
    assert refdes.index("U1") < refdes.index("U2")


def test_drawing_title_label_wins():
    data = parse_pdf_schematic(PDF_TEXT_SAMPLE)
    assert data.drawing_title == "FRDM-MW30-S Sensor Board"


def test_fallback_title_first_line():
    data = parse_pdf_schematic("NXP Semiconductor\nU1 ABC123")
    assert data.drawing_title == "NXP Semiconductor"


def test_meta_title_recorded():
    data = parse_pdf_schematic("", meta_title="SPF-92722 rev B")
    assert data.meta_title == "SPF-92722 rev B"


def test_blank_text_never_raises():
    data = parse_pdf_schematic("")
    assert data.components == [] and data.drawing_title == ""
