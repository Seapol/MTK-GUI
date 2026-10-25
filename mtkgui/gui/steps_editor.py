# -*- coding: utf-8 -*-
"""Shared sequence step editor (task: single sequence source).

Extracted verbatim from ``mtkgui.test_workflow_page._SequenceEditorDialog``
so both Build dialogs (ICT / FCT Test Work Flow Sequence) and the page can
reuse ONE editor instead of each owning a private copy - that duplication
was the root of the "two conflicting edit sources" problem.

The dialog edits a whole sequence: the step list (test items / standard
operations / flash operations / Delay), per-step enable flags, wait and
timeout values.  It works on copies and only writes them back on accept.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..engine import (
    FCT_METHODS,
    METHOD_R_GND,
    OP_STEPS,
    fct_kind_from_name as _fct_kind_from_name,
    normalize_ict_method,
    op_step as _op_step,
    op_summary as _op_summary,
)


class StepsEditorDialog(QDialog):
    """Dialog for reordering, adding, removing, editing, and duplicating
    test case steps. Works on copies; only writes back on accept."""

    def __init__(self, kind, steps, enables, waits, timeouts, parent=None,
                 kinds=None, op_params=None, embedded=False):
        super().__init__(parent)
        # embedded: the dialog is dropped into a host widget (the block-07
        # FCT panel) that owns its own OK / Cancel buttons - the editor
        # then omits its button box and the fixed window size
        self._embedded = bool(embedded)
        self._kind = kind  # "ict" or "fct"
        self._steps = list(steps)
        self._enables = list(enables)
        self._waits = list(waits)
        self._timeouts = list(timeouts)
        # FCT only: parallel Test Method list (ICT steps carry the kind
        # inside their step tuples)
        self._kinds = list(kinds) if kinds is not None else None
        # FCT only: operation parameters for kind == "op" rows
        self._op_params = (list(op_params)
                           if op_params is not None else None)
        self._build_ui()
        self._populate()

    def _lists(self):
        """All parallel step lists (kinds / op params included for FCT)."""
        base = (self._steps, self._enables, self._waits, self._timeouts)
        if self._kinds is not None:
            base += (self._kinds,)
        if self._op_params is not None:
            base += (self._op_params,)
        return base

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # --- list + button column ---
        top = QHBoxLayout()
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemDoubleClicked.connect(self._on_edit)
        self.list_widget.currentRowChanged.connect(self._update_buttons)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        top.addWidget(self.list_widget, 1)

        btn_col = QVBoxLayout()
        self.btn_up = QPushButton("Move Up")
        self.btn_down = QPushButton("Move Down")
        self.btn_add = QPushButton("Add")
        # Add offers every test type ICT / FCT support (dropdown menu)
        self.btn_add.setMenu(self._make_add_menu())
        self.btn_remove = QPushButton("Remove")
        self.btn_edit = QPushButton("Edit")
        self.btn_duplicate = QPushButton("Duplicate")
        for btn in (self.btn_up, self.btn_down, self.btn_add,
                    self.btn_remove, self.btn_edit, self.btn_duplicate):
            btn_col.addWidget(btn)
        btn_col.addStretch()
        top.addLayout(btn_col)
        layout.addLayout(top)

        self.btn_up.clicked.connect(self._on_move_up)
        self.btn_down.clicked.connect(self._on_move_down)
        self.btn_add.clicked.connect(self._on_add)
        self.btn_remove.clicked.connect(self._on_remove)
        self.btn_edit.clicked.connect(self._on_edit)
        self.btn_duplicate.clicked.connect(self._on_duplicate)

        # --- ok / cancel (omitted when embedded: the host dialog owns
        # its own accept / reject buttons) ---
        if not self._embedded:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

            # M10-FIX2 F8: the list + button column + preview need ~1000
            # px, not 1170 - measured with the 96317 ICT sequence
            self.resize(1000, 690)

    def _make_add_menu(self):
        """Dropdown for the Add button: every supported step type."""
        menu = QMenu(self)
        if self._kind == "ict":
            # every standard operation (with its default parameters)
            # plus a custom operation, the generic measurement test and
            # the plain Delay wait step
            types = [(f"Operation: {n}", _op_step(n)) for n in OP_STEPS]
            types += [
                ("Operation: Custom",
                 ("op", "New Operation", "—", "—", "—", "—")),
                # M19f: the generic "Test (measurement)" is gone - the
                # concrete measurement methods are offered instead
                ("R-GND — rail-to-ground impedance (measurement)",
                 (METHOD_R_GND, "New Test", "Ω", "—", "—", "—")),
                ("DAQ AI Sequences — power-rails up sequence "
                 "(measurement)",
                 ("DAQ AI", "New Test", "V", "—", "—", "—")),
                ("Voltage — power rail level (measurement)",
                 ("Power Voltage", "New Test", "V", "—", "—", "—")),
                ("Clock Hz — clock frequency (measurement)",
                 ("Clock Hz", "New Test", "kHz", "—", "—", "—")),
                ("Delay — plain wait (ms)",
                 ("delay", "Delay", "ms", "—", "—", "—")),
            ]
        else:
            # FCT Add dropdown: standard operations first, then every
            # supported test method with a matching template name
            types = [(f"Operation: {n}", n, "op", dict(OP_STEPS[n]))
                     for n in OP_STEPS]
            types += [
                ("MessageOK — notice dialog (Ok -> Done)",
                 "MessageOK: New Test", "MessageOK"),
                ("MessageYesNo — operator Yes / No dialog",
                 "MessageYesNo: New Test", "MessageYesNo"),
                ("MessageGoStop — Go / Stop dialog (No stops the run)",
                 "MessageGoStop: New Test", "MessageGoStop"),
                ("MessageOKtoConsole — wait console msg, OK notice "
                 "(no command)",
                 "MessageOKtoConsole: 'ready' (expected)",
                 "MessageOKtoConsole"),
                ("MessageYesNotoConsole — wait console msg, Yes / No "
                 "(always continues)",
                 "MessageYesNotoConsole: 'ready' (expected)",
                 "MessageYesNotoConsole"),
                ("MessageGoStoptoConsole — wait console msg, Go / Stop "
                 "(No stops the run)",
                 "MessageGoStoptoConsole: 'ready' (expected)",
                 "MessageGoStoptoConsole"),
                ("SendtoConsole — send command to console",
                 "SendtoConsole: COM1, 'cmd'", "SendtoConsole"),
                ("WaitforConsole — wait for a console keyword",
                 "WaitforConsole: COM1, 'Pass' (expected)",
                 "WaitforConsole"),
                ("CapturefromConsole — instant buffer capture",
                 "CapturefromConsole: COM1, 'Pass' (expected)",
                 "CapturefromConsole"),
                ("Delay — plain wait (ms)",
                 "Delay: 1000 ms", "Delay"),
                ("SendtoCLI — run CLI command, check Pass / Success",
                 "SendtoCLI: \"cmd --run\", 'Pass'/'Success' (expected)",
                 "SendtoCLI"),
                ("WaitforCLI — wait for a CLI keyword",
                 "WaitforCLI: 'Pass' (expected)", "WaitforCLI"),
                ("CapturefromCLI — instant CLI buffer capture",
                 "CapturefromCLI: 'Pass' (expected)", "CapturefromCLI"),
                ("WIFI — Wi-Fi connectivity test",
                 "WIFI: scan and associate", "WIFI"),
                ("Bluetooth — Bluetooth connectivity test",
                 "Bluetooth: scan and pair", "Bluetooth"),
            ]
        for entry in types:
            act = menu.addAction(entry[0])
            method = entry[2] if len(entry) > 2 else None
            params = entry[3] if len(entry) > 3 else None
            act.triggered.connect(
                lambda _checked=False, s=entry[1], m=method, p=params:
                    self._on_add(s, m, p))
        return menu

    def _populate(self):
        lw = self.list_widget
        lw.setUpdatesEnabled(False)
        try:
            lw.clear()
            for i, step in enumerate(self._steps):
                label = self._label_for(i, step)
                item = QListWidgetItem(label)
                item.setCheckState(
                    Qt.CheckState.Checked if self._enables[i]
                    else Qt.CheckState.Unchecked)
                lw.addItem(item)
        finally:
            lw.setUpdatesEnabled(True)
        self._update_buttons()

    def _label_for(self, i, step):
        if self._kind == "ict":
            kind, name = step[0], step[1]
            tag = ("[op]" if kind == "op"
                   else f"[{kind}]" if kind != "test" else "[test]")
            if kind == "op" and len(step) > 6 and step[6]:
                return f"{i+1:3d}. {tag} {name} · {_op_summary(step[6])}"
            return f"{i+1:3d}. {tag} {name}"
        else:
            if self._kinds is not None:
                m = self._kinds[i] if i < len(self._kinds) else ""
                return f"{i+1:3d}. [{m}] {step}"
            return f"{i+1:3d}. {step}"

    def _update_buttons(self):
        r = self.list_widget.currentRow()
        n = len(self._steps)
        self.btn_up.setEnabled(r > 0)
        self.btn_down.setEnabled(0 <= r < n - 1)
        # user direction 2026-10-14: zero test items are legal per
        # stage (ICT-only, FCT-only - a stage may run EMPTY); only the
        # BOTH-empty case is warned about elsewhere, so the last row
        # can be removed too
        self.btn_remove.setEnabled(n > 0)
        self.btn_edit.setEnabled(0 <= r < n)
        self.btn_duplicate.setEnabled(0 <= r < n)

    # ------------------------------------------------------- actions
    def _on_move_up(self):
        r = self.list_widget.currentRow()
        if r <= 0:
            return
        self._swap(r, r - 1)
        self._populate()
        self.list_widget.setCurrentRow(r - 1)

    def _on_move_down(self):
        r = self.list_widget.currentRow()
        if r < 0 or r >= len(self._steps) - 1:
            return
        self._swap(r, r + 1)
        self._populate()
        self.list_widget.setCurrentRow(r + 1)

    def _swap(self, i, j):
        for lst in self._lists():
            lst[i], lst[j] = lst[j], lst[i]

    def _on_add(self, new_step=None, new_kind=None, new_params=None):
        """Add a new step of the chosen type after the current row and
        open edit (new_step comes from the Add dropdown; the fallback
        keeps the blank-step behavior for programmatic callers)."""
        if new_step is None:
            new_step = (("test", "New Test", "—", "—", "—", "—")
                        if self._kind == "ict" else "New Test")
        r = self.list_widget.currentRow()
        if r < 0:
            r = len(self._steps) - 1    # no selection -> append at end
        for lst in self._lists():
            lst.insert(r + 1, None)
        self._steps[r + 1] = new_step
        self._enables[r + 1] = True
        self._waits[r + 1] = 100
        self._timeouts[r + 1] = 5000
        if self._kinds is not None:
            if new_kind == "op":
                self._kinds[r + 1] = "op"
            elif new_kind in FCT_METHODS:
                self._kinds[r + 1] = new_kind
            else:
                self._kinds[r + 1] = "MessageOK"
        if self._op_params is not None:
            self._op_params[r + 1] = (dict(new_params)
                                      if new_kind == "op" and new_params
                                      else None)
        self._populate()
        self.list_widget.setCurrentRow(r + 1)
        self._on_edit()

    def _on_remove(self):
        r = self.list_widget.currentRow()
        if r < 0:
            return
        for lst in self._lists():
            del lst[r]
        self._populate()
        self.list_widget.setCurrentRow(min(r, len(self._steps) - 1))

    def _on_edit(self, _item=None):
        r = self.list_widget.currentRow()
        if r < 0:
            return
        if self._kind == "ict":
            edited = self._edit_ict_step(r)
        else:
            edited = self._edit_fct_step(r)
        if edited:
            self._populate()
            self.list_widget.setCurrentRow(r)

    def _on_duplicate(self):
        r = self.list_widget.currentRow()
        if r < 0:
            return
        for lst in self._lists():
            lst.insert(r + 1, lst[r])
        self._populate()
        self.list_widget.setCurrentRow(r + 1)

    def _on_item_changed(self, item):
        """Sync checkbox state to the enables list."""
        r = self.list_widget.row(item)
        if 0 <= r < len(self._enables):
            self._enables[r] = item.checkState() == Qt.CheckState.Checked

    # ------------------------------------------------------- edit dialogs
    #: Test Method -> unit (the Unit field is auto-filled, user
    #: direction) and -> the net category offered in the Net combo
    ICT_METHOD_UNITS = {
        METHOD_R_GND: "Ω",
        "Power Voltage": "V",
        # M19g: clock limits are edited/displayed in kHz (32768 Hz =
        # 32.768 kHz, 4 MHz = 4000.000 kHz); the stored step stays Hz
        "Clock Hz": "kHz",
        "DAQ AI": "V",
        "test": "—",
        "op": "—",
        "delay": "ms",
    }
    #: M19f: Test Method combo shows concrete method LABELS; each item
    #: carries the internal step kind as userData (R-GND / Power
    #: Voltage / DAQ AI / Clock Hz stay the stored kinds, so the
    #: runner / reports / 04 bridge keep working unchanged)
    ICT_KIND_ITEMS = (
        ("R-GND", METHOD_R_GND),
        ("Voltage", "Power Voltage"),
        ("DAQ AI Sequences", "DAQ AI"),
        ("Clock Hz", "Clock Hz"),
        ("delay", "delay"),
    )

    @staticmethod
    def _kind_label(kind: str, name: str) -> str:
        """Map a stored kind to its combo label.  A legacy generic
        'test' row is classified by its NAME prefix (R-GND - x /
        Power Voltage - x / Clock Hz - x / DAQ AI - x)."""
        for label, internal in StepsEditorDialog.ICT_KIND_ITEMS:
            if kind == internal:
                return label
        if kind == "test" and name:
            for label, internal in StepsEditorDialog.ICT_KIND_ITEMS:
                if name == internal or name.startswith(internal):
                    return label
        return StepsEditorDialog.ICT_KIND_ITEMS[0][0]  # fallback R-GND

    ICT_METHOD_NET_CATEGORY = {
        METHOD_R_GND: "Power",
        "Power Voltage": "Power",
        "DAQ AI": "Power",
        "Clock Hz": "Clock",
        "test": "GPIO",
        "op": "",
        "delay": "",
    }

    def _net_choices(self, method: str) -> list[str]:
        """The nets offered for one Test Method (user direction: the
        Net combo follows the method): Power nets for the R-GND /
        voltage methods, Clock nets for Clock Hz, Control IO nets for
        the generic test; the DAQ AI method has NO free net - a
        read-only count of the DAQ AI rails assigned in Channel
        Allocation."""
        if method == "DAQ AI":
            from .yamlbuild.ict_sequence import daq_ai_net_label
            # defensive getattr: this helper also runs on the
            # _SequenceEditorDialog copy, where the provider is wired
            # by the opener (_open_sequence_editor) - never assume
            provider = getattr(self, "daq_ai_rail_count_provider", None)
            count = provider() if callable(provider) else 0
            return [daq_ai_net_label(count)]
        category = self.ICT_METHOD_NET_CATEGORY.get(method, "")
        catalog = (self.net_catalog_provider() if
                   self.net_catalog_provider else {}) or {}
        nets = sorted(name for name, info in catalog.items()
                      if (info or {}).get("category") == category)
        return nets if nets else ["—"]

    def _edit_ict_step(self, r):
        step = self._steps[r]
        if step[0] == "op":
            return self._edit_op_step(r, step)
        kind, name, unit, measured, lo, hi = step[:6]
        kind = normalize_ict_method(kind)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Step {r + 1} — Edit")
        form = QFormLayout(dlg)
        # Test Method FIRST (user direction); Unit auto-fills, the
        # Expected / Min / Max fields are numeric (the "Measured" slot
        # holds the EXPECTED value: Min = Expected * (1 - tol), Max =
        # Expected * (1 + tol) - user direction)
        kind_combo = QComboBox()
        for label, internal in self.ICT_KIND_ITEMS:
            kind_combo.addItem(label, internal)
        kind_combo.setCurrentText(self._kind_label(kind, name))
        unit_edit = QLineEdit(unit)
        unit_edit.setReadOnly(True)
        enable_cb = QCheckBox()
        enable_cb.setChecked(self._enables[r])
        wait_spin = QSpinBox()
        wait_spin.setRange(0, 99999)
        wait_spin.setValue(self._waits[r])
        wait_spin.setSuffix(" ms")
        timeout_spin = QSpinBox()
        timeout_spin.setRange(0, 999999)
        timeout_spin.setValue(self._timeouts[r])
        timeout_spin.setSuffix(" ms")
        # Net combo: the choices follow the Test Method; a legacy name
        # not in the category list stays selectable (prepended)
        net_combo = QComboBox()
        choices = self._net_choices(kind)
        if name and name not in choices and kind != "DAQ AI":
            choices.insert(0, name)
        net_combo.addItems(choices)
        if name in choices:
            net_combo.setCurrentText(name)
        # the DAQ AI Net cell is derived from Channel Allocation and
        # read-only (no free net)
        net_combo.setEnabled(kind != "DAQ AI")

        def _numeric(value: str, decimals: int = 3) -> QDoubleSpinBox:
            # M19f: limits keep 3 decimals and a 0.001 step (V and kHz);
            # the R-GND Min cell switches to 0 decimals / step 1
            spin = QDoubleSpinBox()
            spin.setRange(-1e9, 1e9)
            spin.setDecimals(decimals)
            spin.setSingleStep(10 ** -decimals)
            spin.setSpecialValueText("—")
            spin.setMinimum(-1e9)
            try:
                spin.setValue(float(value))
            except (TypeError, ValueError):
                spin.setValue(spin.minimum())   # the "—" state
            return spin

        # M19g: Clock Hz rows open in kHz (3 decimals) and are saved
        # back as Hz - the display/editing unit is kHz, the stored
        # step and the runner keep Hz at full precision.  The internal
        # kind comes from the Test Method combo (a legacy "test" row
        # gets its real method from _kind_label), so a clock step that
        # arrived as ("test", "Clock Hz - x", ...) still scales.
        def _clock_scale():
            return 1000.0 if (kind_combo.currentData() or "") == "Clock Hz" else 1.0

        def _to_display(value: str, scale: float):
            try:
                return float(value) / scale
            except (TypeError, ValueError):
                return value          # "—" stays the dash state

        measured_spin = _numeric(_to_display(measured, _clock_scale()))
        lo_spin = _numeric(_to_display(lo, _clock_scale()))
        hi_spin = _numeric(_to_display(hi, _clock_scale()))
        form.addRow("Test Method:", kind_combo)
        form.addRow("Net:", net_combo)
        form.addRow("Enable:", enable_cb)
        form.addRow("Wait:", wait_spin)
        form.addRow("Timeout:", timeout_spin)
        form.addRow("Unit:", unit_edit)
        form.addRow("Expected:", measured_spin)
        form.addRow("Min:", lo_spin)
        form.addRow("Max:", hi_spin)

        def _clamp_bounds() -> None:
            """M19f: Min must never exceed Expected, Max must never be
            below Expected (both clamp to Expected while it is set)."""
            exp = measured_spin.value()
            if exp > measured_spin.minimum():
                if lo_spin.value() > exp:
                    lo_spin.setValue(exp)
                if hi_spin.value() < exp:
                    hi_spin.setValue(exp)

        def _sync_unit(method_label: str) -> None:
            # M19f: the stored kind (combo userData) drives unit + policy
            internal = kind_combo.currentData() or ""
            unit_edit.setText(
                self.ICT_METHOD_UNITS.get(internal, "—"))
            # the Net choices follow the method too (keep the old
            # name selectable when it drops out of the category)
            current = net_combo.currentText()
            fresh = self._net_choices(internal)
            if current and current not in fresh and internal != "DAQ AI":
                fresh.insert(0, current)
            net_combo.blockSignals(True)
            net_combo.clear()
            net_combo.addItems(fresh)
            if current in fresh:
                net_combo.setCurrentText(current)
            net_combo.blockSignals(False)
            # DAQ AI Net is derived + read-only; other methods editable
            net_combo.setEnabled(internal != "DAQ AI")
            # M19f: numeric policy per method - R-GND keeps ONLY a Min
            # (integer ohm; Expected/Max carry no value and are locked);
            # everything else stays 3 decimals / 0.001 step
            if internal == METHOD_R_GND:
                lo_spin.setDecimals(0)
                lo_spin.setSingleStep(1)
                measured_spin.setEnabled(False)
                measured_spin.setValue(measured_spin.minimum())
                hi_spin.setEnabled(False)
                hi_spin.setValue(hi_spin.minimum())
            else:
                lo_spin.setDecimals(3)
                lo_spin.setSingleStep(0.001)
                measured_spin.setEnabled(True)
                hi_spin.setEnabled(True)

        _sync_unit(kind_combo.currentText())
        kind_combo.currentTextChanged.connect(_sync_unit)
        # M19f: Min <= Expected <= Max enforced live
        measured_spin.valueChanged.connect(lambda _v: _clamp_bounds())
        lo_spin.valueChanged.connect(lambda v: _clamp_bounds()
                                     if measured_spin.value()
                                     > measured_spin.minimum() else None)
        hi_spin.valueChanged.connect(lambda v: _clamp_bounds()
                                     if measured_spin.value()
                                     > measured_spin.minimum() else None)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False

        def _num_text(spin: QDoubleSpinBox) -> str:
            # M19f: keep the decimals of the cell (3 for V/kHz, 0 for
            # the R-GND Min), never trimmed; a locked cell (disabled,
            # e.g. the R-GND Expected / Max) always saves "—"
            if not spin.isEnabled() or spin.value() <= spin.minimum():
                return "—"
            if _clock_scale() > 1:
                # M19g: the kHz spinner holds Hz/1000 - store the full
                # Hz value (double precision, 3 decimals) so 32768.1 Hz
                # does not lose its fraction through the kHz display
                return f"{spin.value() * _clock_scale():.3f}"
            return f"{spin.value():.{spin.decimals()}f}"

        # M19g: the clock row's Unit field shows "kHz" (user direction)
        # but the stored step keeps unit "Hz" and Hz values - the
        # runner / instruments / test-workflow table all stay Hz
        stored_unit = unit_edit.text().strip() or "—"
        if _clock_scale() > 1:
            stored_unit = "Hz"
        self._steps[r] = (
            kind_combo.currentData() or kind_combo.currentText(),
            net_combo.currentText().strip() or name,
            stored_unit,
            _num_text(measured_spin),
            _num_text(lo_spin),
            _num_text(hi_spin),
        )
        self._enables[r] = enable_cb.isChecked()
        self._waits[r] = wait_spin.value()
        self._timeouts[r] = timeout_spin.value()
        return True

    def _edit_op_step(self, r, step):
        """Edit one operation step: pick a standard step and configure
        its parameters (instruments / fixture signal+level / PSU
        setpoints) in per-type fields. Used by both ICT (step tuple)
        and FCT (name string + parallel kind / op-params lists)."""
        if self._kind == "ict":
            name = step[1]
            params = dict(step[6]) if len(step) > 6 and step[6] else {}
        else:
            name = step
            params = (dict(self._op_params[r])
                      if self._op_params is not None
                      and r < len(self._op_params)
                      and self._op_params[r] else {})

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Step {r + 1} — Edit (Operation)")
        outer = QVBoxLayout(dlg)

        head = QFormLayout()
        op_combo = QComboBox()
        op_combo.setEditable(True)
        op_combo.addItems(list(OP_STEPS) + ["Custom Operation"])
        op_combo.setCurrentText(
            name if (name in OP_STEPS or not name) else "Custom Operation")
        head.addRow("Standard Step:", op_combo)
        outer.addLayout(head)

        # per-type parameter area, rebuilt when the step type changes
        param_form = QFormLayout()
        param_box = QWidget()
        param_box.setLayout(param_form)
        outer.addWidget(param_box)
        fields = {}
        # flash: the mode combo is re-read from here (not from the saved
        # params) because switching it only toggles the manual-only rows
        state = {"mode": str(params.get("mode") or "auto")}

        def current_type():
            return OP_STEPS.get(op_combo.currentText().strip(),
                                {}).get("type", "custom")

        def rebuild_params():
            fields.clear()
            while param_form.rowCount():
                param_form.removeRow(0)
            t = current_type()
            if t in ("instruments", "reset"):
                chosen = set(params.get("instruments", []) or [])
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                checks = []
                for inst in ("DAQM", "DAQ", "PSU"):
                    cb = QCheckBox(inst)
                    cb.setChecked(not chosen or inst in chosen)
                    h.addWidget(cb)
                    checks.append(cb)
                fields["instruments"] = checks
                param_form.addRow("Instruments:", row)
            elif t == "fixture":
                sig = QComboBox()
                sig.addItems(["press", "inpos", "estop"])
                sig.setCurrentText(params.get("signal", "press"))
                lvl = QComboBox()
                lvl.addItems(["H", "L"])
                lvl.setCurrentText(params.get("level", "H"))
                fields["signal"], fields["level"] = sig, lvl
                param_form.addRow("Signal:", sig)
                param_form.addRow("Level:", lvl)
            elif t == "power":
                if "voltage" in params or \
                        op_combo.currentText().strip() == "Power On DUT":
                    volt = QDoubleSpinBox()
                    volt.setRange(0.0, 60.0)
                    volt.setDecimals(2)
                    volt.setSuffix(" V")
                    volt.setValue(float(params.get("voltage", 5.0)))
                    curr = QDoubleSpinBox()
                    curr.setRange(0.0, 12.5)
                    curr.setDecimals(2)
                    curr.setSuffix(" A")
                    curr.setValue(float(params.get("current", 1.0)))
                    fields["voltage"], fields["current"] = volt, curr
                    param_form.addRow("Voltage:", volt)
                    param_form.addRow("Current limit:", curr)
                else:
                    param_form.addRow(
                        QLabel("N5747A output OFF — no setpoints."))
            elif t == "flash":
                # user direction 2026-10-17: dual-path firmware flash.
                # "auto" drives the third-party CLI tool (the judging
                # rules live in the Equipment page tool profile),
                # "manual" opens the third-party GUI and takes the
                # operator GO / STOP answer as the verdict.
                _slot = (OP_STEPS.get(op_combo.currentText().strip(),
                                      {}).get("slot")
                         or params.get("slot") or "fat")
                mode = QComboBox()
                mode.addItems(["auto", "manual"])
                mode.setCurrentText(state["mode"])
                tool = QComboBox()
                tool.setEditable(True)
                try:
                    from ..equipment_page import _DEVICE_EDITORS
                    tool.addItems([name for block, name in _DEVICE_EDITORS
                                   if block == "probes"])
                except Exception:            # pragma: no cover - headless
                    tool.addItems(["J-Link"])
                tool.setCurrentText(str(params.get("tool") or "J-Link"))
                image = QLineEdit(str(params.get("image") or ""))
                image.setPlaceholderText(
                    "empty -> firmware.<slot>_image from the project YAML")
                device = QLineEdit(str(params.get("device") or ""))
                address = QLineEdit(str(params.get("address") or ""))
                address.setPlaceholderText("e.g. 0x60000000 (optional)")
                baud = QSpinBox()
                baud.setRange(0, 100000)
                baud.setSuffix(" kHz")
                baud.setValue(int(params.get("baudrate") or 4000))
                verify = QCheckBox()
                verify.setChecked(bool(params.get("verify", True)))
                reset_run = QCheckBox()
                reset_run.setChecked(bool(params.get("reset_run", True)))
                erase = QCheckBox()
                erase.setChecked(bool(params.get("erase", False)))
                tmo = QSpinBox()
                tmo.setRange(0, 3600)
                tmo.setSuffix(" s")
                tmo.setValue(int(float(params.get("timeout_s") or 120)))
                retries = QSpinBox()
                retries.setRange(0, 5)
                retries.setValue(int(params.get("retries") or 0))
                fields.update(mode=mode, tool=tool, image=image,
                              device=device, address=address,
                              baudrate=baud, verify=verify,
                              reset_run=reset_run, erase=erase,
                              timeout_s=tmo, retries=retries)
                param_form.addRow("Mode:", mode)
                param_form.addRow("Programmer tool:", tool)
                param_form.addRow("Image:", image)
                param_form.addRow("Device:", device)
                param_form.addRow("Address:", address)
                param_form.addRow("Baudrate:", baud)
                param_form.addRow("Verify after write:", verify)
                param_form.addRow("Reset & run:", reset_run)
                param_form.addRow("Erase before write:", erase)
                param_form.addRow("Write timeout:", tmo)
                param_form.addRow("Driver retries:", retries)
                # manual-only rows live in their own container so the
                # mode switch only toggles VISIBILITY - rebuilding the
                # form from inside the combo's own signal handler would
                # delete the emitting widget (segfault)
                launch = QLineEdit(str(params.get("launch") or ""))
                launch.setPlaceholderText(
                    "empty -> the third-party GUI is NOT launched")
                msg = QLineEdit(str(
                    params.get("message")
                    or f"Flash the {_slot} firmware via the "
                       "third-party tool, then answer GO / STOP"))
                mtmo = QSpinBox()
                mtmo.setRange(0, 999999)
                mtmo.setSuffix(" s")
                mtmo.setValue(int(params.get("message_timeout_s") or 0))
                fields.update(launch=launch, message=msg,
                              message_timeout_s=mtmo)
                manual_box = QWidget()
                manual_form = QFormLayout(manual_box)
                manual_form.setContentsMargins(0, 0, 0, 0)
                manual_form.addRow("GUI path (manual):", launch)
                manual_form.addRow("Operator prompt:", msg)
                manual_form.addRow("Answer timeout:", mtmo)
                manual_box.setVisible(state["mode"] == "manual")

                def _on_mode(text):
                    state["mode"] = text
                    manual_box.setVisible(text == "manual")

                mode.currentTextChanged.connect(_on_mode)
                param_form.addRow(manual_box)
            elif t == "dio_out":
                channels = QLineEdit(str(
                    params.get("channels")
                    or OP_STEPS.get(op_combo.currentText().strip(),
                                    {}).get("channels") or "DIO01-DIO08"))
                channels.setPlaceholderText("e.g. DIO01-DIO08")
                pattern = QLineEdit(str(
                    params.get("pattern")
                    or OP_STEPS.get(op_combo.currentText().strip(),
                                    {}).get("pattern") or "0x00"))
                pattern.setPlaceholderText("hex (0x3C) or DIO01=1,DIO03=0")
                fields["channels"], fields["pattern"] = channels, pattern
                param_form.addRow("Channels:", channels)
                param_form.addRow("Pattern:", pattern)
            elif t == "dio_read":
                param_form.addRow(QLabel(
                    "Reads the full U2355A DIO bank and reports each "
                    "allocated Control IO net level (reference only)."))
            else:
                param_form.addRow(
                    QLabel("Custom operation: no parameters."))

        op_combo.currentTextChanged.connect(lambda _t: rebuild_params())
        rebuild_params()

        enable_cb = QCheckBox()
        enable_cb.setChecked(self._enables[r])
        wait_spin = QSpinBox()
        wait_spin.setRange(0, 99999)
        wait_spin.setValue(self._waits[r])
        wait_spin.setSuffix(" ms")
        timeout_spin = QSpinBox()
        timeout_spin.setRange(0, 999999)
        timeout_spin.setValue(self._timeouts[r])
        timeout_spin.setSuffix(" ms")
        meta = QFormLayout()
        meta.addRow("Enable:", enable_cb)
        meta.addRow("Wait:", wait_spin)
        meta.addRow("Timeout:", timeout_spin)
        outer.addLayout(meta)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        outer.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        new_name = op_combo.currentText().strip()
        if not new_name or new_name == "Custom Operation":
            new_name = name or "New Operation"
        t = current_type()
        if t in ("instruments", "reset"):
            new_params = {"type": t, "instruments": [
                cb.text() for cb in fields["instruments"]
                if cb.isChecked()]}
        elif t == "fixture":
            new_params = {"type": "fixture",
                          "signal": fields["signal"].currentText(),
                          "level": fields["level"].currentText()}
        elif t == "power":
            new_params = {"type": "power"}
            if "voltage" in fields:
                new_params["voltage"] = fields["voltage"].value()
                new_params["current"] = fields["current"].value()
        elif t == "flash":
            new_params = {
                "type": "flash",
                "slot": (OP_STEPS.get(new_name, {}).get("slot")
                         or params.get("slot") or "fat"),
                "mode": fields["mode"].currentText(),
                "tool": fields["tool"].currentText().strip() or "J-Link",
                "image": fields["image"].text().strip(),
                "device": fields["device"].text().strip(),
                "address": fields["address"].text().strip(),
                "baudrate": fields["baudrate"].value(),
                "verify": fields["verify"].isChecked(),
                "reset_run": fields["reset_run"].isChecked(),
                "erase": fields["erase"].isChecked(),
                "timeout_s": fields["timeout_s"].value(),
                "retries": fields["retries"].value(),
            }
            if fields["mode"].currentText() == "manual":
                new_params["launch"] = fields["launch"].text().strip()
                new_params["message"] = fields["message"].text().strip()
                new_params["message_timeout_s"] = \
                    fields["message_timeout_s"].value()
        elif t == "dio_out":
            new_params = {
                "type": "dio_out",
                "channels": fields["channels"].text().strip()
                or "DIO01-DIO08",
                "pattern": fields["pattern"].text().strip() or "0x00",
            }
        elif t == "dio_read":
            new_params = {"type": "dio_read"}
        else:
            new_params = None
        if self._kind == "ict":
            self._steps[r] = ("op", new_name, "—", "—", "—", "—",
                              new_params)
        else:
            self._steps[r] = new_name
            if self._kinds is not None:
                self._kinds[r] = "op"
            if self._op_params is not None:
                self._op_params[r] = new_params
        self._enables[r] = enable_cb.isChecked()
        self._waits[r] = wait_spin.value()
        self._timeouts[r] = timeout_spin.value()
        return True

    def _edit_fct_step(self, r):
        name = self._steps[r]
        if self._kinds and r < len(self._kinds) and \
                self._kinds[r] == "op":
            # FCT op rows keep the name in _steps (plain string) and the
            # parameters in _op_params: bridge to the ICT-style op
            # editor, then split the 7-tuple it writes back
            params = (self._op_params[r]
                      if r < len(self._op_params) else None)
            ok = self._edit_op_step(r, _op_step(name, params))
            if ok:
                step = self._steps[r]
                self._steps[r] = step[1]
                while len(self._op_params) <= r:
                    self._op_params.append(None)
                self._op_params[r] = step[6]
            return ok
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Step {r + 1} — Edit")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(name)
        method_combo = QComboBox()
        method_combo.addItems(FCT_METHODS)
        method_combo.setCurrentText(
            self._kinds[r] if self._kinds and r < len(self._kinds)
            else _fct_kind_from_name(name))
        enable_cb = QCheckBox()
        enable_cb.setChecked(self._enables[r])
        wait_spin = QSpinBox()
        wait_spin.setRange(0, 99999)
        wait_spin.setValue(self._waits[r])
        wait_spin.setSuffix(" ms")
        timeout_spin = QSpinBox()
        timeout_spin.setRange(0, 999999)
        timeout_spin.setValue(self._timeouts[r])
        timeout_spin.setSuffix(" ms")
        form.addRow("Name:", name_edit)
        form.addRow("Test Method:", method_combo)
        form.addRow("Enable:", enable_cb)
        form.addRow("Wait:", wait_spin)
        form.addRow("Timeout:", timeout_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        self._steps[r] = name_edit.text().strip() or name
        if self._kinds is not None:
            self._kinds[r] = method_combo.currentText()
        self._enables[r] = enable_cb.isChecked()
        self._waits[r] = wait_spin.value()
        self._timeouts[r] = timeout_spin.value()
        return True

    # ------------------------------------------------------- helpers
    def set_steps(self, steps, enables, waits, timeouts, kinds=None,
                  op_params=None):
        """Replace the whole step list and repopulate (re-seed).

        Used by an embedded host (the block-07 FCT panel) that builds the
        editor empty and then loads the stored sequence when its values
        are restored.
        """
        self._steps = list(steps)
        self._enables = list(enables)
        self._waits = list(waits)
        self._timeouts = list(timeouts)
        self._kinds = list(kinds) if kinds is not None else None
        self._op_params = (list(op_params)
                           if op_params is not None else None)
        self._populate()

    def select_row(self, row):
        if 0 <= row < len(self._steps):
            self.list_widget.setCurrentRow(row)

    def result_data(self):
        """Return (steps, enables, waits, timeouts[, kinds, op_params])."""
        for i in range(len(self._enables)):
            item = self.list_widget.item(i)
            if item:
                self._enables[i] = (
                    item.checkState() == Qt.CheckState.Checked)
        if self._kinds is not None:
            return (self._steps, self._enables,
                    self._waits, self._timeouts, self._kinds,
                    self._op_params)
        return (self._steps, self._enables,
                self._waits, self._timeouts)
