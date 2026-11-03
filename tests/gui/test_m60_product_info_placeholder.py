# -*- coding: utf-8 -*-
"""M60: "No Product Info" placeholder in the Product Information prompt.

An FCT-only project is valid with empty ICT test items, and a freshly
created one has an empty ``product:`` section - so the first Apply Save
YAML always asks for Product Information.  When the product genuinely
carries no data yet, the operator clicks ONE button ("No Product Info")
and the dialog fills No_Name / No_ID / No_Batch and continues the save.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QPushButton,
)

from mtkgui.main_window import (  # noqa: E402
    MainWindow,
    NO_PRODUCT_INFO,
    ask_product_information,
)

MainWindow.__test__ = False

PLACEHOLDERS = {"part_number": "No_Name", "core_id": "No_ID",
                "batch": "No_Batch"}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _sandbox_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "mtkgui.yaml_build_page.save_project_state",
        lambda key, state: True)


@pytest.fixture()
def window(qapp):
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()


def _no_info_button(dlg):
    return next((b for b in dlg.findChildren(QPushButton)
                 if b.text() == "No Product Info"), None)


def _part_field(dlg):
    return next(e for e in dlg.findChildren(QLineEdit)
                if e.placeholderText().startswith("Part Number"))


def _auto_click_no_info(monkeypatch, captured=None):
    """Run ask_product_information without a modal loop: click the
    "No Product Info" button inside exec and return its result."""
    def fake_exec(self):
        btn = _no_info_button(self)
        if captured is not None:
            captured["btn"] = btn
            captured["labels"] = {
                b.text() for b in
                self.findChild(QDialogButtonBox).findChildren(QPushButton)}
        if btn is not None:
            btn.click()
        if captured is not None:
            captured["fields"] = tuple(
                e.text() for e in self.findChildren(QLineEdit))
            captured["btn_enabled"] = btn.isEnabled()
        return QDialog.DialogCode(self.result())

    monkeypatch.setattr(QDialog, "exec", fake_exec)


# ------------------------------------------------------------ the button
def test_dialog_contains_no_product_info_button(qapp, monkeypatch):
    """§1: a third button sits beside OK / Cancel."""
    captured: dict = {}
    _auto_click_no_info(monkeypatch, captured)
    ask_product_information(None, {})
    assert captured["btn"] is not None
    assert {"No Product Info", "OK", "Cancel"} <= captured["labels"]


def test_no_product_info_returns_exact_placeholders(qapp, monkeypatch):
    """§1: one click = fill + accept; the values are exact."""
    _auto_click_no_info(monkeypatch)
    assert ask_product_information(None, {"part_number": "P-0001"}) == \
        PLACEHOLDERS
    assert NO_PRODUCT_INFO == PLACEHOLDERS


def test_button_works_with_empty_part_number(qapp, monkeypatch):
    """§1: the placeholder scenario is exactly an empty dialog - the
    button is clickable and accepted regardless."""
    captured: dict = {}
    _auto_click_no_info(monkeypatch, captured)
    values = ask_product_information(None, {})
    assert values == PLACEHOLDERS
    assert captured["btn_enabled"] is True
    assert captured["fields"] == ("No_Name", "No_ID", "No_Batch")


# ------------------------------------------------------------ invariants
def test_manual_gate_still_requires_part_number(qapp, monkeypatch):
    """§4: OK stays disabled while Part Number is empty."""
    state: dict = {}

    def fake_exec(self):
        box = self.findChild(QDialogButtonBox)
        ok = box.button(QDialogButtonBox.StandardButton.Ok)
        part = _part_field(self)
        state["initial"] = ok.isEnabled()
        part.setText("P-0001")
        state["after_type"] = ok.isEnabled()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    assert ask_product_information(None, {}) is None
    assert state["initial"] is False
    assert state["after_type"] is True


def test_cancel_aborts_the_save(window, monkeypatch):
    """§4: Cancel (dialog rejected) returns None -> save aborted + log."""
    monkeypatch.setattr(QDialog, "exec",
                        lambda self: QDialog.DialogCode.Rejected)
    assert window._ensure_product_information({"product": {}}) is False
    log = window.event_log.toPlainText()
    assert "Yaml save cancelled: Product Information missing" in log


# ------------------------------------------------------------ integration
def test_fct_only_project_writes_the_placeholders(window, monkeypatch):
    """§1/§2: FCT-only state (no ICT items, empty product:) -> the
    placeholder result reaches the three Product Information fields."""
    ict_n, _fct_n = window.workflow_page.test_item_counts()
    assert ict_n == 0
    _auto_click_no_info(monkeypatch)
    assert window._ensure_product_information({"product": {}}) is True
    page = window.workflow_page
    # the Product Information edits upper-case their content (widget
    # behaviour, unchanged by M60) - compare case-insensitively
    assert page.part_edit.text().lower() == "no_name"
    assert page.core_edit.text().lower() == "no_id"
    assert page.batch_edit.text().lower() == "no_batch"


def test_placeholder_path_logs_the_marker_line(window, monkeypatch):
    """§3: the placeholder path logs its own marker (and keeps the
    manual "Product Information set: ..." line)."""
    _auto_click_no_info(monkeypatch)
    assert window._ensure_product_information({"product": {}}) is True
    log = window.event_log.toPlainText()
    assert ("Product Information set to No Product Info placeholders "
            "(No_Name/No_ID/No_Batch)") in log
    assert "Product Information set: No_Name" in log


def test_manual_values_do_not_log_the_placeholder_marker(window,
                                                           monkeypatch):
    """§3/§8: an existing save flow (manual values) keeps the old log
    line and gains no placeholder marker."""
    monkeypatch.setattr(
        "mtkgui.main_window.ask_product_information",
        lambda parent, product: {"part_number": "P-0001", "core_id": "",
                                 "batch": "freebatch"})
    assert window._ensure_product_information({"product": {}}) is True
    log = window.event_log.toPlainText()
    assert "Product Information set: P-0001" in log
    assert "No Product Info placeholders" not in log


def test_already_complete_product_skips_the_prompt(window, monkeypatch):
    """§4/§8: a config carrying a Part Number never opens the dialog
    (existing apply-save behaviour untouched)."""
    calls: list = []
    monkeypatch.setattr(
        "mtkgui.main_window.ask_product_information",
        lambda parent, product: calls.append(product) or None)
    assert window._ensure_product_information(
        {"product": {"part_number": "P-0001"}}) is True
    assert calls == []
