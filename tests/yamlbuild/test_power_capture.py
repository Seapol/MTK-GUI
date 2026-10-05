# -*- coding: utf-8 -*-
"""M0 block-03 power waveform capture list tests: 12-net limit,
auto pre-select, manual finalize, read-only handover to block 04."""
from __future__ import annotations

import pytest
import yaml

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.designinput.netlist import (  # noqa: E402
    power_capture_candidates,
)
from mtkgui.gui.yamlbuild.blocks import (  # noqa: E402
    CAPTURE_FIELD,
    MAX_CAPTURE_NETS,
    BlockConfigDialog,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.gui.yamlbuild.schema import fields_for  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


NETS = ["3V3", "VDD_CORE", "VPRE", "1V8", "VDD_IO", "GND", "SDA",
        "CLK_24M", "5V", "VDDQ", "AVDD", "VBUS", "PP12V", "VOUT_SYS",
        "SDA1"]


# ------------------------------------------------------------ candidates
def test_candidates_power_only_capped_at_12():
    picks = power_capture_candidates(NETS)
    assert len(picks) <= 12
    assert "GND" not in picks and "SDA" not in picks \
        and "CLK_24M" not in picks
    assert "3V3" in picks and "VDD_CORE" in picks


def test_candidates_respect_custom_limit():
    assert len(power_capture_candidates(NETS, 3)) == 3


# ---------------------------------------------------------------- schema
def test_capture_field_only_in_block03():
    """The capture list is defined ONLY in block 03's schema - block 04
    (rails) and every other block cannot edit it (read-only handover)."""
    spec_names = {f.name for f in fields_for("parse_ict")}
    assert CAPTURE_FIELD in spec_names
    for key, specs in ((k, fields_for(k)) for k in
                       ("rails", "instruments", "clocks", "gpios",
                        "fct_build", "validate_sequence",
                        "preview_export")):
        assert CAPTURE_FIELD not in {f.name for f in specs}, key


def test_capture_field_max_lines_12():
    spec = {f.name: f for f in fields_for("parse_ict")}[CAPTURE_FIELD]
    assert spec.max_lines == 12
    ok = "\n".join(f"NET{i}" for i in range(12))
    assert spec.validate(ok) == ""
    bad = "\n".join(f"NET{i}" for i in range(13))
    assert "at most 12" in spec.validate(bad)


# ---------------------------------------------------------------- dialog
def test_dialog_autoprefills_from_candidates(qapp):
    model = YamlBuildModel()
    dlg = BlockConfigDialog("parse_ict", model.get_params("parse_ict"),
                            power_candidates=NETS)
    try:
        text = dlg._editors[CAPTURE_FIELD].toPlainText()
        picks = [ln for ln in text.splitlines() if ln.strip()]
        assert 0 < len(picks) <= 12
        assert "3V3" in picks
    finally:
        dlg.deleteLater()


def test_dialog_preserves_user_finalized_list(qapp):
    """A saved (finalized) capture list is never overwritten by the
    auto pre-fill on reopen."""
    model = YamlBuildModel()
    model.set_params("parse_ict", {CAPTURE_FIELD: "VDD_CORE\n1V8"})
    dlg = BlockConfigDialog("parse_ict", model.get_params("parse_ict"),
                            power_candidates=NETS)
    try:
        assert dlg._editors[CAPTURE_FIELD].toPlainText() == \
            "VDD_CORE\n1V8"
    finally:
        dlg.deleteLater()


def test_dialog_accept_rejects_13_nets(qapp, monkeypatch):
    """Manual add beyond the 12-net limit blocks the save (all-or-
    nothing)."""
    monkeypatch.setattr(
        "mtkgui.gui.yamlbuild.blocks.QMessageBox.warning",
        lambda *a, **k: 0)               # never open a real popup
    model = YamlBuildModel()
    params = model.get_params("parse_ict")
    params[CAPTURE_FIELD] = "\n".join(f"NET{i}" for i in range(13))
    dlg = BlockConfigDialog("parse_ict", params)
    try:
        dlg._on_accept()
        # rejected: the error list is shown and accept() was never
        # reached (the dialog stays open - all-or-nothing save)
        assert "at most 12" in dlg.error_label.text()
    finally:
        dlg.deleteLater()


def test_dialog_manual_add_remove_and_finalize(qapp, monkeypatch):
    """The user can add / remove lines then save - the edited list
    lands in the validated values."""
    monkeypatch.setattr(
        "mtkgui.gui.yamlbuild.blocks.QMessageBox.warning",
        lambda *a, **k: 0)
    dlg = BlockConfigDialog(
        "parse_ict", {"netlist_file": "design.net"},
        power_candidates=NETS)
    try:
        editor = dlg._editors[CAPTURE_FIELD]
        # manual: remove everything, hand-pick two nets, finalize
        editor.setPlainText("VDDQ\nAVDD")
        dlg._on_accept()
        assert dlg.error_label.text() == ""      # accepted cleanly
        assert dlg.values()[CAPTURE_FIELD] == "VDDQ\nAVDD"
    finally:
        dlg.deleteLater()


# ------------------------------------------------------------------ flow
def test_effective_yaml_hands_capture_list_to_block04_readonly():
    """The finalized list is emitted in block 03's section; block 04's
    rails section carries NO editable capture field."""
    model = YamlBuildModel()
    model.set_params("parse_ict", {CAPTURE_FIELD: "3V3\nVDD_CORE"})
    model.set_enabled("parse_ict", True)
    model.set_enabled("rails", True)
    data = yaml.safe_load(model.to_effective_yaml())
    modules = data["yaml_build"]["modules"]
    assert modules["parse_ict"]["power_capture_nets"] == \
        ["3V3", "VDD_CORE"]
    assert "power_capture_nets" not in modules["rails"]
