# -*- coding: utf-8 -*-
"""v2-17: node 07 "Apply & Save Yaml" panel.

A read-only preview of the exact Draft document plus the two fixed
save actions.  All file naming / serialization / archiving is reused
from :mod:`mtkgui.gui.yamlbuild.publish` - this module never
re-implements it.

Buttons (fixed order): ``Apply & Save Yaml`` | ``Save as new yaml``.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild import steps_v2
from mtkgui.style import gui_theme_color
from mtkgui.gui.yamlbuild.mtk_sheet_writer import (
    default_mtk_sheet_name,
    export_mtk_sheet,
)
from mtkgui.gui.yamlbuild.publish import (
    archive_copy,
    build_plan_document,
    plan_filename,
    publish,
)

#: shown instead of the file name while Design Input is incomplete
NO_TARGET = "…"


def _work_dir() -> Path:
    """The project work directory (indirected for tests)."""
    from mtkgui.app_paths import work_dir
    return work_dir()


def default_out_dir(model) -> Path:
    """The project folder a Draft is written into (Core ID tree)."""
    design = model.get_params("design_input") or {}
    core = str(design.get("product_id") or "").strip()
    if not core:
        raise ValueError(
            "Design Input must provide the Core ID before saving")
    return steps_v2.ensure_project_tree(core)


def apply_and_save(model, out_dir: str | Path | None = None) -> tuple[Path, Path]:
    """Publish the Draft into the project folder + archive a copy.

    Returns:
        ``(written_path, archive_path)``.
    """
    target_dir = Path(out_dir) if out_dir is not None else default_out_dir(model)
    path = publish(model, "draft", target_dir)
    archive = archive_copy(path, _work_dir(), model.project_key())
    return path, archive


def save_as(model, path: str | Path) -> tuple[Path, Path]:
    """Write the same Draft document to a chosen path + archive it."""
    target = Path(path)
    if target.suffix.lower() not in (".yaml", ".yml"):
        target = target.with_suffix(".yaml")
    target.parent.mkdir(parents=True, exist_ok=True)
    document = build_plan_document(model, "draft")
    target.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    archive = archive_copy(target, _work_dir(), model.project_key())
    return target, archive


class ApplySavePanel(QWidget):
    """Node 07: read-only Draft preview + the two save actions."""

    #: emitted when the project content was written (previews refresh)
    content_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = None
        template = yaml.safe_dump({}, sort_keys=False, allow_unicode=True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        preview_box = QVBoxLayout()
        preview_box.addWidget(QLabel("Draft YAML preview (read-only):"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setObjectName("apply_save_preview")
        self.preview.setPlainText(template)
        preview_box.addWidget(self.preview, 1)
        root.addLayout(preview_box, 1)

        self.lbl_status = QLabel("Validation: …")
        self.lbl_status.setObjectName("apply_save_status")
        root.addWidget(self.lbl_status)
        self.lbl_errors = QLabel("")
        self.lbl_errors.setWordWrap(True)
        self.lbl_errors.setProperty("tone", "warn")
        root.addWidget(self.lbl_errors)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target file:"))
        self.edit_target = QLineEdit()
        self.edit_target.setReadOnly(True)
        self.edit_target.setPlaceholderText(NO_TARGET)
        target_row.addWidget(self.edit_target, 1)
        root.addLayout(target_row)

        self.lbl_saved = QLabel("")
        self.lbl_saved.setWordWrap(True)
        self.lbl_saved.setProperty("tone", "muted")
        root.addWidget(self.lbl_saved)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_apply = QPushButton("Apply & Save Yaml")
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_save_as = QPushButton("Save as new yaml")
        self.btn_save_as.clicked.connect(self._on_save_as)
        self.btn_export_sheet = QPushButton("Export MTK ICT Excel Sheet\u2026")
        self.btn_export_sheet.clicked.connect(self._on_export_sheet)
        buttons.addWidget(self.btn_apply)
        buttons.addWidget(self.btn_save_as)
        buttons.addWidget(self.btn_export_sheet)
        root.addLayout(buttons)

        self.btn_apply.setEnabled(False)
        self.btn_save_as.setEnabled(False)
        self.btn_export_sheet.setEnabled(False)

    # ------------------------------------------------------------ binding
    def set_values(self, model) -> None:
        """Bind the model and paint the current Draft."""
        self._model = model
        self.refresh()

    def values(self) -> dict:
        """No editable parameters - the panel only previews / saves."""
        return {}

    def validation_errors(self) -> list[str]:
        """The current blocking errors (empty = save buttons enabled)."""
        if self._model is None:
            return ["no model bound"]
        errors = list(self._model.validate_all())
        errors.extend(f"required module disabled: {title}"
                      for title in self._model.missing_required_modules())
        try:
            plan_filename(self._model, "draft")
        except ValueError as exc:
            errors.append(str(exc))
        return list(dict.fromkeys(errors))

    def refresh(self) -> None:
        """Repaint the preview, validation line and target file name."""
        if self._model is None:
            return
        try:
            text = yaml.safe_dump(
                build_plan_document(self._model, "draft"),
                sort_keys=False, allow_unicode=True)
        except Exception as exc:      # noqa: BLE001 - never abort the page
            text = f"# preview unavailable: {exc}"
        self.preview.setPlainText(text)
        errors = self.validation_errors()
        if errors:
            self.lbl_status.setText(f"Validation: {len(errors)} error(s)")
            self.lbl_status.setStyleSheet(
                f"color: {gui_theme_color('bad')};")
            self.lbl_errors.setText("\n".join(errors))
        else:
            self.lbl_status.setText("Validation: OK")
            self.lbl_status.setStyleSheet(
                f"color: {gui_theme_color('ok')};")
            self.lbl_errors.setText("")
        self.btn_apply.setEnabled(not errors)
        self.btn_save_as.setEnabled(not errors)
        self.btn_export_sheet.setEnabled(not errors)
        try:
            self.edit_target.setText(plan_filename(self._model, "draft"))
        except ValueError:
            self.edit_target.setText(NO_TARGET)

    def yaml_text(self) -> str:
        """The preview text (tests / diagnostics)."""
        return self.preview.toPlainText()

    # -------------------------------------------------------------- saving
    def _on_apply(self) -> None:
        if self._model is None:
            return
        try:
            path, archive = apply_and_save(self._model)
        except (ValueError, OSError) as exc:
            self.lbl_saved.setText(f"Apply failed: {exc}")
            self.lbl_saved.setStyleSheet(
                f"color: {gui_theme_color('bad')};")
            return
        self.lbl_saved.setStyleSheet("")
        self.lbl_saved.setText(f"Saved: {path}\nArchived: {archive}")
        self.content_changed.emit()

    def export_sheet_dialog(self) -> None:
        """The node 07 export entry (also called from ``File ▸ Excel``).

        One implementation for both entry points (rule R14a): validate,
        pick the R16 default filename, write the fresh four-sheet
        workbook.
        """
        if self._model is None:
            return
        errors = list(self._model.validate_all())
        if errors:
            QMessageBox.warning(self, "Cannot export", "\n".join(errors))
            return
        try:
            default_name = default_mtk_sheet_name(self._model)
        except Exception:          # noqa: BLE001 - never abort the dialog
            default_name = "MTK_ICT_sheet.xlsx"
        picked, _filter = QFileDialog.getSaveFileName(
            self, "Export MTK ICT Excel Sheet",
            str(_work_dir() / default_name), "Excel (*.xlsx)")
        if not picked:
            return
        path = Path(picked)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        try:
            rows = export_mtk_sheet(self._model, str(path))
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return
        self.lbl_saved.setStyleSheet("")
        self.lbl_saved.setText(f"Exported: {path} ({rows} data rows)")

    def _on_export_sheet(self) -> None:
        self.export_sheet_dialog()

    def _on_save_as(self) -> None:
        if self._model is None:
            return
        try:
            default_name = plan_filename(self._model, "draft")
        except ValueError:
            default_name = "draft.yaml"
        picked, _filter = QFileDialog.getSaveFileName(
            self, "Save as new yaml",
            str(_work_dir() / default_name), "YAML (*.yaml *.yml)")
        if not picked:
            return
        try:
            path, archive = save_as(self._model, picked)
        except OSError as exc:
            self.lbl_saved.setText(f"Save failed: {exc}")
            self.lbl_saved.setStyleSheet(
                f"color: {gui_theme_color('bad')};")
            return
        self.lbl_saved.setStyleSheet("")
        self.lbl_saved.setText(f"Saved: {path}\nArchived: {archive}")
        self.content_changed.emit()
