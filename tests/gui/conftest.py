# -*- coding: utf-8 -*-
"""Headless QApplication fixture for GUI tests (offscreen platform)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _no_blocking_modals(monkeypatch):
    """A GUI test must never wait for a human.

    Under the offscreen platform a real ``QMessageBox.warning`` /
    ``question`` blocks forever, so one un-judged fixture row hangs the
    whole suite instead of failing one test. Every modal is recorded in
    ``_no_blocking_modals.calls`` and answered immediately. A test that
    cares about the answer patches the same attribute itself and its
    patch overrides this guard for that scope.
    """
    calls: list = []
    _no_blocking_modals.calls = calls

    def _record(kind, button):
        def handler(*args, **kwargs):
            calls.append((kind,
                          args[1] if len(args) > 1 else "",
                          args[2] if len(args) > 2 else ""))
            return button
        return handler

    monkeypatch.setattr(QMessageBox, "warning",
                        _record("warning", QMessageBox.StandardButton.Ok),
                        raising=False)
    monkeypatch.setattr(QMessageBox, "critical",
                        _record("critical", QMessageBox.StandardButton.Ok),
                        raising=False)
    monkeypatch.setattr(QMessageBox, "information",
                        _record("information", QMessageBox.StandardButton.Ok),
                        raising=False)
    monkeypatch.setattr(QMessageBox, "question",
                        _record("question", QMessageBox.StandardButton.No),
                        raising=False)
    yield calls
