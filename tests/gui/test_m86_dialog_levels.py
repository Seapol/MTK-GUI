# -*- coding: utf-8 -*-
"""M86-C4: the two-level SharePoint dialog (status A / settings B)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui import sharepoint_store  # noqa: E402
from mtkgui.engine.uploader import (  # noqa: E402
    FakeSharePoint,
    SharePointUploader,
)
from mtkgui.gui.sharepoint_upload_dialog import (  # noqa: E402
    SharePointUploadDialog,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _dialog(tmp_path) -> SharePointUploadDialog:
    outbox = tmp_path / "outbox"
    outbox.mkdir(exist_ok=True)
    uploader = SharePointUploader(
        outbox, state_dir=tmp_path / "state", transport=FakeSharePoint())
    return SharePointUploadDialog(
        None, virtual=True, config_path=tmp_path / "sp_cfg.json",
        state_dir=tmp_path / "state", uploader=uploader)


def test_dialog_opens_on_level_a(qapp, tmp_path):
    dlg = _dialog(tmp_path)
    try:
        assert dlg._stack.currentIndex() == 0
        assert dlg.btn_a_test.text() == "Test connection"
        assert dlg.btn_a_upload.text() == "Upload pending now"
        assert dlg.btn_a_advanced.text() == "Advanced…"
        assert dlg.btn_a_close.text() == "Close"
        assert dlg.status_label.text(), "level A must show a status line"
    finally:
        dlg.deleteLater()


def test_advanced_opens_level_b_and_back_returns(qapp, tmp_path):
    dlg = _dialog(tmp_path)
    try:
        dlg.btn_a_advanced.click()
        assert dlg._stack.currentIndex() == 1
        assert dlg.btn_back.text() == "Back"
        assert dlg.btn_save.text() == "Save"
        assert dlg.btn_close_b.text() == "Close"
        dlg.btn_back.click()
        assert dlg._stack.currentIndex() == 0
    finally:
        dlg.deleteLater()


def test_level_a_shows_pending_count_from_state(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(
        sharepoint_store, "load_state",
        lambda: {"light": "busy", "last_result": "", "last_url": "",
                 "last_attempt_ts": "", "pending": ["a.pdf", "b.pdf"]})
    dlg = _dialog(tmp_path)
    try:
        assert dlg.status_label.text() == "Pending: 2 file(s)"
    finally:
        dlg.deleteLater()


def test_level_b_shows_project_config_and_destination_paths(
        qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("MTKGUI_PROJECT", "M86-DLG")
    dlg = _dialog(tmp_path)
    try:
        dlg.btn_a_advanced.click()
        assert str(tmp_path / "sp_cfg.json") in dlg.config_label.text()
        assert dlg.dest_label.text().startswith("Uploads to: ")
        assert "/M86-DLG/" in dlg.dest_label.text()
        assert sharepoint_store.identity_folder() in dlg.dest_label.text()
    finally:
        dlg.deleteLater()


def test_test_connection_tries_plan_a_first(qapp, tmp_path, monkeypatch):
    """A real-mode test must ask the browser session before plan B."""
    calls = []
    monkeypatch.setattr(
        "mtkgui.gui.sharepoint_upload_dialog.read_session_cookies",
        lambda host: calls.append(host) or None)
    outbox = tmp_path / "outbox"
    outbox.mkdir(exist_ok=True)
    uploader = SharePointUploader(
        outbox, state_dir=tmp_path / "state", transport=FakeSharePoint())
    dlg = SharePointUploadDialog(
        None, virtual=False, config_path=tmp_path / "sp_cfg.json",
        state_dir=tmp_path / "state", uploader=uploader)
    try:
        dlg.site_edit.setText("https://corp.sharepoint.com/ict")
        dlg.test_connection()
        assert calls == ["corp.sharepoint.com"]
        assert "not signed in" in dlg.conn_status.text()
    finally:
        dlg.deleteLater()
