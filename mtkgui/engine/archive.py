# -*- coding: utf-8 -*-
"""P2-7 mass-production report archive (pure incremental tool layer).

Unattended local archiving for the P1 report base (logs_dir CSV /
review / any batch artifacts):

  * pack       — redundant files filtered, lossless ZIP with a
                 standardized name  {batch}_{ts}_{station}_{version}.zip
                 and an embedded manifest (per-file SHA-256 + metadata)
  * 3-tier layout — history/ (long-term) + daily/<date>/ + batch/<id>/
                 the same canonical zip is placed in all three tiers so
                 operators find it under either dimension
  * verify     — re-hash the zip and every member against the manifest
                 (integrity proof: no corruption, no loss)
  * cleanup    — configurable retention (days) and disk capacity cap;
                 oldest archives removed first; every action logged

Zero changes to the test flow, the report writers or the metrics
engine.  Every pack / verify / cleanup step emits an ``[ARCHIVE]`` log
line and is recorded in ``audit`` so results stay traceable.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# redundant / transient artifacts never packed into an archive
JUNK_SUFFIXES = {".tmp", ".bak", ".pyc", ".swp", ".log~"}
JUNK_DIRS = {"__pycache__", ".git", ".pytest_cache"}
JUNK_NAMES = {".DS_Store", "Thumbs.db"}

HISTORY = "history"
DAILY = "daily"
BATCH = "batch"
TIERS = (HISTORY, DAILY, BATCH)


def is_junk(path: Path) -> bool:
    """Redundant-file filter: hidden files, temp/backup suffixes and
    cache directories are excluded from packing."""
    if path.name.startswith(".") or path.name in JUNK_NAMES:
        return True
    if path.suffix.lower() in JUNK_SUFFIXES:
        return True
    return any(p in JUNK_DIRS for p in path.parts)


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class ArchiveEntry:
    """One packed archive (canonical zip) and its provenance."""
    zip_path: Path
    batch: str
    ts: datetime
    station: str
    version: str
    sha256: str
    files: list[str] = field(default_factory=list)
    hashes: dict = field(default_factory=dict)   # name -> sha256
    bytes: int = 0

    @property
    def name(self) -> str:
        return self.zip_path.name

    def to_dict(self) -> dict:
        return {"zip": self.zip_path.name, "batch": self.batch,
                "ts": self.ts.isoformat(timespec="seconds"),
                "station": self.station, "version": self.version,
                "sha256": self.sha256, "bytes": self.bytes,
                "files": list(self.files)}


class ArchiveManager:
    """Three-tier local report archive with retention control.

    root/
      history/<name>.zip          long-term layer
      daily/<YYYYmmdd>/<name>.zip same-day lookup layer
      batch/<batch>/<name>.zip    per-batch lookup layer
    """

    def __init__(self, root, *, station: str = "S1",
                 version: str = "v2.0.0", retain_days: int = 90,
                 max_capacity_mb: int = 1024, now=None):
        self.root = Path(root)
        self.station = station
        self.version = version
        self.retain_days = retain_days
        self.max_capacity_mb = max_capacity_mb
        self._now = now or datetime.now
        self.audit: list[tuple[str, str, str]] = []  # (time,action,detail)
        for tier in TIERS:
            (self.root / tier).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ log
    def _log(self, action: str, detail: str) -> None:
        ts = self._now()
        self.audit.append((ts.isoformat(timespec="seconds"), action,
                           detail))
        print(f"[ARCHIVE] {ts:%Y-%m-%d %H:%M:%S} {action}: {detail}")

    # ----------------------------------------------------------- pack
    def pack(self, files, *, batch: str,
             ts: datetime | None = None) -> ArchiveEntry:
        """Filter, compress and distribute one report archive.

        The canonical zip is written to history/, then copied to
        daily/<date>/ and batch/<batch>/ (three-tier layout).  An
        embedded manifest.json carries per-file SHA-256 hashes and the
        archive metadata for later verification.
        """
        ts = ts or self._now()
        clean = sorted({Path(f) for f in files
                        if Path(f).is_file() and not is_junk(Path(f))})
        name = (f"{batch}_{ts:%Y%m%d_%H%M%S}_"
                f"{self.station}_{self.version}.zip")
        zip_path = self.root / HISTORY / name
        hashes = {p.name: file_sha256(p) for p in clean}
        with zipfile.ZipFile(zip_path, "w",
                             compression=zipfile.ZIP_DEFLATED) as zf:
            for p in clean:
                zf.write(p, arcname=p.name)
            manifest = {"batch": batch,
                        "ts": ts.isoformat(timespec="seconds"),
                        "station": self.station,
                        "version": self.version,
                        "files": hashes}
            zf.writestr("manifest.json",
                        json.dumps(manifest, ensure_ascii=False,
                                   indent=2))
        entry = ArchiveEntry(zip_path=zip_path, batch=batch, ts=ts,
                             station=self.station, version=self.version,
                             sha256=file_sha256(zip_path),
                             files=[p.name for p in clean],
                             hashes=hashes, bytes=zip_path.stat().st_size)
        # distribute to the lookup tiers
        for tier_sub in (self.root / DAILY / f"{ts:%Y%m%d}",
                         self.root / BATCH / batch):
            tier_sub.mkdir(parents=True, exist_ok=True)
            shutil.copy2(zip_path, tier_sub / name)
        self._log("pack", f"{name} files={len(clean)} "
                          f"size={entry.bytes}B sha256={entry.sha256[:12]}")
        return entry

    # --------------------------------------------------------- verify
    def verify(self, entry: ArchiveEntry) -> list[str]:
        """Integrity check: zip hash + every member hash vs manifest.

        Returns a list of problems (empty = intact).  Any zip of the
        three tiers can be verified via the entry metadata.
        """
        problems: list[str] = []
        zip_path = entry.zip_path
        if not zip_path.is_file():
            return [f"{zip_path}: missing"]
        if file_sha256(zip_path) != entry.sha256:
            problems.append(f"{zip_path.name}: archive hash mismatch")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = set(zf.namelist())
                if "manifest.json" not in names:
                    problems.append("manifest.json missing")
                    return problems
                meta = json.loads(zf.read("manifest.json"))
                for fname, want in meta.get("files", {}).items():
                    if fname not in names:
                        problems.append(f"{fname}: missing in zip")
                        continue
                    got = hashlib.sha256(zf.read(fname)).hexdigest()
                    if got != want:
                        problems.append(f"{fname}: content hash mismatch")
                for fname in names - {"manifest.json"}:
                    if fname not in meta.get("files", {}):
                        problems.append(f"{fname}: not in manifest")
        except (zipfile.BadZipFile, OSError, ValueError,
                EOFError) as exc:
            problems.append(f"{zip_path.name}: unreadable zip ({exc})")
        self._log("verify", f"{zip_path.name}: "
                            f"{'OK' if not problems else problems}")
        return problems

    # -------------------------------------------------------- cleanup
    def _all_archives(self) -> list[Path]:
        return sorted(self.root.rglob("*.zip"))

    def cleanup(self, *, now: datetime | None = None) -> dict:
        """Retention enforcement: drop archives older than retain_days,
        then trim to max_capacity_mb (oldest first).  Returns a report
        dict; mirrored tier copies are removed together with the
        canonical history zip."""
        now = now or self._now()
        cutoff = now.timestamp() - self.retain_days * 86400
        zips = self._all_archives()
        removed: list[str] = []
        # 1) age-based removal, keyed by archive name (all tiers)
        by_name: dict[str, list[Path]] = {}
        for z in zips:
            by_name.setdefault(z.name, []).append(z)
        for name, paths in list(by_name.items()):
            mtime = max(p.stat().st_mtime for p in paths)
            if mtime < cutoff:
                for p in paths:
                    p.unlink()
                removed.append(name)
                del by_name[name]
        if removed:
            self._log("cleanup", f"expired (>{self.retain_days}d): "
                                 f"{len(removed)} archives")
        # 2) capacity cap: remove oldest archives until under limit
        #    (footprint measured on the canonical history layer)
        zips_hist = sorted((self.root / HISTORY).rglob("*.zip"))
        total_mb = sum(p.stat().st_size for p in zips_hist) / 1e6
        while total_mb > self.max_capacity_mb and by_name:
            oldest = min(by_name, key=lambda n: min(
                p.stat().st_mtime for p in by_name[n]))
            hist = self.root / HISTORY / oldest
            if hist.is_file():
                total_mb -= hist.stat().st_size / 1e6
            for p in by_name.pop(oldest):
                p.unlink()
            removed.append(oldest)
        if by_name:
            self._log("cleanup", f"capacity check: {total_mb:.1f}MB / "
                                 f"{self.max_capacity_mb}MB, kept "
                                 f"{len(by_name)} archives")
        return {"removed": removed, "kept": len(by_name),
                "total_mb": round(total_mb, 2)}

    # ---------------------------------------------------------- query
    def list_archives(self, *, tier: str = HISTORY) -> list[dict]:
        """Inventory of one tier (name / batch / bytes / mtime)."""
        base = self.root / tier
        out = []
        for z in sorted(base.rglob("*.zip")):
            out.append({"name": z.name, "bytes": z.stat().st_size,
                        "mtime": datetime.fromtimestamp(
                            z.stat().st_mtime)})
        return out
