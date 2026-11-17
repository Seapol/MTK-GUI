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
def _isolate_config_dir(tmp_path_factory, monkeypatch):
    """v2/C3: every test gets a FRESH writable config dir (seeded from the
    repo's factory files), so permissions / settings.json / report folder
    choices can never leak between tests or into the developer's config.

    The dir lives under the session's own temp base - never inside the
    test's ``tmp_path``, which some tests scan for unexpected artifacts.
    """
    from mtkgui import app_paths

    cfg = tmp_path_factory.mktemp("v2config") / "config"
    monkeypatch.setenv("MTKGUI_CONFIG_DIR", str(cfg))
    app_paths.ensure_config()
    return cfg


@pytest.fixture(autouse=True)
def _isolate_wifi_preferences():
    """M40/M41: the Wi-Fi tab reads/writes the QSettings ``wifi/*`` keys
    and the Console tab the ``console/*`` keys.  Every test starts from
    an empty set and the developer's real values are restored afterwards,
    so persisted data can never leak between tests (or into the
    developer's GUI)."""
    from PySide6.QtCore import QSettings

    from mtkgui.style import APP_NAME, APP_ORG
    settings = QSettings(APP_ORG, APP_NAME)
    keys = ["wifi/ap_ssid", "wifi/ap_ip", "wifi/host_ip",
            "wifi/ap_password",
            "console/port", "console/baudrate", "console/ssh_host",
            "console/ssh_user", "console/ssh_password",
            "console/scripts_local_dir", "console/pull_local_dir"]
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


@pytest.fixture(scope="session", autouse=True)
def isolated_work_dir(tmp_path_factory):
    """M96: every test runs against its own work folder, never against the
    developer's <repo>/work (which may hold saved report settings)."""
    work = tmp_path_factory.mktemp("work")
    os.environ["MTKGUI_WORK_DIR"] = str(work)
    return work
