# -*- coding: utf-8 -*-
"""M7 GUI: DIO op catalog / step editor / template cleanup / YAML /
isolation dialog / 96317 capacity (offscreen).

A7: the "DUT GPIO (24 ch)" walking template row is gone and the 96317
allocation reports ``gpio=24 (+4 over capacity)``.
A8: both DIO ops round-trip through the project YAML and are listed in
the step-insertion dropdown.
A9: the STRONG modal defaults to Cancel and offers Force-Continue.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

import yaml  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox,  # noqa: E402
                               QDialog, QLineEdit, QMessageBox)

from mtkgui.gui.yamlbuild.channel_allocation import (  # noqa: E402
    ChannelAllocationPage)
from mtkgui.ict.netparse import parse_nets_file  # noqa: E402
from mtkgui.ict.netparse.bom import load_bom_library  # noqa: E402
from mtkgui.project_config import apply_config, build_config  # noqa: E402
from mtkgui.test_workflow_page import (ICT_STEPS,  # noqa: E402
                                       TestWorkFlowPage,
                                       _SequenceEditorDialog)

REPO = Path(__file__).resolve().parents[2]
NET_96317 = REPO / "tests" / "yamlbuild" / "fixtures" / "NET-96317_A.net"
BOM_96317 = REPO / "projects" / "96317" / "BOM-750-96317.xlsx"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Equip:
    configs = {}


class _Model:
    def __init__(self, testable):
        self.imported = {"testable_nets": testable}
        self.channel_allocation = {}


def test_template_row_removed():
    import mtkgui.test_workflow_page as twp
    assert not any(step[0] == "test" and step[1] == "DUT GPIO (24 ch)"
                   for step in ICT_STEPS)
    assert "DUT GPIO" not in (twp.__doc__ or "")


def test_step_editor_catalog_and_dio_out_params(qapp, monkeypatch):
    step = ("op", "U2355A DIO Read", "—", "—", "—", "—",
            {"type": "dio_read"})
    dlg = _SequenceEditorDialog("ict", [step], [True], [100], [5000])
    seen = {}

    def fake_exec(widget):
        op_combo = next(cb for cb in widget.findChildren(QComboBox)
                        if "U2355A DIO Write" in
                        [cb.itemText(i) for i in range(cb.count())])
        seen["items"] = [op_combo.itemText(i)
                         for i in range(op_combo.count())]
        op_combo.setCurrentText("U2355A DIO Write")   # rebuild the form
        edits = {le.placeholderText(): le
                 for le in widget.findChildren(QLineEdit)}
        edits["e.g. DIO01-DIO08"].setText("DIO01-DIO04")
        edits["hex (0x3C) or DIO01=1,DIO03=0"].setText("0x0A")
        return QDialog.DialogCode.Accepted

    try:
        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        assert "U2355A DIO Read" in seen["items"]
        assert "U2355A DIO Write" in seen["items"]
        params = dlg._steps[0][6]
        assert params == {"type": "dio_out", "channels": "DIO01-DIO04",
                          "pattern": "0x0A"}
    finally:
        dlg.deleteLater()


def test_yaml_round_trips_both_ops(qapp, tmp_path):
    page = TestWorkFlowPage()
    try:
        read = ("op", "U2355A DIO Read", "—", "—", "—", "—",
                {"type": "dio_read"})
        write = ("op", "U2355A DIO Write", "—", "—", "—", "—",
                 {"type": "dio_out", "channels": "DIO01-DIO08",
                  "pattern": "0x3C"})
        for step in (read, write):
            page.ict_steps.append(step)
            page.ict_enables.append(True)
            page.ict_waits.append(100)
            page.ict_timeouts.append(5000)
        config = build_config(page, _Equip())
        cases = config["test_workflow"]["ict_test_cases"][-2:]
        assert cases[0]["op_params"]["type"] == "dio_read"
        assert cases[1]["op_params"]["type"] == "dio_out"
        yaml_file = tmp_path / "plan.yaml"
        yaml_file.write_text(yaml.safe_dump(config), encoding="utf-8")

        fresh = TestWorkFlowPage()
        try:
            apply_config(yaml.safe_load(yaml_file.read_text(
                encoding="utf-8")), fresh, _Equip())
            types = [step[6].get("type") for step in fresh.ict_steps
                     if step[0] == "op" and len(step) > 6 and step[6]]
            assert "dio_read" in types
            assert "dio_out" in types
        finally:
            fresh.deleteLater()
    finally:
        page.deleteLater()


def test_96317_capacity_line(qapp):
    lib, _report, _bom = load_bom_library(str(BOM_96317))
    result = parse_nets_file(str(NET_96317), library=lib)
    testable = {}
    for category, records in (("Power", result.power),
                              ("Clock", result.clock),
                              ("GPIO", result.gpio)):
        for rec in records:
            testable[rec.name] = {"category": category,
                                  "members": list(rec.members),
                                  "isolated": rec.isolated,
                                  "active_drivers": list(rec.active_drivers)}
    page = ChannelAllocationPage()
    try:
        page.set_model(_Model(testable))
        page.auto_allocate()
        text = page.lbl_summary.text()
        assert "gpio=24 (+4 over capacity)" in text
    finally:
        page.deleteLater()


def test_strong_modal_cancel_default_and_force_button(qapp, monkeypatch):
    page = TestWorkFlowPage()
    captured = {}

    def fake_exec(box):
        captured["default"] = box.defaultButton().text()
        captured["buttons"] = [b.text() for b in box.buttons()]
        return 0

    try:
        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
        verdict = page._dio_write_preflight_dialog([
            {"net": "SOC_RST0", "isolated": False,
             "active_drivers": ["U1"]}])
        assert verdict == "cancel"                 # no click -> Cancel
        assert captured["default"] == "Cancel"
        assert "Force-Continue" in captured["buttons"]
    finally:
        page.deleteLater()
