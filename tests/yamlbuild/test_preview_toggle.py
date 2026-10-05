# -*- coding: utf-8 -*-
"""M0 YAML-preview single-toggle button tests: Edit/Apply two-state
button, validation gating, fixed position, no text overlap."""
from __future__ import annotations

import pytest
import yaml

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.preview import (  # noqa: E402
    APPLY_LABEL,
    EDIT_LABEL,
    YamlPreviewWidget,
)
from tests.yamlbuild.conftest import fill_required  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def preview(qapp):
    from tests.yamlbuild.conftest import make_filled_model
    model = make_filled_model()
    w = YamlPreviewWidget()
    w.bind_model(model)
    w.set_model_text(model)
    yield w, model
    w.deleteLater()


# ------------------------------------------------------------- state 1
def test_default_is_read_only_with_edit_label(preview):
    w, _model = preview
    assert not w.is_editing()
    assert w.btn_edit.text() == EDIT_LABEL == "Edit"
    assert w.editor.isReadOnly()


def test_click_enters_edit_mode(preview):
    w, _model = preview
    w.btn_edit.click()
    assert w.is_editing()
    assert w.editor.isReadOnly() is False
    assert w.btn_edit.text() == APPLY_LABEL == "Apply"


# ------------------------------------------------------------- state 2
def test_apply_pass_persists_and_returns_to_edit_label(preview):
    w, model = preview
    w.btn_edit.click()
    doc = yaml.safe_load(w.editor.toPlainText())
    doc["yaml_build"]["modules"]["clocks"]["stabilize_ms"] = 300
    w.editor.setPlainText(yaml.safe_dump(doc, sort_keys=False))
    w.btn_edit.click()                       # Apply
    # persisted + diagram updated (model mutated) + back to READ_ONLY
    assert model.get_params("clocks")["stabilize_ms"] == "300"
    assert not w.is_editing()
    assert w.editor.isReadOnly()
    assert w.btn_edit.text() == "Edit"
    assert w.error_bar.isHidden()


def test_apply_fail_stays_in_edit_mode(preview, monkeypatch):
    w, model = preview
    before = model.to_dict()
    w.btn_edit.click()                        # Edit -> Apply label
    w.editor.setPlainText("yaml_build: [broken")
    w.btn_edit.click()                        # Apply -> FAIL
    assert w.error_bar.isVisible() or not w.error_bar.isHidden()
    assert "YAML invalid" in w.error_bar.text()
    assert w.is_editing()                     # stays in edit mode
    assert w.btn_edit.text() == "Apply"       # label keeps Apply
    after = {k: v for k, v in model.to_dict().items()
             if k != "saved_at"}
    before = {k: v for k, v in before.items() if k != "saved_at"}
    assert after == before                    # nothing persisted


def test_button_single_and_mutually_exclusive(preview):
    """One button, two states only - never both / neither label."""
    w, _model = preview
    labels_seen = {w.btn_edit.text()}
    w.btn_edit.click()
    labels_seen.add(w.btn_edit.text())
    w.btn_edit.click()
    labels_seen.add(w.btn_edit.text())
    assert labels_seen == {"Edit", "Apply"}
    assert w.btn_edit.isCheckable() is False  # no mixed toggle state


def test_button_position_fixed_and_width_fits_label(preview):
    """The button stays at its layout slot (no re-parent / no move on
    label change) and auto-adjusts its width to the label text."""
    w, _model = preview
    w.resize(600, 400)
    w.show()
    try:
        pos_before = w.btn_edit.pos()
        w.btn_edit.click()                    # label -> Apply
        assert w.btn_edit.pos() == pos_before
        # width covers the label text (auto-adjust, no clipping)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(w.btn_edit.font())
        assert w.btn_edit.width() >= fm.horizontalAdvance(
            w.btn_edit.text()) + 8
    finally:
        w.hide()


def test_edit_mode_keeps_operator_text_on_model_refresh(preview):
    """While in EDIT mode an incoming model refresh does not clobber
    the operator's text (the Apply path decides what enters)."""
    w, model = preview
    w.btn_edit.click()
    w.editor.setPlainText("yaml_build: {plan_version: '9.9.9'}")
    model.set_params("clocks", {"stabilize_ms": "77"})
    w.set_model_text(model)                   # external refresh attempt
    assert "9.9.9" in w.editor.toPlainText()  # operator text kept
