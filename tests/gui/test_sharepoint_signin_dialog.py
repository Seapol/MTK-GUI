# -*- coding: utf-8 -*-
"""M10 - real SharePoint sign-in + REST upload wiring (no network).

The embedded QtWebEngine login window is exercised through its
``view_factory`` seam (a plain QWidget stand-in) and the REST transport
is replaced by a fake at the dialog's module seam, so the tests cover
the sign-in state machine, the persisted session and Test Connection
without spawning a browser process or touching nxp1.sharepoint.com.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from mtkgui.engine.sharepoint_site import (  # noqa: E402
    SharePointSession,
    parse_sharepoint_link,
)
from mtkgui.gui import sharepoint_upload_dialog as sp_gui  # noqa: E402
from mtkgui.gui.sharepoint_upload_dialog import (  # noqa: E402
    SharePointSignInDialog,
    SharePointUploadDialog,
)

LINK = ("https://nxp1.sharepoint.com/:f:/r/teams/ext158/BTD/Shared"
        "%20Documents/MTK%20Test%20Data?d=w1&csf=1&web=1")
COOKIE = {"name": "FedAuth", "value": "abc",
          "domain": ".sharepoint.com", "path": "/", "secure": True}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_modals(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    calls = []

    def fake_information(*args, **kwargs):
        calls.append(args[2] if len(args) > 2 else kwargs.get("text"))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", fake_information)
    yield calls


class FakeRest:
    """Stands in for SharePointRestTransport at the dialog seam."""

    instances: list["FakeRest"] = []

    def __init__(self, site_url, cookie_jar=None, *, folder_path="",
                 timeout=30.0):
        self.site_url = site_url
        self.folder_path = folder_path
        self.jar = cookie_jar
        self.probed = 0
        FakeRest.instances.append(self)

    def head(self, path=""):
        self.probed += 1

    def mkdirs(self, path=""):
        self.probed += 1

    def current_user(self):
        return "Jane Operator"


@pytest.fixture
def fake_rest(monkeypatch):
    FakeRest.instances = []
    monkeypatch.setattr(sp_gui, "SharePointRestTransport", FakeRest)
    return FakeRest


def make_dialog(tmp_path, **kwargs):
    return SharePointUploadDialog(
        None, config_path=tmp_path / "sp_cfg.json",
        state_dir=tmp_path / "state", **kwargs)


# ------------------------------------------------------------- sign-in
def test_sign_in_dialog_captures_session_cookies(qapp, tmp_path):
    dlg = SharePointSignInDialog(
        None, site_url="https://nxp1.sharepoint.com",
        profile_dir=tmp_path / "webprofile", view_factory=QWidget)
    try:
        assert not dlg.signed_in
        assert not dlg.add_cookie({"name": "other", "value": "x",
                                   "domain": ".sharepoint.com"})
        assert not dlg.signed_in
        assert dlg.add_cookie(dict(COOKIE))
        assert dlg.signed_in
        assert dlg.session_cookies == [COOKIE]
        assert dlg.status.text() == "Signed in — close this window"
        # a re-emitted cookie replaces instead of duplicating
        dlg.add_cookie(dict(COOKIE, value="def"))
        assert len(dlg.session_cookies) == 1
        assert dlg.session_cookies[0]["value"] == "def"
    finally:
        dlg.deleteLater()


def test_sign_in_dialog_ignores_foreign_host(qapp, tmp_path):
    dlg = SharePointSignInDialog(
        None, site_url="https://nxp1.sharepoint.com",
        profile_dir=tmp_path / "webprofile", view_factory=QWidget)
    try:
        assert not dlg.add_cookie(dict(COOKIE, domain=".example.com"))
        assert not dlg.signed_in and dlg.session_cookies == []
    finally:
        dlg.deleteLater()


# -------------------------------------------------- dialog state (P3)
def test_non_virtual_without_session_requires_sign_in(qapp, tmp_path):
    dlg = make_dialog(tmp_path, virtual=False)
    try:
        assert dlg.btn_signin.isEnabled()
        assert dlg.signin_status.text() == \
            ("not signed in — sign in in your own browser, then "
             "Import Browser Session (no password, no embedded "
             "login)")
        dlg.site_edit.setText(LINK)
        problems = dlg.test_connection()
        assert problems == ["not signed in — click Connect & Sign in… first"]
        assert dlg.conn_status.text().startswith("FAIL")
    finally:
        dlg.deleteLater()


def test_signed_in_session_shows_status_and_tests_ok(qapp, tmp_path,
                                                     fake_rest):
    session = SharePointSession(
        site="https://nxp1.sharepoint.com",
        folder_path="/teams/ext158/BTD/Shared Documents/MTK Test Data",
        user="Jane Operator", link=LINK, cookies=[dict(COOKIE)])
    dlg = make_dialog(tmp_path, virtual=False, session=session)
    try:
        assert dlg.signin_status.text() == \
            "Signed in as Jane Operator — SharePoint test-data upload ready"
        dlg.site_edit.setText(LINK)
        assert dlg.test_connection() == []
        assert dlg.conn_status.text().startswith("OK")
        transport = dlg._transport()
        assert isinstance(transport, FakeRest)
        assert transport.site_url == "https://nxp1.sharepoint.com"
        assert transport.folder_path == \
            "/teams/ext158/BTD/Shared Documents/MTK Test Data"
    finally:
        dlg.deleteLater()


def test_adopt_sign_in_persists_session_and_runs_test_connection(
        qapp, tmp_path, fake_rest):
    dlg = make_dialog(tmp_path, virtual=False)
    try:
        dlg.site_edit.setText(LINK)
        session = dlg.adopt_sign_in(parse_sharepoint_link(LINK),
                                    [dict(COOKIE)])
        assert session.user == "Jane Operator"
        assert dlg.signin_status.text() == \
            "Signed in as Jane Operator — SharePoint test-data upload " \
            "ready"
        saved = tmp_path / "state" / "session.json"
        assert saved.exists()
        restored = SharePointSession.load(saved)
        assert restored is not None and restored.signed_in
        assert restored.link == LINK
        # Test Connection ran once against the fresh session
        assert dlg.conn_status.text().startswith("OK")
    finally:
        dlg.deleteLater()


def test_connect_and_sign_in_guards_bad_or_empty_link(qapp, tmp_path,
                                                      no_modals):
    dlg = make_dialog(tmp_path, virtual=False)
    try:
        assert dlg.connect_and_sign_in() is None
        assert any("Enter the SharePoint site link" in str(c)
                   for c in no_modals)
        dlg.site_edit.setText("not-a-link")
        assert dlg.connect_and_sign_in() is None
        assert any("Invalid SharePoint link" in str(c) for c in no_modals)
    finally:
        dlg.deleteLater()


def test_virtual_mode_sign_in_stays_disabled(qapp, tmp_path):
    from mtkgui.engine.uploader import FakeSharePoint, SharePointUploader
    uploader = SharePointUploader(
        tmp_path / "outbox", state_dir=tmp_path / "state",
        transport=FakeSharePoint())
    dlg = make_dialog(tmp_path, virtual=True, uploader=uploader)
    try:
        assert not dlg.btn_signin.isEnabled()
        assert dlg.signin_status.text() == "virtual mode: no sign-in needed"
        assert dlg.connect_and_sign_in() is None
        dlg.site_edit.setText("https://corp.sharepoint.com/ict")
        assert dlg.test_connection() == []
        assert "virtual" in dlg.conn_status.text()
    finally:
        dlg.deleteLater()
