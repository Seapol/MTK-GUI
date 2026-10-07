# -*- coding: utf-8 -*-
"""The app-wide combo wheel guard: scrolling over a CLOSED dropdown
must never change its value (accident prevention, user direction)."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from mtkgui.main_window import _ComboWheelGuard  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wheel(combo):
    return QWheelEvent(
        QPointF(5, 5), QPointF(5, 5),
        QPointF(0, 0), QPointF(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False)


def test_wheel_blocked_on_closed_combo(qapp):
    guard = _ComboWheelGuard()
    combo = QComboBox()
    combo.addItems(["A", "B", "C"])
    combo.setCurrentIndex(0)
    event = _wheel(combo)
    assert guard.eventFilter(combo, event) is True
    combo.event(event)                      # the swallowed event would
    assert combo.currentIndex() == 0        # have moved to "B"


def test_filter_passes_other_events(qapp):
    guard = _ComboWheelGuard()
    combo = QComboBox()
    combo.addItems(["A", "B"])
    assert guard.eventFilter(combo, QEvent(QEvent.Type.Resize)) is False
    assert guard.eventFilter(object(), _wheel(combo)) is False
