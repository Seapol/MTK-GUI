# -*- coding: utf-8 -*-
"""Diagnostic timing probe: every operation's timing (M16, 2026-10-25).

Records the full operation timeline so a slow startup or a slow GUI
action can be debugged from one log file:

* :func:`mark`     - one-shot checkpoint (cumulative + delta since
                     the previous output).
* :func:`begin` /
  :func:`end`      - paired timing of one operation (nesting is
                     shown by indentation; a mismatch is written as a
                     warning line, never raised).
* :func:`timed`    - context-manager form of begin/end.

Every call appends one line ``<elapsed_s>  <delta_s>  <label>`` to
the timing log.  Frozen builds keep the classic location
(``_startup_timing.log`` next to the exe); development runs write
``logs/_startup_timing.log`` under the working directory (``logs/``
is git-ignored).  Set ``MTK_TIMING=0`` to disable the file logging
(the M14 progress hooks keep working).

Thread-safe: GUI operations emit checkpoints from worker threads too.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_T0 = time.perf_counter()
_FROZEN = bool(getattr(sys, "frozen", False))
_ENABLED = os.environ.get("MTK_TIMING", "1") != "0"

_LOG: Path | None = None
if _ENABLED:
    try:
        if _FROZEN:
            _LOG = Path(sys.executable).parent / "_startup_timing.log"
        else:
            _LOG = Path.cwd() / "logs" / "_startup_timing.log"
            _LOG.parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # pragma: no cover - probe must never break startup
        _LOG = None

_LOCK = threading.Lock()
_LAST = _T0
_STACK: list[tuple[str, float, int]] = []   # (label, t_start, depth)

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


def _append(line: str) -> None:
    if _LOG is not None:
        try:
            with open(_LOG, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass


def _notify(label: str, elapsed: float) -> None:
    handler = _PROGRESS_HANDLER
    if handler is not None:
        try:
            handler(label, elapsed)
        except Exception:  # pragma: no cover - never break startup
            pass


def mark(label: str) -> None:
    """One-shot checkpoint: append ``<elapsed> <delta> <label>``."""
    global _LAST
    now = time.perf_counter()
    with _LOCK:
        delta = now - _LAST
        _LAST = now
        _append(f"{now - _T0:8.3f}s  {delta:6.3f}s  {label}\n")
    _notify(label, now - _T0)


def begin(label: str) -> None:
    """Open a timed operation (pairs with :func:`end`)."""
    global _LAST
    now = time.perf_counter()
    with _LOCK:
        depth = len(_STACK)
        _STACK.append((label, now, depth))
        _LAST = now
        _append(f"{now - _T0:8.3f}s  {'':>6}   "
                f"{'  ' * depth}BEGIN {label}\n")
    _notify(label, now - _T0)


def end(label: str) -> None:
    """Close the most recent :func:`begin`; logs its duration."""
    global _LAST
    now = time.perf_counter()
    with _LOCK:
        if not _STACK:
            _append(f"{now - _T0:8.3f}s  {'':>6}   "
                    f"END {label} (no matching BEGIN - ignored)\n")
            return
        top_label, t_start, depth = _STACK.pop()
        if top_label != label:
            _append(f"{now - _T0:8.3f}s  {'':>6}   "
                    f"END {label} (mismatch: open is '{top_label}')\n")
            return
        delta = now - t_start
        _append(f"{now - _T0:8.3f}s  {delta:6.3f}s  "
                f"{'  ' * depth}END   {label}\n")
    _notify(label, now - _T0)


@contextmanager
def timed(label: str):
    """Context-manager form of :func:`begin` / :func:`end`."""
    begin(label)
    try:
        yield
    finally:
        end(label)
