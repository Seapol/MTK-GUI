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
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.block_flow import (
    MARK_CHECK,
    MARK_NONE,
    MARK_STAR,
    BlockFlowWidget,
)
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
from mtkgui.gui.yamlbuild.stages import (
    DISPLAY_ICT_WORKFLOW,
    STAGE_KEYS,
)
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
    #: navigation: the merged "Build ICT Test Work Flow Sequence"
    #: card asked for the Test Work Flow page (main window switches
    #: the tab and focuses the ICT Test Cases table)
    test_workflow_requested = Signal()
    #: a valid Apply from the YAML preview committed into the model -
    #: the main window offers the file save (overwrite current yaml /
    #: save to a new yaml file)
    yaml_apply_committed = Signal()
    #: the block-04 sequence dialog was accepted - carries the ICT
    #: test rows (step tuples, "test" kind only); the main window
    #: merges the standard operations on the Test Work Flow page and
    #: offers the YAML save
    ict_sequence_ready = Signal(list)
    #: P3-B5: the block-07 FCT config was accepted - carries the
    #: generated FCT case dicts (name/kind/enable/wait_ms/timeout_ms/
    #: op_params.fct_step) for the Test Work Flow page's FCT table
    fct_sequence_ready = Signal(list)

    def __init__(self, parent=None) -> None:
        """Create the page (model + panes + buttons)."""
        super().__init__(parent)
        self.model = YamlBuildModel()
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # the preview pane is created BEFORE the top button row: its
        # Apply button is reparented into that row (item 16; user
        # direction: no Edit mode - the editor is directly editable)
        self.yaml_preview = YamlPreviewWidget()

        # --- top fixed button row (item 16: Build Draft / Release Final
        # YAML buttons removed - the redundant YAML entry is gone; the
        # Excel buttons sit LEFT of the Apply button, all three
        # share one uniform adaptive width = the longest label among
        # them; the row lives ABOVE the YAML Preview pane (user
        # direction)) ----------
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_import_excel = QPushButton("Import from Excel")
        self.btn_export_excel = QPushButton("Export to Excel")
        # the Apply button is created by the preview pane (its
        # validation + permission gate stay there) and is reparented
        self._action_buttons = (
            self.btn_import_excel, self.btn_export_excel,
            self.yaml_preview.btn_apply)
        for btn in self._action_buttons:
            btn.setFixedHeight(34)
            buttons.addWidget(btn, 0)   # uniform width, no stretching
        buttons.addStretch(1)
        self._sync_action_button_widths()
        # standard tooltips (rule 6.1, fixed wording)
        self.btn_import_excel.setToolTip(
            "批量导入流程配置Excel文件，快速回填所有模块参数与状态")
        self.btn_export_excel.setToolTip(
            "导出当前全流程模块配置为标准Excel归档文件")

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
        # valid Apply committed -> the main window offers the file save
        self.yaml_preview.edits_applied.connect(
            self.yaml_apply_committed)
        # right pane: the action button row sits directly ABOVE the
        # YAML Preview (user direction)
        from PySide6.QtWidgets import QWidget as _QWidget
        right = _QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)
        right_lay.addLayout(buttons)
        right_lay.addWidget(self.yaml_preview)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([700, 300])   # default 7 : 3 (user direction)
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
            self.block_flow.set_module_mark(
                key, self.model.marks.get(key, MARK_NONE))
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
    def _emit_fct_sequence(self, params: dict):
        """P3-B5: block 07 params -> FCT work-flow case dicts.

        Parses ``fct_test_config_yaml``, builds the ordered FctStep list
        (console commands + Wi-Fi + Bluetooth) and maps it to the
        project-YAML case shape; a final "FCT done" operator dialog
        closes a non-empty sequence.

        A project may contain ICT only, FCT only, or both - an FCT
        config with every tab disabled is valid and yields zero cases.

        Returns ``(cases, errors)``: ``errors`` is an empty list on
        success (cases may be empty for an ICT-only project); on a parse
        or validation failure it carries the messages and cases is None.
        """
        import yaml as _yaml
        from mtkgui.engine.fct_test_config import FctTestConfig
        from mtkgui.gui.yamlbuild.fct_build import (
            FctSequence,
            to_project_fct_cases,
        )
        text = str((params or {}).get("fct_test_config_yaml", "") or "")
        if not text.strip():
            # nothing configured -> ICT-only project is fine
            return [], []
        try:
            node = _yaml.safe_load(text) or {}
            cfg = FctTestConfig.from_dict(
                node.get("fct_test_config") or {})
        except _yaml.YAMLError as exc:
            return None, [f"FCT config parse failed: {exc}"]
        errors = cfg.validate()
        if errors:
            return None, list(errors)
        from mtkgui.engine.fct_test_config import build_fct_steps
        body = build_fct_steps(cfg)
        if not body:
            # all FCT tabs disabled -> ICT-only project, zero cases
            return [], []
        from mtkgui.engine.fct_test_config import wrap_fct_setup
        steps = wrap_fct_setup(cfg, body)
        seq = FctSequence(name="FCT Test Work Flow", steps=steps)
        cases = to_project_fct_cases(seq)
        # every generated case carries its full step marker so the
        # runner routes the row through fct_exec
        for case, step in zip(cases, steps):
            case.setdefault("op_params", {})["fct_step"] = step.to_dict()
        self._tlog("INFO", f"FCT sequence generated: {len(cases)} cases")
        return cases, []

    def _open_block(self, module_key: str) -> None:
        """Open the dedicated config dialog of one module and store
        the validated result (independent save + validation)."""
        net = self.model.imported.get("net") or {}
        if module_key == "ict_workflow":
            # merged 04/05/06 node: open the ICT Test Work Flow
            # Sequence builder (user direction) - one test per row,
            # impedance -> power rails (voltage) -> clock, manual
            # adjustment; on OK the main window adds the standard
            # operations and offers the YAML save
            from mtkgui.gui.yamlbuild.ict_sequence import (
                IctWorkFlowSequenceDialog,
            )
            dlg = IctWorkFlowSequenceDialog(
                # user rule: nets WITHOUT an allocated instrument
                # channel are auto Do-Not-Test - only allocated nets
                # reach the Test Work Flow sequence builder
                self.model.allocated_testable,
                parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.ict_sequence_ready.emit(dlg.result_tests())
                # configured (OK) -> star mark (user direction)
                self._set_mark(DISPLAY_ICT_WORKFLOW, MARK_STAR)
            return
        params, dialog = self.block_flow.open_dialog(
            module_key, self.model.get_params(module_key), self,
            log_sink=self.task_log.emit,
            progress_sink=self.task_progress.emit,
            net_source=(net.get("raw", ""),
                        Path(net.get("file", "")).name)
            if module_key == "parse_ict" else None,
            panel_state={
                "net_rules": self.model.net_classification_rules,
                "power_dnt": {
                    ln.strip() for ln in
                    (self.model.get_params("parse_ict") or {})
                    .get("power_dont_test", "").splitlines()
                    if ln.strip()},
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
        if module_key == "fct_build":
            # P3-B5: block accepted -> generate the FCT work-flow cases
            # from the configured fct_test_config. Errors are shown
            # explicitly (no silent ignore); an all-disabled FCT is a
            # valid ICT-only project and still offers the YAML save.
            cases, fct_errors = self._emit_fct_sequence(params)
            if fct_errors:
                self._tlog("ERROR", "FCT config invalid: "
                                    + "; ".join(fct_errors))
                QMessageBox.warning(
                    self, "Build FCT Test Work Flow",
                    "The FCT configuration is invalid - fix the "
                    "following before applying:\n\n"
                    + "\n".join(fct_errors[:15]))
                return
            self.fct_sequence_ready.emit(cases)
        if module_key == "validate_sequence":
            # block 09: on OK run the FULL sequence validation - every
            # marked module that passes gets a check; a failure keeps
            # the stars (edited but not validated, user direction)
            errors = self.model.validate_all()
            if errors:
                self._tlog("ERROR", f"Validate Full Test Sequence: "
                                    f"{len(errors)} error(s)")
                QMessageBox.warning(
                    self, "Validate Full Test Sequence",
                    "Validation FAILED - the stars are kept "
                    "(edited but not validated):\n"
                    + "\n".join(errors[:15]))
            else:
                for key in STAGE_KEYS:
                    if self.model.marks.get(key) == MARK_STAR:
                        self._set_mark(key, MARK_CHECK)
                self._tlog("INFO", "Validate Full Test Sequence: "
                                   "PASS - all edited modules checked")
        else:
            # configured (OK) -> star mark (user direction)
            self._set_mark(module_key, MARK_STAR)
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
            # Channel Allocation tables (T10); "Filtered" overrides
            # keep a net out, restored filtered nets join a category
            result = dialog.nets_panel.result
            overrides = dialog.nets_panel._category_overrides
            testable = {}
            for cat, records in (("Power", result.power),
                                 ("Clock", result.clock),
                                 ("GPIO", result.gpio)):
                for rec in records:
                    if overrides.get(rec.name) == "Filtered":
                        continue        # moved to Filtered Nets
                    testable[rec.name] = {
                        "category": overrides.get(rec.name, cat),
                        "members": list(rec.members),
                        **({"auto_generated": True}
                           if dialog.nets_panel._auto_generated.get(
                               rec.name) else {}),
                        **({"category_override": True}
                           if rec.name in overrides else {})}
            for rec in result.filtered_records:
                cat = overrides.get(rec.name)
                if cat and cat != "Filtered":
                    members = [t for t in rec.members
                               if "." in t
                               or t.upper().startswith("TP")]
                    testable[rec.name] = {
                        "category": cat,
                        "members": members or list(rec.members),
                        "category_override": True}
            self.model.imported["testable_nets"] = testable
            # item 24: rules persistence (the channel assignment lives
            # in the Channel Allocation page only; the power tree draft
            # is owned by the dedicated Power Tree page)
            nets_panel = dialog.nets_panel
            self.model.net_classification_rules = \
                dict(nets_panel.net_rules)
            # Do-Not-Test flags persist into the parse_ict params
            self.model.set_params("parse_ict", {
                "power_dont_test":
                    "\n".join(nets_panel.power_dnt_nets())})
            # test path risk: thresholds + per-net advisory scores
            self.model.path_risk = {
                "thresholds": dict(nets_panel.risk_thresholds),
                "scores": dict(nets_panel.risk_scores),
            }
        errors = self.model.validate_module(module_key)
        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
        self._after_model_change()

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

    def _set_mark(self, module_key: str, mark: str) -> None:
        """Set one module's card mark (star = edited / check =
        validated), persisted with the model (restart-safe)."""
        self.model.set_mark(module_key, mark)
        self.block_flow.set_module_mark(module_key, mark)
        self._persist()

    def apply_power_rails(self, seq: dict) -> None:
        """Sync the Test Work Flow page's power-rails capture config
        into the model (user question: configured power rails MUST
        land in the YAML): stored as its own section AND mirrored into
        the rails module's capture parameters; the preview refreshes."""
        self.model.set_power_rails(seq)
        self._persist()
        self.yaml_preview.set_model_text(self.model)

    def _on_preview_edited(self) -> None:
        """Slot for valid hand edits from the YAML preview: refresh
        the block cards (enable states) and persist.  The preview
        text is NOT repainted here - the operator's text stays until
        the next unmodified sync."""
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
        Apply button follow the permission; the editor stays
        read-only for operators."""
        self._edit_allowed = bool(allowed)
        for btn in self._action_buttons:
            btn.setEnabled(self._edit_allowed)
        self.yaml_preview.set_edit_allowed(self._edit_allowed)

    def _sync_action_button_widths(self) -> None:
        """Item 16: the three top toolbar buttons (Import from Excel /
        Export to Excel / Apply) share one uniform adaptive width
        = the widest label among them.  Neat, aligned, equal in
        size."""
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
