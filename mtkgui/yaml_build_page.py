# -*- coding: utf-8 -*-
"""V4.0 Yaml Build page (rightmost classic-shell tab).

Phase A mounting skeleton per docs/interface_spec.md section 31:

* top fixed button row: Import from Excel / Export to Excel /
  Build Draft YAML / Release Final YAML,
* fixed irreversible workflow stage list (left pane),
* live YAML preview placeholder (right pane).

The block-diagram interaction, per-block config dialogs, right-click
Enable/Disable, diagram<->YAML two-way sync, Excel exchange and the
Draft/Final publishing are delivered by phase B1 on the
``feature/yaml-build-page`` branch; the buttons report that state
until then.  This shell changes nothing in the existing pages (pure
increment).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# Fixed, irreversible workflow sequence (interface_spec.md section 31).
WORKFLOW_STAGES = (
    "Design Input",
    "Configure Power On/Off DUT",
    "Parse nets for ICT",
    "Build Impedance/Voltage/Power rails up sequence",
    "Build Clocks",
    "Build GPIOs",
    "Configure Programmer/Debugger",
    "Configure Peripherials",
    "Parse Func/Interface for FCT",
    "Build Func/Interface for FCT",
)

_B1_MSG = ("This function ships with V4.0 phase B1 "
           "(feature/yaml-build-page).")


class YamlBuildPage(QWidget):
    """Yaml Build tab: block-diagram workflow + live YAML preview."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- top fixed button row --------------------------------------
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_import_excel = QPushButton("Import from Excel")
        self.btn_export_excel = QPushButton("Export to Excel")
        self.btn_build_draft = QPushButton("Build Draft YAML")
        self.btn_release_final = QPushButton("Release Final YAML")
        for btn in (self.btn_import_excel, self.btn_export_excel,
                    self.btn_build_draft, self.btn_release_final):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.btn_import_excel.clicked.connect(
            lambda: self._not_yet("Import from Excel"))
        self.btn_export_excel.clicked.connect(
            lambda: self._not_yet("Export to Excel"))
        self.btn_build_draft.clicked.connect(
            lambda: self._not_yet("Build Draft YAML"))
        self.btn_release_final.clicked.connect(
            lambda: self._not_yet("Release Final YAML"))

        # --- dual-pane body: block diagram (left) | YAML preview (right)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.stage_list = QListWidget()
        for stage in WORKFLOW_STAGES:
            self.stage_list.addItem(stage)
        self.stage_list.setToolTip(
            "Fixed irreversible workflow sequence; click a block to "
            "open its configuration (phase B1).")
        splitter.addWidget(self.stage_list)

        self.yaml_preview = QPlainTextEdit()
        self.yaml_preview.setReadOnly(True)
        self.yaml_preview.setPlaceholderText(
            "Live YAML preview (two-way synced with the block diagram, "
            "phase B1)")
        splitter.addWidget(self.yaml_preview)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([600, 400])
        root.addWidget(splitter, 1)

        hint = QLabel(
            "V4.0 Yaml Build - block configuration, right-click "
            "Enable/Disable and Excel exchange arrive in phase B1.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        root.addWidget(hint)

    # ---------------------------------------------------------- helpers
    def _not_yet(self, feature: str) -> None:
        """Report a phase-B1 feature to the operator.

        Args:
            feature: Feature name from the clicked button.
        """
        QMessageBox.information(self, feature, _B1_MSG)
