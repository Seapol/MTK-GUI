# -*- coding: utf-8 -*-
"""V4.0 Yaml Build page (rightmost classic-shell tab).

Full phase-B1 assembly (interface_spec.md section 31):

* top fixed buttons (item 16): Import from Excel / Export to Excel /
  Edit-Apply (uniform adaptive width; the Build Draft / Release Final
  YAML buttons were removed - redundant YAML entry),
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

from PySide6.QtCore import Qt, Signal
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

    #: (percent 0-100, label) long-task progress for the global status
    #: bar (T6): 0 = task start, 100 = task done, stages in between
    task_progress = Signal(int, str)
    #: (level, message) Event-Log mirror for the main window (T6)
    task_log = Signal(str, str)
    #: navigation: the Parse Nets block asked for the dedicated
    #: Power Tree page (main window switches the tab)
    power_tree_page_requested = Signal()

    def __init__(self, parent=None) -> None:
        """Create the page (model + panes + buttons)."""
        super().__init__(parent)
        self.model = YamlBuildModel()
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # the preview pane is created BEFORE the top button row: its
        # Edit/Apply toggle is reparented into that row (item 16)
        self.yaml_preview = YamlPreviewWidget()

        # --- top fixed button row (item 16: Build Draft / Release Final
        # YAML buttons removed - the redundant YAML entry is gone; the
        # Excel buttons moved to the LEFT of the Edit / Apply toggle,
        # all three share one uniform adaptive width = the longest
        # label among them; resizing only rescales the row) ----------
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_import_excel = QPushButton("Import from Excel")
        self.btn_export_excel = QPushButton("Export to Excel")
        # the Edit/Apply toggle is created by the preview pane (its
        # state + permission gate stay there) and is reparented here
        self._action_buttons = (
            self.btn_import_excel, self.btn_export_excel,
            self.yaml_preview.btn_edit)
        for btn in self._action_buttons:
            btn.setFixedHeight(34)
            buttons.addWidget(btn, 0)   # uniform width, no stretching
        buttons.addStretch(1)
        root.addLayout(buttons)
        self._sync_action_button_widths()
        # standard tooltips (rule 6.1, fixed wording)
        self.btn_import_excel.setToolTip(
            "批量导入流程配置Excel文件，快速回填所有模块参数与状态")
        self.btn_export_excel.setToolTip(
            "导出当前全流程模块配置为标准Excel归档文件")
        # label flips (Edit <-> Apply) re-sync the uniform width
        self.yaml_preview.label_changed.connect(
            lambda _text: self._sync_action_button_widths())

        self.btn_import_excel.clicked.connect(self._import_excel)
        self.btn_export_excel.clicked.connect(self._export_excel)
        # account permissions (defaults = supervisor until set_edit_allowed)
        self._edit_allowed = True

        # --- dual-pane body: block flow (left) | YAML preview (right) --
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.block_flow = BlockFlowWidget()
        self.block_flow.configure_requested.connect(self._open_block)
        self.block_flow.enable_requested.connect(self._set_enabled)
        self.block_flow.enable_all_requested.connect(self._enable_all)
        self.block_flow.disable_all_requested.connect(self._disable_all)
        # the flow diagram lives inside a scroll area: its natural
        # content height (ten cards stacked) must never push the
        # window minimum above the screen - small windows scroll the
        # diagram instead of overflowing it vertically
        from PySide6.QtWidgets import QFrame, QScrollArea
        flow_scroll = QScrollArea()
        flow_scroll.setWidgetResizable(True)
        flow_scroll.setFrameShape(QFrame.Shape.NoFrame)
        flow_scroll.setWidget(self.block_flow)
        splitter.addWidget(flow_scroll)
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
            "12-block workflow: click a block to configure it; "
            "right-click to Enable/Disable. Block 03 is the ONLY "
            "rack-ATE instrument editor (later blocks reference it "
            "read-only); block 11 validates the full sequence and "
            "gates block 12. Disabled blocks are grayed, skipped and "
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
        net = self.model.imported.get("net") or {}
        if module_key == "parse_ict" and net.get("raw"):
            # T8: capture prefill candidates come from the formal
            # Parse Nets result (power nets)
            candidates = self._power_candidates()
        else:
            candidates = None
        params, dialog = self.block_flow.open_dialog(
            module_key, self.model.get_params(module_key), self,
            power_candidates=candidates,
            log_sink=self.task_log.emit,
            progress_sink=self.task_progress.emit,
            net_source=(net.get("raw", ""),
                        Path(net.get("file", "")).name)
            if module_key == "parse_ict" else None,
            panel_state={
                "net_rules": self.model.net_classification_rules,
                "clock_overrides": {
                    row["net"]: (row["channel"] or "Not Test")
                    for row in self.model.se_clock_allocation
                    if row["status"] == "Not Test" or row["channel"]},
                "gpio_overrides": {
                    row["net"]: (row["channel"] or "Not Test")
                    for row in self.model.gpio_allocation
                    if row["status"] == "Not Test" or row["channel"]},
                "spf_nets": self.model.imported.get("spf_nets", set()),
                "risk_thresholds": dict(
                    (self.model.path_risk or {}).get("thresholds")
                    or {}),
                "risk_scores": dict(
                    (self.model.path_risk or {}).get("scores") or {}),
            } if module_key == "parse_ict" else None)
        if params is None:
            return
        self.model.set_params(module_key, params)
        if module_key == "design_input" and dialog is not None \
                and dialog.panel is not None:
            # keep the loaded NET bytes for the Parse Nets module (T8)
            panel = dialog.panel
            self.model.imported["net"] = {
                "file": panel.net_path,
                "raw": panel.net_text,
            }
        if module_key == "parse_ict" and dialog is not None \
                and dialog.nets_panel is not None \
                and dialog.nets_panel.result is not None:
            # the parse result is the single data source for the
            # Channel Allocation tables (T10)
            result = dialog.nets_panel.result
            self.model.imported["testable_nets"] = {
                rec.name: {"category": cat,
                           "members": list(rec.members),
                           **({"auto_generated": True}
                              if dialog.nets_panel._auto_generated.get(
                                  rec.name) else {})}
                for cat, records in
                (("Power", result.power), ("Clock", result.clock),
                 ("GPIO", result.gpio))
                for rec in records
            }
            # item 24: rules / allocations persistence (the power tree
            # draft is owned by the dedicated Power Tree page)
            nets_panel = dialog.nets_panel
            self.model.net_classification_rules = \
                dict(nets_panel.net_rules)
            self.model.se_clock_allocation = \
                nets_panel._alloc_rows(nets_panel.clock_table)
            self.model.gpio_allocation = \
                nets_panel._alloc_rows(nets_panel.gpio_table)
            # test path risk: thresholds + per-net advisory scores
            self.model.path_risk = {
                "thresholds": dict(nets_panel.risk_thresholds),
                "scores": dict(nets_panel.risk_scores),
            }
        # navigation: the panel's "Open Power Tree Editor" button
        # closes the dialog and switches to the dedicated page
        if module_key == "parse_ict" and dialog is not None \
                and getattr(dialog, "requested_page", None) \
                == "power_tree":
            self.power_tree_page_requested.emit()
        errors = self.model.validate_module(module_key)
        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
        self._after_model_change()

    def _power_candidates(self) -> list[str]:
        """Candidate power nets for the block-03 capture prefill:
        power nets from the Parse Nets result (T8) when available,
        else the legacy imported-netlist names."""
        testable = self.model.imported.get("testable_nets") or {}
        if testable:
            return [name for name, info in testable.items()
                    if info.get("category") == "Power"]
        return list((self.model.imported.get("netlist") or {}).get(
            "nets") or {})

    def _set_enabled(self, module_key: str, enabled: bool) -> None:
        """Enable / disable one module (parameters retained; disabled
        modules leave the effective YAML and flow validation)."""
        self.model.set_enabled(module_key, enabled)
        self._after_model_change()

    def _enable_all(self) -> None:
        """Batch Enable All (right-click menu): every module joins
        the flow, YAML generation and validation."""
        self.model.enable_all()
        self._after_model_change()

    def _disable_all(self) -> None:
        """Batch Disable All (right-click menu): no module takes part
        in the flow compilation; parameters are silently retained."""
        self.model.disable_all()
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

    # ------------------------------------------------- long-task helpers
    def _task(self, percent: int, label: str) -> None:
        """Emit a long-task progress step to the global status bar."""
        self.task_progress.emit(percent, label)

    def _tlog(self, level: str, message: str) -> None:
        """Mirror one Event-Log line (level, message) to the window."""
        self.task_log.emit(level, message)

    # ------------------------------------------------------- Excel I/O
    def set_edit_allowed(self, allowed: bool) -> None:
        """Operator accounts cannot edit the YAML config (T5): the
        whole action row (Excel import / export) and the preview
        Edit/Apply toggle follow the permission; a pending edit
        session is rolled back to READ_ONLY."""
        self._edit_allowed = bool(allowed)
        for btn in self._action_buttons:
            btn.setEnabled(self._edit_allowed)
        self.yaml_preview.set_edit_allowed(self._edit_allowed)

    def _sync_action_button_widths(self) -> None:
        """Item 16: the three top toolbar buttons (Import from Excel /
        Export to Excel / Edit-Apply) share one uniform adaptive width
        = the widest label among them (re-synced whenever the toggle
        label flips Edit <-> Apply).  Neat, aligned, equal in size."""
        if not hasattr(self, "_action_buttons"):
            return
        widest = max(btn.sizeHint().width()
                     for btn in self._action_buttons)
        width = widest + 8   # small symmetric margin
        for btn in self._action_buttons:
            btn.setFixedWidth(width)

    def _export_excel(self) -> None:
        """Export all module parameters / thresholds / sequence /
        enable state / remarks to an .xlsx workbook."""
        if not self._edit_allowed:
            QMessageBox.information(
                self, "Permission",
                "Operator account cannot modify the YAML configuration.")
            return
        default = (f"YamlBuild_{self.model.project_key()}.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", default, "Excel (*.xlsx)")
        if not path:
            return
        try:
            rows = export_to_excel(self.model, path)
        except OSError as exc:
            self._tlog("ERROR", f"Excel export failed: {exc}")
            QMessageBox.critical(self, "Export Failed", str(exc))
            return
        # short task: one Event-Log line only (no progress machinery)
        self._tlog("INFO", f"Excel export done: {rows} rows -> "
                           f"{Path(path).name}")
        QMessageBox.information(
            self, "Export to Excel",
            f"Exported {rows} rows to {path}")

    def _import_excel(self) -> None:
        """Import a workbook with full-workbook validation (invalid
        rows abort the import with the error list).  Long-task aware
        (T6): global progress + Event-Log step detail, failures with
        the exact row reasons."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import from Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        self._task(0, "import: reading workbook")
        self._tlog("INFO", f"Excel import started: {Path(path).name}")
        self._task(40, "import: validating + applying rows")
        report = import_from_excel(self.model, path)
        if report.errors:
            # precise failure reasons (first rows), no silent fail
            for err in report.errors[:5]:
                self._tlog("ERROR", f"Excel import rejected: {err}")
            self._task(0, "import: idle")
            QMessageBox.warning(
                self, "Import Rejected",
                "The workbook was not applied:\n"
                + "\n".join(report.errors[:20])
                + (f"\n... and {len(report.errors) - 20} more"
                   if len(report.errors) > 20 else ""))
            return
        self._after_model_change()      # parse -> project view refresh
        self._task(100, "import: done")
        self._tlog("INFO", f"Excel import done: {report.imported} "
                           f"parameters applied from {Path(path).name}")
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
            for err in errors[:5]:
                self._tlog("ERROR", f"{kind} blocked by validation: "
                                    f"{err}")
            QMessageBox.warning(
                self, f"Cannot build {kind}",
                "Fix the validation errors first:\n"
                + "\n".join(errors[:15]))
            return
        # B1 closure #4: non-silent Project Part# reminder right before
        # the plan lands on disk (advisory - the kept required-field
        # validation has already passed here)
        part = str((self.model.get_params("design_input") or {})
                   .get("part_number") or "").strip()
        if not part:
            self._tlog("WARNING", "Auto fetch Project Part# "
                                  "unavailable, please fill manually")
            QMessageBox.information(
                self, "Project Part# Missing",
                "Board Project Part# is empty. It cannot be "
                "auto-extracted - please fill it manually.")
        self._task(0, f"{kind}: publishing")
        self._tlog("INFO", f"{kind} publish started "
                           f"(project {self.model.project_key()})")
        self._task(50, f"{kind}: writing YAML")
        try:
            name = plan_filename(self.model, kind)
            path = publish(self.model, kind, PLANS_DIR)
        except (ValueError, OSError) as exc:
            self._tlog("ERROR", f"{kind} publish failed: {exc}")
            self._task(0, "publish: idle")
            QMessageBox.critical(self, f"{kind.capitalize()} Failed",
                                 str(exc))
            return
        archived = archive_copy(path, Path.cwd(),
                                self.model.project_key())
        self._after_model_change()          # refresh the project view
        self._task(100, f"{kind}: done")
        self._tlog("INFO", f"{kind} publish done: {Path(path).name} "
                           f"(archive: {Path(archived).name})")
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
