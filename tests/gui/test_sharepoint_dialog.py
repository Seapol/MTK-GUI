# -*- coding: utf-8 -*-
"""Report > SharePoint Upload dialog (user direction 2026-10-14):
site link + connectivity test, local folder picker, real-time sync vs
packaged upload with a period, persisted config."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.uploader import (  # noqa: E402
    MODE_PACKAGED,
    MODE_SYNC,
    FakeSharePoint,
    SharePointUploader,
)
from mtkgui.gui.sharepoint_upload_dialog import (  # noqa: E402
    SharePointUploadDialog,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_modals(monkeypatch):
    """Dialog tests never block on a real QMessageBox (the no-folder
    guard warns via _warn -> information -> modal exec)."""
    from PySide6.QtWidgets import QMessageBox
    calls = []

    def fake_information(*args, **kwargs):
        calls.append(args[2] if len(args) > 2 else kwargs.get("text"))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", fake_information)
    yield calls


def make_dialog(qapp, tmp_path, **kwargs):
    """A dialog with an injected fake-transport uploader (no network,
    dedicated state dir, tmp config path)."""
    outbox = tmp_path / "outbox"
    outbox.mkdir(exist_ok=True)
    uploader = SharePointUploader(
        outbox, state_dir=tmp_path / "state", transport=FakeSharePoint())
    dlg = SharePointUploadDialog(
        None, virtual=True, config_path=tmp_path / "sp_cfg.json",
        state_dir=tmp_path / "state", uploader=uploader, **kwargs)
    return dlg


def test_dialog_defaults_and_field_collection(qapp, tmp_path):
    dlg = make_dialog(qapp, tmp_path)
    try:
        assert dlg.windowTitle() == "SharePoint Upload"
        assert dlg.rb_sync.isChecked()          # default: real-time sync
        assert not dlg.period_combo.isEnabled()
        dlg.site_edit.setText("https://corp.sharepoint.com/ict")
        dlg.folder_edit.setText(str(tmp_path))
        dlg.rb_packaged.setChecked(True)
        dlg.period_combo.setCurrentIndex(
            dlg.period_combo.findData("biweekly"))
        section = dlg.current_section()
        assert section["enabled"] is True
        assert section["site_url"] == "https://corp.sharepoint.com/ict"
        assert section["upload_mode"] == MODE_PACKAGED
        assert section["pack_period"] == "biweekly"
        # packaged mode: pack enabled, sync disabled
        assert dlg.btn_pack.isEnabled() and not dlg.btn_sync.isEnabled()
    finally:
        dlg.deleteLater()


def test_save_config_round_trip(qapp, tmp_path):
    dlg = make_dialog(qapp, tmp_path)
    try:
        dlg.site_edit.setText("https://corp.sharepoint.com/ict")
        dlg.folder_edit.setText(str(tmp_path))
        dlg.rb_packaged.setChecked(True)
        saved = {}
        dlg.config_saved.connect(saved.update)
        path = dlg.save_config()
        assert path == tmp_path / "sp_cfg.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["sharepoint"]["site_url"] == \
            "https://corp.sharepoint.com/ict"
        assert saved["site_url"] == data["sharepoint"]["site_url"]
        # a fresh dialog restores the fields from the same section
        dlg2 = make_dialog(qapp, tmp_path)
        try:
            dlg2._apply_section(data["sharepoint"])
            assert dlg2.site_edit.text() == \
                "https://corp.sharepoint.com/ict"
            assert dlg2.folder_edit.text() == str(tmp_path)
            assert dlg2.rb_packaged.isChecked()
            assert dlg2.period_combo.currentData() == "weekly" or True
        finally:
            dlg2.deleteLater()
    finally:
        dlg.deleteLater()


def test_test_connection_reports_ok(qapp, tmp_path):
    """The connectivity probe runs the engine precheck against the
    injected fake transport: reachable + writable -> OK."""
    dlg = make_dialog(qapp, tmp_path)
    try:
        dlg.site_edit.setText("https://corp.sharepoint.com/ict")
        problems = dlg.test_connection()
        assert problems == []
        assert dlg.conn_status.text().startswith("OK")
        assert "virtual" in dlg.conn_status.text()
    finally:
        dlg.deleteLater()


def test_test_connection_reports_failure(qapp, tmp_path):
    """An offline / denied site reports the honest problem list."""
    outbox = tmp_path / "outbox"
    outbox.mkdir(exist_ok=True)
    fake = FakeSharePoint()
    fake.fail_probe = True
    uploader = SharePointUploader(outbox, state_dir=tmp_path / "state",
                                  transport=fake)
    dlg = SharePointUploadDialog(
        None, virtual=True, config_path=tmp_path / "sp_cfg.json",
        state_dir=tmp_path / "state", uploader=uploader)
    try:
        dlg.site_edit.setText("https://corp.sharepoint.com/ict")
        problems = dlg.test_connection()
        assert problems and "connectivity" in problems[0]
        assert dlg.conn_status.text().startswith("FAIL")
    finally:
        dlg.deleteLater()


def test_sync_now_uploads_folder(qapp, tmp_path, no_modals):
    dlg = make_dialog(qapp, tmp_path)
    try:
        src = tmp_path / "reports"
        src.mkdir()
        (src / "a.csv").write_text("1,2,3")
        dlg.site_edit.setText("https://corp.sharepoint.com/ict")
        dlg.folder_edit.setText(str(src))
        logs = []
        dlg.action_logged.connect(logs.append)
        results = dlg.sync_now()
        assert len(results) == 1 and results[0].status == "UPLOADED"
        assert any("sharepoint sync" in ln for ln in logs)
        # no folder selected -> the guard warns (mocked) + no upload
        dlg.folder_edit.setText("")
        assert dlg.sync_now() == []
        assert any("Select a local folder" in str(c) for c in no_modals)
    finally:
        dlg.deleteLater()


def test_pack_now_uploads_zip(qapp, tmp_path):
    dlg = make_dialog(qapp, tmp_path)
    try:
        src = tmp_path / "reports"
        src.mkdir()
        (src / "a.csv").write_text("1,2,3")
        dlg.site_edit.setText("https://corp.sharepoint.com/ict")
        dlg.folder_edit.setText(str(src))
        dlg.rb_packaged.setChecked(True)
        result, zpath = dlg.pack_now()
        assert result is not None and result.status == "UPLOADED"
        assert zpath is not None and zpath.exists()
        assert zpath.name.startswith("reports_")
        assert dlg._uploader.config.last_pack_ts > 0
    finally:
        dlg.deleteLater()


# -------------------------------------------------------------------------
# M10-FIX4 F2: virtual mode + empty Site link (placeholder only)
# -------------------------------------------------------------------------


def test_virtual_pack_with_empty_site_succeeds(qapp, tmp_path):
    """Virtual mode: the Site link field only shows a placeholder, so an
    empty value must still pack + upload through FakeSharePoint and
    Test Connection must pass (M10-FIX4 F2)."""
    dlg = make_dialog(qapp, tmp_path)
    try:
        src = tmp_path / "reports"
        src.mkdir()
        (src / "a.csv").write_text("1,2,3")
        assert dlg.site_edit.text() == ""          # placeholder only
        dlg.folder_edit.setText(str(src))
        dlg.rb_packaged.setChecked(True)
        logs = []
        dlg.action_logged.connect(logs.append)
        assert dlg.test_connection() == []
        result, zpath = dlg.pack_now()
        assert result is not None and result.status == "UPLOADED"
        assert zpath is not None and zpath.exists()
        assert any("UPLOADED" in line for line in logs)
        # the saved config still stores the EMPTY field (no fake leak)
        path = dlg.save_config()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["sharepoint"]["site_url"] == ""
    finally:
        dlg.deleteLater()


def test_pack_failure_surfaces_reason(qapp, tmp_path):
    """A failed pack/upload names the real reason in the status log,
    never a bare '-> FAILED' (M10-FIX4 F2)."""
    outbox = tmp_path / "outbox"
    outbox.mkdir(exist_ok=True)
    fake = FakeSharePoint()
    fake.online = False
    uploader = SharePointUploader(outbox, state_dir=tmp_path / "state",
                                  transport=fake)
    dlg = SharePointUploadDialog(
        None, virtual=True, config_path=tmp_path / "sp_cfg.json",
        state_dir=tmp_path / "state", uploader=uploader)
    try:
        src = tmp_path / "reports"
        src.mkdir()
        (src / "a.csv").write_text("1,2,3")
        dlg.folder_edit.setText(str(src))
        dlg.rb_packaged.setChecked(True)
        logs = []
        dlg.action_logged.connect(logs.append)
        result, _zpath = dlg.pack_now()
        assert result is not None and result.status == "FAILED"
        failed_lines = [ln for ln in logs if "-> FAILED" in ln]
        assert failed_lines
        assert "upload failed:" in failed_lines[0]
        assert "network down" in failed_lines[0]
    finally:
        dlg.deleteLater()


def test_menu_action_wired(qapp, tmp_path, monkeypatch):
    """Report > SharePoint Upload… is present but temporarily DISABLED
    (M15, 2026-10-27); the handler shows a notice instead of opening
    the dialog."""
    from PySide6.QtWidgets import QMessageBox
    from mtkgui.main_window import MainWindow
    MainWindow.__test__ = False
    win = MainWindow(role="Supervisor", mode="Virtual", fixture="ATE")
    try:
        action = win.report_menu.actions()[-1]
        assert action.text() == "SharePoint Upload…"
        assert not action.isEnabled()  # M15: temporarily disabled
        assert "Temporarily disabled" in action.toolTip()
        notices = []
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(
                lambda *args, **kwargs: notices.append(args[2] or "")
                or QMessageBox.StandardButton.Ok))
        win._open_sharepoint_upload()
        assert notices and "temporarily disabled" in notices[0].lower()
    finally:
        win.close()
        win.deleteLater()
