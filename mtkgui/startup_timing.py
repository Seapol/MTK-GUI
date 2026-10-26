# -*- coding: utf-8 -*-
"""Full-lifecycle performance probe (M16, 2026-10-25 -> 2026-10-27).

Records EVERY user-visible action's timing across the whole application
lifecycle so GUI responsiveness ("silk-smooth") can be measured from one
log file.  This is a diagnostic probe only - it never blocks or raises.

Checkpoint model (all thread-safe):

* :func:`mark`       - one-shot checkpoint.  The delta column shows how
                       long it took between THIS action and the previous
                       one (that is what a slow UI feels like).
* :func:`begin` /
  :func:`end`        - paired timing of one operation (nesting is shown
                       by indentation; a mismatch is written as a
                       warning line, never raised).  ``wait=True`` on
                       begin marks the span as WAITING FOR THE OPERATOR
                       (login prompt, modal dialog, confirmation) so
                       human time is never confused with program time.
* :func:`timed`      - context-manager form of begin/end.

Log format (one line per event; the wall-clock column makes it easy to
correlate a slow delta with the clock, the ``delta`` column shows the
time since the previous event - that is what a slow UI feels like)::

    session 2026-10-27 01:20:33 | pid 1234 | frozen=1 | py3.12 | MTK-GUI | columns: wall-clock | t-since-start | delta | [category] text
    01:20:33.102  0.000s  +0.000s  [startup ] begin show splash
    01:20:37.207  4.105s  +4.102s  [startup ] QApplication ready
    01:20:37.210  4.108s  +0.003s  [wait    ] [WAIT] BEGIN login - waiting for operator
    01:21:04.434 31.224s +27.116s  [wait    ] [WAIT] END   login - operator signed in (Supervisor, Virtual)

The ``cat`` column is derived from the label prefix (``ui: ...`` ->
``ui``, ``testflow: run`` -> ``testflow``, no prefix -> ``misc``); an
explicit ``category`` argument overrides the inference.

Frozen builds write ``_startup_timing.log`` next to the exe;
development runs write ``logs/_startup_timing.log`` under the working
directory (``logs/`` is git-ignored).  Set ``MTK_TIMING=0`` to disable
the file logging (the progress hooks keep working).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
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
#: begin/end pairing is PER-THREAD (GUI thread + worker threads each
#: open and close their own operations; a global stack would cross-pair
#: them and produce false mismatches).  Each entry:
#: (label, t_start, depth, category, waiting_for_operator)
_LOCAL = threading.local()


def _stack() -> list:
    stack = getattr(_LOCAL, "stack", None)
    if stack is None:
        stack = []
        _LOCAL.stack = stack
    return stack


_HEADER_WRITTEN = False

#: optional progress callback (M14 F4): ``fn(stage_name, elapsed_s)``.
_PROGRESS_HANDLER = None


def set_progress_handler(handler) -> None:
    """Register / clear the startup progress callback (M14 F4)."""
    global _PROGRESS_HANDLER
    _PROGRESS_HANDLER = handler


# ------------------------------------------------------------ helpers
def _category_of(label: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    text = str(label or "")
    if ":" in text:
        prefix = text.split(":", 1)[0].strip().lower()
        if prefix and len(prefix) <= 16:
            return prefix
    return "misc"


def _append(line: str) -> None:
    global _HEADER_WRITTEN
    if _LOG is None:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            if not _HEADER_WRITTEN:
                try:
                    fh.write(_session_header())
                except OSError:
                    pass
                _HEADER_WRITTEN = True
            fh.write(line)
    except OSError:
        pass


def _session_header() -> str:
    """One block per process run, so later analysis can split sessions."""
    try:
        version = sys.version.split()[0]
    except Exception:  # pragma: no cover
        version = "?"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (f"session {now} | pid {os.getpid()} | frozen={1 if _FROZEN else 0}"
            f" | py{version} | MTK-GUI | columns: wall-clock | "
            "t-since-start | delta | [category] text\n")


def _fmt(t: float, delta: float, cat: str, text: str) -> str:
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    return (f"{stamp}  {t:9.3f}s  {delta:+7.3f}s  [{cat:<8}] {text}\n")


def _notify(label: str, elapsed: float) -> None:
    handler = _PROGRESS_HANDLER
    if handler is not None:
        try:
            handler(label, elapsed)
        except Exception:  # pragma: no cover - never break startup
            pass


# ------------------------------------------------------------- public
def mark(label: str, category: str | None = None) -> None:
    """One-shot checkpoint: ``<elapsed> <delta> [cat] <label>``."""
    global _LAST
    now = time.perf_counter()
    cat = _category_of(label, category)
    with _LOCK:
        delta = now - _LAST
        _LAST = now
        _append(_fmt(now - _T0, delta, cat, label))
    _notify(label, now - _T0)


def begin(label: str, category: str | None = None,
          wait: bool = False) -> None:
    """Open a timed operation (pairs with :func:`end`).

    ``wait=True`` marks the span as waiting for the OPERATOR (login,
    modal dialog, confirmation) - the elapsed time between begin/end is
    human time, not program time.
    """
    global _LAST
    now = time.perf_counter()
    cat = _category_of(label, category)
    stack = _stack()
    with _LOCK:
        depth = len(stack)
        stack.append((label, now, depth, cat, wait))
        _LAST = now
        indent = "  " * depth
        wait_mark = "[WAIT] " if wait else ""
        hint = " - waiting for operator" if wait else ""
        _append(_fmt(now - _T0, 0.0, cat,
                     f"{indent}{wait_mark}BEGIN {label}{hint}"))
    _notify(label, now - _T0)


def end(label: str, note: str = "") -> None:
    """Close the most recent :func:`begin`; logs its duration.

    ``note`` appends an outcome detail (e.g. the operator role after a
    login) that makes the line self-explanatory.
    """
    global _LAST
    now = time.perf_counter()
    stack = _stack()
    with _LOCK:
        if not stack:
            _append(_fmt(now - _T0, 0.0, "misc",
                         f"END {label} (no matching BEGIN - ignored)"))
            return
        top_label, t_start, depth, cat, wait = stack.pop()
        if top_label != label:
            _append(_fmt(now - _T0, 0.0, cat,
                         f"END {label} (mismatch: open is '{top_label}')"))
            return
        delta = now - t_start
        indent = "  " * depth
        wait_mark = "[WAIT] " if wait else ""
        suffix = f" ({note})" if note else ""
        waited = f" - waited {delta:.2f}s" if wait else ""
        _append(_fmt(now - _T0, delta, cat,
                     f"{indent}{wait_mark}END   {label}{suffix}{waited}"))
    _notify(label, now - _T0)


@contextmanager
def timed(label: str, category: str | None = None,
          wait: bool = False):
    """Context-manager form of :func:`begin` / :func:`end`."""
    begin(label, category=category, wait=wait)
    try:
        yield
    finally:
        end(label)
