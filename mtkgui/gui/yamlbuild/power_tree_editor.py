# -*- coding: utf-8 -*-
"""Power Tree Editor dialog (item 24, Tasks 2-3).

Renders the :class:`~mtkgui.gui.yamlbuild.power_alloc.PowerTree`
draft as a colour-coded tree (indentation = stage depth):

* primary power input   - green (start node, single / multiple)
* normal power node     - blue
* load node (end)       - grey, read-only (locked)
* island node           - grey (no upstream found - wire manually)
* Do-Not-Test node      - dark grey

Double-click opens the node edit dialog: expected voltage, upper /
lower tolerance, dependency conditions, upstream / downstream
references, manual stage override and the Do-Not-Test checkbox.
[Prune passive bridges] applies the R/L/C/J/SJ pruning rule with the
audit log; pruned nodes can be restored manually.  GUI layer only.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from mtkgui.gui.yamlbuild.power_alloc import (
    MAX_STAGE,
    NODE_LOAD,
    NODE_NORMAL,
    NODE_PRIMARY,
    PowerTree,
)

NODE_COLORS = {
    # head node (primary power input) - green
    "primary": "#16a34a",
    # middle node (neither head nor tail) - light gray
    "normal": "#9ca3af",
    "island": "#9ca3af",
    # tail node (end load) - dark gray
    "load": "#4b5563",
}
#: Do-Not-Test nodes stay recognizable against the tail gray
DONT_TEST_COLOR = "#1f2937"

#: placeholder of the node-reference dropdowns (no selection)
NO_REFERENCE = "—"


class MultiSelectCombo(QComboBox):
    """Drop-down with CHECKABLE items (multi-select, user direction:
    the downstream node reference allows multiple power nets); the
    closed-state text summarises the current selection.  Items carry
    ``(name, label)`` pairs - the label may be annotated (e.g. a
    pruned net) while the stored value stays the raw net name.

    Multi-select FIX: the default QComboBox closes the popup on the
    first item click - the popup viewport therefore gets an event
    filter that toggles the check state and SWALLOWS the mouse events
    (the popup stays open until the user clicks elsewhere)."""

    def __init__(self, choices: list[tuple[str, str]],
                 checked: list[str], parent=None) -> None:
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        placeholder = QStandardItem(NO_REFERENCE)
        placeholder.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._model.appendRow(placeholder)
        for name, label in choices:
            item = QStandardItem(label)
            item.setData(name, Qt.ItemDataRole.UserRole)
            item.setCheckable(True)
            item.setCheckState(
                Qt.CheckState.Checked if name in checked
                else Qt.CheckState.Unchecked)
            self._model.appendRow(item)
        from PySide6.QtWidgets import QAbstractItemView, QListView
        list_view = QListView(self)
        list_view.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.setView(list_view)
        # toggle check states WITHOUT closing the popup
        self.view().viewport().installEventFilter(self)
        self._model.itemChanged.connect(lambda _i: self._sync_text())
        self._sync_text()

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        if obj is self.view().viewport() and event.type() in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick):
            index = self.view().indexAt(event.position().toPoint())
            item = self._model.itemFromIndex(index)
            if item is not None and item.isCheckable():
                if event.type() != QEvent.Type.MouseButtonRelease:
                    item.setCheckState(
                        Qt.CheckState.Unchecked
                        if item.checkState() == Qt.CheckState.Checked
                        else Qt.CheckState.Checked)
                return True        # keep the popup open
        return False

    def _sync_text(self, *_args) -> None:
        selected = self.checked_items()
        self.setItemText(0, ", ".join(selected) if selected
                         else NO_REFERENCE)
        self.setCurrentIndex(0)

    def checked_items(self) -> list[str]:
        """The currently checked net names (raw names, list order)."""
        return [self._model.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(1, self._model.rowCount())
                if self._model.item(row).checkState()
                == Qt.CheckState.Checked]


class NodeEditDialog(QDialog):
    """Edit one power node: voltage / tolerances / dependencies /
    upstream (single-select dropdown) / downstream (multi-select
    checkboxes) / stage override / Do-Not-Test.  Both reference
    dropdowns list ALL power nets of the tree - including the nets
    pruned by the passive-bridge rule (annotated "(pruned)")."""

    def __init__(self, node, tree: PowerTree, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Power Node - {node.name}")
        self.setMinimumWidth(420)
        self._node = node
        self._tree = tree
        # every power net of the tree, minus the node itself (a node
        # can never reference itself); pruned nets stay listed with
        # an explicit "(pruned)" annotation (stored value = raw name)
        choices: list[tuple[str, str]] = []
        for name in sorted(tree.nodes):
            if name == node.name:
                continue
            label = (f"{name} (pruned)"
                     if tree.nodes[name].pruned else name)
            choices.append((name, label))
        form = QFormLayout(self)
        form.setVerticalSpacing(10)
        self.edit_voltage = QLineEdit(node.expected_voltage)
        self.edit_voltage.setPlaceholderText("e.g. 3.3")
        form.addRow("Expected voltage:", self.edit_voltage)
        self.edit_tol_upper = QLineEdit(node.tol_upper)
        self.edit_tol_upper.setPlaceholderText("% or V, optional")
        form.addRow("Upper limit tolerance:", self.edit_tol_upper)
        self.edit_tol_lower = QLineEdit(node.tol_lower)
        self.edit_tol_lower.setPlaceholderText("% or V, optional")
        form.addRow("Lower limit tolerance:", self.edit_tol_lower)
        self.edit_deps = QLineEdit(node.dependencies)
        self.edit_deps.setPlaceholderText(
            "e.g. requires firmware FW1.2, EN signal high (optional)")
        form.addRow("Dependency conditions:", self.edit_deps)
        # node role (user direction): HEAD (primary input, stage 0, no
        # upstream, green) / TAIL (end load, no downstream, dark gray)
        # / MIDDLE (neither) - head and tail are mutually exclusive
        self.chk_head = QCheckBox(
            "Head node (primary power input, stage 0)")
        self.chk_head.setChecked(node.node_type == NODE_PRIMARY)
        form.addRow("", self.chk_head)
        self.chk_tail = QCheckBox("Tail node (end load, no downstream)")
        self.chk_tail.setChecked(node.node_type == NODE_LOAD)
        form.addRow("", self.chk_tail)
        # upstream: SINGLE-select dropdown (one parent node - the
        # upstream stays unique); a primary power input has NO upstream
        self.combo_upstream = QComboBox()
        self.combo_upstream.addItem(NO_REFERENCE, "")
        for name, label in choices:
            self.combo_upstream.addItem(label, name)
        if node.upstream:
            idx = self.combo_upstream.findData(node.upstream[0])
            if idx > 0:
                self.combo_upstream.setCurrentIndex(idx)
        self.combo_upstream.setToolTip(
            "single-select: the upstream power node (all power nets "
            "of the tree are listed)")
        form.addRow("Upstream node reference:", self.combo_upstream)
        # downstream: MULTI-select checkbox dropdown
        self.combo_downstream = MultiSelectCombo(
            choices, [n for n in node.downstream
                      if n != node.name])
        self.combo_downstream.setToolTip(
            "multi-select: the downstream power nodes (all power "
            "nets of the tree are listed)")
        form.addRow("Downstream node reference:", self.combo_downstream)
        self.spin_stage = QSpinBox()
        # stage levels 0..6 (user direction); -1 = auto traversal
        self.spin_stage.setRange(-1, MAX_STAGE)
        self.spin_stage.setValue(
            node.stage if node.stage_override is None
            else node.stage_override)
        self.spin_stage.setSpecialValueText("auto")
        self.spin_stage.setToolTip(
            "-1 = auto (traversal), 0..6 = manual stage override")
        form.addRow("Stage (manual override):", self.spin_stage)
        self.chk_dont_test = QCheckBox("Do Not Test")
        self.chk_dont_test.setChecked(node.dont_test)
        form.addRow("", self.chk_dont_test)
        # mutual exclusion + derived disables (head: no upstream and
        # stage locked to 0; tail: no downstream)
        self.chk_head.toggled.connect(self._sync_role)
        self.chk_tail.toggled.connect(self._sync_role)
        self._sync_role()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _sync_role(self) -> None:
        """Head/tail mutual exclusion with the derived widget states:
        head -> tail disabled + upstream disabled + stage locked 0;
        tail -> head disabled + downstream disabled."""
        head = self.chk_head.isChecked()
        tail = self.chk_tail.isChecked()
        self.chk_tail.setEnabled(not head)
        self.chk_head.setEnabled(not tail)
        self.combo_upstream.setEnabled(not head)
        self.combo_downstream.setEnabled(not tail)
        self.spin_stage.setEnabled(not head)
        if head:
            self.spin_stage.setValue(0)

    def _on_accept(self) -> None:
        node = self._node
        node.expected_voltage = self.edit_voltage.text().strip()
        node.tol_upper = self.edit_tol_upper.text().strip()
        node.tol_lower = self.edit_tol_lower.text().strip()
        node.dependencies = self.edit_deps.text().strip()
        head = self.chk_head.isChecked()
        tail = self.chk_tail.isChecked()
        # upstream: single-select dropdown (one parent node)
        upstream = self.combo_upstream.currentData()
        node.upstream = ([] if head else
                         [upstream] if upstream else [])
        # downstream: multi-select checkbox dropdown
        node.downstream = ([] if tail
                           else self.combo_downstream.checked_items())
        node.dont_test = self.chk_dont_test.isChecked()
        if head:
            node.node_type = NODE_PRIMARY
            node.locked = False
            node.stage_override = 0     # the head node is stage 0
            node.stage = 0
        elif tail:
            node.node_type = NODE_LOAD
            node.locked = True
        else:
            node.node_type = NODE_NORMAL
            node.locked = False
        override = self.spin_stage.value()
        node.stage_override = (0 if head else
                               None if override < 0 else override)
        if node.stage_override is not None:
            node.stage = node.stage_override
        else:
            self._tree.assign_stages([])
        self.accept()


class PowerTreeEditorDialog(QDialog):
    """The power tree draft editor (tree view + node editing + prune
    / restore with the audit log)."""

    def __init__(self, tree: PowerTree, parent=None,
                 bridges: list[dict] | None = None) -> None:
        super().__init__(parent)
        self.tree = tree
        self._bridges = list(bridges or [])
        self.setWindowTitle("Power Tree Editor")
        self.setMinimumSize(640, 520)
        lay = QVBoxLayout(self)
        legend = QLabel(
            "green = primary input | blue = normal node | grey = "
            "load (read-only) / island | dark grey = Do Not Test.  "
            "Double-click a node to edit voltage, tolerances, "
            "dependencies, references and the stage override.")
        legend.setObjectName("muted")
        legend.setWordWrap(True)
        lay.addWidget(legend)
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(
            ["Net / Stage", "Type", "Stage", "Voltage", "Status"])
        self.tree_widget.setColumnWidth(0, 260)
        lay.addWidget(self.tree_widget, 1)
        self.tree_widget.itemDoubleClicked.connect(
            self._on_double_click)

        row = QHBoxLayout()
        btn_prune = QPushButton("Prune passive bridges")
        btn_prune.setToolTip(
            "Two power nets connected only via R/L/C/J/SJ: keep the "
            "load-side net, prune the upstream one (audit logged)")
        btn_prune.clicked.connect(self._prune)
        btn_restore = QPushButton("Restore pruned...")
        btn_restore.setToolTip(
            "Manually restore a pruned node (the audit log stays)")
        btn_restore.clicked.connect(self._restore)
        row.addWidget(btn_prune)
        row.addWidget(btn_restore)
        row.addStretch(1)
        lay.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._reload()

    # ------------------------------------------------------------ render
    def _reload(self) -> None:
        self.tree_widget.clear()
        staged: dict[int, list] = {}
        for node in self.tree.nodes.values():
            staged.setdefault(node.stage if node.stage is not None
                              else 0, []).append(node)
        for stage in sorted(staged):
            top = QTreeWidgetItem(
                [f"Stage {stage}", "", "", "", ""])
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree_widget.addTopLevelItem(top)
            for node in staged[stage]:
                if node.pruned:
                    status = f"pruned ({node.pruned_reason})"
                elif node.dont_test:
                    status = "Do Not Test"
                else:
                    status = "in tree"
                item = QTreeWidgetItem([
                    node.name, node.node_type, str(node.stage),
                    node.expected_voltage or "-", status])
                color = QColor(DONT_TEST_COLOR if node.dont_test
                               else NODE_COLORS.get(node.node_type,
                                                    "#2563eb"))
                item.setForeground(0, QBrush(color))
                item.setData(0, Qt.ItemDataRole.UserRole, node.name)
                top.addChild(item)
            top.setExpanded(True)

    def _node_by_name(self, name: str):
        return self.tree.nodes.get(name)

    # ------------------------------------------------------------ actions
    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        name = item.data(0, Qt.ItemDataRole.UserRole)
        node = self._node_by_name(name) if name else None
        if node is None:
            return
        if node.pruned:
            QMessageBox.information(
                self, "Pruned node",
                "This node is pruned from the tree - restore it "
                "first (Restore pruned...).")
            return
        dlg = NodeEditDialog(node, self.tree, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._reload()

    def _prune(self) -> None:
        """Apply the passive-bridge pruning rule (audit logged)."""
        pruned = self.tree.prune_passive(self._bridges)
        if pruned:
            for entry in pruned:
                QMessageBox.information(
                    self, "Pruned",
                    f"{entry['net']} pruned - load-side "
                    f"{entry['kept']} kept (bridge "
                    f"{entry['refdes']})")
        else:
            QMessageBox.information(
                self, "Prune",
                "no passive-bridge pruning candidates found")
        self._reload()

    def _restore(self) -> None:
        pruned = [n.name for n in self.tree.nodes.values()
                  if n.pruned]
        if not pruned:
            QMessageBox.information(
                self, "Restore", "no pruned nodes")
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getItem(
            self, "Restore pruned node", "net:", pruned, 0, False)
        if ok and name:
            self.tree.restore_pruned(name)
            self._reload()
