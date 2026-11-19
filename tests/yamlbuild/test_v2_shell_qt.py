# -*- coding: utf-8 -*-
"""v2-3a: the seven-step shell — Qt skin (bar, footer, cancel, combos)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QComboBox, QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402


@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


def _model(core="96317", part="MTK12345") -> YamlBuildModel:
    model = YamlBuildModel()
    model.set_params("design_input", {
        "product_id": core, "part_number": part,
        "sw_version": "1.2.3", "hw_version": "A",
        "batch": "EVT (Proto-1)",
    })
    return model


def _wizard(qapp, model=None):
    return YamlBuildWizard(model or _model())


def test_bar_returns_to_visited_step(qapp):
    w = _wizard(qapp)
    try:
        w.goto("parse_ict")
        assert w.current == "parse_ict"
        w._on_bar_clicked("design_input")
        assert w.current == "design_input"
        # an unvisited step does nothing
        w._on_bar_clicked("firmware")
        assert w.current == "design_input"
    finally:
        w.deleteLater()


def test_cancel_before_next_creates_nothing(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    w = _wizard(qapp, _model(core="", part=""))
    try:
        w._on_cancel()
        work = tmp_path / "work"
        assert not (work / "96317").exists()
        assert not (work / "drafts").exists()
    finally:
        w.deleteLater()


def test_cancel_after_next_keeps_tree_and_draft(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    w = _wizard(qapp, _model())
    try:
        # fill the node 01 panel so its validate() passes
        panel = w._panels["design_input"]
        panel.set_values(w.model.get_params("design_input"))
        panel.spf_path = "s.spf"
        panel.net_path = "n.net"
        panel.bom_path = "b.csv"
        w._on_next()            # create the project tree
        w._on_save_draft()      # write the draft into it
        w._on_cancel()
        work = tmp_path / "work"
        assert (work / "96317" / "sources").is_dir()
        drafts = list((work / "96317").glob("*_Draft.yaml"))
        assert drafts, "the draft was not kept after cancel"
    finally:
        w.deleteLater()


def test_yamlbuild_combos_do_not_insert(qapp):
    w = _wizard(qapp)
    try:
        combos = w.findChildren(QComboBox)
        assert combos, "no combos found in the wizard"
        for combo in combos:
            assert combo.insertPolicy() == QComboBox.NoInsert, \
                f"{combo} inserts on duplicate items"
    finally:
        w.deleteLater()


def test_build_fct_is_a_panel_with_advanced(qapp):
    from mtkgui.gui.yamlbuild.fct_sequence_v2_panel import \
        BuildFctSequencePanel
    model = _model()
    model.set_params("design_input", {
        **model.get_params("design_input"),
        "fct_block_enabled": "true",
    })
    w = _wizard(qapp, model)
    try:
        w.goto("build_fct")
        panel = w._panels.get("build_fct")
        assert isinstance(panel, BuildFctSequencePanel)
        emitted = []
        w.build_fct_requested.connect(lambda: emitted.append(True))
        panel.btn_advanced.click()
        assert emitted
    finally:
        w.deleteLater()
