# -*- coding: utf-8 -*-
"""apply_gui_theme dedup guard: re-applying the SAME theme must NOT
call QApplication.setStyleSheet again - Qt re-polishes every widget of
every live window on each call, which made MainWindow construction
pathologically slow once several windows were alive (the observed
"status bar / login fixture tests hang at 100 % CPU")."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.main_window import MainWindow  # noqa: E402
from mtkgui.style import GUI_THEMES  # noqa: E402

ROLE_SUPERVISOR = "Supervisor"
FIXTURE_ATE = "ATE"


@pytest.fixture()
def window(qapp):
    MainWindow._applied_theme = None
    w = MainWindow(role=ROLE_SUPERVISOR, fixture=FIXTURE_ATE)
    yield w
    w.close()
    w.deleteLater()


def test_same_theme_skips_stylesheet_reset(window, monkeypatch):
    calls = []
    monkeypatch.setattr(QApplication, "setStyleSheet",
                        lambda _app, qss: calls.append(qss))
    # the same theme again: NO re-polish ...
    window.apply_gui_theme(window._applied_theme or
                           next(iter(GUI_THEMES)))
    assert calls == []
    # ... but switching to another theme DOES restyle the app
    other = next(n for n in GUI_THEMES
                 if n != MainWindow._applied_theme)
    window.apply_gui_theme(other)
    assert len(calls) == 1
    assert MainWindow._applied_theme == other


def test_unknown_theme_is_ignored(window, monkeypatch):
    calls = []
    monkeypatch.setattr(QApplication, "setStyleSheet",
                        lambda _app, qss: calls.append(qss))
    window.apply_gui_theme("not-a-theme")
    assert calls == []
