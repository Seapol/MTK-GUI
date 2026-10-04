# -*- coding: utf-8 -*-
"""P2-8 uploader tests: config / precheck / filter / dedup / retry /
fallback / ledger / audit."""
from __future__ import annotations

from datetime import datetime

import pytest

from mtkgui.engine.uploader import (BLACKLIST_SUFFIXES,  # noqa: F401
                                    FakeSharePoint, SharePointUploader,
                                    UploadConfig, filter_allowed)

T0 = datetime(2026, 10, 4, 10, 0, 0)

CFG = {"sharepoint": {
    "enabled": True, "site_url": "https://corp.sharepoint.com/ict",
    "upload_retry_count": 2, "resume_on_disconnect": True,
    "overwrite_policy": "keep_both", "project_dir": "PRJ/reports",
    "archive_whitelist": ["*.zip"],
}}


@pytest.fixture()
def up(tmp_path):
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    (outbox / "a.zip").write_bytes(b"PK-a")
    (outbox / "b.zip").write_bytes(b"PK-b")
    mgr = SharePointUploader(outbox, state_dir=tmp_path / "state",
                             transport=FakeSharePoint(),
                             now=lambda: T0, sleep=lambda s: 0)
    mgr.apply_config(CFG)
    return mgr, outbox


def test_config_from_visual_section(up):
    mgr, _ = up
    c = mgr.config
    assert c.enabled and c.site_url.endswith("/ict")
    assert c.retry_count == 2 and c.project_dir == "PRJ/reports"
    assert c.resume_on_disconnect and c.overwrite_policy == "keep_both"


def test_precheck_probes(up):
    mgr, _ = up
    assert mgr.precheck() == [], "healthy site"
    mgr.transport.deny_write = True
    assert any("permission" in p for p in mgr.precheck()), "writable"
    mgr.transport.online = False
    assert any("connectivity" in p for p in mgr.precheck()), "network"
    # not configured at all
    bare = SharePointUploader(mgr.outbox)
    assert any("disabled" in p for p in bare.precheck()), "disabled"


def test_black_whitelist_filter(up):
    assert filter_allowed("evil.exe", []) == "blacklisted type"
    assert filter_allowed("ok.zip", ["*.zip"]) is None
    assert filter_allowed("no.txt", ["*.zip"]) == "not in whitelist"
    mgr, outbox = up
    (outbox / "virus.exe").write_bytes(b"MZ")
    (outbox / "doc.txt").write_text("x")
    res = {r.name: r for r in mgr.upload_pending()}
    assert res["virus.exe"].status == "BLOCKED"
    assert res["doc.txt"].status == "BLOCKED"


def test_upload_success_trace_fields(up):
    mgr, outbox = up
    r = mgr.upload_file(outbox / "a.zip")
    assert r.status == "UPLOADED" and r.attempts == 1
    assert r.url == "https://corp.sharepoint.com/ict/PRJ/reports/a.zip"
    assert len(r.sha256) == 64 and r.ts, "hash + timestamp"


def test_dedup_same_content(up):
    mgr, outbox = up
    first = mgr.upload_file(outbox / "a.zip")
    second = mgr.upload_file(outbox / "a.zip")   # same file re-sent
    assert second.status == "DEDUPED"
    assert second.sha256 == first.sha256
    assert second.url == first.url, "same cloud copy referenced"


def test_retry_then_success(up):
    mgr, outbox = up
    mgr.transport.fail_next_put = 2
    r = mgr.upload_file(outbox / "b.zip")
    assert r.status == "UPLOADED" and r.attempts == 3, \
        "retry_count=2 -> up to 3 attempts"


def test_no_resume_fails_fast(up):
    mgr, outbox = up
    mgr.apply_config({**CFG, "sharepoint": {
        **CFG["sharepoint"], "resume_on_disconnect": False}})
    mgr.transport.fail_next_put = 5
    r = mgr.upload_file(outbox / "b.zip")
    assert r.status == "FAILED" and r.attempts == 1, "no resume"
    assert (outbox / "b.zip").is_file(), "local fallback kept"


def test_fallback_offline_keeps_file(up):
    mgr, outbox = up
    mgr.transport.online = False
    r = mgr.upload_file(outbox / "b.zip")
    assert r.status == "FAILED" and r.attempts == 3
    assert (outbox / "b.zip").is_file(), "outbox fallback"
    assert (outbox / "b.zip").read_bytes() == b"PK-b"


def test_ledger_persistence_and_records(up, tmp_path):
    mgr, outbox = up
    mgr.upload_file(outbox / "a.zip")
    mgr.upload_file(outbox / "b.zip")
    assert len(mgr.records()) == 2
    fresh = SharePointUploader(outbox, state_dir=tmp_path / "state",
                               transport=FakeSharePoint(),
                               now=lambda: T0, sleep=lambda s: 0)
    assert len(fresh.ledger) == 2, "ledger survives restart"


def test_audit_trail(up):
    mgr, outbox = up
    mgr.upload_file(outbox / "a.zip")
    actions = [a for _, a, _ in mgr.audit]
    assert "config" in actions and "uploaded" in actions
    assert all(t.startswith("2026-10-04T10:00:00")
               for t, _, _ in mgr.audit), "injectable clock"
