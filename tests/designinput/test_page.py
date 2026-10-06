# -*- coding: utf-8 -*-
"""Design-Input page (B1-01-00) GUI tests.

IMPORT / PARSE split contract:
* browse buttons only read the file bytes (IMPORT, no structure
  resolve, model untouched);
* "Parse nets for ICT" runs the explicit PARSE step with real-time
  progress + Event-Log step detail; parse errors are never silent
  (exact stage + reason logged and shown)."""
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


def test_load_state_captions_imported(page, files, monkeypatch):
    """IMPORT step: the captions show 'Imported' (not parsed yet)."""
    _load(page, files, monkeypatch)
    assert page.lbl_schematic_status.text() == "Schematic: ✔ Imported"
    assert page.lbl_net_status.text() == "Net: ✔ Imported"


def test_import_reads_bytes_only(page, files, monkeypatch):
    """IMPORT must not resolve structures: model + project name stay
    untouched after both imports."""
    _load(page, files, monkeypatch)
    assert page._schematic_text is not None         # bytes in memory
    assert page.model.component_library.records == []
    assert page.model.net_collection.nets == []
    assert page.edit_project_name.text() == ""
    assert page._parsed is False


def test_import_missing_file_reports_reason(page, tmp_path,
                                             monkeypatch):
    """A vanished / unreadable file fails loudly with the reason."""
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k:
                     (str(tmp_path / "nope.spf"), "")))
    page._browse_schematic()
    assert page._schematic_loaded is False
    assert shown and "schematic import failed" in shown[0][2]


def test_import_empty_netlist_reports_reason(page, tmp_path,
                                             monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)
    empty = tmp_path / "empty.net"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(empty), "")))
    page._browse_net()
    assert page._net_loaded is False
    assert shown and "is empty" in shown[0][2]


# ------------------------------------------------- scanned PDF reject
def test_scanned_pdf_rejected_at_parse_with_fixed_popup(
        page, tmp_path, monkeypatch):
    """Scanned-image PDFs import fine (bytes only) and are rejected at
    the PARSE step with the spec-fixed wording popup."""
    shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a) or 0)
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)
    scan = tmp_path / "scan.pdf"
    scan.write_bytes(b"%PDF-1.4 scanned image\n")
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(scan), "")))
    page._browse_schematic()                        # IMPORT: bytes only
    assert page._schematic_loaded is True
    net = tmp_path / "board.net"
    net.write_text("*SIGNAL* 3V3\nU1.5 U2.VOUT\n", encoding="utf-8")
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(net), "")))
    page._browse_net()
    assert page._net_loaded is True
    # force the QtPdf extractor to see an empty text layer (PARSE step)
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.extract_pdf_text",
        lambda path, pages=5: "")
    page._parse_nets()
    assert page._parsed is False
    assert shown and shown[0][2] == (
        "Scanned image-PDF is not supported, please use Concept-HDL "
        "Publish Smart-PDF or native text-SPF.")


def test_spf_parse_error_blocks_parse_with_reason(page, tmp_path,
                                                  monkeypatch):
    """A broken SPF imports fine and fails at PARSE with the exact
    parser reason (no silent fail)."""
    bad = tmp_path / "bad.spf"
    bad.write_text("garbage, no sections", encoding="utf-8")
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: shown.append(a) or 0)
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(bad), "")))
    page._browse_schematic()
    net = tmp_path / "board.net"
    net.write_text("*SIGNAL* 3V3\nU1.5 U2.VOUT\n", encoding="utf-8")
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(net), "")))
    page._browse_net()
    page._parse_nets()
    assert page._parsed is False
    assert shown and "no [Document]" in shown[0][2]
    assert "schematic parse failed" in shown[0][2]


def test_smart_pdf_status_carries_review_marker(page, files,
                                                monkeypatch):
    from PySide6.QtGui import QFont, QPainter, QPdfWriter
    pdf_path = files[0] + ".pdf"
    writer = QPdfWriter(pdf_path)
    painter = QPainter(writer)
    painter.setFont(QFont("Helvetica", 24))
    painter.drawText(100, 200, "FRDM-MW30-S Sensor Board")
    painter.end()
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: 0)     # never open real popups
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (pdf_path, "")))
    page._browse_schematic()
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (files[1], "")))
    page._browse_net()
    page._parse_nets()
    assert "✔ Parsed" in page.lbl_schematic_status.text()
    assert SMART_PDF_MARKER in page.lbl_schematic_status.text()


# ---------------------------------------------------------- auto fill
def test_project_name_autofill_from_drawing_title(page, files,
                                                  monkeypatch):
    _load(page, files, monkeypatch)
    page._parse_nets()                       # name resolves at PARSE
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
    # step detail: all four parse stages are logged
    for step in ("step 1/4", "step 2/4", "step 3/4", "step 4/4"):
        assert any(step in msg for _l, msg in lines), step


def test_parse_progress_bar_reaches_done(page, files, monkeypatch):
    """Real-time progress: 0 before, 100 'done' after the parse."""
    _load(page, files, monkeypatch)
    assert page.progress.value() == 0
    page._parse_nets()
    assert page.progress.value() == 100
    assert "done" in page.progress.format()


def test_parse_failure_resets_progress(page, tmp_path, monkeypatch):
    """A parse failure resets the progress bar and logs ERROR."""
    bad = tmp_path / "bad.spf"
    bad.write_text("garbage, no sections", encoding="utf-8")
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: 0)
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(bad), "")))
    page._browse_schematic()
    net = tmp_path / "board.net"
    net.write_text("*SIGNAL* 3V3\nU1.5 U2.VOUT\n", encoding="utf-8")
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(net), "")))
    page._browse_net()
    lines = []
    page.event_log.connect(lambda level, msg: lines.append(
        (level, msg)))
    page._parse_nets()
    assert page.progress.value() == 0
    assert any(level == "ERROR" and "schematic parse failed" in msg
               for level, msg in lines)


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
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(pdf_path), "")))
    page._browse_schematic()
    monkeypatch.setattr(
        "mtkgui.gui.designinput.page.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (files[1], "")))
    page._browse_net()
    page._parse_nets()
    assert any("Smart-PDF" in msg and level == "WARNING"
               for level, msg in lines)


def test_qtpdf_extractor_still_available():
    """The bundled QtPdf extractor import path stays functional."""
    assert callable(extract_pdf_text)
