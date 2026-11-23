# -*- coding: utf-8 -*-
"""m106a: the Yaml Build flowchart must paint and use QPointF anchors."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QApplication

from mtkgui.gui.yamlbuild.flow_view import YamlBuildFlowView


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_flow_view_edge_anchor_returns_points():
    view = YamlBuildFlowView()
    p = view._edge_anchor(QRectF(0, 0, 10, 10), QRectF(100, 0, 10, 10))
    assert isinstance(p, QPointF)
    assert hasattr(p, "x") and hasattr(p, "y")


def test_flow_view_paints_nodes():
    view = YamlBuildFlowView()
    view.resize(1200, 320)
    view.show()
    _app().processEvents()
    image = view.grab().toImage()
    colours = set()
    for x in range(0, image.width(), 8):
        for y in range(0, image.height(), 8):
            colours.add(image.pixelColor(x, y).name())
    # A painted flowchart has node fills (#fbfcfd), borders and text; an empty
    # white widget would sample a single colour.
    assert len(colours) > 1
