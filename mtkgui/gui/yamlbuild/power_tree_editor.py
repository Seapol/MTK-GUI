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
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
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
    NODE_LOAD,
    NODE_PRIMARY,
    PowerTree,
)

NODE_COLORS = {
    "primary": "#16a34a",
    "normal": "#2563eb",
    "load": "#9ca3af",
    "island": "#9ca3af",
}
DONT_TEST_COLOR = "#4b5563"


class NodeEditDialog(QDialog):
    """Edit one power node: voltage / tolerances / dependencies /
    upstream / downstream / stage override / Do-Not-Test."""

    def __init__(self, node, tree: PowerTree, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit Power Node - {node.name}")
        self.setMinimumWidth(420)
        self._node = node
        self._tree = tree
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
        self.edit_upstream = QLineEdit(",".join(node.upstream))
        self.edit_upstream.setPlaceholderText(
            "comma separated upstream net names (optional)")
        form.addRow("Upstream node reference:", self.edit_upstream)
        self.edit_downstream = QLineEdit(",".join(node.downstream))
        self.edit_downstream.setPlaceholderText(
            "comma separated downstream net names (optional)")
        form.addRow("Downstream node reference:", self.edit_downstream)
        self.spin_stage = QSpinBox()
        self.spin_stage.setRange(-1, 99)
        self.spin_stage.setValue(
            node.stage if node.stage_override is None
            else node.stage_override)
        self.spin_stage.setSpecialValueText("auto")
        self.spin_stage.setToolTip(
            "-1 = auto (traversal), 0..N = manual stage override")
        form.addRow("Stage (manual override):", self.spin_stage)
        self.chk_dont_test = QCheckBox("Do Not Test")
        self.chk_dont_test.setChecked(node.dont_test)
        form.addRow("", self.chk_dont_test)
        if node.node_type == NODE_LOAD or node.locked:
            hint = QLabel("Load node (end node) - read-only.")
            hint.setObjectName("muted")
            form.addRow("", hint)
            for widget in (self.edit_voltage, self.edit_tol_upper,
                           self.edit_tol_lower, self.edit_deps,
                           self.chk_dont_test):
                widget.setEnabled(False)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _on_accept(self) -> None:
        if self._node.node_type == NODE_LOAD or self._node.locked:
            QMessageBox.information(
                self, "Read-only",
                "Load nodes are read-only (end of the power tree).")
            self.reject()
            return
        node = self._node
        node.expected_voltage = self.edit_voltage.text().strip()
        node.tol_upper = self.edit_tol_upper.text().strip()
        node.tol_lower = self.edit_tol_lower.text().strip()
        node.dependencies = self.edit_deps.text().strip()
        node.upstream = [x.strip() for x in
                         self.edit_upstream.text().split(",")
                         if x.strip()]
        node.downstream = [x.strip() for x in
                           self.edit_downstream.text().split(",")
                           if x.strip()]
        node.dont_test = self.chk_dont_test.isChecked()
        override = self.spin_stage.value()
        node.stage_override = None if override < 0 else override
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
