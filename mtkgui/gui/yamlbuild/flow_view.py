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

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from mtkgui.gui.yamlbuild import steps_v2 as sv

#: logical canvas size (scaled to the widget in paintEvent)
CANVAS_W = 1340.0
CANVAS_H = 320.0

#: node footprint in logical coordinates (M128: grown for the larger
#: fonts and the bottom-right status badge)
NODE_W = 215.0
NODE_H = 104.0

#: node centres in logical coordinates (design_input left, apply_save right)
NODE_CENTRES = {
    "design_input": (130.0, 160.0),
    "parse_ict":    (360.0, 70.0),
    "firmware":     (360.0, 250.0),
    "equipment":    (640.0, 160.0),
    "build_ict":    (920.0, 70.0),
    "build_fct":    (920.0, 250.0),
    "apply_save":   (1160.0, 160.0),
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
    "design_input": "This is the entry point. Import SPF (auto-parses Core ID + product name), NET (read-only), BoM (optional), or switch to the Excel route; all five product-info fields are required, and select the FCT test types to enable. Locking this node also parses the Route A netlist.",
    "parse_ict":    "Review the netlist parsed when node 01 was locked: the left table holds recognized categories (power / clock / ground / other), the right table holds unclassified nets; move nets between tables to adjust, and press Parse nets again only if the NET file changed outside the tool.",
    "firmware":     "Configure FAT / OOBE flashing: CLI (command + pass/fail keywords, auto-verdict) or third-party GUI (tool path, runtime dialog for manual Go/Stop).",
    "equipment":    "Assign instrument channels: R-GND / voltage → DAQ, clock → counter / totalizer, DUT → console; then configure production peripherals (Wi-Fi, BT, Router, display, etc.).",
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


def skip_message(_key: str) -> str:
    """The read-only note of a node skipped by the design route."""
    return (
        "Skipped — ICT nets were parsed on import from the MTK ICT Excel "
        "Sheet (Route C). Read-only preview."
    )


#: state → (border colour, glyph) for the node painting
_STATE_STYLE = {
    "disabled": (QColor("#9aa0a6"), ""),
    "locked":   (QColor("#e67e22"), "🔒"),
    "editable": (QColor("#2471a3"), ""),
    "valid":    (QColor("#1e8449"), "✓"),
    "invalid":  (QColor("#c0392b"), "✗"),
    # M102: node 02 on Route C - enterable, read-only, auditable
    "skipped":  (QColor("#8e8e8e"), ""),
}

#: M128 module colouring (user direction): unused = grey,
#: needs configuration = light yellow, locked (completed) = green
_UNUSED = {
    "border": QColor("#9aa0a6"), "fill": QColor("#f2f3f5"),
    "title": QColor("#6b7280"), "hint": QColor("#9aa0a6"),
    "badge_bg": QColor("#9aa0a6"), "badge_text": QColor("#ffffff"),
}
_TODO = {
    "border": QColor("#d9a400"), "fill": QColor("#fff8dc"),
    "title": QColor("#1c2430"), "hint": QColor("#6b7280"),
    "badge_bg": QColor("#b7791f"), "badge_text": QColor("#ffffff"),
}
_LOCKED = {
    "border": QColor("#1e8449"), "fill": QColor("#eaf7ec"),
    "title": QColor("#12351f"), "hint": QColor("#4a6b55"),
    "badge_bg": QColor("#1e8449"), "badge_text": QColor("#ffffff"),
}
#: badge caption for "never edited" in the yellow state
_EMPTY_BADGE = (QColor("#8a9099"), QColor("#ffffff"))


class YamlBuildFlowView(QWidget):
    """Horizontal flowchart: one clickable node per ``sv.YAML_STEPS``."""

    #: emitted with the step key when a node is clicked
    step_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._states: dict[str, str] = {}
        self._visual: dict[str, dict] = {}
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

    # ------------------------------------------------------ M128 visual
    def set_step_visual(self, key: str, *, unused: bool = False,
                        locked: bool = False, edited: bool = False) -> None:
        """Set the module colour family and the status badge.

        Args:
            key:    Step key.
            unused: True when the ICT/FCT selection does not use it
                    (grey card, no configuration needed).
            locked: True when the module is locked (green card, badge
                    ``Completed``).
            edited: True when the module carries content but is still
                    open (badge ``Edited``; else ``Empty``).
        """
        self._visual[key] = {"unused": bool(unused),
                             "locked": bool(locked),
                             "edited": bool(edited)}
        self.update()

    def step_visual(self, key: str) -> dict:
        """The visual flags of *key* (all False when never set)."""
        return dict(self._visual.get(key) or {})

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
            return QPointF(sx + half, sy)
        half = (src.height() / 2.0) * scale * (1.0 if vy >= 0 else -1.0)
        return QPointF(sx, sy + half)

    def _draw_node(self, painter: QPainter, key: str) -> None:
        rect = self._widget_rect(self.node_rects[key])
        state = self.step_state(key)
        flags = self._visual.get(key) or {}
        step = sv.STEP_BY_KEY[key]

        # M128 colour family: unused (grey) / locked (green) / todo (yellow)
        unused = bool(flags.get("unused")) or state in ("disabled", "skipped")
        locked = bool(flags.get("locked")) and not unused
        edited = bool(flags.get("edited", True))
        palette = _UNUSED if unused else (_LOCKED if locked else _TODO)
        if locked:
            badge_text = "Completed"
        elif unused:
            badge_text = "Unused"
        elif edited:
            badge_text = "Edited"
        else:
            badge_text = "Empty"

        painter.save()
        painter.setBrush(palette["fill"])
        painter.setPen(QPen(palette["border"], 2.5))
        painter.drawRoundedRect(rect, 8.0, 8.0)

        # title (M128: bigger - the card text was hard to read)
        title_font = QFont(painter.font())
        title_font.setPointSizeF(12.0)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(palette["title"])
        title_rect = rect.adjusted(10, 8, -8, -rect.height() + 32)
        title_metrics = QFontMetrics(title_font)
        painter.drawText(
            title_rect, Qt.AlignLeft | Qt.AlignVCenter,
            title_metrics.elidedText(step.title, Qt.ElideRight,
                                     int(title_rect.width())))

        # hint lines (bigger than the old 8 pt, elided to fit)
        hint_font = QFont(painter.font())
        hint_font.setPointSizeF(9.5)
        painter.setFont(hint_font)
        painter.setPen(palette["hint"])
        metrics = QFontMetrics(hint_font)
        hint = STEP_HINTS[key]
        line_y = rect.top() + 34.0
        for line in hint.split("\n"):
            elided = metrics.elidedText(line, Qt.ElideRight,
                                        int(rect.width() - 18))
            painter.drawText(QRectF(rect.left() + 9.0, line_y,
                                    rect.width() - 18, 14.0),
                             Qt.AlignLeft | Qt.AlignVCenter, elided)
            line_y += 14.0

        # M128: status badge - bottom-right, coloured background
        badge_font = QFont(painter.font())
        badge_font.setPointSizeF(8.0)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        badge_metrics = QFontMetrics(badge_font)
        badge_w = badge_metrics.horizontalAdvance(badge_text) + 12.0
        badge_h = 16.0
        badge = QRectF(rect.right() - 7.0 - badge_w,
                       rect.bottom() - 6.0 - badge_h, badge_w, badge_h)
        if unused:
            bg, fg = _UNUSED["badge_bg"], _UNUSED["badge_text"]
        elif locked:
            bg, fg = _LOCKED["badge_bg"], _LOCKED["badge_text"]
        elif edited:
            bg, fg = _TODO["badge_bg"], _TODO["badge_text"]
        else:
            bg, fg = _EMPTY_BADGE
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(badge, 5.0, 5.0)
        painter.setPen(fg)
        painter.drawText(badge, Qt.AlignCenter, badge_text)
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
