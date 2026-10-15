# -*- coding: utf-8 -*-
"""Startup timing probe (diagnostic, 2026-10-15).

Frozen builds append one line per :func:`mark` call to
``_startup_timing.log`` next to the exe (``dist\\mtk\\``); development
runs are a no-op.  Purpose: pinpoint the Windows-only startup stall
(~1 min between login and the main window) that does not reproduce on
macOS.  Remove the probe once the stall is diagnosed.
"""

from __future__ import annotations

import sys
import time

_T0 = time.perf_counter()
_FROZEN = bool(getattr(sys, "frozen", False))
_LOG = None
if _FROZEN:
    try:
        _LOG = __import__("pathlib").Path(sys.executable).parent / \
            "_startup_timing.log"
    except Exception:  # pragma: no cover - probe must never break startup
        _LOG = None


def mark(label: str) -> None:
    """Append ``<elapsed>  <label>`` to the frozen-build timing log."""
    if not _FROZEN or _LOG is None:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.perf_counter() - _T0:8.3f}s  {label}\n")
    except OSError:
        pass
