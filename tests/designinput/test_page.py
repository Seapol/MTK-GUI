# -*- coding: utf-8 -*-
"""Design-Input page (B1-01-00) GUI tests: load gating, scanned-PDF
interception, auto-fill and manual markers."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from mtkgui.gui.designinput.page import (  # noqa: E402
    MANUAL_MARKER,
    SMART_PDF_MARKER,
    DesignInputPage,
)
from mtkgui.gui.yamlbuild.parser import extract_pdf_text  # noqa: E402

SPF_SAMPLE = """[Drawing]
FRDM-IMXRT700 CPU Board

[Component]
U1 ; MIMXRT798S
U2 ; PF1500

[Net]
3V3 U1.5 U2.VOUT
GND J1.2 U1.1
VPRE U2.VOUT U3.VIN
"""

NET_SAMPLE = """*SIGNAL* 3V3
U1.5 U2.VOUT
*SIGNAL* GND
J1.2 U1.1
*SIGNAL* VPRE
U2.VOUT U3.VIN
"""


@pytest.fixture()
def page(qapp):
    p = DesignInputPage()
    yield p
    p.deleteLater()


@pytest.fixture()
def files(tmp_path):
    spf = tmp_path / "spf-92722_revB.spf"
    spf.write_text(SPF_SAMPLE, encoding="utf-8")
    net = tmp_path / "board.net"
    net.write_text(NET_SAMPLE, encoding="utf-8")
    return str(spf), str(net)


def _load(page, files, monkeypatch):
    """Drive both browse handlers with the file dialogs patched out."""
    spf, net = files
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (spf, "")))
    page._browse_schematic()
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (net, "")))
    page._browse_net()


# ------------------------------------------------------------- gating
def test_parse_button_disabled_until_both_loaded(page):
    assert page.btn_parse.isEnabled() is False
    page._schematic_loaded = True
    page._sync_parse_button()
    assert page.btn_parse.isEnabled() is False      # net still missing
    page._net_loaded = True
    page._sync_parse_button()
    assert page.btn_parse.isEnabled() is True


def test_load_state_captions(page, files, monkeypatch):
    _load(page, files, monkeypatch)
    assert page.lbl_schematic_status.text() == "Schematic: ✔ Loaded"
    assert page.lbl_net_status.text() == "Net: ✔ Loaded"


def test_spf_parse_error_blocks_loading(page, tmp_path, monkeypatch):
    bad = tmp_path / "bad.spf"
    bad.write_text("garbage, no sections", encoding="utf-8")
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(bad), "")))
    page._browse_schematic()
    assert page._schematic_loaded is False
    assert shown and "no [Document]" in shown[0][2]


# ------------------------------------------------- scanned PDF reject
def test_scanned_pdf_rejected_with_fixed_popup(page, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a) or 0)
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: ("scan.pdf", "")))
    # force the QtPdf extractor to see an empty text layer
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.extract_pdf_text",
        lambda path, pages=5: "")
    page._browse_schematic()
    assert shown and shown[0][2] == (
        "Scanned image-PDF is not supported, please use Concept-HDL "
        "Publish Smart-PDF or native text-SPF.")
    assert page._schematic_loaded is False


def test_smart_pdf_status_carries_review_marker(page, tmp_path,
                                                monkeypatch):
    from PySide6.QtGui import QFont, QPainter, QPdfWriter
    pdf_path = tmp_path / "spf-92722_revB.pdf"
    writer = QPdfWriter(str(pdf_path))
    painter = QPainter(writer)
    painter.setFont(QFont("Helvetica", 24))
    painter.drawText(100, 200, "FRDM-MW30-S Sensor Board")
    painter.end()
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: 0)     # never open real popups
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(pdf_path), "")))
    page._browse_schematic()
    assert "✔ Loaded" in page.lbl_schematic_status.text()
    assert SMART_PDF_MARKER in page.lbl_schematic_status.text()


# ---------------------------------------------------------- auto fill
def test_project_name_autofill_from_drawing_title(page, files,
                                                  monkeypatch):
    _load(page, files, monkeypatch)
    assert page.edit_project_name.text() == "FRDM-IMXRT700 CPU Board"
    assert page.lbl_name_marker.text() == ""     # auto, not manual


def test_manual_edit_sets_marker(page, files, monkeypatch):
    _load(page, files, monkeypatch)
    page.edit_project_name.clear()
    page.edit_project_name.setText("My Project")     # programmatic
    assert page.lbl_name_marker.text() == ""         # setText no marker
    # user typing (textEdited) DOES set the marker
    page.edit_project_name.textEdited.emit("My Project")
    assert page.lbl_name_marker.text() == MANUAL_MARKER


def test_core_id_autofill_after_parse(page, files, monkeypatch):
    _load(page, files, monkeypatch)
    page._parse_nets()
    assert page.edit_core_id.text() == "MIMXRT798S"


# ------------------------------------------------------------- parse
def test_parse_produces_draft_and_board_type(page, files, monkeypatch):
    _load(page, files, monkeypatch)
    page._parse_nets()
    assert page.model.net_collection.nets
    assert page.model.candidate_power_tree is not None
    assert not page.model.is_committed               # DRAFT forever here
    assert page.combo_board_type.currentData() == "FULL_SYSTEM_BOARD"


def test_parse_writes_event_log(page, files, monkeypatch):
    lines = []
    page.event_log.connect(lambda level, msg: lines.append((level, msg)))
    _load(page, files, monkeypatch)
    page._parse_nets()
    levels = {level for level, _msg in lines}
    assert "INFO" in levels
    assert any("parse done" in msg for _l, msg in lines)


def test_smart_pdf_parse_warns_review(page, files, tmp_path, monkeypatch):
    """Smart-PDF source raises the review warning during parse."""
    from PySide6.QtGui import QFont, QPainter, QPdfWriter
    pdf_path = tmp_path / "spf-92722_revB.pdf"
    writer = QPdfWriter(str(pdf_path))
    painter = QPainter(writer)
    painter.setFont(QFont("Helvetica", 24))
    painter.drawText(100, 200, "FRDM-MW30-S Sensor Board")
    painter.end()
    lines = []
    page.event_log.connect(lambda level, msg: lines.append((level, msg)))
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: 0)     # never open real popups
    _load(page, files, monkeypatch)              # both inputs loaded
    monkeypatch.setattr(                          # switch source to PDF
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(pdf_path), "")))
    page._browse_schematic()
    page._parse_nets()
    assert any("Smart-PDF" in msg and level == "WARNING"
               for level, msg in lines)


def test_qtpdf_extractor_still_available():
    """The bundled QtPdf extractor import path stays functional."""
    assert callable(extract_pdf_text)
