# -*- coding: utf-8 -*-
"""P2-6 lightweight chart widgets (pure incremental, QPainter only).

Zero external chart dependencies: three self-contained widgets drawn
with QPainter — :class:`LineChart` (yield / CpK trends),
:class:`BarChart` (cycle-time comparison / defect TOP with highlight)
and :class:`PieChart` (failure classification share).  All widgets are
headless-safe (offscreen paint works) and never touch the engine: they
only receive already-computed data.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

PALETTE = ("#4f8cff", "#39c26d", "#ffb02e", "#ff5d5d", "#9a6bff",
           "#00b8d9", "#ff8fab", "#8bc34a")


def _fit(values: list[float]) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    if lo == hi:
        lo, hi = lo - 1.0, hi + 1.0
    pad = (hi - lo) * 0.1
    return lo - pad, hi + pad


class LineChart(QWidget):
    """Polylines over labelled x points; one series per call."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self._series: dict[str, list[tuple[str, float]]] = {}
        self.setMinimumHeight(120)

    def set_series(self, name: str,
                   points: list[tuple[str, float]]) -> None:
        """Replace one named series (other series untouched)."""
        self._series[name] = list(points)
        self.update()

    def add_series(self, name: str,
                   points: list[tuple[str, float]]) -> None:
        self._series[name] = list(points)
        self.update()

    def point_count(self, name: str | None = None) -> int:
        if name is None:
            return sum(len(v) for v in self._series.values())
        return len(self._series.get(name, []))

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
        if self.title:
            p.drawText(QRectF(0, 2, w, 16), Qt.AlignmentFlag.AlignCenter,
                       self.title)
        all_vals = [v for pts in self._series.values()
                    for _x, v in pts] or [0.0, 1.0]
        lo, hi = _fit(all_vals)
        margin_l, margin_b, margin_t = 36.0, 18.0, 20.0
        plot_w, plot_h = w - margin_l - 8, h - margin_b - margin_t
        if plot_w <= 10 or plot_h <= 10 or not self._series:
            return
        p.setPen(QPen(QColor("#888"), 1))
        p.drawLine(QPointF(margin_l, margin_t + plot_h),
                   QPointF(margin_l + plot_w, margin_t + plot_h))
        p.drawLine(QPointF(margin_l, margin_t),
                   QPointF(margin_l, margin_t + plot_h))
        p.drawText(QRectF(0, margin_t, margin_l - 2, 12),
                   Qt.AlignmentFlag.AlignRight, f"{hi:.3g}")
        p.drawText(QRectF(0, margin_t + plot_h - 12, margin_l - 2, 12),
                   Qt.AlignmentFlag.AlignRight, f"{lo:.3g}")
        max_len = max(len(pts) for pts in self._series.values())
        x_of = lambda i: (margin_l + plot_w * i / max(max_len - 1, 1))
        y_of = lambda v: (margin_t + plot_h
                          * (1 - (v - lo) / (hi - lo)))
        for idx, (name, pts) in enumerate(self._series.items()):
            color = QColor(PALETTE[idx % len(PALETTE)])
            p.setPen(QPen(color, 2))
            prev: QPointF | None = None
            for i, (_label, v) in enumerate(pts):
                cur = QPointF(x_of(i), y_of(v))
                if prev is not None:
                    p.drawLine(prev, cur)
                prev = cur
            for i, (_label, v) in enumerate(pts):
                p.setBrush(color)
                p.drawEllipse(x_of(i) - 3, y_of(v) - 3, 6, 6)
            # series legend
            p.drawText(QRectF(margin_l + 4 + idx * 90, h - 14, 90, 12),
                       Qt.AlignmentFlag.AlignLeft, name)


class BarChart(QWidget):
    """Horizontal bars with value labels; ``highlight`` marks the
    bottleneck / top-defect bar in a warning color."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self._items: list[tuple[str, float]] = []
        self._highlight: str | None = None
        self.setMinimumHeight(120)

    def set_data(self, items: list[tuple[str, float]],
                 highlight: str | None = None) -> None:
        self._items = list(items)
        self._highlight = highlight
        self.update()

    def bar_count(self) -> int:
        return len(self._items)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
        if self.title:
            p.drawText(QRectF(0, 2, w, 16), Qt.AlignmentFlag.AlignCenter,
                       self.title)
        if not self._items:
            return
        top = 20.0
        bar_h = max((h - top - 8) / len(self._items) - 4, 6.0)
        vmax = max(v for _l, v in self._items) or 1.0
        y = top
        for label, v in self._items:
            color = QColor("#ff5d5d") if label == self._highlight \
                else QColor(PALETTE[1])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRect(QRectF(70, y, max((w - 150) * v / vmax, 2.0),
                              bar_h))
            p.setPen(QColor("#333"))
            p.drawText(QRectF(2, y, 66, bar_h),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, label)
            p.drawText(QRectF(w - 76, y, 74, bar_h),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, f"{v:.4g}")
            y += bar_h + 4


class PieChart(QWidget):
    """Share pie with an inline legend (failure classification)."""

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self._items: list[tuple[str, float]] = []
        self.setMinimumHeight(120)

    def set_data(self, items: list[tuple[str, float]]) -> None:
        self._items = [(k, v) for k, v in items if v > 0]
        self.update()

    def slice_count(self) -> int:
        return len(self._items)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
        if self.title:
            p.drawText(QRectF(0, 2, w, 16), Qt.AlignmentFlag.AlignCenter,
                       self.title)
        total = sum(v for _k, v in self._items)
        if total <= 0:
            return
        size = min(w * 0.45, h - 30)
        rect = QRectF(10, 24, size, size)
        start = 90.0 * 16
        for i, (label, v) in enumerate(self._items):
            span = 360.0 * 16 * v / total
            color = QColor(PALETTE[i % len(PALETTE)])
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPie(rect, int(start), int(-span))
            p.setPen(QColor("#333"))
            p.drawText(QRectF(14 + size, 26 + i * 16, w - size - 18, 14),
                       Qt.AlignmentFlag.AlignLeft,
                       f"{label}  {v / total * 100:.1f}%")
            start -= span
