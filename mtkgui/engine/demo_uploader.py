# -*- coding: utf-8 -*-
"""P2-8 SharePoint upload closed-loop demo (headless-safe, rc=0).

Closed loop: P2-2 visual config -> hot apply -> precheck (connectivity/
permission/writable) -> filter (blacklist/whitelist) -> dedup -> retry
with resume-on-disconnect -> ledger + cloud URL + sha256 + ts ->
failure fallback keeps the file in the local outbox.  Exit 0 = all
checkpoints passed.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from mtkgui.engine.uploader import (FakeSharePoint,  # noqa: E402
                                    SharePointUploader)

T0 = datetime(2026, 10, 4, 10, 0, 0)

CFG = {
    "sharepoint": {
        "enabled": True,
        "site_url": "https://corp.sharepoint.com/ict",
        "username": "station01@corp.com",
        "password": "secret",
        "token": "",
        "upload_retry_count": 2,
        "resume_on_disconnect": True,
        "overwrite_policy": "keep_both",
        "project_dir": "FRDM-IMX93/reports",
        "archive_whitelist": ["*.csv", "*.zip"],
    }
}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p2_8_demo_"))
    outbox = tmp / "outbox"
    outbox.mkdir()
    (outbox / "report_B001.zip").write_bytes(b"PK\x03\x04archive")
    (outbox / "rail_capture.csv").write_text("t,v\n0,3.30\n")
    (outbox / "tool.exe").write_bytes(b"MZ")          # blacklisted
    (outbox / "notes.txt").write_text("hi")           # not whitelisted

    sp = FakeSharePoint()
    up = SharePointUploader(outbox, state_dir=tmp / "state",
                            transport=sp, now=lambda: T0, sleep=lambda s: 0)
    up.apply_config(CFG)                     # hot update from P2-2 dict

    # 1. config read back through the visual-config section
    c = up.config
    assert c.enabled and c.retry_count == 2 and \
        c.project_dir == "FRDM-IMX93/reports", c

    # 2. precheck OK against the live fake site
    assert up.precheck() == [], "precheck clean"

    # 3. full sweep: allowed upload, blacklist + whitelist interception
    results = {r.name: r for r in up.upload_pending()}
    assert results["report_B001.zip"].status == "UPLOADED"
    assert results["report_B001.zip"].url == \
        "https://corp.sharepoint.com/ict/FRDM-IMX93/reports/" \
        "report_B001.zip"
    assert results["report_B001.zip"].sha256 and \
        results["report_B001.zip"].ts, "trace fields"
    assert results["rail_capture.csv"].status == "UPLOADED"
    assert results["tool.exe"].status == "BLOCKED", "blacklist"
    assert "notes.txt" in results and \
        results["notes.txt"].status == "BLOCKED", "whitelist"
    assert len(sp.uploaded) == 2, "only allowed payloads on cloud"

    # 4. dedup: identical content second sweep -> DEDUPED, no re-put
    before = len(sp.uploaded)
    again = {r.name: r for r in up.upload_pending()}
    assert again["report_B001.zip"].status == "DEDUPED"
    assert len(sp.uploaded) == before, "no duplicate payload"

    # 5. retry with resume: 2 transient drops then success
    sp.fail_next_put = 2
    (outbox / "report_B002.zip").write_bytes(b"PK\x03\x04batch2")
    r = up.upload_file(outbox / "report_B002.zip")
    assert r.status == "UPLOADED" and r.attempts == 3, r

    # 6. fallback: dead network -> FAILED, file kept in outbox
    sp.online = False
    (outbox / "report_B003.zip").write_bytes(b"PK\x03\x04batch3")
    r = up.upload_file(outbox / "report_B003.zip")
    assert r.status == "FAILED" and r.attempts == 3, r
    assert (outbox / "report_B003.zip").is_file(), "local fallback"
    sp.online = True

    # 7. ledger persistence across restart (traceability)
    up2 = SharePointUploader(outbox, state_dir=tmp / "state",
                             transport=sp, now=lambda: T0,
                             sleep=lambda s: 0)
    up2.apply_config(CFG)
    assert len(up2.ledger) == 3, "ledger reloaded"
    again2 = up2.upload_file(outbox / "report_B001.zip")
    assert again2.status == "DEDUPED", "cross-restart dedup"
    raw = json.loads((tmp / "state" / "upload_ledger.json")
                     .read_text(encoding="utf-8"))
    assert all(e["status"] == "UPLOADED" for e in raw), "book clean"

    # 8. audit trail
    actions = [a for _, a, _ in up.audit]
    for need in ("config", "precheck", "blocked", "dedup", "retry",
                 "uploaded", "failed"):
        assert need in actions, need

    print("[P2-8 upload demo] SharePoint closed loop OK — config hot "
          "apply, precheck, black/white filter, dedup, retry/resume, "
          "ledger + url/sha256/ts trace, local fallback all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
