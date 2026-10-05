# -*- coding: utf-8 -*-
"""V4.0 Yaml Build page (rightmost classic-shell tab).

Full phase-B1 assembly (interface_spec.md section 31):

* top fixed buttons: Import from Excel / Export to Excel / Build
  Draft YAML / Release Final YAML,
* left: the ten fixed workflow blocks (click = dedicated config
  dialog, right click = Enable / Disable; disabled blocks gray out,
  are skipped and are not written into the effective YAML),
* right: live YAML preview - two-way synced with the block diagram
  through the model, with syntax / sequence / parameter validation
  and red error-line markers,
* Draft / Final publishing with the fixed Plan_ naming, version
  compare and archiving,
* model state persistence per tenant project (restart-safe).

Pure increment: nothing outside this page (and its subpackage) is
touched.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.block_flow import BlockFlowWidget
from mtkgui.gui.yamlbuild.excel_io import export_to_excel, \
    import_from_excel
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.preview import YamlPreviewWidget
from mtkgui.gui.yamlbuild.publish import (
    archive_copy,
    compare_plans,
    plan_filename,
    publish,
)
from mtkgui.gui.yamlbuild.stages import STAGE_KEYS
from mtkgui.gui.yamlbuild.store import load_project_state, \
    save_project_state
from mtkgui.version_info import get_version_info

#: default output directory for published plan files (created on use)
PLANS_DIR = "config/plans"


class YamlBuildPage(QWidget):
    """Yaml Build tab: block-diagram workflow + live YAML preview."""

    def __init__(self, parent=None) -> None:
        """Create the page (model + panes + buttons)."""
        super().__init__(parent)
        self.model = YamlBuildModel()
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- top fixed button row (rule 6.3: uniform horizontal
        # distribution at a fixed height; resizing only rescales the
        # whole row - buttons never wrap, overlap or wander) ---------
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_import_excel = QPushButton("Import from Excel")
        self.btn_export_excel = QPushButton("Export to Excel")
        self.btn_build_draft = QPushButton("Build Draft YAML")
        self.btn_release_final = QPushButton("Release Final YAML")
        self._action_buttons = (
            self.btn_import_excel, self.btn_export_excel,
            self.btn_build_draft, self.btn_release_final)
        for btn in self._action_buttons:
            btn.setFixedHeight(34)
            btn.setMinimumWidth(170)
            buttons.addWidget(btn, 1)   # equal stretch -> uniform row
        root.addLayout(buttons)

        self.btn_import_excel.clicked.connect(self._import_excel)
        self.btn_export_excel.clicked.connect(self._export_excel)
        self.btn_build_draft.clicked.connect(
            lambda: self._publish("draft"))
        self.btn_release_final.clicked.connect(
            lambda: self._publish("final"))

        # --- dual-pane body: block flow (left) | YAML preview (right) --
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.block_flow = BlockFlowWidget()
        self.block_flow.configure_requested.connect(self._open_block)
        self.block_flow.enable_requested.connect(self._set_enabled)
        splitter.addWidget(self.block_flow)
        self.yaml_preview = YamlPreviewWidget()
        self.yaml_preview.bind_model(self.model)
        # YAML -> diagram: a valid hand edit refreshes the block
        # cards (enable states) and persists; the preview text itself
        # keeps the operator's version while editing
        self.yaml_preview.edits_applied.connect(self._on_preview_edited)
        splitter.addWidget(self.yaml_preview)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([600, 400])
        root.addWidget(splitter, 1)
        self.hint = QLabel(
            "Click a block to configure it; right-click to "
            "Enable/Disable. Disabled blocks are grayed, skipped and "
            "kept out of the effective YAML (parameters retained).")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        # restore the persisted state of the current project, then
        # paint both panes from the model
        self._load_persisted()
        self.refresh_all()

    # ------------------------------------------------------ model -> UI
    def refresh_all(self) -> None:
        """Repaint both panes from the model (single broadcast point;
        keeps the diagram <-> YAML sync loop-free)."""
        for key in STAGE_KEYS:
            self.block_flow.set_state(key, self.model.is_enabled(key))
        self.yaml_preview.set_model_text(self.model)

    def _load_persisted(self) -> None:
        """Restore this project's persisted state (restart-safe)."""
        state = load_project_state(self.model.project_key())
        if state is not None:
            self.model.apply_state(state)

    def _persist(self) -> None:
        """Persist the model state (silent on failure - the GUI must
        never break because persistence did)."""
        save_project_state(self.model.project_key(),
                           self.model.to_dict())

    # ------------------------------------------------------ UI -> model
    def _open_block(self, module_key: str) -> None:
        """Open the dedicated config dialog of one module and store
        the validated result (independent save + validation)."""
        params = self.block_flow.open_dialog(
            module_key, self.model.get_params(module_key), self)
        if params is None:
            return
        self.model.set_params(module_key, params)
        errors = self.model.validate_module(module_key)
        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
        self._after_model_change()

    def _set_enabled(self, module_key: str, enabled: bool) -> None:
        """Enable / disable one module (parameters retained; disabled
        modules leave the effective YAML and flow validation)."""
        self.model.set_enabled(module_key, enabled)
        self._after_model_change()

    def _after_model_change(self) -> None:
        """Single broadcast point after every model mutation."""
        self._persist()
        self.refresh_all()

    def _on_preview_edited(self) -> None:
        """Slot for valid hand edits from the YAML preview: refresh
        the block cards (enable states) and persist.  The preview
        text is NOT repainted here - the operator's text stays until
        edit mode is left."""
        self._persist()
        for key in STAGE_KEYS:
            self.block_flow.set_state(key, self.model.is_enabled(key))

    # ------------------------------------------------------- Excel I/O
    def _export_excel(self) -> None:
        """Export all module parameters / thresholds / sequence /
        enable state / remarks to an .xlsx workbook."""
        default = (f"YamlBuild_{self.model.project_key()}.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", default, "Excel (*.xlsx)")
        if not path:
            return
        try:
            rows = export_to_excel(self.model, path)
        except OSError as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return
        QMessageBox.information(
            self, "Export to Excel",
            f"Exported {rows} rows to {path}")

    def _import_excel(self) -> None:
        """Import a workbook with full-workbook validation (invalid
        rows abort the import with the error list)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import from Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        report = import_from_excel(self.model, path)
        if report.errors:
            QMessageBox.warning(
                self, "Import Rejected",
                "The workbook was not applied:\n"
                + "\n".join(report.errors[:20])
                + (f"\n... and {len(report.errors) - 20} more"
                   if len(report.errors) > 20 else ""))
            return
        self._after_model_change()
        QMessageBox.information(
            self, "Import from Excel",
            f"Applied {report.imported} parameters from {path}")

    # ------------------------------------------------------- publishing
    def _publish(self, kind: str) -> None:
        """Build Draft / Release Final YAML - fully automatic (V4.0
        rule 5.4: the file name is composed from the Design Input
        Core ID / Project Part #, no manual input).

        The model must be valid (all enabled modules).  The file is
        written to the standard plans directory, archived under the
        project key, and the result dialog shows all paths.
        """
        errors = self.model.validate_all()
        if errors:
            QMessageBox.warning(
                self, f"Cannot build {kind}",
                "Fix the validation errors first:\n"
                + "\n".join(errors[:15]))
            return
        try:
            name = plan_filename(self.model, kind)
            path = publish(self.model, kind, PLANS_DIR)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, f"{kind.capitalize()} Failed",
                                 str(exc))
            return
        archived = archive_copy(path, Path.cwd(),
                                self.model.project_key())
        self._after_model_change()
        QMessageBox.information(
            self, f"{kind.capitalize()} YAML published",
            f"File: {path}\n"
            f"Archive copy: {archived}\n"
            f"Plan version: {self.model.plan_version}\n"
            f"Build version: {get_version_info().suffix()}")

    def compare_with(self, other_path: str) -> str:
        """Unified diff of the last published file against another
        plan (version compare / archive traceability).

        Args:
            other_path: The plan file to compare with.

        Returns:
            Diff text.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "Compare with plan", "", "YAML (*.yaml *.yml)")
        if not path:
            return ""
        return compare_plans(other_path, path)

    # ---------------------------------------------------- test helpers
    def state(self) -> dict:
        """Return the persisted model state (diagnostics / tests).

        Returns:
            Model state dict.
        """
        return self.model.to_dict()

    def dump_yaml(self) -> str:
        """Return the current effective YAML text (tests / export).

        Returns:
            YAML text.
        """
        return self.model.to_effective_yaml()
