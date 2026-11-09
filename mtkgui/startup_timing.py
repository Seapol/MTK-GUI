# -*- coding: utf-8 -*-
"""Full-lifecycle performance probe (M16, 2026-10-25 -> M51 2026-11-02).

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
                       ``no_slow=True`` marks a deliberate wait (the
                       Delay step) the same way for [SLOW] only.
* :func:`timed`      - context-manager form of begin/end.

Log format (one line per event; the wall-clock column makes it easy to
correlate a slow delta with the clock, the ``delta`` column shows the
time since the previous event - that is what a slow UI feels like)::

    session 2026-10-27 01:20:33 | pid 1234 | frozen=1 | py3.12 | MTK-GUI | columns: wall-clock | t-since-start | delta | [category] text
    01:20:33.102  0.000s  +0.000s  [startup ] begin show splash
    01:20:37.207  4.105s  +4.102s  [startup ] QApplication ready [SLOW 4.105s]
    01:20:37.210  4.108s  +0.003s  [wait    ] [WAIT] BEGIN login - waiting for operator
    01:21:04.434 31.224s +27.116s  [wait    ] [WAIT] END   login - operator signed in (Supervisor, Virtual)

M51 additions (ticks stay APPENDED to the text, never new categories):

* ``[SLOW x.xxxs]``  - span delta above the QSettings threshold
  (``perf_timing_slow_threshold``, default 1.0 s), re-read per event.
  Operator waits (``wait=True``) and deliberate waits (``no_slow=True``)
  are never tagged.
* ``[EXCEPTION]``    - unhandled exception (main thread or worker
  thread), logged with class / message / file:line / traceback tail.
* ``====== session summary ======`` - TOP-N slowest spans plus every
  captured exception, appended on exit (only for a session that
  STARTED with the log enabled).

Switch (Tools menu, M51): ``perf_timing_enabled`` in QSettings decides
whether a session logs at all; the checkbox takes effect on the NEXT
restart.  When logging is off (or ``MTK_TIMING=0``) every public
function returns immediately before touching the clock / lock, and no
hooks or summary are installed - the app behaves as if the probe did
not exist.

Frozen builds write ``_startup_timing.log`` next to the exe;
development runs write ``logs/_startup_timing.log`` under the working
directory (``logs/`` is git-ignored).  Set ``MTK_TIMING=0`` to disable
the file logging (the progress hooks keep working).
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

#: QSettings keys (M51)
SLOW_THRESHOLD_KEY = "perf_timing_slow_threshold"
ENABLED_KEY = "perf_timing_enabled"
SUMMARY_TOP_KEY = "perf_timing_summary_top"
#: QSettings organisation / application names (same as mtkgui.style)
SETTINGS_ORG = "MTK GUI"
SETTINGS_APP = "Manufacturing Test Kit"

_SLOW_DEFAULT = 1.0
_SUMMARY_TOP_DEFAULT = 10
#: cheap bound for the in-memory span list (summary keeps only the top)
_MAX_SPANS = 512

_T0 = time.perf_counter()
_FROZEN = bool(getattr(sys, "frozen", False))

_UNSET = object()
_SETTINGS = _UNSET


def settings():
    """The QSettings store used by the probe (tests may replace it)."""
    global _SETTINGS
    if _SETTINGS is _UNSET:
        try:
            from PySide6.QtCore import QSettings
            _SETTINGS = QSettings(SETTINGS_ORG, SETTINGS_APP)
        except Exception:                       # pragma: no cover
            _SETTINGS = None
    return _SETTINGS


def _setting_value(key, default=None):
    store = settings()
    if store is None:
        return default
    try:
        value = store.value(key, default)
    except Exception:                           # pragma: no cover
        return default
    return default if value is None else value


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return None


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def saved_enabled() -> bool:
    """The SAVED Tools-menu state (first run follows ``MTK_TIMING``)."""
    saved = _as_bool(_setting_value(ENABLED_KEY, None))
    if saved is None:
        return os.environ.get("MTK_TIMING", "1") != "0"
    return saved


def save_enabled(value: bool) -> None:
    """Persist the Tools-menu switch (applies on the next GUI start)."""
    store = settings()
    if store is None:                           # pragma: no cover
        return
    try:
        store.setValue(ENABLED_KEY, bool(value))
        store.sync()
    except Exception:                           # pragma: no cover
        pass


def slow_threshold() -> float:
    """The [SLOW] threshold in seconds (QSettings, re-read per event)."""
    return _as_float(_setting_value(SLOW_THRESHOLD_KEY, _SLOW_DEFAULT),
                     _SLOW_DEFAULT)


def _summary_top() -> int:
    try:
        return max(1, int(_setting_value(SUMMARY_TOP_KEY,
                                         _SUMMARY_TOP_DEFAULT)))
    except (TypeError, ValueError):
        return _SUMMARY_TOP_DEFAULT


def _startup_enabled() -> bool:
    """Session decision, read ONCE at import (never toggles at runtime)."""
    if os.environ.get("MTK_TIMING") == "0":
        return False                            # hard kill switch
    saved = _as_bool(_setting_value(ENABLED_KEY, None))
    if saved is None:
        return True                             # first run: on
    return saved


_ENABLED = _startup_enabled()

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
#: (label, t_start, depth, category, waiting_for_operator, no_slow)
_LOCAL = threading.local()

#: M51 session state (only kept while the session started enabled)
_SPANS: list = []
_EXCEPTIONS: list = []
_SUMMARY_WRITTEN = False
_HOOKS_INSTALLED = False
_PREV_SYS_EXCEPTHOOK = None
_PREV_THREAD_EXCEPTHOOK = None


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


def is_enabled() -> bool:
    """The logging state THIS session started with (M51 §3)."""
    return _ENABLED


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


def _switch_line(text: str) -> str:
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    return (f"{stamp}  {time.perf_counter() - _T0:9.3f}s  +0.000s"
            f"  [switch  ] {text}\n")


def _append(line: str) -> None:
    global _HEADER_WRITTEN
    if _LOG is None:
        return
    try:
        with open(_LOG, "a", encoding="utf-8") as fh:
            if not _HEADER_WRITTEN:
                try:
                    fh.write(_session_header())
                    fh.write(_switch_line(
                        "timing log enabled (startup, QSettings)"))
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


def _slow_tag(delta: float, excluded: bool) -> str:
    if excluded:
        return ""
    try:
        limit = slow_threshold()
    except Exception:  # pragma: no cover
        limit = _SLOW_DEFAULT
    if delta > limit:
        return f" [SLOW {delta:.3f}s]"
    return ""


def _record_span(delta: float, cat: str, label: str) -> None:
    """Keep the span for the exit summary (locked by the caller)."""
    _SPANS.append((float(delta), str(cat), str(label)))
    if len(_SPANS) > _MAX_SPANS * 2:
        _SPANS.sort(reverse=True)
        del _SPANS[_MAX_SPANS:]


# ------------------------------------------------------------- public
def mark(label: str, category: str | None = None,
         no_slow: bool = False) -> None:
    """One-shot checkpoint: ``<elapsed> <delta> [cat] <label>``."""
    if not _ENABLED:                            # M51 §3: hard no-op
        return
    global _LAST
    now = time.perf_counter()
    cat = _category_of(label, category)
    with _LOCK:
        delta = now - _LAST
        _LAST = now
        tag = _slow_tag(delta, no_slow)
        _append(_fmt(now - _T0, delta, cat, f"{label}{tag}"))
        if not no_slow:
            _record_span(delta, cat, label)
    _notify(label, now - _T0)


def begin(label: str, category: str | None = None,
          wait: bool = False, no_slow: bool = False) -> None:
    """Open a timed operation (pairs with :func:`end`).

    ``wait=True`` marks the span as waiting for the OPERATOR (login,
    modal dialog, confirmation) - the elapsed time between begin/end is
    human time, not program time.  ``no_slow=True`` excludes a
    deliberate wait (Delay step) from the [SLOW] judgement as well.
    """
    if not _ENABLED:                            # M51 §3: hard no-op
        return
    global _LAST
    now = time.perf_counter()
    cat = _category_of(label, category)
    stack = _stack()
    with _LOCK:
        depth = len(stack)
        stack.append((label, now, depth, cat, wait, no_slow))
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
    if not _ENABLED:                            # M51 §3: hard no-op
        return
    global _LAST
    now = time.perf_counter()
    stack = _stack()
    with _LOCK:
        if not stack:
            _append(_fmt(now - _T0, 0.0, "misc",
                         f"END {label} (no matching BEGIN - ignored)"))
            return
        top_label, t_start, depth, cat, wait, no_slow = stack.pop()
        if top_label != label:
            _append(_fmt(now - _T0, 0.0, cat,
                         f"END {label} (mismatch: open is '{top_label}')"))
            return
        delta = now - t_start
        _LAST = now        # W2-2: the closed span is not charged to the next step
        indent = "  " * depth
        wait_mark = "[WAIT] " if wait else ""
        suffix = f" ({note})" if note else ""
        waited = f" - waited {delta:.2f}s" if wait else ""
        tag = _slow_tag(delta, wait or no_slow)
        _append(_fmt(now - _T0, delta, cat,
                     f"{indent}{wait_mark}END   {label}{suffix}{waited}{tag}"))
        if not (wait or no_slow):
            _record_span(delta, cat, label)
    _notify(label, now - _T0)


@contextmanager
def timed(label: str, category: str | None = None,
          wait: bool = False, no_slow: bool = False):
    """Context-manager form of :func:`begin` / :func:`end`."""
    if not _ENABLED:                            # M51 §3: hard no-op
        yield
        return
    begin(label, category=category, wait=wait, no_slow=no_slow)
    try:
        yield
    finally:
        end(label)


# ------------------------------------------------- M51: exception capture
def _exception_fields(exc_type, exc_value, exc_tb):
    cls = getattr(exc_type, "__name__", str(exc_type))
    try:
        msg = str(exc_value).splitlines()[0] if str(exc_value) else ""
    except Exception:                           # pragma: no cover
        msg = ""
    frames = traceback.extract_tb(exc_tb) if exc_tb is not None else []
    where = "?:?"
    if frames:
        last = frames[-1]
        where = f"{Path(last.filename).name}:{last.lineno}"
    tail = " <- ".join(
        f"{Path(f.filename).name}:{f.lineno} in {f.name}"
        for f in frames[-5:])
    return cls, msg, where, tail


def _log_exception(exc_type, exc_value, exc_tb) -> None:
    """Append one ``[EXCEPTION]`` line (never raises)."""
    if not _ENABLED:
        return
    try:
        cls, msg, where, tail = _exception_fields(
            exc_type, exc_value, exc_tb)
        text = f"[EXCEPTION] {cls}: {msg} ({where})"
        if tail:
            text += f" tail: {tail}"
        with _LOCK:
            _append(_fmt(time.perf_counter() - _T0, 0.0, "error", text))
            stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            _EXCEPTIONS.append((stamp, f"{cls}: {msg}", where))
    except Exception:                           # pragma: no cover
        pass


def _sys_excepthook(exc_type, exc_value, exc_tb) -> None:
    _log_exception(exc_type, exc_value, exc_tb)
    prev = _PREV_SYS_EXCEPTHOOK
    if prev is not None and prev is not _sys_excepthook:
        try:
            prev(exc_type, exc_value, exc_tb)
        except Exception:                       # pragma: no cover
            pass


def _thread_excepthook(args) -> None:
    try:
        _log_exception(args.exc_type, args.exc_value, args.exc_traceback)
    except Exception:                           # pragma: no cover
        pass
    prev = _PREV_THREAD_EXCEPTHOOK
    if prev is not None and prev is not _thread_excepthook:
        try:
            prev(args)
        except Exception:                       # pragma: no cover
            pass


def install_exception_hooks() -> None:
    """Chain-safe global exception hooks (M51 §2, idempotent)."""
    global _HOOKS_INSTALLED, _PREV_SYS_EXCEPTHOOK, _PREV_THREAD_EXCEPTHOOK
    if not _ENABLED or _HOOKS_INSTALLED:
        return
    try:
        _PREV_SYS_EXCEPTHOOK = sys.excepthook
        _PREV_THREAD_EXCEPTHOOK = threading.excepthook
        sys.excepthook = _sys_excepthook
        threading.excepthook = _thread_excepthook
        _HOOKS_INSTALLED = True
    except Exception:                           # pragma: no cover
        pass


def remove_exception_hooks() -> None:
    """Restore the previous hooks (used by tests / shutdown)."""
    global _HOOKS_INSTALLED
    if not _HOOKS_INSTALLED:
        return
    try:
        sys.excepthook = (_PREV_SYS_EXCEPTHOOK
                          if _PREV_SYS_EXCEPTHOOK is not None
                          else sys.__excepthook__)
        threading.excepthook = (_PREV_THREAD_EXCEPTHOOK
                                if _PREV_THREAD_EXCEPTHOOK is not None
                                else threading.__excepthook__)
    except Exception:                           # pragma: no cover
        pass
    _HOOKS_INSTALLED = False


# ---------------------------------------------------- M51: session summary
def write_session_summary() -> None:
    """Append the TOP-N slowest spans + exceptions (crash-safe, once)."""
    global _SUMMARY_WRITTEN
    if not _ENABLED:                            # started OFF -> nothing
        return
    if _SUMMARY_WRITTEN:
        return
    _SUMMARY_WRITTEN = True
    try:
        if _LOG is None:
            return
        top = _summary_top()
        spans = sorted(_SPANS, key=lambda s: s[0], reverse=True)[:top]
        parts = ["====== session summary ======",
                 f"slowest steps (threshold {slow_threshold():.1f}s):"]
        if spans:
            for i, (delta, cat, label) in enumerate(spans, 1):
                parts.append(f"  {i:2d}. {delta:8.3f}s  [{cat:<8}] {label}")
        else:
            parts.append("  (none)")
        parts.append(f"exceptions ({len(_EXCEPTIONS)}):")
        for stamp, text, where in _EXCEPTIONS:
            parts.append(f"  - {stamp}  {text}  ({where})")
        parts.append("====== end summary ======")
        _append("\n".join(parts) + "\n")
    except Exception:                           # pragma: no cover
        pass


# ------------------------------------------------------------ activation
if _ENABLED:
    # M51 §4: summary on interpreter exit (dev + frozen builds); the
    # MainWindow close path calls it earlier, the flag makes it once-only.
    try:
        atexit.register(write_session_summary)
    except Exception:  # pragma: no cover
        pass
    install_exception_hooks()
