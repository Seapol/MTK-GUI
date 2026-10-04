# -*- coding: utf-8 -*-
"""P2-8 upload page tests (headless offscreen)."""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from mtkgui.engine.uploader import FakeSharePoint, SharePointUploader
from mtkgui.gui.shell import MainWindow
from mtkgui.gui.upload_page import UploadPage

T0 = datetime(2026, 10, 4, 10, 0, 0)
CFG = {"sharepoint": {
    "enabled": True, "site_url": "https://corp.sharepoint.com/ict",
    "upload_retry_count": 1, "resume_on_disconnect": True,
    "overwrite_policy": "overwrite", "project_dir": "PRJ",
    "archive_whitelist": ["*.zip"],
}}


@pytest.fixture()
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(app, tmp_path):
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    (outbox / "a.zip").write_bytes(b"PK-a")
    mgr = SharePointUploader(outbox, state_dir=tmp_path / "state",
                             transport=FakeSharePoint(),
                             now=lambda: T0, sleep=lambda s: 0)
    p = UploadPage(mgr)
    p.interactive = False
    return p, outbox


def test_initial_status_and_empty_ledger(page):
    p, _ = page
    assert "停用" in p.status_label.text()
    assert p.ledger_table.rowCount() == 0


def test_hot_config_apply(page):
    p, _ = page
    p.apply_config(CFG)
    assert "启用" in p.status_label.text()
    assert "/PRJ" in p.status_label.text(), "project dir shown"
    assert p.manager.config.retry_count == 1, "hot update"


def test_upload_sweep_updates_ledger_and_signal(page, qtbot=None):
    p, outbox = page
    p.apply_config(CFG)
    fired = []
    p.upload_done.connect(lambda ok, bad: fired.append((ok, bad)))
    p.on_upload()
    assert p.ledger_table.rowCount() == 1, "ledger book visible"
    assert p.ledger_table.item(0, 0).text() == "a.zip"
    assert p.ledger_table.item(0, 1).text() == "UPLOADED"
    assert fired == [(1, 0)]


def test_failed_upload_shows_fallback_note(page):
    p, outbox = page
    p.apply_config(CFG)
    p.manager.transport.online = False
    p.on_upload()
    assert "失败 1" in p.status_label.text(), "failure surfaced"
    assert "outbox" in p.status_label.text(), "fallback note"
    assert (outbox / "a.zip").is_file(), "file kept locally"


def test_precheck_surface(page):
    p, _ = page
    p.manager.apply_config(CFG)
    p.on_precheck()
    assert "预检通过" in p.status_label.text()
    p.manager.transport.deny_write = True
    p.on_precheck()
    assert "预检异常" in p.status_label.text()


def test_shell_registers_upload_route(app):
    win = MainWindow()
    win.interactive = False
    win.mount_default_routes()
    assert isinstance(win.upload_manager, SharePointUploader)
    win.navigate("upload")
    current = win.stack.currentWidget()
    assert isinstance(current, UploadPage)
    assert current.manager is win.upload_manager
