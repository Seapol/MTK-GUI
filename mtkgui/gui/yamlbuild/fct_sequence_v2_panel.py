# -*- coding: utf-8 -*-
"""v2 node 06 Build FCT Test Sequence — Qt panel (M160).

Qt skin over :mod:`mtkgui.gui.yamlbuild.fct_build`.  Renders the edited
FCT sequence into a six-column step table, exposes a two-level
``category`` + ``type`` selector and a right-side editor split into the
common block plus one page per category (QStackedWidget).

This panel is PURE data editing: it wraps ``FctSequence`` / ``FctStep``
and ``to_project_fct_cases`` / ``from_project_fct_cases`` — no execution
logic, no channel I/O (the P3-B3 red line).
"""
from __future__ import annotations

import copy
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.engine.step_types import (
    CATEGORY_BLUETOOTH,
    CATEGORY_CONSOLE,
    CATEGORY_EXTERNAL_GUI,
    CATEGORY_MEASUREMENT,
    CATEGORY_MESSAGE,
    CATEGORY_OPERATION,
    CATEGORY_ORDER,
    CATEGORY_TRANSFER,
    CATEGORY_WIFI,
    STEP_CATEGORIES,
)
from mtkgui.gui.yamlbuild.command_snippet_helper import (
    PAGE_WINDOWS,
    with_snippets,
)
from mtkgui.gui.yamlbuild.fct_build import (
    DEFAULT_KEYWORD_FAIL,
    DEFAULT_KEYWORD_PASS,
    ON_FAIL_POLICIES,
    FctSequence,
    FctStep,
)

#: step table columns, in order (M160)
COLUMNS = ("#", "Name", "Type", "Channel", "Timeout (s)", "Retries")

_SPINE_TEXT = "ICT → Flash FAT → FCT body → Flash OOBE → Teardown"


def _split_csv(text: str) -> list:
    """Comma-separated keywords -> list (stripped, empties dropped)."""
    return [part.strip() for part in str(text).split(",") if part.strip()]


def _type_label(step: FctStep) -> str:
    """The left ``Type`` cell — the SAME sub-type the right Type combo
    shows, so the two can never disagree."""
    return step.type


class BuildFctSequencePanel(QWidget):
    """Node 06: edit the flat FCT sequence + keyword tables."""

    content_changed = Signal()
    advanced_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sequence = FctSequence(name="FCT Sequence")
        self._selected_index = -1
        self._loading = False
        # M159: console-authored steps land here from the shared buffer
        self._capture_buffer = None
        self._dut_type = "linux"

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
        # M159: pull the steps drafted from console annotations
        self.btn_import = QPushButton("Import from Console capture")
        self.btn_import.setToolTip(
            "Append the steps captured in the Test Work Flow console")
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self._import_capture)
        self.btn_delete = QPushButton("Delete")
        self.btn_move_up = QPushButton("Move up")
        self.btn_move_down = QPushButton("Move down")
        self.btn_advanced = QPushButton("Advanced…")
        self.btn_delete.clicked.connect(self._delete_step)
        self.btn_move_up.clicked.connect(lambda: self._move(-1))
        self.btn_move_down.clicked.connect(lambda: self._move(+1))
        self.btn_advanced.clicked.connect(self.advanced_requested.emit)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_import)
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
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((32, 0, 110, 90, 100, 70)):
            if column == 1:
                continue
            self.table.setColumnWidth(column, width)
        self.table.currentCellChanged.connect(self._on_row_selected)

        # M158f: master-detail split - the step table on the left, the
        # selected-step editor and the (collapsed) keyword tables on the
        # right.
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.table)
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        self._build_editor(right_lay)
        self._build_keywords(right_lay)
        right_lay.addStretch(1)
        split.addWidget(right)
        split.setStretchFactor(0, 45)
        split.setStretchFactor(1, 55)
        split.setSizes([450, 550])
        root.addWidget(split, 1)

        # M159: one-line authoring hint (never a block)
        self.lbl_recommend = QLabel()
        root.addWidget(self.lbl_recommend)
        self.set_dut_type("linux")

        self._render()

    # ------------------------------------------------------------- UI
    def _build_add_menu(self) -> QMenu:
        menu = QMenu(self.btn_add)
        for category in CATEGORY_ORDER:
            sub = menu.addMenu(category)
            for sub_type in STEP_CATEGORIES[category]:
                sub.addAction(
                    sub_type,
                    lambda c=category, t=sub_type: self._add_step(c, t))
        return menu

    def _build_editor(self, root) -> None:
        group = QGroupBox("Selected step")
        outer = QVBoxLayout(group)

        common = QFormLayout()
        self.edit_name = QLineEdit()
        self.edit_category = QComboBox()
        self.edit_category.setInsertPolicy(QComboBox.NoInsert)
        self.edit_category.addItems(list(CATEGORY_ORDER))
        self.edit_type = QComboBox()
        self.edit_type.setInsertPolicy(QComboBox.NoInsert)
        self.edit_timeout = QDoubleSpinBox()
        self.edit_timeout.setRange(0.0, 86400.0)
        self.edit_timeout.setDecimals(1)
        self.edit_timeout.setSpecialValueText("no timeout")
        self.edit_retries = QSpinBox()
        self.edit_retries.setRange(0, 99)
        self.edit_on_fail = QComboBox()
        self.edit_on_fail.setInsertPolicy(QComboBox.NoInsert)
        self.edit_on_fail.addItems(list(ON_FAIL_POLICIES))

        common.addRow("Name", self.edit_name)
        common.addRow("Category", self.edit_category)
        common.addRow("Type", self.edit_type)
        common.addRow("Timeout (s)", self.edit_timeout)
        common.addRow("Retries", self.edit_retries)
        common.addRow("On fail", self.edit_on_fail)
        outer.addLayout(common)

        self.stack = QStackedWidget()
        self._pages = {}
        for category in CATEGORY_ORDER:
            page = QWidget()
            page.setLayout(self._build_category_page(category))
            self._pages[category] = page
            self.stack.addWidget(page)
        outer.addWidget(self.stack)

        for widget in (self.edit_name,):
            widget.textChanged.connect(self._on_editor_edited)
        self.edit_category.currentTextChanged.connect(self._on_category_changed)
        self.edit_type.currentTextChanged.connect(self._on_editor_edited)
        self.edit_timeout.valueChanged.connect(self._on_editor_edited)
        self.edit_retries.valueChanged.connect(self._on_editor_edited)
        self.edit_on_fail.currentTextChanged.connect(self._on_editor_edited)
        root.addWidget(group)

    def _build_category_page(self, category: str) -> QFormLayout:
        """One stack page holding ONLY this category's fields."""
        form = QFormLayout()
        if category == CATEGORY_MEASUREMENT:
            self.edit_unit = QLineEdit()
            self.edit_min = QLineEdit()
            self.edit_max = QLineEdit()
            form.addRow("Unit", self.edit_unit)
            form.addRow("Min", self.edit_min)
            form.addRow("Max", self.edit_max)
            self._wire(self.edit_unit, self.edit_min, self.edit_max)
        elif category == CATEGORY_OPERATION:
            from mtkgui.engine.steps import OP_STEPS
            self.edit_op = QComboBox()
            self.edit_op.setInsertPolicy(QComboBox.NoInsert)
            self.edit_op.addItems(list(OP_STEPS))
            self.edit_args = QLineEdit()
            self.edit_args.setPlaceholderText(
                'Operation args JSON, e.g. {"rate_hz": 20000}')
            form.addRow("Operation", self.edit_op)
            form.addRow("Args", self.edit_args)
            self._wire(self.edit_op, self.edit_args)
        elif category == CATEGORY_CONSOLE:
            self.edit_channel = QLineEdit()
            self.edit_wait = QLineEdit()
            self.edit_wait.setPlaceholderText("Wait-for pattern")
            self.edit_send = QLineEdit()
            self.edit_send.setPlaceholderText("Command sent to the console")
            self.edit_send_enabled = QCheckBox("Send this command")
            self.edit_capture_pass = QLineEdit()
            self.edit_capture_pass.setPlaceholderText("Expect pass (comma)")
            self.edit_capture_fail = QLineEdit()
            self.edit_capture_fail.setPlaceholderText("Expect fail (comma)")
            self.edit_command = QLineEdit()
            self._command_box = with_snippets(
                self.edit_command, PAGE_WINDOWS)
            form.addRow("CLI command", self._command_box)
            form.addRow("Channel", self.edit_channel)
            form.addRow("Wait for", self.edit_wait)
            form.addRow("Send", self.edit_send)
            form.addRow("", self.edit_send_enabled)
            form.addRow("Expect pass", self.edit_capture_pass)
            form.addRow("Expect fail", self.edit_capture_fail)
            self._wire(self.edit_channel, self.edit_wait, self.edit_send,
                       self.edit_send_enabled, self.edit_capture_pass,
                       self.edit_capture_fail, self.edit_command)
            form.setRowVisible(self._command_box, False)
        elif category == CATEGORY_MESSAGE:
            self.edit_message = QLineEdit()
            self.edit_message.setPlaceholderText("Operator message body")
            form.addRow("Message", self.edit_message)
            self._wire(self.edit_message)
        elif category == CATEGORY_TRANSFER:
            self.edit_local = QLineEdit()
            self.edit_remote = QLineEdit()
            form.addRow("Local path", self.edit_local)
            form.addRow("Remote path", self.edit_remote)
            self._wire(self.edit_local, self.edit_remote)
        elif category == CATEGORY_EXTERNAL_GUI:
            self.edit_tool = QLineEdit()
            self.edit_tool.setPlaceholderText("External tool / GUI name")
            self.edit_prompt = QLineEdit()
            self.edit_prompt.setPlaceholderText("Operator prompt")
            form.addRow("Slot", self._slot_combo())
            form.addRow("Tool", self.edit_tool)
            form.addRow("Prompt", self.edit_prompt)
            self._wire(self.edit_tool, self.edit_prompt, self.edit_slot)
            form.setRowVisible(self.edit_slot, False)
        else:  # Wifi / Bluetooth (one field instance per page)
            field = QLineEdit()
            field.setPlaceholderText(
                'RF config JSON (fct_rf), e.g. {"mode": "rssi_only"}')
            setattr(self, self._rf_attr(category), field)
            form.addRow("RF config", field)
            self._wire(field)
        return form

    @staticmethod
    def _rf_attr(category: str) -> str:
        return f"edit_rf_{str(category).lower()}"

    def _slot_combo(self) -> QComboBox:
        self.edit_slot = QComboBox()
        self.edit_slot.setInsertPolicy(QComboBox.NoInsert)
        self.edit_slot.addItems(["fat", "oobe"])
        return self.edit_slot

    def _wire(self, *widgets) -> None:
        for widget in widgets:
            if isinstance(widget, QLineEdit):
                widget.textChanged.connect(self._on_editor_edited)
            elif isinstance(widget, QComboBox):
                widget.currentTextChanged.connect(self._on_editor_edited)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._on_editor_edited)

    def _build_keywords(self, root) -> None:
        group = QGroupBox("Keyword tables (sequence-level)")
        group.setCheckable(True)
        # M158f: sequence-level keywords are not per-row detail - they
        # start collapsed so the selected-step editor keeps the height.
        group.setChecked(False)
        self.keyword_group = group
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

    # --------------------------------------------------- console capture
    def set_capture_buffer(self, buffer) -> None:
        """Bind the application CaptureBuffer (main window owns it)."""
        self._capture_buffer = buffer
        if buffer is not None:
            buffer.subscribe(self._refresh_import_button)
        self._refresh_import_button()

    def set_dut_type(self, dut_type: str) -> None:
        """One-line authoring hint for the DUT kind (never a block)."""
        self._dut_type = str(dut_type or "linux")
        if self._dut_type == "bare_metal":
            self.lbl_recommend.setText(
                "Recommended: Annotate (listen only)")
        else:
            self.lbl_recommend.setText(
                "Recommended: Record (auto-split on TX)")

    def _refresh_import_button(self) -> None:
        self.btn_import.setEnabled(self._capture_buffer is not None
                                   and not self._capture_buffer.is_empty())

    def _import_capture(self) -> None:
        """Append every captured step, then clear the buffer."""
        if self._capture_buffer is None:
            return
        captured = self._capture_buffer.steps()
        if not captured:
            return
        sequence = self.sequence()
        names = {step.name for step in sequence.steps}
        for step in captured:
            if step.name in names:
                base, index = step.name, 2
                while f"{base} ({index})" in names:
                    index += 1
                step.name = f"{base} ({index})"
            names.add(step.name)
            sequence.steps.append(step)
        self._capture_buffer.clear()
        self.set_sequence(sequence)
        self.content_changed.emit()
        self.table.setCurrentCell(len(sequence.steps) - 1, 0)

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
                      step.channel,
                      "" if step.timeout_s == 0 else f"{step.timeout_s:g}",
                      str(step.retries))
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col == 1:
                    item.setToolTip(step.name)
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
            self.edit_category.setCurrentText(CATEGORY_ORDER[0])
            self.edit_type.clear()
            return
        self._loading = True
        try:
            self.edit_name.setText(step.name)
            # set category FIRST, then the type (never a stale label)
            self.edit_category.setCurrentText(step.category)
            self._repopulate_types(step.category)
            self.edit_type.setCurrentText(step.type)
            self.stack.setCurrentWidget(
                self._pages.get(step.category, self._pages[CATEGORY_ORDER[0]]))
            self.edit_timeout.setValue(float(step.timeout_s or 0.0))
            self.edit_retries.setValue(int(step.retries or 0))
            self.edit_on_fail.setCurrentText(step.on_fail)
            self._load_category_fields(step)
        finally:
            self._loading = False

    def _repopulate_types(self, category: str) -> None:
        types = list(STEP_CATEGORIES.get(category, ()))
        current = self.edit_type.currentText()
        self.edit_type.blockSignals(True)
        self.edit_type.clear()
        self.edit_type.addItems(types)
        if current in types:
            self.edit_type.setCurrentText(current)
        self.edit_type.blockSignals(False)

    def _load_category_fields(self, step: FctStep) -> None:
        p = dict(step.params or {})
        category = step.category
        if category == CATEGORY_MEASUREMENT:
            self.edit_unit.setText(str(p.get("unit", "")))
            self.edit_min.setText(str(p.get("min", "")))
            self.edit_max.setText(str(p.get("max", "")))
        elif category == CATEGORY_OPERATION:
            self.edit_op.setCurrentText(
                str(p.get("op", "") or (step.name if step.name else "")))
            args = p.get("args")
            self.edit_args.setText(
                json.dumps(args) if isinstance(args, dict) and args else "")
        elif category == CATEGORY_CONSOLE:
            self.edit_channel.setText(step.channel)
            self.edit_wait.setText(str(p.get("wait_pattern", "") or
                                       p.get("expect_pass_re", "")))
            self.edit_send.setText(str(p.get("send", step.command) or ""))
            self.edit_send_enabled.setChecked(
                bool(p.get("send_enabled", bool(step.command))))
            self.edit_capture_pass.setText(", ".join(step.expect_pass))
            self.edit_capture_fail.setText(", ".join(step.expect_fail))
            self.edit_command.setText(step.command)
            form = self._pages[CATEGORY_CONSOLE].layout()
            form.setRowVisible(self._command_box, step.type == "cli")
        elif category == CATEGORY_MESSAGE:
            self.edit_message.setText(str(p.get("message", "") or ""))
        elif category == CATEGORY_TRANSFER:
            self.edit_local.setText(str(p.get("local", "") or ""))
            self.edit_remote.setText(str(p.get("remote", "") or ""))
        elif category == CATEGORY_EXTERNAL_GUI:
            self.edit_tool.setText(str(p.get("tool", "") or ""))
            self.edit_prompt.setText(str(p.get("message", "") or
                                         p.get("flash_gui_prompt", "") or ""))
            self.edit_slot.setCurrentText(str(p.get("slot", "fat")))
            form = self._pages[CATEGORY_EXTERNAL_GUI].layout()
            form.setRowVisible(self.edit_slot, step.type == "flash")
        elif category in (CATEGORY_WIFI, CATEGORY_BLUETOOTH):
            rf = p.get("fct_rf")
            getattr(self, self._rf_attr(category)).setText(
                json.dumps(rf) if isinstance(rf, dict) and rf else "")

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

    def _on_category_changed(self, category: str) -> None:
        if self._loading:
            return
        step = self._selected_step()
        if step is None:
            return
        self._loading = True
        try:
            step.category = category
            self._repopulate_types(category)
            if step.type not in STEP_CATEGORIES.get(category, ()):
                step.type = STEP_CATEGORIES[category][0]
                self.edit_type.setCurrentText(step.type)
            self.stack.setCurrentWidget(
                self._pages.get(category, self._pages[CATEGORY_ORDER[0]]))
            self._load_category_fields(step)
        finally:
            self._loading = False
        self.content_changed.emit()
        self._reload_row()

    def _on_editor_edited(self, *_args) -> None:
        if self._loading:
            return
        step = self._selected_step()
        if step is None:
            return
        step.name = self.edit_name.text().strip()
        step.category = self.edit_category.currentText()
        step.type = self.edit_type.currentText()
        step.timeout_s = float(self.edit_timeout.value())
        step.retries = int(self.edit_retries.value())
        step.on_fail = self.edit_on_fail.currentText()
        self._write_category_fields(step)
        self.content_changed.emit()
        self._reload_row()

    def _write_category_fields(self, step: FctStep) -> None:
        """Persist ONLY the active category's page (no cross-leaks)."""
        p = dict(step.params or {})
        category = step.category
        if category == CATEGORY_MEASUREMENT:
            p["unit"] = self.edit_unit.text().strip()
            p["min"] = self.edit_min.text().strip()
            p["max"] = self.edit_max.text().strip()
        elif category == CATEGORY_OPERATION:
            p["op"] = self.edit_op.currentText()
            text = self.edit_args.text().strip()
            if text:
                try:
                    args = json.loads(text)
                except ValueError:
                    args = None
                if isinstance(args, dict):
                    p["args"] = args
            else:
                p.pop("args", None)
        elif category == CATEGORY_CONSOLE:
            step.channel = self.edit_channel.text().strip()
            if step.type == "cli":
                step.command = self.edit_command.text().strip()
                p["send"] = step.command
            else:
                p["send"] = self.edit_send.text()
                p["send_enabled"] = self.edit_send_enabled.isChecked()
            p["wait_pattern"] = self.edit_wait.text().strip()
            step.expect_pass = _split_csv(self.edit_capture_pass.text())
            step.expect_fail = _split_csv(self.edit_capture_fail.text())
        elif category == CATEGORY_MESSAGE:
            p["message"] = self.edit_message.text()
        elif category == CATEGORY_TRANSFER:
            p["local"] = self.edit_local.text().strip()
            p["remote"] = self.edit_remote.text().strip()
        elif category == CATEGORY_EXTERNAL_GUI:
            p["tool"] = self.edit_tool.text().strip()
            p["message"] = self.edit_prompt.text()
            if step.type == "flash":
                p["slot"] = self.edit_slot.currentText()
        elif category in (CATEGORY_WIFI, CATEGORY_BLUETOOTH):
            text = getattr(self, self._rf_attr(category)).text().strip()
            if text:
                try:
                    rf = json.loads(text)
                except ValueError:
                    rf = None
                if isinstance(rf, dict):
                    p["fct_rf"] = rf
            else:
                p.pop("fct_rf", None)
        step.params = p
        # per-type visibility inside the active page
        if category == CATEGORY_CONSOLE:
            self._pages[CATEGORY_CONSOLE].layout().setRowVisible(
                self._command_box, step.type == "cli")
        elif category == CATEGORY_EXTERNAL_GUI:
            self._pages[CATEGORY_EXTERNAL_GUI].layout().setRowVisible(
                self.edit_slot, step.type == "flash")

    def _reload_row(self) -> None:
        """Re-render the table so the Type cell follows the editor."""
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
    def _add_step(self, category: str, sub_type: str) -> None:
        params = {}
        if category == CATEGORY_EXTERNAL_GUI and sub_type == "flash":
            params = {"slot": "fat"}
        self._sequence.steps.append(
            FctStep(name=f"New {sub_type}", category=category,
                    type=sub_type, params=params))
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
