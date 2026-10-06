# -*- coding: utf-8 -*-
"""Standalone Power Tree topology page (relocated from the Parse Nets
for ICT panel).

Fully contains the interactive power tree topology:

* graph canvas (QGraphicsView) - one editable node per power net,
  layered by stage; wheel zoom, hand-drag pan, fit-to-view and
  automatic scrollbars for large topologies;
* double-click node edit dialog (voltage / tolerances / dependencies /
  upstream / downstream / stage override / Do-Not-Test);
* side summary panel - every power node with its stage label, test
  path risk score and status;
* audit log panel - the passive-bridge pruning history plus every
  manual override record.

Data binding stays on the Parse Nets result: the tree, node
attributes, connections, stages and the audit log live in the
``model.power_tree`` dict (project YAML section ``power_tree``).
GUI layer only - the parsing core is untouched.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QWheelEvent
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
)

from mtkgui.gui.yamlbuild.power_alloc import (
    NODE_PRIMARY,
    PowerTree,
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
    """One power net node on the canvas (double-click opens the edit
    dialog via the page callback)."""

    def __init__(self, name: str, on_edit) -> None:
        super().__init__(0, 0, NODE_W, NODE_H)
        self.name = name
        self._on_edit = on_edit
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsFocusable)

    def mouseDoubleClickEvent(self, event) -> None:
        self._on_edit(self.name)
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

    def __init__(self, parent: QWidget | None = None) -> None:
        # NOTE: the model is injected AFTER construction via
        # set_model() (PySide 6.10.x shiboken GC bug workaround -
        # see ChannelAllocationPage.__init__).
        super().__init__(parent)
        self.model = None
        self.tree = PowerTree()
        self._bridges: list[dict] = []

        lay = QVBoxLayout(self)
        hint = QLabel(
            "Interactive power tree topology (data source: the Parse "
            "Nets result). Passive-bridge pruning runs automatically "
            "at parse time; a wrongly-pruned net is restored by "
            "re-categorizing it as Power in the Parsed Nets table. "
            "Double-click a node to edit voltage, tolerances, "
            "dependencies, upstream/downstream links, the stage "
            "override and the Do-Not-Test flag. Wheel = zoom, "
            "drag = pan.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        btn_rebuild = QPushButton("Rebuild from Parse Nets")
        btn_rebuild.setToolTip(
            "Rebuild the tree from the current Parse Nets result "
            "(saved node attributes kept via the YAML draft); the "
            "passive-bridge pruning runs automatically")
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
        for btn in (btn_rebuild, btn_fit, btn_zoom_in, btn_zoom_out):
            row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = _TreeCanvas()
        self.canvas.setScene(QGraphicsScene(self))
        splitter.addWidget(self.canvas)

        side = QWidget()
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 0, 0)
        lbl_nodes = QLabel("Power Nodes (stage / risk / status):")
        lbl_nodes.setObjectName("strong")
        side_lay.addWidget(lbl_nodes)
        self.node_summary = QTreeWidget()
        self.node_summary.setHeaderLabels(
            ["Net", "Stage", "Type", "Risk", "Status"])
        self.node_summary.setRootIsDecorated(False)
        self.node_summary.itemDoubleClicked.connect(
            self._on_summary_double_click)
        side_lay.addWidget(self.node_summary, 3)
        lbl_audit = QLabel("Audit Log (pruning + manual overrides):")
        lbl_audit.setObjectName("strong")
        side_lay.addWidget(lbl_audit)
        self.audit_list = QTreeWidget()
        self.audit_list.setHeaderLabels(["Net", "Record"])
        self.audit_list.setRootIsDecorated(False)
        side_lay.addWidget(self.audit_list, 2)
        splitter.addWidget(side)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([700, 300])
        lay.addWidget(splitter, 1)

        # ------------------------- power waveform capture configuration
        # migrated from the Parse Nets dialog (core standard 5.4: the
        # Tree page owns the capture list; persisted in the parse_ict
        # params, passed READ-ONLY to block 04)
        capture_row = QHBoxLayout()
        lbl_capture = QLabel(
            "Power Waveform Capture Nets (max 12, one per line - "
            "block 04 reads this list read-only):")
        lbl_capture.setObjectName("strong")
        capture_row.addWidget(lbl_capture)
        capture_row.addStretch(1)
        self.btn_apply_capture = QPushButton("Apply Capture Nets")
        self.btn_apply_capture.setToolTip(
            "Save the capture net list into the project YAML "
            "(Event-Log traced)")
        self.btn_apply_capture.clicked.connect(self._apply_capture)
        capture_row.addWidget(self.btn_apply_capture)
        lay.addLayout(capture_row)
        self.edit_capture = QPlainTextEdit()
        self.edit_capture.setMaximumHeight(72)
        self.edit_capture.setPlaceholderText(
            "e.g.\nVDD_3V3\nVDD_CORE")
        lay.addWidget(self.edit_capture)

    # ------------------------------------------------------------ model
    def set_model(self, model) -> None:
        """Inject the model AFTER construction (shiboken GC bug
        workaround) and refresh."""
        self.model = model
        self.refresh_from_model()
        self._load_capture()

    def _load_capture(self) -> None:
        """Load the persisted capture list into the editor (only when
        the editor is untouched - never clobber user input)."""
        if self.model is None:
            return
        if self.edit_capture.toPlainText().strip():
            return
        current = (self.model.get_params("parse_ict") or {}).get(
            "power_capture_nets") or ""
        if current:
            self.edit_capture.setPlainText(str(current))

    def _apply_capture(self) -> None:
        """Apply + persist the capture list (max 12 nets; Event-Log
        traced - core standard 5.5)."""
        nets = [ln.strip() for ln in
                self.edit_capture.toPlainText().splitlines()
                if ln.strip()]
        if len(nets) > 12:
            QMessageBox.warning(
                self, "Capture Nets",
                "at most 12 capture nets allowed "
                f"({len(nets)} given)")
            return
        if self.model is not None:
            self.model.set_params("parse_ict", {
                "power_capture_nets": "\n".join(nets)})
        self._log("INFO",
                  f"Waveform capture nets updated "
                  f"({len(nets)} nets)")

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
        """Auto-build the draft from the parse result (keeps nothing:
        only called when no YAML draft exists yet).  The passive-bridge
        pruning runs AUTOMATICALLY here (user direction: no manual
        prune/restore buttons) - a wrongly-pruned net is restored by
        re-categorizing it as Power in the Parse Nets Parsed Nets
        table (the category_override flag travels via testable_nets)."""
        power, members = self._parse_members()
        self._bridges = find_bridges(members)
        self.tree = PowerTree.build(power, self._bridges, primaries=[])
        pruned = self.tree.prune_passive(self._bridges)
        testable = ((self.model.imported.get("testable_nets") or {})
                    if self.model else {})
        for entry in pruned:
            if (testable.get(entry["net"]) or {}).get(
                    "category_override"):
                self.tree.restore_pruned(entry["net"])

    # ------------------------------------------------------------ canvas
    def _render(self) -> None:
        """Repaint the topology graph + the side panels."""
        self._render_canvas()
        self._render_summary()
        self._render_audit()

    def _render_canvas(self) -> None:
        scene = self.canvas.scene()
        scene.clear()
        staged: dict[int, list] = {}
        for node in self.tree.active_nodes():
            staged.setdefault(
                node.stage if node.stage is not None else 0,
                []).append(node)
        pos: dict[str, tuple[float, float]] = {}
        for stage in sorted(staged):
            for i, node in enumerate(staged[stage]):
                x = stage * COL_STEP
                y = i * ROW_STEP
                pos[node.name] = (x, y)
        # edges first (behind the nodes)
        for node in self.tree.active_nodes():
            for upstream in node.upstream:
                if upstream not in pos:
                    continue
                x0, y0 = pos[upstream]
                x1, y1 = pos[node.name]
                scene.addLine(x0 + NODE_W, y0 + NODE_H / 2,
                              x1, y1 + NODE_H / 2,
                              QBrush(QColor("#94a3b8")))
        for node in self.tree.active_nodes():
            x, y = pos[node.name]
            color = QColor(DONT_TEST_COLOR if node.dont_test
                           else NODE_COLORS.get(node.node_type,
                                                "#2563eb"))
            item = _NodeItem(node.name, self._edit_node)
            item.setRect(x, y, NODE_W, NODE_H)
            item.setBrush(QBrush(color))
            item.setPen(Qt.PenStyle.NoPen)
            label = scene.addText(
                f"{node.name}\nStage {node.stage} · "
                f"{node.expected_voltage or '-'}")
            label.setDefaultTextColor(QColor("#ffffff"))
            label.setPos(x + 6, y)
            label.setParentItem(item)
            scene.addItem(item)
        self.canvas.fit_view()

    def _render_summary(self) -> None:
        self.node_summary.clear()
        scores = ((self.model.path_risk or {}).get("scores") or {}
                  if self.model else {})
        for node in self.tree.nodes.values():
            if node.pruned:
                status = f"pruned ({node.pruned_reason})"
            elif node.dont_test:
                status = "Do Not Test"
            else:
                status = node.node_type
            risk = scores.get(node.name) or {}
            item = QTreeWidgetItem([
                node.name, str(node.stage), node.node_type,
                str(risk.get("score", "-")), status])
            item.setData(0, Qt.ItemDataRole.UserRole, node.name)
            self.node_summary.addTopLevelItem(item)

    def _render_audit(self) -> None:
        self.audit_list.clear()
        for entry in self.tree.audit_log:
            self.audit_list.addTopLevelItem(QTreeWidgetItem(
                [entry.get("net") or "-",
                 entry.get("reason") or "-"]))

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

    def _on_summary_double_click(self, item: QTreeWidgetItem,
                                 _col: int) -> None:
        name = item.data(0, Qt.ItemDataRole.UserRole)
        if name:
            self._edit_node(name)

    def _rebuild(self) -> None:
        """Rebuild the tree from the current Parse Nets result (the
        passive-bridge pruning is part of the automatic build)."""
        self._build_tree()
        self._render()
        self.save_to_model()
        pruned = [n.name for n in self.tree.nodes.values() if n.pruned]
        self._log(
            "INFO",
            f"Power tree rebuilt from parse result "
            f"({len(self.tree.nodes)} nodes, "
            f"{len(pruned)} auto-pruned)")

    def _fit(self) -> None:
        self.canvas.fit_view()

    # ------------------------------------------------------------ persist
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
