# -*- coding: utf-8 -*-
"""P2-7 report archive demo (headless-safe, rc=0 on success).

Closed loop: report files pack (redundant filter + ZIP + manifest +
3-tier distribution) -> integrity verify (incl. tamper detection) ->
retention cleanup (expired + capacity cap, injectable clock) -> audit
trail.  Exit 0 = all checkpoints passed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mtkgui.engine.archive import (ArchiveManager, is_junk,  # noqa: E402
                                   file_sha256)

T0 = datetime(2026, 10, 4, 9, 0, 0)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="p2_7_demo_"))
    mgr = ArchiveManager(tmp / "archive", station="S1",
                         version="v2.0.0", retain_days=30,
                         max_capacity_mb=1)

    # 1. report files: 3 real + junk (tmp/bak/hidden/pycache)
    reports = tmp / "logs"
    reports.mkdir()
    real = {}
    for nm, body in (("report_B001.csv", "sn,verdict\n1,PASS\n"),
                     ("rail_capture.csv", "t,v\n0,3.30\n"),
                     ("ai_review.txt", "anomaly: none\n")):
        p = reports / nm
        p.write_text(body, encoding="utf-8")
        real[nm] = body
    (reports / "leftover.tmp").write_text("junk", encoding="utf-8")
    (reports / "old.bak").write_text("junk", encoding="utf-8")
    (reports / ".hidden").write_text("junk", encoding="utf-8")
    pyc = reports / "__pycache__"
    pyc.mkdir()
    (pyc / "mod.pyc").write_text("junk", encoding="utf-8")
    assert is_junk(Path("x/leftover.tmp")) and \
        is_junk(Path("a/__pycache__/m.pyc")) and \
        is_junk(Path(".DS_Store")), "junk filter"
    assert not is_junk(reports / "report_B001.csv"), "real file kept"

    # 2. pack: standardized name + 3-tier distribution + manifest
    e = mgr.pack([reports / n for n in real], batch="B001", ts=T0)
    assert e.name == "B001_20261004_090000_S1_v2.0.0.zip", e.name
    assert e.files == sorted(real), "redundant files filtered out"
    day = f"{T0:%Y%m%d}"
    tiers = [tmp / "archive/history" / e.name,
             tmp / f"archive/daily/{day}" / e.name,
             tmp / "archive/batch/B001" / e.name]
    assert all(t.is_file() for t in tiers), "3-tier layout"
    import zipfile, json
    with zipfile.ZipFile(tiers[0]) as zf:
        meta = json.loads(zf.read("manifest.json"))
        assert meta["batch"] == "B001" and meta["station"] == "S1"
        assert set(meta["files"]) == set(real), "manifest hashes"
        assert zf.read("report_B001.csv") == \
            real["report_B001.csv"].encode(), "lossless content"

    # 3. verify: intact zip passes; tampered member is detected
    assert mgr.verify(e) == [], "intact archive verifies clean"
    victim = tmp / f"archive/daily/{day}" / e.name
    victim.write_bytes(victim.read_bytes()[:-3] + b"xxx")
    mgr2 = ArchiveManager(tmp / "archive", station="S1",
                          version="v2.0.0")
    e2 = type(e)(zip_path=victim, batch=e.batch, ts=e.ts,
                 station=e.station, version=e.version,
                 sha256=file_sha256(victim),  # outer ok, member broken
                 files=e.files, hashes=e.hashes, bytes=1)
    assert mgr2.verify(e2), "tampered member detected"
    # zip member completeness (manifest + payloads all present)
    with zipfile.ZipFile(e.zip_path) as zf:
        names = zf.namelist()
    assert "manifest.json" in names and \
        "report_B001.csv" in names, "zip members complete"

    # 4. capacity cleanup (1MB cap on the history layer): incompressible
    #    blobs, oldest evicted first, newest small batch survives
    import os as _os
    big = reports / "big_blob.bin"
    big.write_bytes(_os.urandom(1_200_000))
    e_b2 = mgr.pack([big], batch="B002", ts=T0 + timedelta(hours=5))
    small = reports / "report_B003.csv"
    small.write_text("sn,verdict\n1,PASS\n", encoding="utf-8")
    e_b3 = mgr.pack([small], batch="B003", ts=T0 + timedelta(hours=6))
    rep = mgr.cleanup(now=T0 + timedelta(days=1))
    assert rep["removed"] == [e.name, e_b2.name], rep  # oldest evicted
    assert rep["kept"] == 1
    assert not (tmp / "archive/history" / e.name).exists(), "evicted"
    assert (tmp / "archive/history" / e_b3.name).exists(), "kept"

    # 5. expiry cleanup with injectable clock (>30d old)
    rep2 = mgr.cleanup(now=T0 + timedelta(days=40))
    assert e_b3.name in rep2["removed"], "expired archive removed"
    assert rep2["kept"] == 0 and rep2["total_mb"] == 0.0, "root empty"

    # 6. audit trail: every action logged with [ARCHIVE] lines
    actions = [a for _, a, _ in mgr.audit]
    assert actions.count("pack") == 3, "pack logged"
    assert "verify" in actions and "cleanup" in actions, "traceability"
    inv = mgr.list_archives()
    assert inv == [], "empty after full expiry"

    print("[P2-7 archive demo] report archive OK — junk filter, "
          "standardized zip naming, 3-tier layout, sha256 manifest, "
          "integrity verify + tamper detection, retention + capacity "
          "cleanup, [ARCHIVE] audit trail all validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
