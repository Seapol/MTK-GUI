# -*- coding: utf-8 -*-
"""P3-B2 T5 permission tests: Operator / Supervisor isolation.

Operator: cannot edit the YAML configuration (Yaml Build page hidden,
Edit/Apply disabled, save actions disabled) - only run tests and view
reports.  Supervisor: full edit rights.  Node comments follow the
existing ICT / FCT edit permissions."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.permissions import (  # noqa: E402
    DEFAULT_PERMISSIONS,
    PERMISSION_LABELS,
)
from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402
from mtkgui.gui.yamlbuild.preview import (  # noqa: E402
    APPLY_LABEL,
    YamlPreviewWidget,
)
from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    yield w
    w.deleteLater()


@pytest.fixture()
def yaml_page(qapp):
    w = YamlBuildPage()
    yield w
    w.deleteLater()


# --------------------------------------------------------------- matrix
def test_edit_yaml_build_key_in_matrix():
    """The new permission key exists and defaults to ro (operator)."""
    assert "edit_yaml_build" in PERMISSION_LABELS
    assert DEFAULT_PERMISSIONS["edit_yaml_build"] is False


# -------------------------------------------------- Yaml Build page gate
def test_yaml_build_page_operator_cannot_edit(yaml_page):
    """set_edit_allowed(False): action row + Edit/Apply disabled."""
    yaml_page.set_edit_allowed(False)
    for btn in yaml_page._action_buttons:
        assert not btn.isEnabled()
    assert not yaml_page.yaml_preview.btn_apply.isEnabled()


def test_yaml_build_page_supervisor_full_edit(yaml_page):
    """Supervisor (default state): everything enabled."""
    assert yaml_page._edit_allowed is True
    for btn in yaml_page._action_buttons:
        assert btn.isEnabled()
    assert yaml_page.yaml_preview.btn_apply.isEnabled()


def test_yaml_preview_gate_sets_editor_read_only(qapp):
    """Disabling the edit right makes the editor read-only (the
    preview stays viewable); the Apply button is disabled."""
    preview = YamlPreviewWidget()
    try:
        preview.set_edit_allowed(False)
        assert preview.editor.isReadOnly()
        assert not preview.btn_apply.isEnabled()
    finally:
        preview.deleteLater()


def test_yaml_preview_gate_re_enables(qapp):
    """Re-granting the right re-enables the Apply button and the
    editor editing."""
    preview = YamlPreviewWidget()
    try:
        preview.set_edit_allowed(False)
        assert not preview.btn_apply.isEnabled()
        preview.set_edit_allowed(True)
        assert preview.btn_apply.isEnabled()
        assert preview.btn_apply.text() == APPLY_LABEL
        assert not preview.editor.isReadOnly()
    finally:
        preview.deleteLater()


def test_yaml_build_export_blocked_for_operator(yaml_page, monkeypatch):
    """The export action is guarded even if triggered programmatically
    (button disabled + in-function permission check)."""
    yaml_page.set_edit_allowed(False)
    called = []
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.QMessageBox.information",
        staticmethod(lambda *a, **k: called.append(1)))
    yaml_page._export_excel()
    assert called, "permission notice expected"


# ------------------------------------------ workflow page comment rights
def test_node_comment_follows_edit_permission_source(page):
    """The comment edit action is gated by edit_ict / edit_fct in both
    context menus (regression guard)."""
    import inspect
    src = inspect.getsource(page._ict_context_menu)
    assert "_can_edit_ict" in src and "Edit comment..." in src
    src = inspect.getsource(page._fct_context_menu)
    assert "_can_edit_fct" in src and "Edit comment..." in src


def test_operator_defaults_leave_run_control_usable(page):
    """Operator (all-default permissions): run/debug stays usable -
    only the edit paths are disabled."""
    page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=False)
    assert not page._can_edit_ict
    assert not page._can_edit_fct
    # run + debug controls remain enabled
    assert page.btn_run.isEnabled()
    assert not page.btn_step.isEnabled()      # idle: disabled per state
    assert not page.btn_continue.isEnabled()  # idle: disabled per state


def test_supervisor_full_edit(page):
    page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=True)
    assert page._can_edit_ict
    assert page._can_edit_fct
