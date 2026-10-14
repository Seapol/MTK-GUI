# -*- coding: utf-8 -*-
"""Packaged upload + real-time folder sync on the P2-8 uploader
(user direction 2026-10-14): timestamped zip per period, period
scheduler, hash-dedup folder mirror."""
from __future__ import annotations

import time
import zipfile

import pytest

from mtkgui.engine.uploader import (
    PERIOD_DAYS,
    MODE_PACKAGED,
    MODE_SYNC,
    UploadConfig,
    FakeSharePoint,
    SharePointUploader,
)


def make_uploader(tmp_path):
    outbox = tmp_path / "outbox"
    fake = FakeSharePoint()
    up = SharePointUploader(outbox, state_dir=tmp_path / "state",
                            transport=fake)
    up.apply_config(UploadConfig(enabled=True,
                                 site_url="https://corp.sharepoint.com"))
    return up, fake


def test_config_round_trip_mode_fields():
    cfg = UploadConfig(enabled=True, site_url="s", mode=MODE_PACKAGED,
                       pack_period="quarterly", last_pack_ts=123.5)
    restored = UploadConfig.from_config({"sharepoint": cfg.to_config()})
    assert restored.mode == MODE_PACKAGED
    assert restored.pack_period == "quarterly"
    assert restored.last_pack_ts == 123.5
    # defaults survive a legacy config without the new keys
    legacy = UploadConfig.from_config({"sharepoint": {"site_url": "x"}})
    assert legacy.mode == MODE_SYNC and legacy.pack_period == "weekly"


def test_pack_and_upload_timestamped_zip(tmp_path):
    up, fake = make_uploader(tmp_path)
    src = tmp_path / "reports"
    src.mkdir()
    (src / "a.csv").write_text("1,2,3")
    (src / "sub").mkdir()
    (src / "sub" / "b.log").write_text("hello")
    result, zpath = up.pack_and_upload(src)
    assert result is not None and result.status == "UPLOADED"
    assert zpath is not None and zpath.exists()
    assert zpath.parent == tmp_path / "state"       # never the source
    assert zpath.name.startswith("reports_") and zpath.suffix == ".zip"
    # timestamp in the name: reports_YYYYMMDD_HHMMSS.zip
    stamp = zpath.stem[len("reports_"):]
    assert len(stamp) == 15 and stamp[8] == "_"
    with zipfile.ZipFile(zpath) as zf:
        assert set(zf.namelist()) == {"a.csv", "sub/b.log"}
    remote_name = f"{result.url.rsplit('/', 1)[-1]}"
    assert remote_name in {n.rsplit('/', 1)[-1]
                           for n in fake.uploaded}
    assert up.config.last_pack_ts > 0               # period marked


def test_pack_empty_folder_marks_period(tmp_path):
    up, _fake = make_uploader(tmp_path)
    src = tmp_path / "empty"
    src.mkdir()
    result, zpath = up.pack_and_upload(src)
    assert result is None and zpath is None
    assert up.config.last_pack_ts > 0


def test_pack_due_period_scheduler(tmp_path):
    up, _fake = make_uploader(tmp_path)
    assert up.pack_due() is True                    # never packed
    up.mark_packed()
    assert up.pack_due() is False                   # just packed
    # weekly period: due again after 7 days, not after 6
    up.config.pack_period = "weekly"
    base = up.config.last_pack_ts
    assert up.pack_due(now=base + 6 * 86400) is False
    assert up.pack_due(now=base + 7 * 86400 + 1) is True
    # every configured period maps to its day count
    for period, days in PERIOD_DAYS.items():
        up.config.pack_period = period
        assert up.pack_due(now=base + days * 86400 + 1) is True
        assert up.pack_due(now=base + (days - 1) * 86400) is False
    up.config.pack_period = "biweekly"
    assert PERIOD_DAYS["biweekly"] == 14
    assert up.pack_due(now=base + 14 * 86400 + 1) is True


def test_sync_folder_mirrors_and_dedups(tmp_path):
    up, fake = make_uploader(tmp_path)
    src = tmp_path / "reports"
    src.mkdir()
    (src / "a.csv").write_text("1,2,3")
    (src / "b.csv").write_text("4,5,6")
    results = up.sync_folder(src)
    assert [r.status for r in results] == ["UPLOADED", "UPLOADED"]
    assert len(fake.uploaded) == 2
    # second sweep: identical content -> deduped, nothing re-uploaded
    results2 = up.sync_folder(src)
    assert all(r.status == "DEDUPED" for r in results2)
    assert fake.uploaded["a.csv"] == b"1,2,3"
    # a changed file syncs again (same remote name, new content)
    (src / "a.csv").write_text("9,9,9")
    results3 = up.sync_folder(src)
    changed = next(r for r in results3 if r.name == "a.csv")
    assert changed.status == "UPLOADED"
    assert fake.uploaded["a.csv"] == b"9,9,9"


def test_packaged_mode_uses_sync_gate(tmp_path):
    """The mode fields ride the same config: a packaged uploader keeps
    the sync gate semantics (blacklist / dedup / retry) for zips, and
    every pack carries a FRESH timestamp (injectable clock)."""
    from datetime import datetime, timedelta

    class Clock:
        def __init__(self):
            self.t = datetime(2026, 10, 14, 12, 0, 0)

        def __call__(self):
            self.t += timedelta(hours=1)
            return self.t

    fake = FakeSharePoint()
    up = SharePointUploader(tmp_path / "outbox",
                            state_dir=tmp_path / "state",
                            transport=fake, now=Clock())
    up.apply_config(UploadConfig(enabled=True,
                                 site_url="https://corp.sharepoint.com",
                                 mode=MODE_PACKAGED))
    src = tmp_path / "reports"
    src.mkdir()
    (src / "a.csv").write_text("1")
    result, zpath = up.pack_and_upload(src)
    assert result.status == "UPLOADED"
    result2, zpath2 = up.pack_and_upload(src)
    assert zpath2.name != zpath.name          # fresh timestamp
    assert result2.status == "UPLOADED"
    assert len(fake.uploaded) == 2
