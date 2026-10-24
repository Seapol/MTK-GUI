# -*- coding: utf-8 -*-
"""M13-FIX: packaged-upload period scheduler (Daily/Weekly) must gate
the 30 s auto tick, survive a restart, and never turn a failure into a
30 s retry storm."""
from __future__ import annotations

import json
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.uploader import (  # noqa: E402
    MODE_PACKAGED,
    UploadConfig,
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
    """Never block on the real folder guard QMessageBox."""
    from PySide6.QtWidgets import QMessageBox

    def fake_information(*args, **kwargs):
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "information", fake_information)


def _uploader(tmp_path, fake):
    outbox = tmp_path / "outbox"
    outbox.mkdir(exist_ok=True)
    return SharePointUploader(
        outbox, state_dir=tmp_path / "state", transport=fake)


def make_dialog(tmp_path, *, virtual=True, fake=None):
    """Dialog on a temp config path + injected FakeSharePoint uploader."""
    fake = fake or FakeSharePoint()
    uploader = _uploader(tmp_path, fake)
    dlg = SharePointUploadDialog(
        None, virtual=virtual, config_path=tmp_path / "sp_cfg.json",
        state_dir=tmp_path / "state", uploader=uploader)
    return dlg, fake


def _folder_with_file(tmp_path, name="a.csv", text="1,2,3"):
    src = tmp_path / "reports"
    src.mkdir(exist_ok=True)
    (src / name).write_text(text)
    return src


def _packed(dlg, src, period="daily"):
    dlg.folder_edit.setText(str(src))
    dlg.rb_packaged.setChecked(True)
    dlg.period_combo.setCurrentIndex(dlg.period_combo.findData(period))


# ---------------------------------------------------------------- engine
def test_pack_due_respects_period(tmp_path):
    """`pack_due(now)` honours the configured period."""
    up = _uploader(tmp_path, FakeSharePoint())
    up.apply_config(UploadConfig(
        enabled=True, site_url="https://corp.sharepoint.com/ict",
        mode=MODE_PACKAGED, pack_period="daily"))
    up.config.last_pack_ts = 1_000_000.0
    assert up.pack_due(now=1_000_000.0 + 3600) is False
    assert up.pack_due(now=1_000_000.0 + 86400) is True
    up.config.last_pack_ts = 0.0
    assert up.pack_due(now=123.0) is True


# ----------------------------------------------------------------- F1
def test_successful_pack_persists_last_pack_ts(qapp, tmp_path):
    """A successful pack writes sharepoint.last_pack_ts; a fresh
    uploader built from that section is no longer due."""
    dlg, fake = make_dialog(tmp_path)
    try:
        src = _folder_with_file(tmp_path)
        _packed(dlg, src)
        result, _zpath = dlg.pack_now()
        assert result is not None and result.status == "UPLOADED"
        assert fake.uploaded
        data = json.loads(
            (tmp_path / "sp_cfg.json").read_text(encoding="utf-8"))
        section = data["sharepoint"]
        ts = float(section["last_pack_ts"])
        assert ts > 0
        assert dlg._last_pack_ts == ts
        # round-trips through UploadConfig.from_config / to_config
        cfg = UploadConfig.from_config({"sharepoint": section})
        assert UploadConfig.from_config(
            {"sharepoint": cfg.to_config()}).last_pack_ts == ts
        # a NEW uploader on the persisted section is not due
        fresh = _uploader(tmp_path, FakeSharePoint())
        fresh.apply_config(cfg)
        assert fresh.pack_due() is False
    finally:
        dlg.deleteLater()


def test_failed_pack_does_not_persist_last_pack_ts(qapp, tmp_path):
    """A failed pack keeps the previous marker (still due, but backoff
    protected) - it must not push the next due time a full period out."""
    dlg_first, _fake = make_dialog(tmp_path)
    try:
        _packed(dlg_first, _folder_with_file(tmp_path))
        path = dlg_first.save_config()
        assert json.loads(path.read_text(encoding="utf-8"))[
            "sharepoint"]["last_pack_ts"] == 0.0
    finally:
        dlg_first.deleteLater()

    offline = FakeSharePoint()
    offline.online = False
    dlg, _fake = make_dialog(tmp_path, fake=offline)
    try:
        _packed(dlg, tmp_path / "reports")
        result, _zpath = dlg.pack_now()
        assert result is not None and result.status == "FAILED"
        data = json.loads(
            (tmp_path / "sp_cfg.json").read_text(encoding="utf-8"))
        assert float(data["sharepoint"]["last_pack_ts"]) == 0.0
        assert dlg._last_pack_ts == 0.0
        # still due for a retry, but the failure armed the backoff
        assert dlg._build_uploader().pack_due() is True
        assert dlg._auto_pack_backoff_until > time.time()
    finally:
        dlg.deleteLater()


# ----------------------------------------------------------------- F3
def test_auto_tick_skips_pack_without_session(qapp, tmp_path):
    """Real mode, no signed-in session: the 30 s tick never packs."""
    fake = FakeSharePoint()
    dlg, _fake = make_dialog(tmp_path, virtual=False, fake=fake)
    try:
        assert dlg._session is None
        src = _folder_with_file(tmp_path)
        _packed(dlg, src)
        logs = []
        dlg.action_logged.connect(logs.append)
        dlg._auto_tick()
        assert [ln for ln in logs if "sharepoint pack:" in ln] == []
        assert fake.uploaded == {}
        assert not list((tmp_path / "state").glob("*.zip"))
    finally:
        dlg.deleteLater()


def test_auto_tick_backoff_after_failure(qapp, tmp_path):
    """Consecutive auto ticks must not re-pack within the 5 min backoff."""
    offline = FakeSharePoint()
    offline.online = False
    dlg, _fake = make_dialog(tmp_path, fake=offline)
    try:
        _packed(dlg, _folder_with_file(tmp_path))
        logs = []
        dlg.action_logged.connect(logs.append)
        dlg._auto_tick()
        packs = [ln for ln in logs if ln.startswith("sharepoint pack:")]
        assert len(packs) == 1 and "FAILED" in packs[0]
        dlg._auto_tick()
        dlg._auto_tick()
        packs = [ln for ln in logs if ln.startswith("sharepoint pack:")]
        assert len(packs) == 1
        assert dlg._auto_pack_backoff_until >= time.time() + 240
    finally:
        dlg.deleteLater()


# ----------------------------------------------------------------- F4
def test_virtual_auto_tick_packs_once_per_period(qapp, tmp_path):
    """Virtual mode still honours the period: daily -> one pack, and the
    marker survives into a freshly opened dialog."""
    dlg, fake = make_dialog(tmp_path)
    try:
        _packed(dlg, _folder_with_file(tmp_path), period="daily")
        logs = []
        dlg.action_logged.connect(logs.append)
        for _ in range(3):
            dlg._auto_tick()
        packs = [ln for ln in logs if ln.startswith("sharepoint pack:")]
        assert len(packs) == 1 and "UPLOADED" in packs[0]
        assert len(fake.uploaded) == 1
    finally:
        dlg.deleteLater()

    dlg2, _fake2 = make_dialog(tmp_path)
    try:
        assert dlg2._last_pack_ts > 0
        assert dlg2._build_uploader().pack_due() is False
    finally:
        dlg2.deleteLater()


# ----------------------------------------------------------------- F2
def test_manual_pack_ignores_period_gate(qapp, tmp_path):
    """Manual Pack & Upload Now always runs, even when not due."""
    dlg, _fake = make_dialog(tmp_path)
    try:
        src = _folder_with_file(tmp_path)
        _packed(dlg, src)
        first, _z = dlg.pack_now()
        assert first is not None and first.status == "UPLOADED"
        assert dlg._build_uploader().pack_due() is False
        (src / "b.csv").write_text("4,5,6")
        second, _z = dlg.pack_now()
        assert second is not None
        assert second.status in ("UPLOADED", "DEDUPED")
    finally:
        dlg.deleteLater()
