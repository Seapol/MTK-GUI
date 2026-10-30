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
def _reset_event_log_level_preference():
    """M11: the Event Log display level is a USER preference persisted
    in QSettings.  Every test starts from the role defaults (no saved
    choice) and the key is cleared again afterwards, so a menu-switch
    test can never leak into the next test or depend on the developer's
    real GUI settings."""
    from PySide6.QtCore import QSettings

    from mtkgui.style import APP_NAME, APP_ORG
    settings = QSettings(APP_ORG, APP_NAME)
    settings.remove("event_log/level")
    settings.sync()
    yield
    settings.remove("event_log/level")
    settings.sync()


@pytest.fixture(autouse=True)
def _isolate_wifi_preferences():
    """M40: the Wi-Fi tab reads/writes the QSettings ``wifi/*`` keys.
    Every test starts from an empty set and the developer's real values
    are restored afterwards, so persisted Wi-Fi data can never leak
    between tests (or into the developer's GUI)."""
    from PySide6.QtCore import QSettings

    from mtkgui.style import APP_NAME, APP_ORG
    settings = QSettings(APP_ORG, APP_NAME)
    keys = ["wifi/ap_ssid", "wifi/ap_ip", "wifi/host_ip",
            "wifi/ap_password"]
    saved = {key: settings.value(key) for key in keys}
    for key in keys:
        settings.remove(key)
    settings.sync()
    yield
    for key in keys:
        settings.remove(key)
    for key, value in saved.items():
        if value is not None:
            settings.setValue(key, value)
    settings.sync()


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
