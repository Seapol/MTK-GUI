# -*- coding: utf-8 -*-
"""M86-C2: the certificate manifest and the per-project remote path."""
from __future__ import annotations

from mtkgui.engine.uploader import (
    MANIFEST_PATTERNS,
    NAME_BLACKLIST,
    FakeSharePoint,
    SharePointUploader,
    UploadConfig,
    filter_allowed,
)

MANIFEST = ("DUT_PASS_SN1.pdf", "DUT_detail_SN1.csv",
            "power_rails_SN1.csv", "DUT_PASS_SN1_console_log.txt")


def _uploader(tmp_path):
    fake = FakeSharePoint()
    uploader = SharePointUploader(tmp_path / "outbox", transport=fake,
                                  state_dir=tmp_path / "state")
    cfg = UploadConfig(enabled=True, site_url="https://x/share",
                       project_dir="root", dest_segments=["P", "ID"])
    uploader.apply_config(cfg)
    return uploader, fake


def test_manifest_accepts_the_four_patterns_and_nothing_else():
    for name in MANIFEST:
        assert filter_allowed(name, list(MANIFEST_PATTERNS)) is None, name
    for name in ("notes.txt", "screenshot.png", "DUT_PASS_SN1_ai_review.txt",
                 "run.log"):
        assert filter_allowed(name, list(MANIFEST_PATTERNS)) is not None, name


def test_ai_review_is_never_uploaded(tmp_path):
    uploader, fake = _uploader(tmp_path)
    review = tmp_path / "DUT_PASS_SN1_ai_review.txt"
    review.write_text("internal review", encoding="utf-8")
    result = uploader.upload_file(review)
    assert result.status == "BLOCKED"
    assert result.detail == "never uploaded"
    assert fake.uploaded == {}
    # the blacklist applies even with an empty whitelist
    assert filter_allowed(review.name, []) == "never uploaded"
    assert NAME_BLACKLIST == ("*_ai_review.txt",)


def test_dest_dir_is_project_then_identity(tmp_path):
    uploader, _fake = _uploader(tmp_path)
    assert uploader._dest_dir() == "root/P/ID"
    resource = tmp_path / MANIFEST[0]
    resource.write_bytes(b"%PDF-1.4")
    result = uploader.upload_file(resource)
    assert result.status == "UPLOADED"
    assert result.url.endswith("/root/P/ID/DUT_PASS_SN1.pdf")


def test_dest_segments_roundtrip_through_config():
    cfg = UploadConfig(dest_segments=["96317", "ST-01-op"])
    section = cfg.to_config()
    assert section["dest_segments"] == ["96317", "ST-01-op"]
    again = UploadConfig.from_config({"sharepoint": section})
    assert again.dest_segments == ["96317", "ST-01-op"]
