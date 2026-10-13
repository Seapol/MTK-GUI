# -*- coding: utf-8 -*-
"""Root test fixtures (P2-1, test-only — zero product-code change).

Creates ONE QApplication for the whole session before any test runs.
Engine demo code needs a QCoreApplication; when the GUI tests run in the
same process they need a full QApplication.  QApplication IS a
QCoreApplication subclass, so building it first satisfies both and
avoids the Qt abort from mixing the two app types in one process.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _qapp_session():
    QApplication.instance() or QApplication([])
    yield


@pytest.fixture(autouse=True)
def _drain_deferred_deletes():
    """Flush pending deleteLater()s and zero-timeout timers at every
    test boundary.

    Defense-in-depth against the PySide6 6.10.x SIGSEGV family (see
    mtkgui/qt_guard.py): a widget tree destroyed here can no longer be
    hit by a LATER test's event pump, and any still-pending zero-timeout
    timer fires NOW - every product callback is qt_safe-wrapped, so a
    timer outliving its context is a harmless no-op instead of a
    segfault inside activateTimers."""
    yield
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QApplication.processEvents()
