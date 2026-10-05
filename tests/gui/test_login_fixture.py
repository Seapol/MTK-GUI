# -*- coding: utf-8 -*-
"""B1-final login refactor tests (spec items 1-5).

Covers the login form layout order, the Real/Virtual slide switch and
its supervisor-only unlock rule, the ATE/Manual fixture selector
(ATE restart baseline) and the Manual-fixture global disabling link.
"""
from __future__ import annotations

import types

import pytest

import mtkgui.equipment_page as equipment_page_module
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QMessageBox,
)

from mtkgui.equipment_page import (
    _MANUAL_FIXTURE_KEYS,
    _InstrumentDialog,
)
from mtkgui.main_window import MainWindow
from mtkgui.permissions import (
    FIXTURE_ATE,
    FIXTURE_MANUAL,
    MANUAL_FIXTURE_NOTICE,
    MODE_REAL,
    MODE_VIRTUAL,
    ROLE_OPERATOR,
    ROLE_SUPERVISOR,
    SUPERVISOR_PASSWORD,
    FixtureSelector,
    LoginDialog,
    ModeSwitch,
)


@pytest.fixture()
def login_dlg(qapp):
    dlg = LoginDialog(None, allow_cancel=True)
    yield dlg
    dlg.deleteLater()


# --------------------------------------------------------------- item 1
def test_form_layout_order(login_dlg):
    """Fixed vertical order: Account -> Password -> Mode -> Fixture
    -> Login button."""
    form = login_dlg.findChild(QFormLayout)
    labels = []
    for i in range(form.rowCount()):
        item = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
        if item is not None and item.widget() is not None:
            text = item.widget().text()
            if text:
                labels.append(text)
    assert labels == ["Account:", "Password:", "Mode:", "Fixture:"]


def test_login_button_label(login_dlg):
    """The OK button reads Login and sits below the form fields."""
    box = login_dlg.findChild(QDialogButtonBox)
    assert box.button(QDialogButtonBox.StandardButton.Ok).text() == "Login"


# --------------------------------------------------------------- item 2
def test_mode_switch_default_real_left_and_disabled(login_dlg):
    """Default docking is left (Real); the switch starts disabled."""
    sw = login_dlg.mode_switch
    assert isinstance(sw, ModeSwitch)
    assert not sw.isChecked()          # left = Real
    assert not sw.isEnabled()          # grayed until supervisor unlock


# --------------------------------------------------------------- item 3
def test_mode_switch_unlocks_only_for_supervisor(login_dlg):
    """Unlock requires Supervisor + the correct password (live)."""
    sw = login_dlg.mode_switch
    # operator + anything -> locked
    login_dlg.role_combo.setCurrentText(ROLE_OPERATOR)
    login_dlg.password_edit.setText(SUPERVISOR_PASSWORD)
    assert not sw.isEnabled()
    # supervisor + wrong password -> locked
    login_dlg.role_combo.setCurrentText(ROLE_SUPERVISOR)
    login_dlg.password_edit.setText("wrong")
    assert not sw.isEnabled()
    # supervisor + correct password -> unlocked
    login_dlg.password_edit.setText(SUPERVISOR_PASSWORD)
    assert sw.isEnabled()
    # any later credential change re-locks
    login_dlg.password_edit.setText(SUPERVISOR_PASSWORD[:-1])
    assert not sw.isEnabled() and not sw.isChecked()


def test_supervisor_accepts_virtual_mode(login_dlg):
    """A validated supervisor can slide to Virtual and it sticks."""
    login_dlg.role_combo.setCurrentText(ROLE_SUPERVISOR)
    login_dlg.password_edit.setText(SUPERVISOR_PASSWORD)
    login_dlg.mode_switch.setEnabled(True)
    login_dlg.mode_switch.setChecked(True)          # right = Virtual
    login_dlg._on_accept()
    assert login_dlg.mode == MODE_VIRTUAL
    assert login_dlg.role == ROLE_SUPERVISOR


def test_operator_always_real(login_dlg):
    """Operator logins stay locked on the Real baseline forever."""
    login_dlg.role_combo.setCurrentText(ROLE_OPERATOR)
    login_dlg._on_accept()
    assert login_dlg.mode == MODE_REAL


def test_wrong_supervisor_password_rejected(login_dlg, monkeypatch):
    """Wrong password: warning popup, dialog stays open."""
    shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.append(a) or 0)
    login_dlg.role_combo.setCurrentText(ROLE_SUPERVISOR)
    login_dlg.password_edit.setText("nope")
    login_dlg._on_accept()
    assert shown and "Wrong supervisor password." == shown[0][2]
    assert login_dlg.role is None
    assert login_dlg.result() != QDialog.DialogCode.Accepted


# --------------------------------------------------------------- item 4
def test_fixture_selector_default_ate(qapp):
    sel = FixtureSelector()
    assert sel.fixture_type() == FIXTURE_ATE          # restart baseline


def test_fixture_selector_manual_choice(qapp):
    sel = FixtureSelector()
    sel.set_fixture_type(FIXTURE_MANUAL)
    assert sel.fixture_type() == FIXTURE_MANUAL
    sel.set_fixture_type(FIXTURE_ATE)
    assert sel.fixture_type() == FIXTURE_ATE


def test_accept_returns_fixture_type(login_dlg):
    login_dlg.role_combo.setCurrentText(ROLE_OPERATOR)
    login_dlg.fixture_selector.set_fixture_type(FIXTURE_MANUAL)
    login_dlg._on_accept()
    assert login_dlg.fixture_type == FIXTURE_MANUAL


# --------------------------------------------------------------- item 5
@pytest.fixture()
def window(qapp):
    w = MainWindow(role=ROLE_SUPERVISOR, fixture=FIXTURE_MANUAL)
    yield w
    w.close()
    w.deleteLater()


def test_manual_fixture_blocks_fixture_blocks(window, monkeypatch):
    """Manual mode: fixture-band config entries show the fixed notice."""
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.append(a) or 0)
    assert window.equipment_page._manual_fixture is True
    for key in _MANUAL_FIXTURE_KEYS:
        shown.clear()
        window.equipment_page._on_block_clicked(
            window.equipment_page.blocks[key])
        assert shown, f"block {key} must be blocked in Manual mode"
        assert shown[0][2] == MANUAL_FIXTURE_NOTICE   # fixed wording


def test_ate_fixture_allows_fixture_blocks(qapp, monkeypatch):
    """ATE baseline: fixture-band config entries stay usable (no
    blocking popup, the normal config dialog factory is reached)."""
    popups = []
    opened = []
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: popups.append(a) or 0)
    monkeypatch.setattr(equipment_page_module, "_form_dialog",
                        lambda parent, title, fields:
                        (opened.append(title),
                         types.SimpleNamespace(exec=lambda: None))[1])
    w = MainWindow(role=ROLE_SUPERVISOR, fixture=FIXTURE_ATE)
    try:
        assert w.equipment_page._manual_fixture is False
        w.equipment_page._on_block_clicked(
            w.equipment_page.blocks["fixture"])
        assert opened, "ATE mode must open the fixture config dialog"
        assert popups == []
    finally:
        w.close()
        w.deleteLater()


def test_manual_fixture_disables_io_control(window):
    """Manual mode: instrument dialog IO-control group is disabled."""
    dlg = _InstrumentDialog(window.equipment_page, "DAQ973A - Configuration",
                            [("Model", "DAQ973A")], "daq973a",
                            virtual=False, manual=True)
    try:
        ctl = [g for g in dlg.findChildren(QGroupBox)
               if "Control" in g.title()][0]
        assert not ctl.isEnabled()
    finally:
        dlg.deleteLater()


def test_ate_fixture_enables_io_control(qapp):
    """ATE baseline: IO-control group stays enabled."""
    dlg = _InstrumentDialog(None, "DAQ973A - Configuration",
                            [("Model", "DAQ973A")], "daq973a",
                            virtual=False, manual=False)
    try:
        ctl = [g for g in dlg.findChildren(QGroupBox)
               if "Control" in g.title()][0]
        assert ctl.isEnabled()
    finally:
        dlg.deleteLater()
