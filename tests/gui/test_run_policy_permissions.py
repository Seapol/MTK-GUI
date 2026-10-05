# -*- coding: utf-8 -*-
"""M0 run-policy permission tests: Stop if failure / Stop if any
short / Auto-SN checkboxes - supervisor rw, operator ro until granted,
dynamic re-evaluation on every panel load, YAML persistence."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.permissions import (  # noqa: E402
    DEFAULT_PERMISSIONS,
    PERMISSION_LABELS,
    ROLE_OPERATOR,
    ROLE_SUPERVISOR,
    PermissionsDialog,
)
from mtkgui.project_config import apply_config, build_config  # noqa: E402
from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402

RUN_POLICY_KEYS = ("run_policy_stop_failure", "run_policy_stop_short",
                   "run_policy_auto_sn")
CHECKBOXES = ("stop_if_fail_cb", "stop_if_short_cb", "auto_sn")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    yield w
    w.deleteLater()


# ------------------------------------------------------ permission matrix
def test_run_policy_keys_in_global_matrix():
    for key in RUN_POLICY_KEYS:
        assert key in PERMISSION_LABELS
        assert DEFAULT_PERMISSIONS[key] is False      # Operator: ro


def test_authorization_dialog_lists_run_policy_items():
    """The role authorization page (Settings > Operator Permissions)
    carries the three new items so the supervisor can grant them."""
    dlg = PermissionsDialog(DEFAULT_PERMISSIONS)
    try:
        labels = {c.text() for c in dlg._checks.values()}
        for key in RUN_POLICY_KEYS:
            assert PERMISSION_LABELS[key] in labels
    finally:
        dlg.deleteLater()


# ------------------------------------------------------------- GUI states
def test_supervisor_has_readwrite(page):
    page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=True)
    for name in CHECKBOXES:
        assert getattr(page, name).isEnabled(), name


def test_operator_default_readonly(page):
    page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=False)
    for name in CHECKBOXES:
        assert not getattr(page, name).isEnabled(), name


def test_operator_with_grant_is_editable(page):
    granted = dict(DEFAULT_PERMISSIONS)
    granted["run_policy_stop_short"] = True
    granted["run_policy_auto_sn"] = True
    page.apply_permissions(granted, supervisor=False)
    assert not page.stop_if_fail_cb.isEnabled()   # not granted
    assert page.stop_if_short_cb.isEnabled()      # granted
    assert page.auto_sn.isEnabled()               # granted


def test_permission_check_reruns_on_every_panel_load(page):
    """Dynamic enable/disable: the same page instance flips between
    operator and supervisor sessions."""
    page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=True)
    assert page.stop_if_fail_cb.isEnabled()
    page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=False)
    assert not page.stop_if_fail_cb.isEnabled()
    granted = dict(DEFAULT_PERMISSIONS,
                   run_policy_stop_failure=True)
    page.apply_permissions(granted, supervisor=False)
    assert page.stop_if_fail_cb.isEnabled()
    page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=True)
    assert page.stop_if_fail_cb.isEnabled()


# --------------------------------------------------------- YAML round trip
def test_run_policy_persisted_to_project_yaml(page):
    """Supervisor toggles persist: build_config writes the three states
    into test_workflow; apply_config restores them."""
    page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=True)
    page.stop_if_fail_cb.setChecked(True)
    page.stop_if_short_cb.setChecked(False)
    page.auto_sn.setChecked(True)

    equipment = pytest.importorskip(
        "mtkgui.equipment_page").EquipmentPage()
    try:
        config = build_config(page, equipment)
        tw = config["test_workflow"]
        assert tw["stop_if_failure"] is True
        assert tw["stop_if_any_short"] is False
        assert tw["auto_sn"] is True

        fresh = TestWorkFlowPage()
        try:
            apply_config(config, fresh, equipment)
            assert fresh.stop_if_fail_cb.isChecked() is True
            assert fresh.stop_if_short_cb.isChecked() is False
            assert fresh.auto_sn.isChecked() is True
        finally:
            fresh.deleteLater()
    finally:
        equipment.deleteLater()
