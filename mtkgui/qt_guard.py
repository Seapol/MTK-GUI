# -*- coding: utf-8 -*-
"""Qt event-pump safety guard (PySide6 6.10.x SIGSEGV class).

Root cause of the recurring macOS SIGSEGV family (app-close crash +
full-suite crashes, 5/5 identical native stacks:
``Sbk_QCoreApplicationFunc_processEvents -> QTimerInfoList::
activateTimers -> EXC_BAD_ACCESS @ NULL``):

``QTimer.singleShot(msec, context, callable)`` does NOT reliably cancel
the timer when ``context`` is destroyed (observed on PySide6 6.10.3 /
Python 3.9.6-CLT): a zero-timeout timer armed at widget CONSTRUCTION
outlives its context tree when the tree is destroyed before any event
pump ran (e.g. a test builds a page, asserts, ``deleteLater()`` - the
next ``processEvents`` anywhere then dispatches the timer into the
destroyed tree).

``qt_safe`` wraps such callbacks: if the C++ object behind the touched
widget is already gone, PySide raises ``RuntimeError`` ("Internal C++
object already deleted") - swallow it and return.  The timer becomes a
harmless no-op instead of a segfault, regardless of PySide's
cancellation behavior.
"""
from __future__ import annotations

import functools
from typing import Callable


def qt_safe(fn: Callable) -> Callable:
    """Make a QTimer.singleShot callback safe to fire on a destroyed
    widget tree (see module docstring)."""

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RuntimeError:
            # "Internal C++ object already deleted" - the context tree
            # died before this timer fired; nothing to do, and letting
            # the exception escape into the C++ event dispatch crashes
            # shiboken's error-store path (SIGSEGV).
            return None

    return _wrapped
