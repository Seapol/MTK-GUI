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

from PySide6.QtCore import Signal
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

#: block 02 power waveform capture list (M0 additional requirement)
CAPTURE_FIELD = "power_capture_nets"
MAX_CAPTURE_NETS = 12


class BlockConfigDialog(QDialog):
    """Dedicated configuration popup for exactly one workflow module.

    The dialog edits a COPY of the module parameters; on accept the
    values are validated against the field schema - invalid input
    keeps the dialog open with the error list, so a module save is
    always all-or-nothing (independent save + validation).
    """

    #: (level, message) Event-Log mirror from embedded panels (T6)
    task_log = Signal(str, str)
    #: (percent, label) long-task progress mirror (T6)
    task_progress = Signal(int, str)

    def __init__(self, module_key: str, params: dict,
                 parent: QWidget | None = None,
                 power_candidates: list[str] | None = None,
                 net_source: tuple[str, str] | None = None,
                 panel_state: dict | None = None) -> None:
        """Create the dialog for one module.

        Args:
            module_key:       Stage key (defines the field set).
            params:           Current parameter values (name -> str).
            parent:           Parent widget.
            power_candidates: Block 02 only - candidate power nets
                              (from the Parse Nets result) used to
                              auto-prefill the capture list.
            net_source:       Block 02 only - (raw netlist text, file
                              name) loaded by the Design Input panel
                              (T8 formal parse source).
            panel_state:      Block 02 only - item 24 restore data
                              (net rules, power tree, allocation
                              overrides, SPF net names).
        """
        super().__init__(parent)
        self.module_key = module_key
        self._specs: tuple[FieldSpec, ...] = fields_for(module_key)
        self._edited: dict[str, str] = dict(params or {})
        self._power_candidates = list(power_candidates or [])
        # navigation target requested by an embedded panel (e.g. the
        # Parse Nets "Open Power Tree Editor" button); the page reads
        # this after the dialog accepts
        self.requested_page: str | None = None
        self.setWindowTitle(
            f"Configure - {STAGE_BY_KEY[module_key].title}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        self.form = QFormLayout()
        lay.addLayout(self.form)
        self._editors: dict[str, QWidget] = {}
        self.panel: QWidget | None = None
        if module_key == "design_input":
            # T7: the unified Design Input panel replaces both the
            # generic form fields and the deprecated standalone
            # "Design data import" popup
            from mtkgui.gui.yamlbuild.design_input_panel import \
                DesignInputPanel
            self.panel = DesignInputPanel()
            self.panel.set_values(params or {})
            self.panel.task_log.connect(self._panel_log)
            self.panel.task_progress.connect(self._panel_progress)
            lay.addWidget(self.panel)
        elif module_key == "instruments":
            # T9: the simplified Configure Instruments panel - the
            # instrument parameters stay on the Equipment page
            from mtkgui.gui.yamlbuild.instruments_panel import \
                InstrumentsPanel
            self.panel = InstrumentsPanel()
            self.panel.set_params(params or {})
            self.panel.task_log.connect(self._panel_log)
            lay.addWidget(self.panel)
        else:
            for spec in self._specs:
                if spec.hidden:
                    # internal bookkeeping field: kept in the params /
                    # YAML but never rendered as a dialog input
                    continue
                editor = self._make_editor(spec)
                self._editors[spec.name] = editor
                self.form.addRow(f"{spec.label}" +
                                 (f" ({spec.unit})" if spec.unit else "")
                                 + ":", editor)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b91c1c;")
        self.error_label.setWordWrap(True)
        lay.addWidget(self.error_label)
        # block 02: formal net pre-analysis (T8 Parse Nets for ICT)
        self.nets_panel: QWidget | None = None
        if module_key == "parse_ict":
            from mtkgui.gui.yamlbuild.parse_nets import ParseNetsPanel
            self.nets_panel = ParseNetsPanel()
            text, name = net_source or ("", "")
            self.nets_panel.set_net_source(text, name)
            state = panel_state or {}
            self.nets_panel.set_rules(state.get("net_rules") or {})
            self.nets_panel.set_dnt_state(state.get("power_dnt"))
            self.nets_panel.spf_nets = set(
                state.get("spf_nets") or [])
            self.nets_panel.risk_thresholds = dict(
                state.get("risk_thresholds") or {})
            if not self.nets_panel.risk_thresholds:
                from mtkgui.gui.yamlbuild.path_risk import (
                    DEFAULT_THRESHOLDS,
                )
                self.nets_panel.risk_thresholds = dict(
                    DEFAULT_THRESHOLDS)
            self.nets_panel.risk_scores = dict(
                state.get("risk_scores") or {})
            # navigation: "Open Power Tree Editor" closes this dialog
            # and asks the page to switch to the dedicated tab
            self.nets_panel.power_tree_requested.connect(
                self._request_power_tree_page)
            self.nets_panel.task_log.connect(self._panel_log)
            self.nets_panel.task_progress.connect(self._panel_progress)
            lay.addWidget(self.nets_panel)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ------------------------------------------------- panel log mirror
    def _panel_log(self, level: str, message: str) -> None:
        """Forward embedded-panel Event-Log lines to the page."""
        self.task_log.emit(level, message)

    def _panel_progress(self, percent: int, label: str) -> None:
        """Forward embedded-panel progress to the page."""
        self.task_progress.emit(percent, label)

    def _request_power_tree_page(self) -> None:
        """The Parse Nets panel asked for the dedicated Power Tree
        page: save + close this dialog; the page switches the tab."""
        self.requested_page = "power_tree"
        self.accept()

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

    # ------------------------------------------------------------- save
    def _on_accept(self) -> None:
        """Validate all fields; accept only when clean."""
        if self.panel is not None:
            # Design Input: the embedded panel owns the values
            self._edited = dict(self.panel.values())
        else:
            edited = {
                spec.name: self._editor_value(spec)
                for spec in self._specs if not spec.hidden
            }
            # hidden bookkeeping fields keep their existing values
            # (they are not dialog inputs - never blanked by a save)
            for spec in self._specs:
                if spec.hidden:
                    edited[spec.name] = self._edited.get(spec.name,
                                                         spec.default)
            self._edited = edited
        errors = [msg for msg in (
            spec.validate(self._edited.get(spec.name, ""))
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
