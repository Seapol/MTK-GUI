# -*- coding: utf-8 -*-
"""v2-18: the horizontal Yaml Build flowchart view.

Replaces the step bar + stacked body: node 01 on the left, node 07 on
the right, with the two parallel pairs (02/03 and 05/06) branching above
and below the main line.  Clicking a node emits ``step_clicked``; the
wizard shell opens the per-node dialog.

The node list comes from ``steps_v2.YAML_STEPS`` (single source of
truth) - the view never hard-codes a second list.  Rendering is a fixed,
deterministic ``QPainter`` paint (no drag, no zoom).

This module also owns the shared copy tables (``PREREQS`` /
``STEP_HINTS`` / ``STEP_GUIDE`` / ``STEP_NEXT`` / ``lock_message``) so
the shell imports them instead of redefining them.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from mtkgui.gui.yamlbuild import steps_v2 as sv

#: logical canvas size (scaled to the widget in paintEvent)
CANVAS_W = 1200.0
CANVAS_H = 320.0

#: node footprint in logical coordinates
NODE_W = 150.0
NODE_H = 76.0

#: node centres in logical coordinates (design_input left, apply_save right)
NODE_CENTRES = {
    "design_input": (60.0, 160.0),
    "parse_ict":    (350.0, 70.0),
    "firmware":     (350.0, 250.0),
    "equipment":    (640.0, 160.0),
    "build_ict":    (930.0, 70.0),
    "build_fct":    (930.0, 250.0),
    "apply_save":   (1120.0, 160.0),
}

#: directed edges (solid main line; parallel pairs use a dashed branch)
EDGES = (
    ("design_input", "parse_ict"),
    ("design_input", "firmware"),
    ("parse_ict", "equipment"),
    ("firmware", "equipment"),
    ("equipment", "build_ict"),
    ("equipment", "build_fct"),
    ("build_ict", "apply_save"),
    ("build_fct", "apply_save"),
)

#: which edges are the "branch" lines drawn dashed (the parallel pairs)
DASHED_EDGES = {
    ("design_input", "firmware"),
    ("equipment", "build_fct"),
}

#: prerequisite table (single source of truth shared with the shell)
PREREQS = {
    "design_input": (),
    "parse_ict":    ("design_input",),
    "firmware":     ("design_input",),
    "equipment":    ("parse_ict", "firmware"),
    "build_ict":    ("equipment",),
    "build_fct":    ("equipment",),
    "apply_save":   ("build_ict", "build_fct"),
}

#: what each node does (rendered as small muted lines inside the node)
STEP_HINTS = {
    "design_input": "① Import SPF/NET/BoM or Excel\n② Auto-parse product info (editable)\n③ Preselect FCT test types",
    "parse_ict":    "Parse netlist from SPF/NET/BoM or Excel\nSort nets into Parsed / Other tables",
    "firmware":     "Configure FAT / OOBE flashing\nCLI auto Pass/Fail · GUI dialog manual confirm",
    "equipment":    "Assign DAQ / counter / console channels\nConfigure peripherals (Wi-Fi / BT / Router…)",
    "build_ict":    "Author ICT test sequence\nAdd/Edit/Delete/Move steps · set limits (Ω / V / Hz)",
    "build_fct":    "Author FCT test sequence\nMessage tests · firmware flash · RF",
    "apply_save":   "Preview generated YAML\nValidate then Apply & Save",
}

#: first block of an editable dialog, under the "What this step does" heading
STEP_GUIDE = {
    "design_input": "This is the entry point. Import SPF (auto-parses Core ID + product name), NET (read-only), BoM (optional), or switch to the Excel route; all five product-info fields are required, and select the FCT test types to enable.",
    "parse_ict":    "Parse the netlist into testable nets: the left table holds recognized categories (power / clock / ground / other), the right table holds unclassified nets; move nets between tables to adjust.",
    "firmware":     "Configure FAT / OOBE flashing: CLI (command + pass/fail keywords, auto-verdict) or third-party GUI (tool path, runtime dialog for manual Go/Stop).",
    "equipment":    "Assign instrument channels: R-GND / voltage → DAQ, clock → counter / totalizer, DUT → console; then configure production peripherals (Wi-Fi, BT, Router, Jlink, display, etc.).",
    "build_ict":    "Author the ICT test sequence: add / edit / delete / move steps, and set limits for numeric tests — R-GND (Ω), voltage (V), clock (Hz); PASS when the measured value is within range.",
    "build_fct":    "Author the FCT test sequence: message tests (console Wait → Send → Capture, verdict Pass/Fail), firmware flashing, and RF (Wi-Fi / BT) — mostly third-party CLI or manual dialog confirm.",
    "apply_save":   "Final step: preview the generated YAML (read-only), confirm validation passes, then Apply & Save to produce the Draft / Final files.",
}

#: next-step hint shown directly under the guide
STEP_NEXT = {
    "design_input": "Completing unlocks 02 / 03.",
    "parse_ict":    "Completing unlocks 04.",
    "firmware":     "Completing unlocks 04.",
    "equipment":    "Completing unlocks 05 / 06.",
    "build_ict":    "Completing unlocks 07.",
    "build_fct":    "Completing unlocks 07.",
    "apply_save":   "Completing finishes the flow.",
}


def lock_message(key: str) -> str:
    """The read-only note naming the pending prerequisite(s)."""
    prereq_labels = ", ".join(sv.step_label(p) for p in PREREQS[key])
    return (
        f"Prerequisites not finished: complete 「{prereq_labels}」 first, "
        "then this step becomes editable. Read-only preview for now."
    )


#: state → (border colour, glyph) for the node painting
_STATE_STYLE = {
    "disabled": (QColor("#9aa0a6"), ""),
    "locked":   (QColor("#e67e22"), "🔒"),
    "editable": (QColor("#2471a3"), ""),
    "valid":    (QColor("#1e8449"), "✓"),
    "invalid":  (QColor("#c0392b"), "✗"),
}


class YamlBuildFlowView(QWidget):
    """Horizontal flowchart: one clickable node per ``sv.YAML_STEPS``."""

    #: emitted with the step key when a node is clicked
    step_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._states: dict[str, str] = {}
        self.node_rects: dict[str, QRectF] = self._compute_rects()
        self.setMinimumHeight(180)
        self.setMinimumWidth(420)

    # ---------------------------------------------------------- geometry
    @staticmethod
    def _compute_rects() -> dict[str, QRectF]:
        rects: dict[str, QRectF] = {}
        for step in sv.YAML_STEPS:
            cx, cy = NODE_CENTRES[step.key]
            rects[step.key] = QRectF(cx - NODE_W / 2.0, cy - NODE_H / 2.0,
                                     NODE_W, NODE_H)
        return rects

    def _transform(self) -> tuple[float, float, float]:
        """Uniform scale + centring offsets from logical → widget."""
        w = float(self.width())
        h = float(self.height())
        if w <= 0 or h <= 0:
            return 1.0, 0.0, 0.0
        scale = min(w / CANVAS_W, h / CANVAS_H)
        ox = (w - CANVAS_W * scale) / 2.0
        oy = (h - CANVAS_H * scale) / 2.0
        return scale, ox, oy

    def _widget_rect(self, rect: QRectF) -> QRectF:
        scale, ox, oy = self._transform()
        return QRectF(ox + rect.x() * scale, oy + rect.y() * scale,
                      rect.width() * scale, rect.height() * scale)

    # ------------------------------------------------------------ state
    def set_step_state(self, key: str, state: str) -> None:
        """Persist and repaint one node's state."""
        if state not in _STATE_STYLE:
            raise ValueError(f"unknown step state {state!r}")
        self._states[key] = state
        self.update()

    def step_state(self, key: str) -> str:
        return self._states.get(key, "disabled")

    # ------------------------------------------------------------ paint
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), Qt.transparent)
        self._draw_edges(painter)
        for step in sv.YAML_STEPS:
            self._draw_node(painter, step.key)
        painter.end()

    def _draw_edges(self, painter: QPainter) -> None:
        painter.save()
        pen = QPen(QColor("#8a9099"))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        for src, dst in EDGES:
            if (src, dst) in DASHED_EDGES:
                pen = QPen(QColor("#8a9099"))
                pen.setStyle(Qt.DashLine)
                pen.setWidthF(2.0)
                painter.setPen(pen)
            else:
                pen = QPen(QColor("#8a9099"))
                pen.setStyle(Qt.SolidLine)
                pen.setWidthF(2.0)
                painter.setPen(pen)
            sx, sy = NODE_CENTRES[src]
            dx, dy = NODE_CENTRES[dst]
            # start/stop at the node border, not the centre
            r1 = self.node_rects[src]
            r2 = self.node_rects[dst]
            p1 = self._edge_anchor(r1, r2)
            p2 = self._edge_anchor(r2, r1)
            painter.drawLine(p1, p2)
        painter.restore()

    def _edge_anchor(self, src: QRectF, dst: QRectF):
        """The point on *src*'s border facing *dst*'s centre."""
        scale, ox, oy = self._transform()
        cx = src.center().x()
        cy = src.center().y()
        dx = dst.center().x()
        dy = dst.center().y()
        sx = ox + cx * scale
        sy = oy + cy * scale
        # direction from src centre to dst centre (logical)
        vx, vy = dx - cx, dy - cy
        if abs(vx) >= abs(vy):
            half = (src.width() / 2.0) * scale * (1.0 if vx >= 0 else -1.0)
            return (sx + half, sy)
        half = (src.height() / 2.0) * scale * (1.0 if vy >= 0 else -1.0)
        return (sx, sy + half)

    def _draw_node(self, painter: QPainter, key: str) -> None:
        rect = self._widget_rect(self.node_rects[key])
        state = self.step_state(key)
        colour, glyph = _STATE_STYLE[state]
        step = sv.STEP_BY_KEY[key]

        painter.save()
        # fill
        painter.setBrush(QColor("#fbfcfd"))
        painter.setPen(QPen(colour, 2.5))
        painter.drawRoundedRect(rect, 8.0, 8.0)

        # title
        title_font = QFont(painter.font())
        title_font.setPointSizeF(10.0)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#1c2430"))
        title_rect = rect.adjusted(10, 6, -26, -rect.height() + 24)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         step.title)

        # status dot + glyph (top-right corner)
        dot = 10.0
        dot_x = rect.right() - 6.0 - dot
        dot_y = rect.top() + 8.0
        painter.setBrush(colour)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(int(dot_x), int(dot_y), int(dot), int(dot))
        if glyph:
            glyph_font = QFont(painter.font())
            glyph_font.setPointSizeF(10.0)
            painter.setFont(glyph_font)
            painter.setPen(QColor("#1c2430"))
            painter.drawText(
                QRectF(rect.right() - 26.0, rect.top() + 2.0, 22.0, 18.0),
                Qt.AlignRight | Qt.AlignVCenter, glyph)

        # hint lines (small muted font, elided to fit)
        hint_font = QFont(painter.font())
        hint_font.setPointSizeF(8.0)
        painter.setFont(hint_font)
        painter.setPen(QColor("#6b7280"))
        metrics = QFontMetrics(hint_font)
        hint = STEP_HINTS[key]
        line_y = rect.top() + 28.0
        for line in hint.split("\n"):
            elided = metrics.elidedText(line, Qt.ElideRight,
                                        int(rect.width() - 18))
            painter.drawText(QRectF(rect.left() + 9.0, line_y,
                                    rect.width() - 18, 12.0),
                             Qt.AlignLeft | Qt.AlignVCenter, elided)
            line_y += 13.0
        painter.restore()

    # ----------------------------------------------------------- events
    def mousePressEvent(self, event) -> None:
        pos = event.position()
        scale, ox, oy = self._transform()
        if scale <= 0:
            return
        lx = (pos.x() - ox) / scale
        ly = (pos.y() - oy) / scale
        for key, rect in self.node_rects.items():
            if rect.contains(lx, ly):
                self.step_clicked.emit(key)
                return
        super().mousePressEvent(event)
