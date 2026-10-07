# -*- coding: utf-8 -*-
"""YAML-preview fixed Apply-button tests (user direction: no Edit
mode - the editor is directly editable): validation gating, operator
text protection and the red error marks."""
from __future__ import annotations

import pytest
import yaml

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.preview import (  # noqa: E402
    APPLY_LABEL,
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


# ------------------------------------------------------------- editor
def test_editor_directly_editable_with_apply_label(preview):
    """No Edit mode any more: the editor is writable from the start
    and the single button label is Apply."""
    w, _model = preview
    assert w.editor.isReadOnly() is False
    assert w.btn_apply.text() == APPLY_LABEL == "Apply"
    assert w.btn_apply.isCheckable() is False  # no mixed toggle state


def test_apply_pass_persists(preview):
    w, model = preview
    doc = yaml.safe_load(w.editor.toPlainText())
    doc["yaml_build"]["modules"]["clocks"]["stabilize_ms"] = 300
    w.editor.setPlainText(yaml.safe_dump(doc, sort_keys=False))
    w.btn_apply.click()                      # Apply
    # persisted + diagram updated (model mutated) + modified flag clear
    assert model.get_params("clocks")["stabilize_ms"] == "300"
    assert not w.editor.document().isModified()
    assert w.error_bar.isHidden()


def test_apply_fail_keeps_operator_text(preview):
    w, model = preview
    before = model.to_dict()
    w.editor.setPlainText("yaml_build: [broken")
    w.btn_apply.click()                      # Apply -> FAIL
    assert w.error_bar.isVisible() or not w.error_bar.isHidden()
    assert "YAML invalid" in w.error_bar.text()
    assert "broken" in w.editor.toPlainText()   # operator text stays
    after = {k: v for k, v in model.to_dict().items()
             if k != "saved_at"}
    before = {k: v for k, v in before.items() if k != "saved_at"}
    assert after == before                    # nothing persisted


def test_button_width_fits_label(preview):
    """The button auto-adjusts its width to the label text."""
    w, _model = preview
    w.resize(600, 400)
    w.show()
    try:
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(w.btn_apply.font())
        assert w.btn_apply.width() >= fm.horizontalAdvance(
            w.btn_apply.text()) + 8
    finally:
        w.hide()


def test_unapplied_operator_text_survives_model_refresh(preview):
    """With UNAPPLIED hand edits an incoming model refresh does not
    clobber the operator's text (the Apply path decides what
    enters)."""
    w, model = preview
    w.editor.setPlainText("yaml_build: {plan_version: '9.9.9'}")
    # simulate a real keystroke (user input marks the document
    # modified; setPlainText alone does not)
    w.editor.document().setModified(True)
    model.set_params("clocks", {"stabilize_ms": "77"})
    w.set_model_text(model)                   # external refresh attempt
    assert "9.9.9" in w.editor.toPlainText()  # operator text kept
