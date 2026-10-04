# -*- coding: utf-8 -*-
"""Firmware slot image registry - single trusted source (P1 Task7).

Mass-production safeguards for firmware images, purely additive
(the flash parameter layer stays authoritative for path/argument
legality; this module adds image-level integrity management):

  * one canonical load entry - images are inspected, fingerprinted
    and state-tracked before any flash flow may use them
  * SHA-256 fingerprint - catches same-name-different-package and
    tampered images (a changed hash for a known path = STALE)
  * four states: VALID / STALE / CORRUPT / MISSING - queryable,
    judgeable, interceptable
  * reuse decision - skip an already-flashed identical image
    (opt-in via skip_if_same_hash, default OFF for P0 compatibility)
  * [SLOT_IMG] structured audit lines (path, hash, size, state)
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from enum import Enum

MAX_IMAGE_BYTES = 64 * 1024 * 1024        # 64 MB sanity ceiling
ALLOWED_IMAGE_EXTS = (".bin", ".hex", ".srec", ".elf", ".mot")


class ImageState(str, Enum):
    VALID = "VALID"
    STALE = "STALE"          # hash changed for a known path (tamper / swap)
    CORRUPT = "CORRUPT"      # empty, oversized or unreadable
    MISSING = "MISSING"      # not on disk


class SlotImageError(ValueError):
    """A non-VALID image was rejected before the flash flow."""

    def __init__(self, record: "ImageRecord"):
        self.record = record
        super().__init__(
            f"[SLOT_IMG] image rejected: state={record.state.value} "
            f"path={record.path!r} reason={record.reason}")


@dataclass
class ImageRecord:
    """One inspected image: identity, state and provenance."""
    slot: str
    path: str
    sha256: str = ""
    size: int = 0
    state: ImageState = ImageState.MISSING
    reason: str = ""
    inspected_at: float = 0.0

    def fingerprint(self) -> str:
        return f"{self.sha256[:12]}"

    def log_lines(self) -> list[str]:
        return [
            "[SLOT_IMG] image inspect:",
            f"[SLOT_IMG]   slot={self.slot!r} path={self.path!r}",
            f"[SLOT_IMG]   sha256={self.sha256 or '-'} "
            f"size={self.size} state={self.state.value}",
            f"[SLOT_IMG]   verdict={self.reason or 'ok'}",
        ]


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class SlotImageRegistry:
    """Slot-scoped image registry with session flash history."""

    def __init__(self, skip_if_same_hash: bool = False):
        self.skip_if_same_hash = skip_if_same_hash
        self._known: dict[str, str] = {}       # path -> last seen sha256
        self._flashed: dict[str, str] = {}     # slot -> last flashed sha
        self._dirty: set[str] = set()          # rolled-back slots

    # ------------------------------------------------------- inspect
    def inspect(self, path: str, slot: str = "") -> ImageRecord:
        """The one canonical load entry: full legality + integrity
        chain.  Never raises; the state carries the verdict."""
        rec = ImageRecord(slot=slot, path=path,
                          inspected_at=time.time())
        if not path or not os.path.isfile(path):
            rec.state = ImageState.MISSING
            rec.reason = "file does not exist"
            return rec
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            rec.state = ImageState.CORRUPT
            rec.reason = f"unreadable: {exc}"
            return rec
        rec.size = size
        if size == 0:
            rec.state = ImageState.CORRUPT
            rec.reason = "image file is empty"
            return rec
        if size > MAX_IMAGE_BYTES:
            rec.state = ImageState.CORRUPT
            rec.reason = (f"image larger than sanity ceiling "
                          f"({MAX_IMAGE_BYTES} bytes)")
            return rec
        if not path.lower().endswith(ALLOWED_IMAGE_EXTS):
            rec.state = ImageState.CORRUPT
            rec.reason = "illegal image file extension"
            return rec
        try:
            digest = _sha256_file(path)
        except OSError as exc:
            rec.state = ImageState.CORRUPT
            rec.reason = f"hash failed: {exc}"
            return rec
        rec.sha256 = digest
        known = self._known.get(path)
        if known is not None and known != digest:
            # same name, different package: tamper or silent swap
            rec.state = ImageState.STALE
            rec.reason = (f"hash changed for known path "
                          f"(was {known[:12]}, now {digest[:12]})")
            return rec
        rec.state = ImageState.VALID
        rec.reason = "ok"
        self._known[path] = digest
        return rec

    def load(self, path: str, slot: str = "") -> ImageRecord:
        """Inspect + enforce: raises SlotImageError unless VALID."""
        rec = self.inspect(path, slot)
        if rec.state is not ImageState.VALID:
            raise SlotImageError(rec)
        return rec

    # --------------------------------------------------------- reuse
    def should_flash(self, slot: str, sha256: str) -> bool:
        """Reuse decision: an identical image already flashed in this
        session does not need a second write (same-version overwrite
        protection)."""
        return self._flashed.get(slot) != sha256

    def mark_flashed(self, slot: str, sha256: str) -> None:
        self._flashed[slot] = sha256
        self._dirty.discard(slot)

    def mark_dirty(self, slot: str) -> None:
        """Rollback marker (P1 Task8): a failed/rolled-back write must
        never be treated as flashed - the next flash re-writes."""
        self._dirty.add(slot)
        self._flashed.pop(slot, None)

    def is_dirty(self, slot: str) -> bool:
        return slot in self._dirty

    def flashed_version(self, slot: str) -> str:
        return self._flashed.get(slot, "")
