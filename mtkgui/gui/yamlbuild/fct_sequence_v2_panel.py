# -*- coding: utf-8 -*-
"""v2 node 06 Build FCT Test Sequence — Qt panel.

Qt skin over :mod:`mtkgui.gui.yamlbuild.fct_build`.  Renders the edited
FCT sequence into a step table, exposes a bottom editor for the selected
row, a collapsible keyword-tables section, and an ``Advanced…`` button
that still reaches the v1 FCT dialog through ``advanced_requested``.

This panel is PURE data editing: it wraps ``FctSequence`` / ``FctStep``
and ``to_project_fct_cases`` / ``from_project_fct_cases`` — no execution
logic, no channel I/O (the P3-B3 red line).
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.fct_build import (
    DEFAULT_KEYWORD_FAIL,
    DEFAULT_KEYWORD_PASS,
    FLASH_CLI,
    FLASH_GUI,
    FLASH_MODES,
    ON_FAIL_POLICIES,
    STEP_EXTERNAL_TOOL,
    STEP_FLASH,
    STEP_MESSAGE_CHECK,
    STEP_TYPES,
    FctSequence,
    FctStep,
)

#: step table columns, in order
COLUMNS = ("#", "Name", "Type", "Channel", "Command", "Expect pass",
           "Expect fail", "Timeout (s)", "Retries", "On fail")

_SPINE_TEXT = "ICT → Flash FAT → FCT body → Flash OOBE → Teardown"


def _split_csv(text: str) -> list:
    """Comma-separated keywords -> list (stripped, empties dropped)."""
    return [part.strip() for part in str(text).split(",") if part.strip()]


def _type_label(step: FctStep) -> str:
    """The ``Type`` cell: the step_type, plus the mode for a FLASH step."""
    if step.step_type == STEP_FLASH:
        mode = str((step.params or {}).get("flash_mode", "")).lower()
        return f"{STEP_FLASH} ({mode})"
    return step.step_type


class BuildFctSequencePanel(QWidget):
    """Node 06: edit the flat FCT sequence + keyword tables."""

    content_changed = Signal()
    advanced_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sequence = FctSequence(name="FCT Sequence")
        self._selected_index = -1
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.setMinimumWidth(900)

        # --------------------------------------------------- spine label
        self.lbl_spine = QLabel(_SPINE_TEXT)
        self.lbl_spine.setObjectName("strong")
        root.addWidget(self.lbl_spine)

        # ------------------------------------------------- row buttons
        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Step")
        self.btn_add.setMenu(self._build_add_menu())
        self.btn_delete = QPushButton("Delete")
        self.btn_move_up = QPushButton("Move up")
        self.btn_move_down = QPushButton("Move down")
        self.btn_advanced = QPushButton("Advanced…")
        self.btn_delete.clicked.connect(self._delete_step)
        self.btn_move_up.clicked.connect(lambda: self._move(-1))
        self.btn_move_down.clicked.connect(lambda: self._move(+1))
        self.btn_advanced.clicked.connect(self.advanced_requested.emit)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_delete)
        btn_row.addWidget(self.btn_move_up)
        btn_row.addWidget(self.btn_move_down)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_advanced)
        root.addLayout(btn_row)

        # -------------------------------------------------------- table
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((32, 200, 110, 80, 180, 110, 110,
                                        80, 70, 80)):
            self.table.setColumnWidth(column, width)
        self.table.currentCellChanged.connect(self._on_row_selected)
        root.addWidget(self.table, 1)

        # ------------------------------------------------------ editor
        self._build_editor(root)

        # -------------------------------------------------- keywords
        self._build_keywords(root)

        self._render()

    # ------------------------------------------------------------- UI
    def _build_add_menu(self) -> QMenu:
        menu = QMenu(self.btn_add)
        for step_type in STEP_TYPES:
            menu.addAction(step_type, lambda t=step_type: self._add_step(t))
        return menu

    def _build_editor(self, root) -> None:
        group = QGroupBox("Selected step")
        form = QFormLayout(group)
        self.edit_name = QLineEdit()
        self.edit_type = QComboBox()
        self.edit_type.setInsertPolicy(QComboBox.NoInsert)
        self.edit_type.addItems(list(STEP_TYPES))
        self.edit_channel = QLineEdit()
        self.edit_command = QLineEdit()
        self.edit_expect_pass = QLineEdit()
        self.edit_expect_fail = QLineEdit()
        self.edit_timeout = QDoubleSpinBox()
        self.edit_timeout.setRange(0.0, 1_000_000.0)
        self.edit_timeout.setDecimals(2)
        self.edit_retries = QSpinBox()
        self.edit_retries.setRange(0, 1_000_000)
        self.edit_on_fail = QComboBox()
        self.edit_on_fail.setInsertPolicy(QComboBox.NoInsert)
        self.edit_on_fail.addItems(list(ON_FAIL_POLICIES))
        # FLASH-only fields
        self.edit_slot = QComboBox()
        self.edit_slot.setInsertPolicy(QComboBox.NoInsert)
        self.edit_slot.addItems(["fat", "oobe"])
        self.edit_flash_mode = QComboBox()
        self.edit_flash_mode.setInsertPolicy(QComboBox.NoInsert)
        self.edit_flash_mode.addItems(list(FLASH_MODES))

        self._editor_form = form
        form.addRow("Name", self.edit_name)
        form.addRow("Type", self.edit_type)
        form.addRow("Channel", self.edit_channel)
        self._command_row = form.addRow("Command", self.edit_command)
        form.addRow("Expect pass", self.edit_expect_pass)
        form.addRow("Expect fail", self.edit_expect_fail)
        form.addRow("Timeout (s)", self.edit_timeout)
        form.addRow("Retries", self.edit_retries)
        form.addRow("On fail", self.edit_on_fail)
        self._slot_row = form.addRow("Slot", self.edit_slot)
        self._flash_mode_row = form.addRow("Flash mode", self.edit_flash_mode)
        # hide the FLASH-only rows until a FLASH step is selected
        form.setRowVisible(self._slot_row, False)
        form.setRowVisible(self._flash_mode_row, False)

        for widget in (self.edit_name, self.edit_channel, self.edit_command,
                       self.edit_expect_pass, self.edit_expect_fail):
            widget.textChanged.connect(self._on_editor_edited)
        self.edit_type.currentTextChanged.connect(self._on_editor_edited)
        self.edit_slot.currentTextChanged.connect(self._on_editor_edited)
        self.edit_flash_mode.currentTextChanged.connect(
            self._on_editor_edited)
        self.edit_on_fail.currentTextChanged.connect(self._on_editor_edited)
        self.edit_timeout.valueChanged.connect(self._on_editor_edited)
        self.edit_retries.valueChanged.connect(self._on_editor_edited)
        root.addWidget(group)

    def _build_keywords(self, root) -> None:
        group = QGroupBox("Keyword tables (sequence-level)")
        group.setCheckable(True)
        group.setChecked(True)
        lay = QVBoxLayout(group)
        lay.addWidget(QLabel("Positive keywords (one per line)"))
        self.edit_keyword_pass = QPlainTextEdit()
        lay.addWidget(self.edit_keyword_pass)
        lay.addWidget(QLabel("Negative keywords (one per line)"))
        self.edit_keyword_fail = QPlainTextEdit()
        lay.addWidget(self.edit_keyword_fail)
        self.edit_keyword_pass.textChanged.connect(self._on_keywords_edited)
        self.edit_keyword_fail.textChanged.connect(self._on_keywords_edited)
        root.addWidget(group)

    # ----------------------------------------------------------- access
    def set_sequence(self, sequence: FctSequence) -> None:
        """Load a sequence (deep copy), seed the table and the editor."""
        self._sequence = copy.deepcopy(sequence)
        self._selected_index = -1
        self._render()

    def sequence(self) -> FctSequence:
        """The edited sequence (a deep copy)."""
        return copy.deepcopy(self._sequence)

    # ------------------------------------------------------------- gate
    def validate(self) -> tuple[bool, str]:
        errors = self._sequence.validate()
        if errors:
            return False, " | ".join(errors)
        return True, ""

    # ----------------------------------------------------------- render
    def _render(self) -> None:
        self._loading = True
        try:
            self._render_table()
            self._render_keywords()
            self._refresh_editor()
        finally:
            self._loading = False

    def _render_table(self) -> None:
        steps = self._sequence.steps
        self.table.setRowCount(len(steps))
        for row_index, step in enumerate(steps):
            values = (str(row_index + 1), step.name, _type_label(step),
                      step.channel, step.command,
                      ", ".join(step.expect_pass),
                      ", ".join(step.expect_fail),
                      "" if step.timeout_s == 0 else f"{step.timeout_s:g}",
                      str(step.retries), step.on_fail)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, col, item)

    def _render_keywords(self) -> None:
        self.edit_keyword_pass.setPlainText(
            "\n".join(self._sequence.keyword_pass))
        self.edit_keyword_fail.setPlainText(
            "\n".join(self._sequence.keyword_fail))

    def _refresh_editor(self) -> None:
        step = self._selected_step()
        if step is None:
            self.edit_name.clear()
            self.edit_channel.clear()
            self.edit_command.clear()
            self.edit_expect_pass.clear()
            self.edit_expect_fail.clear()
            self.edit_timeout.setValue(0.0)
            self.edit_retries.setValue(0)
            return
        self.edit_name.setText(step.name)
        self.edit_type.setCurrentText(step.step_type)
        self.edit_channel.setText(step.channel)
        self.edit_command.setText(step.command)
        self.edit_expect_pass.setText(", ".join(step.expect_pass))
        self.edit_expect_fail.setText(", ".join(step.expect_fail))
        self.edit_timeout.setValue(step.timeout_s)
        self.edit_retries.setValue(int(step.retries))
        self.edit_on_fail.setCurrentText(step.on_fail)
        self.edit_slot.setCurrentText(
            str((step.params or {}).get("slot", "fat")))
        self.edit_flash_mode.setCurrentText(
            str((step.params or {}).get("flash_mode", FLASH_GUI)))
        self._update_flash_visibility()

    def _update_flash_visibility(self) -> None:
        """Show FLASH-only rows, and hide Command when gui mode."""
        is_flash = self.edit_type.currentText() == STEP_FLASH
        self._editor_form.setRowVisible(self._slot_row, is_flash)
        self._editor_form.setRowVisible(self._flash_mode_row, is_flash)
        if is_flash:
            gui = self.edit_flash_mode.currentText() == FLASH_GUI
            self._editor_form.setRowVisible(self._command_row, not gui)
        else:
            self._editor_form.setRowVisible(self._command_row, True)

    # ------------------------------------------------------------ sync
    def _selected_step(self) -> FctStep | None:
        if 0 <= self._selected_index < len(self._sequence.steps):
            return self._sequence.steps[self._selected_index]
        return None

    def _on_row_selected(self, row: int, _col: int, _prev_row: int,
                         _prev_col: int) -> None:
        if self._loading:
            return
        self._selected_index = row
        self._loading = True
        try:
            self._refresh_editor()
        finally:
            self._loading = False

    def _on_editor_edited(self, *_args) -> None:
        if self._loading:
            return
        step = self._selected_step()
        if step is None:
            return
        step.name = self.edit_name.text().strip()
        step.step_type = self.edit_type.currentText()
        step.channel = self.edit_channel.text().strip()
        step.command = self.edit_command.text().strip()
        step.expect_pass = _split_csv(self.edit_expect_pass.text())
        step.expect_fail = _split_csv(self.edit_expect_fail.text())
        step.timeout_s = float(self.edit_timeout.value())
        step.retries = int(self.edit_retries.value())
        step.on_fail = self.edit_on_fail.currentText()
        if step.step_type == STEP_FLASH:
            step.params["slot"] = self.edit_slot.currentText()
            step.params["flash_mode"] = self.edit_flash_mode.currentText()
        self._update_flash_visibility()
        self.content_changed.emit()
        # re-render the single row so the Type cell stays in step
        self._loading = True
        try:
            self._render_table()
            self.table.setCurrentCell(self._selected_index, 0)
        finally:
            self._loading = False

    def _on_keywords_edited(self) -> None:
        if self._loading:
            return
        self._sequence.keyword_pass = [
            ln.strip() for ln in self.edit_keyword_pass.toPlainText()
            .splitlines() if ln.strip()]
        self._sequence.keyword_fail = [
            ln.strip() for ln in self.edit_keyword_fail.toPlainText()
            .splitlines() if ln.strip()]
        self.content_changed.emit()

    # --------------------------------------------------------- actions
    def _add_step(self, step_type: str) -> None:
        name = f"New {step_type}" if step_type != STEP_FLASH else \
            "New FLASH"
        params = {}
        if step_type == STEP_FLASH:
            params = {"slot": "fat", "flash_mode": FLASH_GUI}
        self._sequence.steps.append(
            FctStep(name=name, step_type=step_type, params=params))
        self.content_changed.emit()
        self._render()
        self.table.setCurrentCell(len(self._sequence.steps) - 1, 0)

    def _delete_step(self) -> None:
        if self._selected_index < 0:
            return
        del self._sequence.steps[self._selected_index]
        self._selected_index = -1
        self.content_changed.emit()
        self._render()

    def _move(self, delta: int) -> None:
        steps = self._sequence.steps
        i = self._selected_index
        if not (0 <= i < len(steps)) or not (0 <= i + delta < len(steps)):
            return
        steps[i], steps[i + delta] = steps[i + delta], steps[i]
        self._selected_index = i + delta
        self.content_changed.emit()
        self._render()
        self.table.setCurrentCell(self._selected_index, 0)
