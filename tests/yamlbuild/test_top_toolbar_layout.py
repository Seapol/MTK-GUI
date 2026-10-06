# -*- coding: utf-8 -*-
"""Item 16: Top Toolbar YAML & Excel Button Layout Refactor.

* Build Draft YAML / Release Final YAML buttons are completely gone
* Import from Excel / Export to Excel sit LEFT of the Edit/Apply
  toggle in the unified top toolbar row
* The three buttons share one uniform adaptive width = the widest
  label among them (re-synced when the toggle flips Edit <-> Apply)
* Function zero regression: the import / export / edit-apply logic
  and every existing access path keep working (GUI layer only).
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp, tmp_path, monkeypatch):
    from mtkgui.gui.yamlbuild import store
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "state.json")
    w = YamlBuildPage()
    yield w
    w.deleteLater()


# ------------------------------------------------------- button removal
def test_yaml_buttons_removed(page):
    assert not hasattr(page, "btn_build_draft")
    assert not hasattr(page, "btn_release_final")


def test_top_row_order_excel_left_of_edit_apply(page):
    """Import / Export sit on the LEFT of the Edit/Apply toggle in the
    same unified top row."""
    row = [page.btn_import_excel, page.btn_export_excel,
           page.yaml_preview.btn_edit]
    assert tuple(page._action_buttons) == tuple(row)
    page.resize(1600, 900)
    page.show()
    QApplication.processEvents()
    xs = [b.geometry().x() for b in row]
    ys = {b.geometry().y() for b in row}
    assert xs == sorted(xs)                 # stable order: Excel first
    assert len(ys) == 1                     # one aligned row
    # the toggle left the preview pane header
    assert page.yaml_preview.btn_edit.parent() is not page.yaml_preview


# -------------------------------------------------- uniform width rule
def test_uniform_adaptive_button_width(page):
    """All three buttons share one fixed width = widest label."""
    page.resize(1600, 900)
    page.show()
    QApplication.processEvents()
    widths = {b.width() for b in page._action_buttons}
    assert len(widths) == 1
    w = widths.pop()
    hints = [b.sizeHint().width() for b in page._action_buttons]
    assert w >= max(hints)                  # fits the longest label


def test_width_resync_on_label_flip(page):
    """Flipping Edit <-> Apply re-syncs the uniform width (the label
    changes, the shared width adapts, all three stay equal).  The
    page reacts to the preview's label_changed signal."""
    page.resize(1600, 900)
    page.show()
    QApplication.processEvents()
    for label in ("Apply", "Edit"):
        page.yaml_preview.label_changed.emit(label)
        QApplication.processEvents()
        widths = {b.width() for b in page._action_buttons}
        assert len(widths) == 1, label
        assert widths.pop() >= page.yaml_preview.btn_edit.sizeHint(
        ).width()


# ------------------------------------------------ function consistency
def test_excel_and_edit_apply_logic_unchanged(page, monkeypatch):
    """Zero regression: the buttons still drive the original slots and
    the Edit/Apply toggle still runs the original validate / persist
    cycle (page-level round trip)."""
    called = []
    monkeypatch.setattr(page, "_import_excel",
                        lambda: called.append("import"))
    monkeypatch.setattr(page, "_export_excel",
                        lambda: called.append("export"))
    page.btn_import_excel.click()
    page.btn_export_excel.click()
    assert called == ["import", "export"]

    # Edit -> Apply persists a model change and returns to Edit
    from tests.yamlbuild.conftest import fill_required
    page.model.enable_all()
    fill_required(page.model)
    page._after_model_change()
    import yaml as _yaml
    page.yaml_preview.btn_edit.click()      # enter edit mode
    doc = _yaml.safe_load(page.yaml_preview.editor.toPlainText())
    doc["yaml_build"]["modules"]["rails"]["on_delay_ms"] = 555
    page.yaml_preview.editor.setPlainText(
        _yaml.safe_dump(doc, sort_keys=False))
    page.yaml_preview.btn_edit.click()      # Apply: validate + persist
    assert page.model.get_params("rails")["on_delay_ms"] == "555"
    assert page.yaml_preview.btn_edit.text() == "Edit"
    assert not page.yaml_preview.is_editing()
