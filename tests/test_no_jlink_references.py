# -*- coding: utf-8 -*-
"""v2/C2: the retired flash-probe vendors must stay gone.

The acceptance of ``v2-1`` is a grep, not prose: the five vendor tokens
may not appear anywhere under ``mtkgui/``, ``tests/`` or ``docs/``.
This module is the test form of that grep.  It skips ITSELF because the
token list below has to name the tokens it searches for.
"""
from __future__ import annotations

from pathlib import Path

#: vendor tokens retired by v2-1
RETIRED = ("jlink", "j-link", "pemicro", "lauterbach", "cmsisdap")

ROOTS = ("mtkgui", "tests", "docs")

#: generated / cached directories (never source, regenerated on demand)
SKIP_PARTS = ("__pycache__", "_build")

REPO = Path(__file__).resolve().parents[1]


def _candidate_files():
    """Every readable file under the scanned roots (no caches)."""
    me = Path(__file__).resolve()
    for root in ROOTS:
        for path in (REPO / root).rglob("*"):
            if not path.is_file():
                continue
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            if path.suffix == ".pyc":
                continue
            if path.resolve() == me:
                continue
            yield path


def test_no_jlink_references():
    """No file under mtkgui/, tests/ or docs/ names a retired vendor."""
    hits: list[str] = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:                      # pragma: no cover - unreadable
            continue
        for token in RETIRED:
            if token in text:
                hits.append(f"{path.relative_to(REPO)}: {token}")
    assert not hits, ("retired flash-probe references remain:\n"
                      + "\n".join(hits))
