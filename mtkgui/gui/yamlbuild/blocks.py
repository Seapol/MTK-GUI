# -*- coding: utf-8 -*-
"""Per-module configuration dialogs (V4.0 rule 5.2-1).

One dialog class, instantiated per module from that module's
independent field schema (``schema.MODULE_FIELDS``): every module
gets its own dedicated popup window with its own parameters, its own
validation and its own save - module state never crosses modules.
Values are strings in the dialog layer; type coercion happens in the
model/schema layer.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.schema import (
    FieldSpec,
    T_BOOL,
    T_CHOICE,
    T_TEXT,
    fields_for,
)
from mtkgui.gui.yamlbuild.stages import STAGE_BY_KEY


class BlockConfigDialog(QDialog):
    """Dedicated configuration popup for exactly one workflow module.

    The dialog edits a COPY of the module parameters; on accept the
    values are validated against the field schema - invalid input
    keeps the dialog open with the error list, so a module save is
    always all-or-nothing (independent save + validation).
    """

    def __init__(self, module_key: str, params: dict,
                 parent: QWidget | None = None) -> None:
        """Create the dialog for one module.

        Args:
            module_key: Stage key (defines the field set).
            params:     Current parameter values (name -> str).
            parent:     Parent widget.
        """
        super().__init__(parent)
        self.module_key = module_key
        self._specs: tuple[FieldSpec, ...] = fields_for(module_key)
        self._edited: dict[str, str] = dict(params or {})
        self.setWindowTitle(
            f"Configure - {STAGE_BY_KEY[module_key].title}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        self.form = QFormLayout()
        lay.addLayout(self.form)
        self._editors: dict[str, QWidget] = {}
        for spec in self._specs:
            editor = self._make_editor(spec)
            self._editors[spec.name] = editor
            self.form.addRow(f"{spec.label}" +
                             (f" ({spec.unit})" if spec.unit else "")
                             + ":", editor)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b91c1c;")
        self.error_label.setWordWrap(True)
        lay.addWidget(self.error_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ----------------------------------------------------------- editors
    def _make_editor(self, spec: FieldSpec) -> QWidget:
        """Create the editor widget for one field.

        Args:
            spec: Field schema.

        Returns:
            QLineEdit / QPlainTextEdit / QCheckBox / QComboBox with
            the current value loaded.
        """
        value = str(self._edited.get(spec.name, spec.default) or "")
        if spec.ftype == T_TEXT:
            editor = QPlainTextEdit()
            editor.setPlainText(value)
            editor.setMinimumHeight(72)
            editor.setPlaceholderText(spec.remarks)
            return editor
        if spec.ftype == T_BOOL:
            editor = QCheckBox()
            editor.setChecked(value.lower() in ("true", "1", "yes"))
            return editor
        if spec.ftype == T_CHOICE:
            from PySide6.QtWidgets import QComboBox
            editor = QComboBox()
            editor.addItems(list(spec.choices))
            if value in spec.choices:
                editor.setCurrentText(value)
            return editor
        editor = QLineEdit(value)
        editor.setPlaceholderText(spec.remarks)
        return editor

    def _editor_value(self, spec: FieldSpec) -> str:
        """Read one editor back into its string value.

        Args:
            spec: Field schema.

        Returns:
            Raw string value (booleans normalized to true/false).
        """
        editor = self._editors[spec.name]
        if spec.ftype == T_TEXT:
            return editor.toPlainText()
        if spec.ftype == T_BOOL:
            return "true" if editor.isChecked() else "false"
        if spec.ftype == T_CHOICE:
            return editor.currentText()
        return editor.text().strip()

    # ------------------------------------------------------------- save
    def _on_accept(self) -> None:
        """Validate all fields; accept only when clean."""
        self._edited = {
            spec.name: self._editor_value(spec) for spec in self._specs
        }
        errors = [msg for msg in (
            spec.validate(self._edited[spec.name])
            for spec in self._specs) if msg]
        if errors:
            self.error_label.setText("\n".join(errors))
            QMessageBox.warning(
                self, "Validation",
                "Please fix the highlighted fields before saving.")
            return
        self.accept()

    def values(self) -> dict:
        """Return the validated parameter set (after accept).

        Returns:
            Dict of parameter name -> string value.
        """
        return dict(self._edited)
