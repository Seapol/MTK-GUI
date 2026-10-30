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
    QHBoxLayout,
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
from mtkgui.gui.dialog_sizing import apply_scroll_to_dialog, fit_dialog
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
    parts: list[str] = [f"Purpose: {spec.label}"]
    if spec.minimum is not None and spec.maximum is not None:
        parts.append(f"Range {spec.minimum:g} - {spec.maximum:g}"
                     + (f" {spec.unit}" if spec.unit else ""))
    elif spec.minimum is not None:
        parts.append(f"Min {spec.minimum:g}"
                     + (f" {spec.unit}" if spec.unit else ""))
    elif spec.maximum is not None:
        parts.append(f"Max {spec.maximum:g}"
                     + (f" {spec.unit}" if spec.unit else ""))
    elif spec.unit:
        parts.append(f"Unit: {spec.unit}")
    if spec.choices:
        parts.append("Choices: " + " / ".join(spec.choices))
    if spec.required:
        parts.append("Required")
    if spec.remarks:
        parts.append(spec.remarks)
    return "; ".join(parts)


class ExitPromptDialog(QDialog):
    """M45a: the dirty-Exit decision with a FIXED left-to-right order.

    M44 used a ``QMessageBox`` with role-based buttons - Qt reorders
    those by platform role, so macOS showed "Save as new yaml | Cancel
    (discard changes) | Apply_Save yaml" instead of the owner's
    required "Apply_Save yaml | Save as new yaml | Cancel".  This
    dialog lays the three buttons out explicitly in one ``QHBoxLayout``.
    """

    APPLY = 1
    SAVE_AS = 2
    CANCEL = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Unsaved changes")
        self.choice = self.CANCEL
        lay = QVBoxLayout(self)
        label = QLabel("This configuration page has unsaved changes.\n"
                       "What should happen?")
        label.setWordWrap(True)
        lay.addWidget(label)
        row = QHBoxLayout()
        self.btn_apply = QPushButton("Apply_Save yaml")
        self.btn_new = QPushButton("Save as new yaml")
        self.btn_cancel = QPushButton("Cancel")
        for btn in (self.btn_apply, self.btn_new, self.btn_cancel):
            row.addWidget(btn)
        lay.addLayout(row)
        self.btn_apply.clicked.connect(lambda: self._choose(self.APPLY))
        self.btn_new.clicked.connect(lambda: self._choose(self.SAVE_AS))
        self.btn_cancel.clicked.connect(self.reject)

    def _choose(self, choice: int) -> None:
        self.choice = choice
        self.accept()

    def buttons_in_order(self) -> list[QPushButton]:
        """The three buttons in their visible left-to-right order."""
        return [self.btn_apply, self.btn_new, self.btn_cancel]


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
                 net_source: tuple[str, str] | None = None,
                 panel_state: dict | None = None,
                 yaml_model=None,
                 apply_save_cb=None,
                 available_ops=None,
                 save_as_cb=None) -> None:
        """Create the dialog for one module.

        Args:
            module_key:       Stage key (defines the field set).
            params:           Current parameter values (name -> str).
            parent:           Parent widget.
            net_source:       Block 02 only - (raw netlist text, file
                              name) loaded by the Design Input panel
                              (T8 formal parse source).
            panel_state:      Block 02 only - item 24 restore data
                              (net rules, power tree, allocation
                              overrides, SPF net names).
            yaml_model:       Block 02 only - the project YamlBuildModel
                              the Test Plan sync writes into (M5).
            apply_save_cb:    Block 07 only - callable(values) invoked by
                              the single "Apply_Save yaml" button before
                              the dialog accepts; it applies the sequence
                              to every view and saves the project yaml in
                              place, returning an error string (None =
                              saved; an error keeps the dialog open).
                              M45a: the former duplicate "Apply & Save
                              yaml" button (bottom-left) is gone - every
                              config page shows exactly ONE Apply_Save
                              yaml + ONE Exit.
            available_ops:    M37 - block 07 only: the standard operations
                              usable with the configured resources
                              (None = all of them).
            save_as_cb:       M44 - callable(values) invoked by the Exit
                              prompt's "Save as new yaml" choice; the
                              page applies the values and routes the
                              request to the Save as new yaml entry.
        """
        super().__init__(parent)
        self.module_key = module_key
        self._specs: tuple[FieldSpec, ...] = fields_for(module_key)
        self._edited: dict[str, str] = dict(params or {})
        self._apply_save_cb = apply_save_cb
        self._save_as_cb = save_as_cb
        # navigation target requested by an embedded panel (e.g. the
        # Parse Nets "Open Power Tree Editor" button); the page reads
        # this after the dialog accepts
        self.requested_page: str | None = None
        self.setWindowTitle(
            f"Configure - {STAGE_BY_KEY[module_key].title}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        self.form = QFormLayout()
        body_lay.addLayout(self.form)
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
            body_lay.addWidget(self.panel)
            # M10-FIX2 F3: the Design Input content is compact - give the
            # dialog a sane, short initial size instead of letting an
            # oversized hint leave a dead band above OK/Cancel.  The
            # property keeps the app-wide DialogCenterer from inflating
            # it to 1.5x sizeHint on first show (it honours
            # _dlg_enlarged as "size already chosen").
            self.setProperty("_dlg_enlarged", True)
            self.setMinimumSize(560, 0)
            fit_dialog(self, 600, 540)
        elif module_key == "instruments":
            # T9: the simplified Configure Instruments panel - the
            # instrument parameters stay on the Equipment page
            from mtkgui.gui.yamlbuild.instruments_panel import \
                InstrumentsPanel
            self.panel = InstrumentsPanel()
            self.panel.set_params(params or {})
            self.panel.task_log.connect(self._panel_log)
            body_lay.addWidget(self.panel)
        elif module_key == "fct_build":
            # P3-B5: the FCT Test Work Flow Sequence panel - three tabs
            # (Console / Wi-Fi / Bluetooth) editing fct_test_config
            from mtkgui.gui.yamlbuild.FCTTestConfigWidget import \
                FCTTestConfigPanel
            self.panel = FCTTestConfigPanel()
            self.panel.set_available_ops(available_ops)
            self.panel.set_values(params or {})
            self.panel.task_log.connect(self._panel_log)
            body_lay.addWidget(self.panel)
            # M27 P4: the FCT panel demands 1100 px (8-column step
            # editor); give the dialog a width that satisfies it and mark
            # _dlg_enlarged so the DialogCenterer never re-inflates it.
            # Height 700: the two-column Wi-Fi/BT tabs (2026-10-29)
            # brought the panel minimum down to ~594 px, so the dialog
            # now fits a 1440x900 laptop screen and stays user-resizable.
            self.setProperty("_dlg_enlarged", True)
            fit_dialog(self, 1180, 700)
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
        body_lay.addWidget(self.error_label)
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
            self.nets_panel.set_yaml_model(yaml_model)
            self.nets_panel.task_log.connect(self._panel_log)
            self.nets_panel.task_progress.connect(self._panel_progress)
            body_lay.addWidget(self.nets_panel)
            # M10-FIX2 F1: the tables stretch inside a sane initial size
            # instead of forcing a tall empty block above the buttons;
            # fit_dialog marks _dlg_enlarged so the DialogCenterer only
            # centers it and never inflates it to the screen height
            # (2026-10-26: the button row used to fall behind the
            # taskbar on big builders).
            fit_dialog(self, 1060, 780)
        # M34: the dialog body scrolls, the OK / Cancel row stays outside
        # the scroll area (always visible).  The FCT step editor keeps its
        # 1100 px minimum width on the scroll wrapper.
        apply_scroll_to_dialog(
            self, body, 1100 if module_key == "fct_build" else 0)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        # M44: the lifecycle buttons are "Apply_Save yaml" (OK applies and
        # saves through the unified apply save yaml) and "Exit" (Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Apply_Save yaml")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            "Exit")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self._on_exit)
        # the dirty check compares the values read back at Exit time with
        # the values the dialog opened with
        self._initial_values = self._current_values()
        lay.addWidget(buttons)

    # ------------------------------------------------- panel log mirror
    def _panel_log(self, level: str, message: str) -> None:
        """Forward embedded-panel Event-Log lines to the page."""
        self.task_log.emit(level, message)

    def _panel_progress(self, percent: int, label: str) -> None:
        """Forward embedded-panel progress to the page."""
        self.task_progress.emit(percent, label)

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
    def _collect(self) -> dict | None:
        """Read + validate every field; None when the input is invalid
        (the error list is shown in the dialog)."""
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
            return None
        return dict(self._edited)

    def _on_accept(self) -> None:
        """Validate all fields; accept only when clean.

        M45a: block 07's single "Apply_Save yaml" button runs the
        in-place apply/save callback BEFORE accepting (the M22b
        refresh behaviour, now on the one lifecycle button); an error
        from the callback keeps the dialog open with the message.
        """
        values = self._collect()
        if values is None:
            return
        if self._apply_save_cb is not None:
            error = self._apply_save_cb(values)
            if error:
                self.error_label.setText(str(error))
                return
            self.error_label.setText("")
            self.task_log.emit("info",
                               "FCT sequence applied and yaml saved")
        if self.nets_panel is not None:
            # M5 commit gate: a workbook import may write the
            # production YAML only after the block was applied
            self.nets_panel.mark_applied()
        self.accept()

    def _current_values(self) -> dict:
        """Read the current editor values WITHOUT validating (the Exit
        dirty check only needs a comparison)."""
        try:
            if self.panel is not None:
                return dict(self.panel.values())
            return {spec.name: self._editor_value(spec)
                    for spec in self._specs if not spec.hidden}
        except Exception:      # noqa: BLE001 - unreadable -> unchanged
            return dict(self._initial_values
                        if hasattr(self, "_initial_values") else {})

    def _is_dirty(self) -> bool:
        """True when the dialog holds values different from the ones it
        opened with (M44)."""
        current = self._current_values()
        initial = getattr(self, "_initial_values", {}) or {}
        for key, value in current.items():
            if str(initial.get(key, "")) != str(value):
                return True
        return False

    def _on_exit(self) -> None:
        """M44/M45a: Exit with unsaved changes prompts three choices in
        the FIXED left-to-right order Apply_Save yaml | Save as new yaml
        | Cancel.  An unchanged dialog exits silently."""
        if not self._is_dirty():
            self.reject()
            return
        prompt = ExitPromptDialog(self)
        prompt.exec()
        if prompt.choice == ExitPromptDialog.APPLY:
            # validate + apply save; accept closes the dialog
            self._on_accept()
        elif prompt.choice == ExitPromptDialog.SAVE_AS:
            if self._save_as_cb is not None:
                self._save_as_cb(self._current_values())
            self.reject()
        else:
            self.reject()

    def values(self) -> dict:
        """Return the validated parameter set (after accept).

        Returns:
            Dict of parameter name -> string value.
        """
        return dict(self._edited)
