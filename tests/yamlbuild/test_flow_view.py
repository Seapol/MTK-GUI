# -*- coding: utf-8 -*-
"""v2-18: the horizontal Yaml Build flowchart view tests."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild import steps_v2 as sv  # noqa: E402
from mtkgui.gui.yamlbuild.flow_view import (  # noqa: E402
    PREREQS,
    STEP_GUIDE,
    STEP_HINTS,
    STEP_NEXT,
    YamlBuildFlowView,
    lock_message,
)


@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view(qapp):
    widget = YamlBuildFlowView()
    widget.resize(1200, 320)
    return widget


def _logical_pos(view, key: str) -> QPointF:
    rect = view.node_rects[key]
    return QPointF(rect.center().x(), rect.center().y())


def test_view_exposes_one_rect_per_node(view):
    assert set(view.node_rects.keys()) == set(sv.STEP_KEYS)
    for key in sv.STEP_KEYS:
        rect = view.node_rects[key]
        assert rect.width() > 0 and rect.height() > 0


def test_step_clicked_fires_inside_a_node(view):
    emitted: list[str] = []
    view.step_clicked.connect(lambda k: emitted.append(k))
    pos = _logical_pos(view, "design_input")
    scale, ox, oy = view._transform()
    from PySide6.QtGui import QMouseEvent
    widget_pos = QPointF(ox + pos.x() * scale, oy + pos.y() * scale)
    event = QMouseEvent(
        QMouseEvent.MouseButtonPress, widget_pos, view.mapToGlobal(widget_pos),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    view.mousePressEvent(event)
    assert emitted == ["design_input"]


def test_step_clicked_does_not_fire_outside(view):
    emitted: list[str] = []
    view.step_clicked.connect(lambda k: emitted.append(k))
    from PySide6.QtGui import QMouseEvent
    # a point far from every node centre (bottom-left empty area)
    event = QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(5.0, 5.0),
        view.mapToGlobal(QPointF(5.0, 5.0)),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    view.mousePressEvent(event)
    assert emitted == []


def test_set_step_state_persists_and_repaints(view):
    view.set_step_state("design_input", "invalid")
    assert view.step_state("design_input") == "invalid"
    # repaint does not raise and keeps the state
    view.repaint()
    assert view.step_state("design_input") == "invalid"


def test_lock_message_names_each_prerequisite():
    message = lock_message("equipment")
    assert sv.step_label("parse_ict") in message
    assert sv.step_label("firmware") in message


def test_shared_copy_tables_have_all_seven_entries():
    for key in sv.STEP_KEYS:
        assert key in PREREQS
        assert key in STEP_HINTS
        assert key in STEP_GUIDE
        assert key in STEP_NEXT
