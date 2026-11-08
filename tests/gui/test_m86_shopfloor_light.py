# -*- coding: utf-8 -*-
"""M86-C5: shopfloor light + the three retry moments (fake transport only)."""
from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui import sharepoint_store  # noqa: E402
from mtkgui.engine.uploader import FakeSharePoint  # noqa: E402
from mtkgui.gui.shopfloor_worker import (  # noqa: E402
    LIGHT_UI,
    ShopfloorUploadWorker,
    light_ui,
)

SECTION = {"enabled": True, "site_url": "https://virtual.sharepoint.local/x"}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    """Every test owns its work folder (state + dedup ledger)."""
    monkeypatch.setenv("MTKGUI_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("MTKGUI_PROJECT", "M86-SHOP")
    yield


def _worker(files, transport) -> ShopfloorUploadWorker:
    return ShopfloorUploadWorker(files, SECTION, transport=transport)


def _manifest_folder(tmp_path) -> list[str]:
    folder = tmp_path / "run"
    folder.mkdir()
    for name in ("DUT_PASS_SN1.pdf", "DUT_detail_SN1.csv",
                 "power_rails_SN1.csv", "DUT_PASS_SN1_console_log.txt",
                 "DUT_PASS_SN1_ai_review.txt", "notes.txt"):
        (folder / name).write_text("x", encoding="utf-8")
    return [str(path) for path in folder.iterdir() if path.is_file()]


# ------------------------------------------------------------- the light
def test_light_starts_from_persisted_state():
    expected = {
        "off": ("disconnected", "SharePoint upload off or not configured"),
        "ok": ("connected", "Last upload succeeded - nothing pending"),
        "busy": ("untested", "Uploading, or files waiting to retry"),
        "fail": ("error", "Upload failed - files stay in the outbox"),
    }
    for state, (colour, tooltip) in expected.items():
        assert light_ui({"light": state}) == (colour, tooltip)
    assert light_ui({}) == LIGHT_UI["off"]
    assert light_ui({"light": "bogus"}) == LIGHT_UI["off"]


def test_light_goes_busy_then_ok_on_success(tmp_path):
    sharepoint_store.save_state(light="busy")
    transport = FakeSharePoint()
    worker = _worker(_manifest_folder(tmp_path), transport)
    worker.run()
    state = sharepoint_store.load_state()
    assert state["light"] == "ok"
    assert state["last_result"] == "OK"
    assert state["pending"] == []
    assert state["last_url"]
    assert len(transport.uploaded) == 4


def test_light_goes_fail_and_keeps_pending_list(tmp_path):
    transport = FakeSharePoint()
    transport.online = False
    files = _manifest_folder(tmp_path)
    pdf = [name for name in files if name.endswith(".pdf")][0]
    worker = _worker([pdf], transport)
    worker.run()
    state = sharepoint_store.load_state()
    assert state["light"] == "fail"
    assert state["last_result"] == "FAILED"
    assert state["pending"] == [pdf]
    assert transport.uploaded == {}


def test_run_end_uploads_only_the_manifest_files(tmp_path):
    transport = FakeSharePoint()
    worker = _worker(_manifest_folder(tmp_path), transport)
    worker.run()
    names = {path.rsplit("/", 1)[-1] for path in transport.uploaded}
    assert names == {"DUT_PASS_SN1.pdf", "DUT_detail_SN1.csv",
                     "power_rails_SN1.csv", "DUT_PASS_SN1_console_log.txt"}
    assert "DUT_PASS_SN1_ai_review.txt" not in names
    assert "notes.txt" not in names


# --------------------------------------------------- window integration
def test_exit_does_not_clear_the_light(qapp):
    from mtkgui.main_window import MainWindow
    from mtkgui.permissions import FIXTURE_ATE, ROLE_SUPERVISOR

    sharepoint_store.save_state(light="ok")
    window = MainWindow(role=ROLE_SUPERVISOR, fixture=FIXTURE_ATE)
    try:
        assert "succeeded" in window.shopfloor_led.toolTip()
        window.close()
        assert sharepoint_store.load_state()["light"] == "ok"
    finally:
        window.deleteLater()


def test_close_waits_for_the_upload_worker(qapp, tmp_path):
    from mtkgui.main_window import MainWindow
    from mtkgui.permissions import FIXTURE_ATE, ROLE_SUPERVISOR

    class SlowSharePoint(FakeSharePoint):
        def put(self, path, data):
            time.sleep(2.0)
            return super().put(path, data)

    sharepoint_store.save_state(light="ok")
    window = MainWindow(role=ROLE_SUPERVISOR, fixture=FIXTURE_ATE)
    target = tmp_path / "DUT_PASS_SN1.pdf"
    target.write_bytes(b"%PDF")
    worker = ShopfloorUploadWorker(
        [str(target)], SECTION, state_dir=tmp_path / "state",
        transport=SlowSharePoint())
    try:
        window._shopfloor_workers.add(worker)
        worker.start()
        deadline = time.monotonic() + 5.0
        while not worker.isRunning() and time.monotonic() < deadline:
            qapp.processEvents()
        assert worker.isRunning()
        window.close()
        assert worker.isRunning() is False
        assert worker not in window._shopfloor_workers
        assert sharepoint_store.load_state()["light"] != "off"
    finally:
        window.deleteLater()


def test_startup_retries_pending_once(qapp, tmp_path, monkeypatch):
    from mtkgui.main_window import MainWindow
    from mtkgui.permissions import FIXTURE_ATE, ROLE_SUPERVISOR

    pending = tmp_path / "pending.pdf"
    pending.write_bytes(b"%PDF")
    sharepoint_store.save_state(pending=[str(pending)])
    window = MainWindow(role=ROLE_SUPERVISOR, fixture=FIXTURE_ATE)
    calls = []
    monkeypatch.setattr(window, "_shopfloor_upload",
                        lambda files: calls.append(list(files)))
    try:
        window._shopfloor_started = False
        window._startup_shopfloor_retry()
        window._startup_shopfloor_retry()
        assert calls == [[str(pending)]]
    finally:
        window.deleteLater()
