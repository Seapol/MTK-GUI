# -*- coding: utf-8 -*-
"""Item 15: Main UI Product Info Read-Only Rule (YAML driven).

part / core / batch are 100% YAML-driven: read-only on the GUI layer
for every role, empty fallback (no default placeholder text, no
residual cached data) and refresh only through a YAML load / switch.
Serial Number stays the single per-unit manual input field.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.permissions import (  # noqa: E402
    DEFAULT_PERMISSIONS,
    PERMISSION_LABELS,
)
from mtkgui.project_config import apply_config  # noqa: E402
from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402

YAML_FIELDS = ("part_edit", "core_edit", "batch_edit")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    w = TestWorkFlowPage()
    yield w
    w.deleteLater()


# ------------------------------------------------------------ read-only UI
def test_yaml_driven_fields_read_only(page):
    """part / core / batch are readOnly, serial stays editable."""
    for name in YAML_FIELDS:
        assert getattr(page, name).isReadOnly(), name
    assert not page.serial_edit.isReadOnly()


def test_read_only_regardless_of_role_and_permission(page):
    """Even a supervisor (or an operator granted the legacy key) cannot
    edit the YAML-driven fields - the YAML file is the only entrance."""
    for supervisor in (True, False):
        page.apply_permissions(DEFAULT_PERMISSIONS, supervisor=supervisor)
        for name in YAML_FIELDS:
            assert getattr(page, name).isReadOnly(), (supervisor, name)
        assert not page.serial_edit.isReadOnly()


def test_legacy_edit_product_info_key_removed():
    """The obsolete GUI-editing entrance is gone from the permission
    matrix (Product Info is YAML-driven now)."""
    assert "edit_product_info" not in PERMISSION_LABELS


# ----------------------------------------------------------- empty fallback
def test_startup_fields_empty_no_defaults_no_placeholder(page):
    """No hardcoded defaults, no placeholder text, no cached data."""
    for name in YAML_FIELDS:
        edit = getattr(page, name)
        assert edit.text() == "", name
        assert edit.placeholderText() == "", name


def test_missing_product_nodes_clear_fields(page):
    """apply_config with missing / empty product nodes clears all
    Product Info fields (no residual cached data)."""
    page.part_edit.setText("RESIDUAL")
    page.core_edit.setText("99999")
    page.batch_edit.setText("stale-batch")
    page.serial_edit.setText("FS1234567890")
    apply_config({}, page, object())
    for name in YAML_FIELDS + ("serial_edit",):
        assert getattr(page, name).text() == "", name


# ------------------------------------------------------- data refresh path
def test_yaml_load_refreshes_fields_only_via_apply_config(page):
    """Loading (or switching) a valid YAML project is the only refresh:
    apply_config populates part / core / batch and keeps them
    read-only; a missing serial node leaves the field blank."""
    apply_config(
        {"product": {"part_number": "frdm-imx93", "core_id": "10342",
                     "batch": "proto"}}, page, object())
    assert page.part_edit.text() == "FRDM-IMX93"   # forced upper case
    assert page.core_edit.text() == "10342"
    assert page.batch_edit.text() == "proto"
    for name in YAML_FIELDS:
        assert getattr(page, name).isReadOnly(), name
    assert page.serial_edit.text() == ""


def test_yaml_load_autofills_serial_from_yaml(page):
    """Item 19: the Serial Number field auto-fills from the YAML
    ``product.serial`` node on a valid project load."""
    apply_config(
        {"product": {"part_number": "P1", "core_id": "1",
                     "batch": "proto", "serial": "FS1234567890"}},
        page, object())
    assert page.serial_edit.text() == "FS1234567890"
    assert not page.serial_edit.isReadOnly()   # per-unit input as designed


def test_freebatch_and_switch_clears_previous_values(page):
    """freebatch maps to an empty display; switching to a project
    without product nodes clears the previously shown values."""
    apply_config({"product": {"part_number": "A1", "core_id": "1",
                              "batch": "freebatch"}}, page, object())
    assert page.batch_edit.text() == ""
    apply_config({"product": {}}, page, object())
    assert page.part_edit.text() == ""
    assert page.core_edit.text() == ""
    assert page.batch_edit.text() == ""


# -------------------------------------------------------- GUI layer guard
def test_programmatic_fill_still_possible_virtual_autosn(page):
    """Only upper-GUI programmatic fills (e.g. Auto-SN virtual values)
    can set the read-only fields - user input cannot."""
    page.part_edit.setText("VIRTUAL-PART")     # setText works on ro
    assert page.part_edit.text() == "VIRTUAL-PART"
    # simulating a user keystroke must not change the text
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    QTest.keyClicks(page.part_edit, "X")
    assert page.part_edit.text() == "VIRTUAL-PART"
    assert Qt is not None
