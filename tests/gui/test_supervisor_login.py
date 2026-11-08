# -*- coding: utf-8 -*-
"""M97 supervisor login tests - the hash file decides, never a source constant.

The station work folder is redirected by the autouse ``isolated_work_dir``
fixture in ``tests/conftest.py``.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mtkgui import accounts  # noqa: E402
from mtkgui.permissions import (  # noqa: E402
    ROLE_OPERATOR,
    ROLE_SUPERVISOR,
    LoginDialog,
)

STATION_PASSWORD = "Station-2026"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _clean_station_account():
    accounts.clear_password()
    yield
    accounts.clear_password()


@pytest.fixture()
def dlg(qapp):
    d = LoginDialog(None, allow_cancel=True)
    yield d
    d.deleteLater()


def test_unconfigured_station_refuses_and_names_the_owner(dlg, monkeypatch):
    shown = []
    monkeypatch.setattr("mtkgui.permissions.QMessageBox.warning",
                        lambda *a, **k: shown.append(a) or 0)
    dlg.role_combo.setCurrentText(ROLE_SUPERVISOR)
    dlg.password_edit.setText(STATION_PASSWORD)
    dlg._on_accept()
    assert not dlg.result()
    assert shown, "an unconfigured station must warn"
    assert shown[0][1] == "Supervisor Password Not Set"
    assert "Ask your NXP owner to set it once at station setup." in shown[0][2]


def test_configured_station_accepts_the_right_password(qapp):
    accounts.set_password(STATION_PASSWORD)
    d = LoginDialog(None, allow_cancel=True)
    try:
        d.role_combo.setCurrentText(ROLE_SUPERVISOR)
        d.password_edit.setText(STATION_PASSWORD)
        d._on_accept()
        assert d.result() == QDialog.DialogCode.Accepted
    finally:
        d.deleteLater()


def test_configured_station_rejects_a_wrong_password(qapp, monkeypatch):
    accounts.set_password(STATION_PASSWORD)
    shown = []
    monkeypatch.setattr("mtkgui.permissions.QMessageBox.warning",
                        lambda *a, **k: shown.append(a) or 0)
    d = LoginDialog(None, allow_cancel=True)
    try:
        d.role_combo.setCurrentText(ROLE_SUPERVISOR)
        d.password_edit.setText("nope")
        d._on_accept()
        assert not d.result()
        assert shown and shown[0][1] == "Login Failed"
    finally:
        d.deleteLater()


def test_operator_never_reads_the_hash_file(dlg, monkeypatch):
    calls = []
    monkeypatch.setattr(accounts, "verify", lambda p: calls.append(p) or True)
    monkeypatch.setattr(accounts, "is_configured",
                        lambda: calls.append("configured") or True)
    dlg.role_combo.setCurrentText(ROLE_OPERATOR)
    dlg._on_accept()
    assert calls == []
    assert dlg.result() == QDialog.DialogCode.Accepted
