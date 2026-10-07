# -*- coding: utf-8 -*-
"""Standalone Power Tree topology page (relocated from the Parse Nets
for ICT panel).

Fully contains the interactive power tree topology:

* graph canvas (QGraphicsView) - one editable node per power net,
  layered by stage; wheel zoom, hand-drag pan, fit-to-view and
  automatic scrollbars for large topologies;
* double-click node edit dialog (voltage / tolerances / dependencies /
  upstream / downstream / stage override / Do-Not-Test).

The passive-bridge pruning runs automatically at parse/build time; a
wrongly-pruned net is restored by re-categorizing it as Power in the
Parsed Nets table.

Data binding stays on the Parse Nets result: the tree, node
attributes, connections, stages and the audit log live in the
``model.power_tree`` dict (project YAML section ``power_tree``).
GUI layer only - the parsing core is untouched.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QPolygonF,
    QWheelEvent,
)
import shiboken6
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.power_alloc import (
    MAX_STAGE,
    NODE_PRIMARY,
    PowerTree,
    auto_fill_voltage,
    auto_primaries,
    find_bridges,
)
from mtkgui.gui.yamlbuild.power_tree_editor import (
    DONT_TEST_COLOR,
    NODE_COLORS,
    NodeEditDialog,
)

#: canvas node geometry (per stage-column layered layout)
NODE_W = 170
NODE_H = 44
COL_STEP = NODE_W + 110
ROW_STEP = NODE_H + 34
ZOOM_FACTOR = 1.15


class _NodeItem(QGraphicsRectItem):
    """One power net node on the canvas.

    Normal mode: drag moves the node - on release the page snaps the
    horizontal position to the stage column (defines the stage level
    0..6) and the vertical position to the row of an upstream /
    downstream node (aligning = same row).  Double-click opens the
    edit dialog.  Link mode: drag draws a flow arrow - on release over
    another node the page creates the upstream -> downstream edge.
    """

    def __init__(self, name: str, page: "PowerTreePage") -> None:
        super().__init__(0, 0, NODE_W, NODE_H)
        self.name = name
        self._page = page
        self._dragging = False
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsFocusable)

    def _alive(self) -> bool:
        """True while the C++ item exists: a scene rebuild
        (scene.clear) deletes the item while stale Qt events (the
        double-click sequence spans press/release/dblclick) may still
        dispatch to the Python wrapper - guard every override."""
        return shiboken6.isValid(self)

    def mousePressEvent(self, event) -> None:
        if not self._alive():
            return
        if self._page._link_mode:
            self._page._link_start(self.name)
            event.accept()
            return
        self._dragging = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._alive():
            return
        if self._page._link_mode:
            self._page._link_update(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if not self._alive():
            return
        if self._page._link_mode:
            self._page._link_end(self.name)
            event.accept()
            return
        if self._dragging:
            self._dragging = False
            self._page._on_node_dropped(self.name, self.scenePos())
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._alive():
            return
        if not self._page._link_mode:
            self._page._edit_node(self.name)
        super().mouseDoubleClickEvent(event)


class _TreeCanvas(QGraphicsView):
    """Zoomable / pannable topology canvas (scrollbars as needed)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        # automatic scrollbars when the topology exceeds the viewport
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Mouse-wheel zoom (anchored at the view center)."""
        if event.angleDelta().y() > 0:
            self.scale(ZOOM_FACTOR, ZOOM_FACTOR)
        else:
            self.scale(1 / ZOOM_FACTOR, 1 / ZOOM_FACTOR)

    def fit_view(self) -> None:
        """Fit the whole topology into the viewport."""
        if self.scene() and self.scene().itemsBoundingRect():
            self.fitInView(self.scene().itemsBoundingRect(),
                           Qt.AspectRatioMode.KeepAspectRatio)


class PowerTreePage(QWidget):
    """The dedicated Power Tree tab (topology graph + node editing +
    stage/pruning summary + audit log)."""

    #: (level, message) Event-Log mirror (T6)
    task_log = Signal(str, str)
    #: Apply to YAML clicked: the tree draft was persisted into the
    #: model - the main window switches to the Yaml Build tab
    apply_yaml_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        # NOTE: the model is injected AFTER construction via
        # set_model() (PySide 6.10.x shiboken GC bug workaround -
        # see ChannelAllocationPage.__init__).
        super().__init__(parent)
        self.model = None
        self.tree = PowerTree()
        self._bridges: list[dict] = []
        self._link_mode = False          # draw-flow-arrow mode
        self._link_from: str | None = None
        self._link_line: QGraphicsLineItem | None = None
        self._layout_pos: dict[str, tuple[float, float]] = {}
        self._node_items: list[_NodeItem] = []

        lay = QVBoxLayout(self)
        hint = QLabel(
            "Interactive power tree topology (data source: the Parse "
            "Nets result). Passive-bridge pruning runs automatically "
            "at parse time; a wrongly-pruned net is restored by "
            "re-categorizing it as Power in the Parsed Nets table. "
            "Double-click a node to edit voltage, tolerances, "
            "dependencies, links, stage override and Do-Not-Test. "
            "Drag a node horizontally to set its power stage (0-6); "
            "drag it vertically onto an upstream/downstream node to "
            "align rows. 'Draw Flow Arrow': drag from the upstream "
            "node and drop on the downstream node to define the power "
            "flow (the upstream stays unique; a primary has none). "
            "Drag empty canvas to pan, wheel = zoom.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        btn_rebuild = QPushButton("AI Power Tree Topology")
        btn_rebuild.setToolTip(
            "Automated topology analysis (the groundwork, then manual "
            "editing): detects the primary sources, assigns the power "
            "stages via the bridge graph (regulator bridges increment "
            "the stage), links the upstream / downstream power nets "
            "and auto-fills Expected Voltage (+/-5 % tolerances) from "
            "the rail names (blank when not parseable); saved node "
            "attributes are kept via the YAML draft")
        btn_rebuild.clicked.connect(self._rebuild)
        btn_fit = QPushButton("Fit View")
        btn_fit.clicked.connect(self._fit)
        btn_zoom_in = QPushButton("Zoom In")
        btn_zoom_in.clicked.connect(
            lambda: self.canvas.scale(ZOOM_FACTOR, ZOOM_FACTOR))
        btn_zoom_out = QPushButton("Zoom Out")
        btn_zoom_out.clicked.connect(
            lambda: self.canvas.scale(1 / ZOOM_FACTOR,
                                      1 / ZOOM_FACTOR))
        btn_link = QPushButton("Draw Flow Arrow")
        btn_link.setCheckable(True)
        btn_link.setToolTip(
            "Flow-arrow mode: press on the UPSTREAM node, drag and "
            "drop on the DOWNSTREAM node to define the power flow. "
            "Every node keeps at most ONE upstream (re-defining it "
            "replaces the old edge); a primary power input has no "
            "upstream; one node may feed many downstream nodes.")
        btn_link.toggled.connect(self._set_link_mode)
        btn_apply = QPushButton("Apply to YAML")
        btn_apply.setToolTip(
            "Persist the power tree draft into the YAML config and "
            "switch to the Yaml Build page")
        btn_apply.clicked.connect(self._apply_to_yaml)
        for btn in (btn_rebuild, btn_fit, btn_zoom_in, btn_zoom_out,
                    btn_link, btn_apply):
            row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = _TreeCanvas()
        self.canvas.setScene(QGraphicsScene(self))
        splitter.addWidget(self.canvas)
        lay.addWidget(splitter, 1)

    # ------------------------------------------------------------ model
    def set_model(self, model) -> None:
        """Inject the model AFTER construction (shiboken GC bug
        workaround) and refresh."""
        self.model = model
        self.refresh_from_model()

    def refresh_from_model(self) -> None:
        """Load the YAML draft (or auto-build from the Parse Nets
        result) and repaint canvas + panels."""
        if self.model is None:
            return
        draft = self.model.power_tree or {}
        if draft.get("nodes"):
            self.tree = PowerTree.from_dict(draft)
        else:
            self._build_tree()
        self._render()

    def _parse_members(self) -> tuple[list[str], dict[str, list[str]]]:
        """(power net names, all net members) from the Parse Nets
        result stored in the model (the single data source)."""
        testable = (self.model.imported.get("testable_nets")
                    if self.model else None) or {}
        members = {name: list(info.get("members") or [])
                   for name, info in testable.items()}
        power = [name for name, info in testable.items()
                 if info.get("category") == "Power"]
        return power, members

    def _build_tree(self) -> None:
        """AI topology build from the parse result (keeps nothing:
        only called when no YAML draft exists yet).  The automation
        does the groundwork (user direction): primary detection ->
        stage assignment (regulator bridges increment the stage, no
        more all-stage-1 islands) -> upstream / downstream links ->
        Expected Voltage (+/-5 %) auto-fill from the rail names.  The
        passive-bridge pruning runs AUTOMATICALLY here and a wrongly
        pruned net is restored by re-categorizing it as Power in the
        Parse Nets Parsed Nets table (category_override flag)."""
        power, members = self._parse_members()
        self._bridges = find_bridges(members)
        self.tree = PowerTree.build(power, self._bridges,
                                    primaries=auto_primaries(
                                        power, self._bridges))
        pruned = self.tree.prune_passive(self._bridges)
        testable = ((self.model.imported.get("testable_nets") or {})
                    if self.model else {})
        for entry in pruned:
            if (testable.get(entry["net"]) or {}).get(
                    "category_override"):
                self.tree.restore_pruned(entry["net"])
        self._voltages_filled = auto_fill_voltage(self.tree)

    # ------------------------------------------------------------ canvas
    def _render(self) -> None:
        """Repaint the topology graph."""
        self._render_canvas()

    def _render_canvas(self) -> None:
        scene = self.canvas.scene()
        scene.clear()
        self._node_items = []             # wrappers of the new items
        self._link_line = None
        self._link_from = None
        active = self.tree.active_nodes()
        # layout: column = stage, row = manual row (vertical drag) or
        # the first free row of the column (no overlaps)
        staged: dict[int, list] = {}
        for node in active:
            staged.setdefault(
                node.stage if node.stage is not None else 0,
                []).append(node)
        pos: dict[str, tuple[float, float]] = {}
        for stage in sorted(staged):
            used: set[int] = {
                n.row for n in staged[stage] if n.row is not None}
            free = (r for r in range(len(active))
                    if r not in used)
            for node in staged[stage]:
                row = node.row if node.row is not None else next(free)
                used.add(row)
                pos[node.name] = (stage * COL_STEP, row * ROW_STEP)
        self._layout_pos = pos            # layout slot per node name
        # edges first (behind the nodes): power-flow arrows
        for node in active:
            for upstream in node.upstream:
                if upstream not in pos:
                    continue
                self._add_arrow(scene, pos[upstream], pos[node.name])
        for node in active:
            x, y = pos[node.name]
            color = QColor(DONT_TEST_COLOR if node.dont_test
                           else NODE_COLORS.get(node.node_type,
                                                "#2563eb"))
            item = _NodeItem(node.name, self)
            self._node_items.append(item)   # keep the wrapper alive
            item.setRect(x, y, NODE_W, NODE_H)
            item.setBrush(QBrush(color))
            item.setPen(Qt.PenStyle.NoPen)
            item.setFlag(
                QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
            label = scene.addText(
                f"{node.name}\nStage {node.stage} · "
                f"{node.expected_voltage or '-'}")
            label.setDefaultTextColor(QColor("#ffffff"))
            label.setPos(x + 6, y)
            label.setParentItem(item)
            scene.addItem(item)
        self.canvas.fit_view()

    @staticmethod
    def _add_arrow(scene, src: tuple[float, float],
                   dst: tuple[float, float]) -> None:
        """Straight power-flow arrow: line + filled arrowhead at the
        downstream end (power flows upstream -> downstream)."""
        import math
        x0, y0 = src[0] + NODE_W, src[1] + NODE_H / 2
        x1, y1 = dst[0], dst[1] + NODE_H / 2
        pen = QPen(QColor("#94a3b8"))
        scene.addLine(x0, y0, x1, y1, pen)
        # arrowhead triangle pointing along the line direction
        rad = math.atan2(y1 - y0, x1 - x0)
        back, side = 10.0, 4.5
        dx, dy = math.cos(rad), math.sin(rad)
        scene.addPolygon(QPolygonF([
            QPointF(x1, y1),
            QPointF(x1 - back * dx + side * -dy,
                    y1 - back * dy + side * dx),
            QPointF(x1 - back * dx - side * -dy,
                    y1 - back * dy - side * dx),
        ]), QPen(QColor("#94a3b8"), 0))

    # --------------------------------------------------- mouse interactions
    def _set_link_mode(self, enabled: bool) -> None:
        """Toggle the flow-arrow drawing mode (canvas cursor + the
        pending temp line reset)."""
        self._link_mode = enabled
        self.canvas.setCursor(
            Qt.CursorShape.CrossCursor if enabled
            else Qt.CursorShape.ArrowCursor)
        self._link_reset()

    def _link_reset(self) -> None:
        if self._link_line is not None:
            self._link_line.scene().removeItem(self._link_line)
            self._link_line = None
        self._link_from = None

    def _link_start(self, name: str) -> None:
        """Flow-arrow mode: press on the upstream node - start the
        temp rubber line."""
        node = self.tree.nodes.get(name)
        if node is None or node.pruned:
            return
        self._link_from = name
        pos = self._node_pos(name)
        self._link_line = self.canvas.scene().addLine(
            pos[0] + NODE_W, pos[1] + NODE_H / 2,
            pos[0] + NODE_W, pos[1] + NODE_H / 2,
            QPen(QColor("#16a34a")))

    def _node_pos(self, name: str) -> tuple[float, float]:
        """Scene position of the node item (default: layout slot)."""
        for item in self.canvas.scene().items():
            if isinstance(item, _NodeItem) and item.name == name:
                return item.scenePos().x(), item.scenePos().y()
        return self._layout_pos.get(name, (0.0, 0.0))

    def _link_update(self, scene_pos) -> None:
        """Flow-arrow mode: the temp line follows the mouse."""
        if self._link_line is None:
            return
        line = self._link_line.line()
        self._link_line.setLine(line.x1(), line.y1(),
                                scene_pos.x(), scene_pos.y())

    def _link_end(self, name: str | None) -> None:
        """Flow-arrow mode: drop - a node target creates the
        upstream -> downstream edge (unique upstream rules apply),
        an empty target cancels."""
        source = self._link_from
        self._link_reset()
        if not source or not name or name == source:
            return
        ok, message = self.tree.link(source, name)
        if ok:
            self._render()
            self.save_to_model()
            self._log("INFO", f"Power flow link: {source} -> {name}")
        else:
            QMessageBox.warning(self, "Flow link rejected", message)

    def _on_node_dropped(self, name: str, scene_pos) -> None:
        """Node drag released: horizontal snap defines the stage
        (0..MAX_STAGE), the vertical snap aligns the row with an
        upstream / downstream node (half-row tolerance) or falls back
        to the nearest free row slot."""
        node = self.tree.nodes.get(name)
        if node is None or node.pruned:
            return
        changed = False
        stage = round(scene_pos.x() / COL_STEP)
        stage = max(0, min(MAX_STAGE, stage))
        if stage != node.stage:
            self.tree.set_stage(name, stage)
            changed = True
        # vertical: align with a linked node's row when close
        linked = [self.tree.nodes[n] for n in
                  list(node.upstream) + list(node.downstream)
                  if n in self.tree.nodes and not self.tree.nodes[n].pruned]
        target_row = None
        for other in linked:
            oy = self._node_pos(other.name)[1]
            if abs(scene_pos.y() - oy) <= ROW_STEP / 2:
                target_row = (other.row if other.row is not None
                              else round(oy / ROW_STEP))
                break
        if target_row is None:
            target_row = max(0, round(scene_pos.y() / ROW_STEP))
        if target_row != node.row:
            node.row = target_row
            changed = True
        self._render()
        if changed:
            self.save_to_model()
            self._log("INFO",
                      f"Node {name} moved: stage {node.stage}, "
                      f"row {node.row}")

    # ------------------------------------------------------------ actions
    def _log(self, level: str, message: str) -> None:
        """Unified Event-Log reporting (same format / levels as every
        other page: task_log INFO / WARNING / ERROR mirror)."""
        self.task_log.emit(level, message)

    #: node attributes tracked for the manual-override change summary
    _TRACKED_ATTRS = ("expected_voltage", "tol_upper", "tol_lower",
                      "dependencies", "dont_test")
    _ATTR_LABELS = {
        "expected_voltage": "voltage",
        "tol_upper": "upper tolerance",
        "tol_lower": "lower tolerance",
        "dependencies": "dependencies",
        "dont_test": "Do Not Test",
    }

    @classmethod
    def _change_summary(cls, before, after) -> list[str]:
        """Human-readable summary of the edited fields (for the
        Event-Log record)."""
        changed = [cls._ATTR_LABELS[k] for k in cls._TRACKED_ATTRS
                   if getattr(before, k) != getattr(after, k)]
        if list(before.upstream) != list(after.upstream):
            changed.append("upstream links")
        if list(before.downstream) != list(after.downstream):
            changed.append("downstream links")
        if before.stage_override != after.stage_override:
            target = "auto" if after.stage_override is None \
                else str(after.stage_override)
            changed.append(f"stage -> {target}")
        return changed

    def _edit_node(self, name: str) -> None:
        node = self.tree.nodes.get(name)
        if node is None:
            return
        if node.pruned:
            QMessageBox.information(
                self, "Pruned node",
                "This node was pruned from the tree by the automatic "
                "passive-bridge pruning - re-categorize the net as "
                "Power in the Parse Nets Parsed Nets table to restore "
                "it.")
            return
        before = copy.deepcopy(node)
        dlg = NodeEditDialog(node, self.tree, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            changed = self._change_summary(before, node)
            self.tree.audit_log.append({
                "net": name,
                "reason": "manual override (attributes / stage / "
                          "links / Do-Not-Test)",
                "refdes": "", "kept": ""})
            self._render()
            self.save_to_model()
            self._log(
                "INFO",
                "Manual tree attribute override on "
                f"{name}: {', '.join(changed) or 'saved'}")

    def _rebuild(self) -> None:
        """AI Power Tree Topology: rebuild with the automatic primary
        / stage / link / voltage analysis (the passive-bridge pruning
        is part of the automatic build)."""
        self._build_tree()
        self._render()
        self.save_to_model()
        pruned = [n.name for n in self.tree.nodes.values() if n.pruned]
        self._log(
            "INFO",
            f"AI power tree topology built: {len(self.tree.nodes)} "
            f"nodes, {len(pruned)} auto-pruned, "
            f"{getattr(self, '_voltages_filled', 0)} voltages "
            "auto-filled (+/-5%)")

    def _fit(self) -> None:
        self.canvas.fit_view()

    # ------------------------------------------------------------ persist
    def _apply_to_yaml(self) -> None:
        """Apply-to-YAML (user direction): persist the tree draft
        into the model and jump to the Yaml Build page."""
        self.save_to_model()
        self.apply_yaml_requested.emit()

    def save_to_model(self) -> None:
        """Persist the draft into the model (project YAML section
        ``power_tree``)."""
        if self.model is not None:
            self.model.power_tree = self.tree.to_dict()
            self.model.changed = True

    def showEvent(self, event) -> None:
        """Refresh on every tab entry (always mirrors the model)."""
        super().showEvent(event)
        self.refresh_from_model()

    def hideEvent(self, event) -> None:
        """Persist the draft when the tab is left."""
        self.save_to_model()
        super().hideEvent(event)
