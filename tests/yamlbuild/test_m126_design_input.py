# -*- coding: utf-8 -*-
"""M126 - Design Input node: two-column meta, revision dropdowns,
side-by-side ICT / FCT blocks, route clearing, FCT defaults.

Owner report (2026-11-25): the Product Information rows were one
column (every field as wide as the dialog), FSW/HW were free text,
Design Files for ICT / Pre-Configure for FCT stacked full width, "A/B/C"
did not say Route, a disabled block only greyed its controls, and the
FCT list had no standard / FCT-specific split nor select-all shortcuts.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QInputDialog,
    QRadioButton,
)

from mtkgui.gui.yamlbuild.design_input_panel import (  # noqa: E402
    FCT_DEFAULT_TESTS,
    FCT_SPECIFIC_TESTS,
    FCT_STANDARD_TESTS,
    DesignInputPanel,
    REVISION_CHOICES,
    REVISION_CUSTOMIZED,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    w = DesignInputPanel()
    yield w
    w.deleteLater()


def _full(panel, **extra):
    data = {"part_number": "S32N79-RDB-S", "product_id": "96624",
            "sw_version": "Rev C", "hw_version": "Rev B",
            "batch": "EVT (Proto-1)", "ict_block_enabled": "true",
            "fct_block_enabled": "true", "dut_board_software": "linux"}
    data.update(extra)
    panel.set_values(data)
    return panel


# ----------------------------------------------------------- revisions
def test_revision_dropdown_offers_rev_a_to_h_and_customized(panel):
    for combo in (panel.combo_sw_revision, panel.combo_hw_revision):
        items = [combo.itemText(i) for i in range(combo.count())]
        assert items == list(REVISION_CHOICES) + [REVISION_CUSTOMIZED]
        assert combo.currentIndex() == -1, "nothing picked on a fresh panel"


def test_revision_choice_round_trips_through_values(panel):
    _full(panel, sw_version="Rev E", hw_version="Rev G")
    assert panel.values()["sw_version"] == "Rev E"
    assert panel.values()["hw_version"] == "Rev G"


def test_legacy_revision_text_is_shown_verbatim(panel, monkeypatch):
    _full(panel, sw_version="1.0.3", hw_version="Rev C-2")
    data = panel.values()
    assert data["sw_version"] == "1.0.3"
    assert data["hw_version"] == "Rev C-2"
    assert panel.combo_sw_revision.currentText() == "1.0.3"


def test_customized_revision_asks_for_text(panel, monkeypatch):
    asked: list = []

    def fake(parent, title, label, text=""):
        asked.append(text)
        return "Rev Pre-B", True

    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: fake(*a, **k)))
    panel.combo_sw_revision.setCurrentText(REVISION_CUSTOMIZED)
    panel._on_revision_activated(panel.combo_sw_revision)
    assert asked == [""]
    assert panel.values()["sw_version"] == "Rev Pre-B"


def test_customized_revision_cancel_keeps_the_previous_value(panel,
                                                           monkeypatch):
    _full(panel, sw_version="Rev B")
    panel.combo_sw_revision.setCurrentText(REVISION_CUSTOMIZED)
    monkeypatch.setattr(
        QInputDialog, "getText",
        staticmethod(lambda *a, **k: ("", False)))
    panel._on_revision_activated(panel.combo_sw_revision)
    assert panel.values()["sw_version"] == "Rev B"


# --------------------------------------------------------------- layout
def test_ict_and_fct_blocks_share_one_row(panel):
    panel.resize(900, 600)
    panel.show()
    QApplication.processEvents()
    ict = panel._ict_body.parentWidget()
    fct = panel._fct_body.parentWidget()
    row_top_ict = ict.mapTo(panel, ict.rect().topLeft()).y()
    row_top_fct = fct.mapTo(panel, fct.rect().topLeft()).y()
    assert abs(row_top_ict - row_top_fct) <= 2, "blocks must sit side by side"
    assert ict.width() > 100 and fct.width() > 100
    panel.hide()


def test_route_labels_spell_out_route(panel):
    assert panel.radio_files.text() == "Route A - SPF + NET + BoM"
    assert panel.radio_excel.text() == (
        "Route B - ICT Excel Spreadsheet (Traditional)")
    assert panel.radio_mtk.text() == "Route C - MTK ICT Excel Sheet"


def test_routes_are_stacked_top_to_bottom(panel):
    panel.show()
    QApplication.processEvents()
    ys = [r.mapTo(panel, r.rect().topLeft()).y()
          for r in (panel.radio_files, panel.radio_excel, panel.radio_mtk)]
    assert ys == sorted(ys) and len(set(ys)) == 3
    panel.hide()


# ------------------------------------------------------- disabled look
def test_disable_greys_every_glyph(panel):
    panel.chk_ict.setChecked(False)
    assert not panel._ict_body.isEnabled()
    assert "color" in panel._ict_body.styleSheet()
    panel.chk_ict.setChecked(True)
    assert panel._ict_body.isEnabled()
    assert panel._ict_body.styleSheet() == ""


def test_disable_greys_the_card_caption_too(panel):
    """The coloured card caption above a grey card still reads enabled."""
    panel.chk_ict.setChecked(False)
    assert "QGroupBox::title" in panel._ict_box.styleSheet()
    panel.chk_ict.setChecked(True)
    assert panel._ict_box.styleSheet() == ""
    panel.chk_fct.setChecked(False)
    assert "QGroupBox::title" in panel._fct_box.styleSheet()


def test_disable_greys_the_fct_block_too(panel):
    panel.chk_fct.setChecked(False)
    assert not panel._fct_body.isEnabled()
    assert "color" in panel._fct_body.styleSheet()
    # a colour rule alone would leave the accent check marks vivid
    assert "QCheckBox::indicator:checked:disabled" \
        in panel._fct_body.styleSheet()
    panel.chk_fct.setChecked(True)
    assert panel._fct_body.isEnabled()


def test_unchosen_routes_grey_out_entirely(panel):
    _full(panel, ict_route="excel")
    assert panel._files_route.isEnabled() is False
    assert panel._mtk_route.isEnabled() is False
    assert panel._excel_route.isEnabled() is True
    for radio, grey in ((panel.radio_files, True),
                        (panel.radio_excel, False),
                        (panel.radio_mtk, True)):
        assert bool(radio.styleSheet()) is grey


# --------------------------------------------------------- route clear
def test_switching_route_clears_the_imported_files(panel):
    _full(panel)
    panel.spf_path = "s.spf"
    panel.net_path = "n.net"
    panel.bom_path = "b.csv"
    panel._ict_excel_path = "x.xlsx"
    panel._mtk_sheet_path = "m.xlsx"
    logs: list = []
    panel.task_log.connect(lambda _lvl, msg: logs.append(msg))
    panel.radio_mtk.setChecked(True)
    assert panel.spf_path == panel.net_path == panel.bom_path == ""
    assert panel._ict_excel_path == panel._mtk_sheet_path == ""
    assert panel.lbl_spf.text() == "SPF: (not imported)"
    assert panel.lbl_mtk.text() == "Sheet: (not imported)"
    assert panel.values()["spf_file"] == ""
    assert any("cleared" in msg for msg in logs)


def test_loading_a_project_keeps_its_files(panel, tmp_path):
    sheet = tmp_path / "a.xlsx"
    sheet.write_bytes(b"x")
    _full(panel, ict_route="mtk_sheet", ict_mtk_sheet_file=str(sheet))
    assert panel._mtk_sheet_path == str(sheet)
    assert panel.values()["ict_route"] == "mtk_sheet"
    assert panel.values()["ict_mtk_sheet_file"] == str(sheet)


# ------------------------------------------------------------ fct list
def test_fct_defaults_follow_the_board_software(panel):
    _full(panel, dut_board_software="linux")
    assert all(c.isChecked() for c in panel._fct_type_checks.values())
    panel.combo_board_software.setCurrentText("bare_metal")
    panel._on_board_software_changed(panel.combo_board_software.currentIndex())
    ticks = {k for k, c in panel._fct_type_checks.items() if c.isChecked()}
    assert ticks == {"console", "message"}
    panel.combo_board_software.setCurrentText("slave_daughter")
    panel._on_board_software_changed(panel.combo_board_software.currentIndex())
    ticks = {k for k, c in panel._fct_type_checks.items() if c.isChecked()}
    assert ticks == {"message"}


def test_fct_defaults_only_when_the_yaml_has_no_value(panel):
    panel.set_values({"part_number": "P", "product_id": "C",
                      "sw_version": "Rev A", "hw_version": "Rev A",
                      "batch": "EVT (Proto-1)",
                      "dut_board_software": "linux"})
    assert all(c.isChecked() for c in panel._fct_type_checks.values())
    # an explicit empty string means "all off" and must survive a load
    panel.set_values({"part_number": "P", "product_id": "C",
                      "sw_version": "Rev A", "hw_version": "Rev A",
                      "batch": "EVT (Proto-1)",
                      "dut_board_software": "linux",
                      "fct_supported_tests": ""})
    assert not any(c.isChecked() for c in panel._fct_type_checks.values())


def test_select_all_and_select_none_buttons(panel):
    panel.btn_fct_none.click()
    assert panel.values()["fct_supported_tests"] == ""
    panel.btn_fct_all.click()
    ticks = set(panel.values()["fct_supported_tests"].splitlines())
    assert ticks == set(FCT_STANDARD_TESTS) | set(FCT_SPECIFIC_TESTS)


def test_all_off_is_a_legal_configuration(panel, tmp_path):
    for name in ("s.spf", "n.net", "b.csv"):
        (tmp_path / name).write_bytes(b"x")
    _full(panel, spf_file=str(tmp_path / "s.spf"),
          net_file=str(tmp_path / "n.net"),
          bom_file=str(tmp_path / "b.csv"))
    panel.btn_fct_none.click()
    ok, message = panel.validate()
    assert ok, message


def test_fct_list_is_split_into_standard_and_specific_groups(panel):
    labels = [w.text() for w in panel.findChildren(QRadioButton)]
    assert "Route A - SPF + NET + BoM" in labels
    assert len(FCT_STANDARD_TESTS) + len(FCT_SPECIFIC_TESTS) \
        == len(panel._fct_type_checks)
    assert not set(FCT_STANDARD_TESTS) & set(FCT_SPECIFIC_TESTS)
    assert set(FCT_DEFAULT_TESTS["bare_metal"]) == {"console", "message"}
