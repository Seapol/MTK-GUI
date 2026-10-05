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
    QPushButton,
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


def spec_tooltip(spec: FieldSpec) -> str:
    """Compose the standard hover tooltip for one parameter field
    (rule 6.4: no empty tooltips - label, unit, range, choices,
    requirement and usage notes are all derived from the schema).

    Args:
        spec: Field schema.

    Returns:
        A concise, informative tooltip text.
    """
    parts: list[str] = [f"用途：{spec.label}"]
    if spec.minimum is not None and spec.maximum is not None:
        parts.append(f"取值范围 {spec.minimum:g} – {spec.maximum:g}"
                     + (f" {spec.unit}" if spec.unit else ""))
    elif spec.minimum is not None:
        parts.append(f"最小 {spec.minimum:g}"
                     + (f" {spec.unit}" if spec.unit else ""))
    elif spec.maximum is not None:
        parts.append(f"最大 {spec.maximum:g}"
                     + (f" {spec.unit}" if spec.unit else ""))
    elif spec.unit:
        parts.append(f"单位：{spec.unit}")
    if spec.choices:
        parts.append("可选：" + " / ".join(spec.choices))
    if spec.required:
        parts.append("必填项")
    if spec.remarks:
        parts.append(spec.remarks)
    return "；".join(parts)

#: modules with a dedicated import sub-dialog (V4.0 acceptance 3.1.1)
_IMPORT_MODULES = {"design_input"}

#: block 03 power waveform capture list (M0 additional requirement)
CAPTURE_FIELD = "power_capture_nets"
MAX_CAPTURE_NETS = 12


class BlockConfigDialog(QDialog):
    """Dedicated configuration popup for exactly one workflow module.

    The dialog edits a COPY of the module parameters; on accept the
    values are validated against the field schema - invalid input
    keeps the dialog open with the error list, so a module save is
    always all-or-nothing (independent save + validation).
    """

    def __init__(self, module_key: str, params: dict,
                 parent: QWidget | None = None,
                 power_candidates: list[str] | None = None) -> None:
        """Create the dialog for one module.

        Args:
            module_key:       Stage key (defines the field set).
            params:           Current parameter values (name -> str).
            parent:           Parent widget.
            power_candidates: Block 03 only - candidate power nets
                              (from the power tree / imported netlist)
                              used to auto-prefill the capture list.
        """
        super().__init__(parent)
        self.module_key = module_key
        self._specs: tuple[FieldSpec, ...] = fields_for(module_key)
        self._edited: dict[str, str] = dict(params or {})
        self._power_candidates = list(power_candidates or [])
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
        # Design Input: dedicated import / parse sub-dialog
        # (schematic PDF + netlist + TP tolerance, rule 3.1.1)
        self.import_result: dict | None = None
        if module_key in _IMPORT_MODULES:
            btn_import = QPushButton("Import Schematic / Netlist…")
            btn_import.clicked.connect(self._open_import_dialog)
            lay.addWidget(btn_import)
        # block 03: power waveform capture net selection (M0)
        if module_key == "parse_ict" and CAPTURE_FIELD in self._editors:
            btn_autoselect = QPushButton(
                f"Auto-select Capture Nets (≤{MAX_CAPTURE_NETS})")
            btn_autoselect.setToolTip(
                "从电源树候选网络自动预选最多12路捕获网络；"
                "可手动增删后定稿")
            btn_autoselect.clicked.connect(self._autoselect_capture_nets)
            lay.addWidget(btn_autoselect)
            self._autoselect_capture_nets(initial=True)
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
            editor.setToolTip(spec_tooltip(spec))
            return editor
        if spec.ftype == T_BOOL:
            editor = QCheckBox()
            editor.setChecked(value.lower() in ("true", "1", "yes"))
            editor.setToolTip(spec_tooltip(spec))
            return editor
        if spec.ftype == T_CHOICE:
            from PySide6.QtWidgets import QComboBox
            editor = QComboBox()
            editor.addItems(list(spec.choices))
            if value in spec.choices:
                editor.setCurrentText(value)
            editor.setToolTip(spec_tooltip(spec))
            return editor
        editor = QLineEdit(value)
        editor.setPlaceholderText(spec.remarks)
        editor.setToolTip(spec_tooltip(spec))
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

    # ------------------------------------------------- capture nets (M0)
    def _autoselect_capture_nets(self, initial: bool = False) -> None:
        """Auto-prefill the power waveform capture list (block 03).

        Args:
            initial: True when called from __init__ - prefill ONLY an
                     empty list (an existing user-finalized list is
                     never overwritten); False = explicit button
                     click, which re-selects from the candidates.
        """
        editor = self._editors.get(CAPTURE_FIELD)
        if editor is None:
            return
        current = editor.toPlainText()
        if initial and current.strip():
            return                       # keep the finalized list
        from mtkgui.gui.designinput.netlist import \
            power_capture_candidates
        picks = power_capture_candidates(
            self._power_candidates, MAX_CAPTURE_NETS)
        if not picks:
            return
        editor.setPlainText("\n".join(picks))
        self._edited[CAPTURE_FIELD] = "\n".join(picks)

    # ------------------------------------------------------------ import
    def _open_import_dialog(self) -> None:
        """Open the Design Input import sub-dialog and merge its
        parsed results into the edited values (acceptance 3.1.1).

        Backfill: Core ID / project name / schematic file into the
        form; the netlist and TP resolutions travel via
        ``import_result`` for the page to store in the shared design
        data section.
        """
        from mtkgui.gui.yamlbuild.design_import import DesignImportDialog
        dialog = DesignImportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.import_result = {
            "schematic": dialog.schematic_meta,
            "netlist_file": dialog.netlist_file,
            "netlist": dialog.netlist_data,
            "tp_resolutions": dict(dialog.tp_resolutions),
        }
        meta = dialog.schematic_meta
        if meta.get("core_id") and "core_id" in self._editors:
            self._editors["core_id"].setText(meta["core_id"])
            self._edited["core_id"] = meta["core_id"]
        if "project_name" in self._editors:
            self._editors["project_name"].setText(
                meta.get("project_name", ""))
            self._edited["project_name"] = meta.get("project_name", "")
        if "schematic_file" in self._editors:
            self._editors["schematic_file"].setText(
                meta.get("file", ""))
            self._edited["schematic_file"] = meta.get("file", "")
        if dialog.netlist_file and "netlist_file" in self._editors:
            self._editors["netlist_file"].setText(dialog.netlist_file)
            self._edited["netlist_file"] = dialog.netlist_file
        if "tp_resolutions" in self._editors:
            text = "\n".join(f"{net}={value}" for net, value
                             in dialog.tp_resolutions.items())
            self._editors["tp_resolutions"].setPlainText(text)
            self._edited["tp_resolutions"] = text

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
