# -*- coding: utf-8 -*-
"""P2-7 archive module tests: pack / verify / cleanup / audit."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta

import pytest

from mtkgui.engine.archive import (ArchiveManager, is_junk,  # noqa: F401
                                   file_sha256)

T0 = datetime(2026, 10, 4, 9, 0, 0)


@pytest.fixture()
def env(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    files = []
    for i, nm in enumerate(("r.csv", "rails.csv", "review.txt")):
        p = logs / nm
        p.write_text(f"data-{i}\n", encoding="utf-8")
        files.append(p)
    (logs / "x.tmp").write_text("junk")
    (logs / ".hid").write_text("junk")
    cache = logs / "__pycache__"
    cache.mkdir()
    (cache / "m.pyc").write_text("junk")
    mgr = ArchiveManager(tmp_path / "arch", station="ST7",
                         version="v1.2.3", retain_days=30,
                         max_capacity_mb=100)
    return mgr, files


def test_naming_and_three_tiers(env):
    mgr, files = env
    e = mgr.pack(files, batch="B7", ts=T0)
    assert e.name == "B7_20261004_090000_ST7_v1.2.3.zip"
    day = f"{T0:%Y%m%d}"
    for tier in (mgr.root / "history" / e.name,
                 mgr.root / "daily" / day / e.name,
                 mgr.root / "batch" / "B7" / e.name):
        assert tier.is_file()
    assert e.files == ["r.csv", "rails.csv", "review.txt"]
    assert e.sha256 == file_sha256(mgr.root / "history" / e.name)


def test_junk_excluded_and_lossless(env):
    mgr, files = env
    e = mgr.pack(files, batch="B1", ts=T0)
    with zipfile.ZipFile(e.zip_path) as zf:
        assert "manifest.json" in zf.namelist()
        meta = json.loads(zf.read("manifest.json"))
        assert meta["batch"] == "B1" and meta["station"] == "ST7"
        assert set(meta["files"]) == {p.name for p in files}
        assert zf.read("r.csv") == b"data-0\n"      # lossless
    assert "x.tmp" not in e.hashes and ".hid" not in e.hashes


def test_verify_clean_and_tampered(env):
    mgr, files = env
    e = mgr.pack(files, batch="B2", ts=T0)
    assert mgr.verify(e) == [], "clean archive"
    # flip a byte inside one member -> content hash mismatch
    victim = mgr.root / "daily" / f"{T0:%Y%m%d}" / e.name
    with zipfile.ZipFile(victim) as zf:
        members = {n: zf.read(n) for n in zf.namelist()}
    members["r.csv"] = members["r.csv"].replace(b"data-0", b"data-X")
    with zipfile.ZipFile(victim, "w") as zf:
        for n, body in members.items():
            zf.writestr(n, body)
    e2 = type(e)(zip_path=victim, batch=e.batch, ts=e.ts,
                 station=e.station, version=e.version,
                 sha256=file_sha256(victim),   # outer hash re-signed
                 files=e.files, hashes=e.hashes, bytes=1)
    problems = mgr.verify(e2)
    assert problems and "r.csv" in problems[0], "member tamper caught"


def test_verify_missing_zip(env):
    mgr, files = env
    e = mgr.pack(files, batch="B3", ts=T0)
    e.zip_path.unlink()
    assert mgr.verify(e) == [f"{e.zip_path}: missing"]


def test_capacity_cleanup_oldest_first(tmp_path):
    import os
    logs = tmp_path / "logs"
    logs.mkdir()
    mgr = ArchiveManager(tmp_path / "arch", retain_days=3650,
                         max_capacity_mb=1.0)
    small = logs / "s.csv"
    small.write_text("x", encoding="utf-8")
    entries = []
    for i in range(3):
        blob = logs / f"b{i}.bin"
        blob.write_bytes(os.urandom(800_000))  # incompressible
        entries.append(mgr.pack([blob, small], batch=f"BX{i}",
                                ts=T0 + timedelta(hours=i)))
    rep = mgr.cleanup(now=T0 + timedelta(hours=4))
    # history footprint ~2.4MB > 1MB -> two oldest evicted, newest kept
    assert rep["removed"] == [entries[0].name, entries[1].name]
    assert rep["kept"] == 1
    assert (mgr.root / "history" / entries[2].name).is_file()


def test_expiry_cleanup_and_tier_copy_removal(env):
    mgr, files = env
    e = mgr.pack(files, batch="B9", ts=T0)
    rep = mgr.cleanup(now=T0 + timedelta(days=31))
    assert rep["removed"] == [e.name]
    # ALL tier copies gone (history + daily + batch)
    assert mgr._all_archives() == []
    assert mgr.list_archives() == []
    rep2 = mgr.cleanup(now=T0 + timedelta(days=32))
    assert rep2["removed"] == [] and rep2["kept"] == 0


def test_audit_trail(env):
    mgr, files = env
    e = mgr.pack(files, batch="BA", ts=T0)
    mgr.verify(e)
    mgr.cleanup(now=T0 + timedelta(days=1))    # capacity check branch
    mgr.cleanup(now=T0 + timedelta(days=40))   # expiry branch
    actions = [a for _, a, _ in mgr.audit]
    assert actions == ["pack", "verify", "cleanup", "cleanup"]
    assert all(len(t) == 19 for t, _, _ in mgr.audit), "timestamped"
