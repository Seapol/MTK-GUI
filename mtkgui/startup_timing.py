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

#: optional progress callback (M14 F4): ``fn(stage_name, elapsed_s)``.
#: Registered by the startup progress window; None = no listener.
_PROGRESS_HANDLER = None


def set_progress_handler(handler) -> None:
    """Register / clear the startup progress callback (M14 F4).

    Args:
        handler: ``fn(stage_name: str, elapsed_s: float)`` or ``None``.
    """
    global _PROGRESS_HANDLER
    _PROGRESS_HANDLER = handler


def mark(label: str) -> None:
    """Append ``<elapsed>  <label>`` to the frozen-build timing log and
    forward the stage to the optional progress handler.

    The timing-log behaviour is unchanged (frozen builds only); the
    progress hook is purely additional.
    """
    elapsed = time.perf_counter() - _T0
    if _FROZEN and _LOG is not None:
        try:
            with open(_LOG, "a", encoding="utf-8") as fh:
                fh.write(f"{elapsed:8.3f}s  {label}\n")
        except OSError:
            pass
    handler = _PROGRESS_HANDLER
    if handler is not None:
        try:
            handler(label, elapsed)
        except Exception:  # pragma: no cover - never break startup
            pass

