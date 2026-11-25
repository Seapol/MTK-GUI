# -*- coding: utf-8 -*-
"""v2-18: the seven-step Yaml Build wizard — flowchart + per-node dialogs.

The page hosts the seven steps of ``mtkgui/gui/yamlbuild/steps_v2.py``:
a horizontal flowchart (node 01 on the left, node 07 on the right) and
nothing else.  Clicking a node opens a modal dialog that hosts that node's
panel together with the node's own actions - ``Save Draft`` and, for every
node but the last, ``Next: <node> ->``.  (M127: the page-level
``[Cancel] [Save Draft] [Next]`` footer and the in-page
``Export to Excel`` strip were removed; the workbook export lives in
``File > Export Config Workbook...``.)

Routing, greying and the project tree / draft hook come from
``steps_v2`` (Qt-free, tested separately).  This widget is the thin Qt
skin over that state — it hosts the finished panels unchanged (re-parented
into a hidden host so ``findChildren`` and ``self._panels`` keep working).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild import model as model_module
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild import steps_v2 as sv
from mtkgui.gui.yamlbuild import flow_view


def _parsed_nets_dict(state) -> dict:
    """The model's ``parsed_nets`` shape, derived from a ``V2ParseState``.

    Net names are emitted in table order (the ``rows`` order) and are not
    sorted or de-duplicated.
    """
    from mtkgui.ict.netparse.model import (CATEGORY_GND, CATEGORY_OTHER,
                                           CATEGORY_POWER,
                                           CATEGORY_SE_CLOCK)

    return {
        "route": state.route,
        "gate_ok": state.gate_ok,
        "gate_error": state.gate_error,
        "power_nets": [r.name for r in state.rows
                       if r.category == CATEGORY_POWER],
        "clock_nets": [r.name for r in state.rows
                       if r.category == CATEGORY_SE_CLOCK],
        "gnd_nets": [r.name for r in state.rows
                     if r.category == CATEGORY_GND],
        "other_nets": [r.name for r in state.rows
                       if r.category == CATEGORY_OTHER],
    }


class YamlBuildWizard(QWidget):
    """Seven-step shell: flowchart + per-node dialog + footer."""

    #: the operator pressed [Cancel] (the wizard stops; no file is deleted)
    cancelled = Signal()
    #: the FCT launcher step asked to open its external builder
    build_fct_requested = Signal()

    def __init__(self, model: YamlBuildModel | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model or YamlBuildModel()
        # v2-16 B: the Custom snippet page writes through to the
        # project YAML (yaml_build.command_snippets) via this binding.
        from mtkgui.gui.yamlbuild.command_snippet_helper import bind_model
        bind_model(self.model)
        self.current: str = "design_input"
        self.visited: set[str] = {"design_input"}
        self.tree_created: bool = False
        # M103: a live test run makes every node read-only (set by the
        # MainWindow's single _apply_yaml_guards()).
        self._run_active: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # hidden host that owns the seven panels (keeps ``self._panels``
        # and ``findChildren`` contracts working while the dialog re-parents)
        self._panel_host = QWidget(self)
        self._panel_host.setVisible(False)
        self._panel_host_lay = QVBoxLayout(self._panel_host)
        self._panel_host_lay.setContentsMargins(0, 0, 0, 0)

        # ------------------------------------------------ body: flowchart
        self.flow = flow_view.YamlBuildFlowView()
        self.flow.step_clicked.connect(self._open_step_dialog)
        root.addWidget(self.flow, 1)

        # build all seven panels (unchanged internals), parked in the host
        self._panels: dict[str, QWidget] = {}
        for step in sv.YAML_STEPS:
            panel = self._make_panel(step.key)
            self._panels[step.key] = panel
            self._panel_host_lay.addWidget(panel)

        # M127: the page carries the flowchart only - Cancel / Save Draft /
        # Next are node-window actions now (see _open_step_dialog).

        self._refresh()

    def _make_panel(self, key: str) -> QWidget:
        """Instantiate the real panel for a ``panel`` step."""
        if key == "design_input":
            from mtkgui.gui.yamlbuild.design_input_panel import \
                DesignInputPanel
            panel = DesignInputPanel()
            # v2-3e: node 01 reaches the model - load the persisted
            # design_input params, then write back on every change.
            panel.set_values(self.model.get_params("design_input") or {})
            panel.content_changed.connect(
                lambda: self.model.set_params("design_input",
                                              panel.values()))
            # M102: Route C parses on import here; the result is applied
            # to the model (nets + limits) immediately.
            panel.mtk_sheet_imported.connect(self._apply_route_c)
            # keep the live panel for the route read of node 02
            self._design_panel = panel
            return panel
        if key == "parse_ict":
            from mtkgui.gui.yamlbuild.parse_nets_v2_panel import \
                ParseNetsV2Panel
            panel = ParseNetsV2Panel()
            # v2-4: Route B re-imports the ICT Excel recorded on node 01
            # (LOAD ONLY there); Route A is driven by an explicit parse.
            # M102: Route C reads the route from the LIVE node 01 values -
            # the model only sees node 01 after its first content change.
            design = self._design_values()
            route = str(design.get("ict_route") or "")
            loaded = True
            if route == "excel":
                excel = str(design.get("ict_excel_file") or "").strip()
                if excel:
                    panel.load_route_b(excel)
            elif route == "mtk_sheet":
                mtk = str(design.get("ict_mtk_sheet_file") or "").strip()
                if mtk:
                    loaded, error = panel.load_route_c(mtk)
                    if not loaded:
                        panel.lbl_summary.setText(f"Parse failed: {error}")
            # v2-12a A: the Parse button runs a Route A parse from the raw
            # NET text recorded on node 01 (load only there).
            panel.parse_requested.connect(lambda: self._parse_route_a(panel))
            # v2-12a B: node 02 writes the parsed nets back to the model,
            # and seeds it once so a Route B import is persisted immediately
            # (not only on the next category edit).
            panel.content_changed.connect(
                lambda: self.model.set_parsed_nets(
                    _parsed_nets_dict(panel.state())))
            if loaded:
                # an unreadable file must never wipe the applied nets
                self.model.set_parsed_nets(
                    _parsed_nets_dict(panel.state()))
            return panel
        if key == "firmware":
            from mtkgui.gui.yamlbuild.firmware_panel import \
                FirmwareConfigPanel
            panel = FirmwareConfigPanel()
            # v2-5: node 03 reaches the model - load the persisted
            # firmware config, then write back on every change.
            panel.set_values(self.model.get_firmware_config())
            panel.content_changed.connect(
                lambda: self.model.set_firmware_config(panel.values()))
            return panel
        if key == "equipment":
            from mtkgui.gui.yamlbuild.equipment_panel import \
                EquipmentConfigPanel
            panel = EquipmentConfigPanel()
            # v2-10: node 04 reaches the model - load the persisted
            # equipment config, then write back on every change.
            panel.set_values(self.model.get_equipment_config())
            panel.content_changed.connect(
                lambda: self.model.set_equipment_config(panel.values()))
            return panel
        if key == "build_ict":
            from mtkgui.gui.yamlbuild.ict_sequence_v2_panel import \
                BuildIctSequencePanel
            panel = BuildIctSequencePanel()
            # v2-11: node 05 seeds its flat sequence from node 04's
            # power / clock nets, rails capture and enabled instruments.
            self._seed_build_ict(panel)
            # v2-11b B: node 05 writes the engine-shape sequence back to
            # the model, and seeds it once so a save before any edit
            # already carries the generated sequence.
            panel.content_changed.connect(
                lambda: self.model.set_ict_test_cases(
                    panel.engine_cases(self.model.get_equipment_config())))
            self.model.set_ict_test_cases(
                panel.engine_cases(self.model.get_equipment_config()))
            return panel
        if key == "build_fct":
            from mtkgui.gui.yamlbuild.fct_build import (
                from_project_fct_cases,
                to_project_fct_cases,
            )
            from mtkgui.gui.yamlbuild.fct_sequence_v2_panel import (
                BuildFctSequencePanel)
            panel = BuildFctSequencePanel()
            # v2-13 D: node 06 seeds from the model's FCT cases and writes
            # back on every change.
            cases = self.model.get_fct_test_cases()
            panel.set_sequence(from_project_fct_cases(cases))
            panel.content_changed.connect(
                lambda: self.model.set_fct_test_cases(
                    to_project_fct_cases(panel.sequence())))
            self.model.set_fct_test_cases(
                to_project_fct_cases(panel.sequence()))
            # the v1 dialog remains reachable through the Advanced button
            panel.advanced_requested.connect(self.build_fct_requested.emit)
            return panel
        if key == "apply_save":
            from mtkgui.gui.yamlbuild.apply_save_panel import ApplySavePanel
            panel = ApplySavePanel()
            # v2-17: node 07 previews the Draft from the same model and
            # saves through the shared publish helpers.
            panel.set_values(self.model)
            panel.content_changed.connect(panel.refresh)
            return panel
        label = QLabel(sv.PLACEHOLDER_TEXT)
        return label

    def _seed_build_ict(self, panel) -> None:
        """Seed node 05 from the latest node 04 equipment facts."""
        eq = self.model.get_equipment_config()
        panel.refresh(
            [r.net for r in eq.power_rows],
            [r.net for r in eq.clock_rows],
            rails_enabled=bool(eq.rails.rows),
            fixture_type=eq.fixture.type,
            instruments=[k for k, on in eq.instruments.items() if on])

    def _design_values(self) -> dict:
        """The LIVE node 01 values (fallback: the persisted params).

        The model only receives node 01 after its first
        ``content_changed``; the route read must not depend on that.
        """
        panel = getattr(self, "_design_panel", None)
        if panel is not None:
            try:
                return dict(panel.values())
            except Exception:                    # noqa: BLE001 - defensive
                pass
        return self.model.get_params("design_input") or {}

    def _design_route(self) -> str:
        """The selected ICT input route (``files`` / ``excel`` /
        ``mtk_sheet``)."""
        return str(self._design_values().get("ict_route") or "files")

    # ------------------------------------------------------------ parse
    def _apply_route_c(self, result) -> None:
        """M102: apply an imported MTK sheet (nets + allocation limits).

        Fresh limits / test points come from the sheet; the operator's
        resource cells (instrument, channel, ...) are carried over for
        the same net so a corrected re-import keeps the channel picks.
        """
        from mtkgui.gui.yamlbuild.channel_allocation import (
            UNSET, AllocatedRow)

        self.model.set_parsed_nets(result.to_parsed_nets())
        fresh = result.to_allocation_rows()
        existing = self.model.get_channel_allocation() or {}
        carry = ("instrument", "channel", "impedance", "power_rails",
                 "voltage", "se_clock_hz", "band")
        merged: dict = {}
        for kind in ("power", "clock"):
            previous = {
                str(row.get("net") or ""): row
                for row in (existing.get(kind) or [])
                if isinstance(row, dict)}
            rows = []
            for data in fresh.get(kind) or []:
                row = AllocatedRow.from_dict(data)
                old = previous.get(row.net) or {}
                for key in carry:
                    value = old.get(key)
                    if value not in (None, "", UNSET):
                        setattr(row, key, str(value))
                rows.append(row)
            merged[kind] = [row.to_dict() for row in rows]
        # Route C never seeds GPIO rows and never touches power_rails
        merged["gpio"] = list(existing.get("gpio") or [])
        self.model.set_channel_allocation(merged)
        # node 02 is the read-only audit view of the same sheet
        panel = self._panels.get("parse_ict")
        path = str(self._design_values().get("ict_mtk_sheet_file") or "")
        if panel is not None and path and hasattr(panel, "load_route_c"):
            panel.load_route_c(path)
        self._refresh()

    # ------------------------------------------------------------ parse
    def _parse_route_a(self, panel) -> None:
        """Run a Route A parse from the raw NET text recorded on node 01.

        ``net_file`` is a project-relative path (the same convention as
        ``spf_file`` / ``bom_file``); resolve it against the working
        directory, read the text, and hand the collapse to the panel.  A
        netlist that yields no nets raises ``ValueError`` and is reported
        on the panel's summary label - never propagated.
        """
        design = self.model.get_params("design_input") or {}
        net_file = str(design.get("net_file") or "").strip()
        if not net_file:
            return
        from pathlib import Path

        from mtkgui.ict.netparse import read_text_any_encoding
        from mtkgui.ict.netparse.parser import parse_testable_nets

        path = Path(net_file)
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            net_text = read_text_any_encoding(str(path))
            result = parse_testable_nets(net_text)
        except ValueError as exc:
            panel.lbl_summary.setText(f"Parse failed: {exc}")
            return
        panel.load_route_a(result)
        # a Route A parse is not a signal-emitter (like a Route B load):
        # persist it immediately rather than waiting for a category edit
        self.model.set_parsed_nets(_parsed_nets_dict(panel.state()))

    # ------------------------------------------------------------- state
    def _design_values(self) -> dict:
        """Live node 01 values, falling back to the saved model."""
        panel = self._panels.get("design_input")
        getter = getattr(panel, "values", None)
        payload = getter() if callable(getter) else None
        if isinstance(payload, dict) and payload:
            return payload
        return self.model.get_params("design_input") or {}

    def ict_on(self) -> bool:
        design = self._design_values()
        return str(design.get("ict_block_enabled", "true")).lower() \
            not in ("false", "0", "no")

    def fct_on(self) -> bool:
        design = self._design_values()
        return str(design.get("fct_block_enabled", "true")).lower() \
            not in ("false", "0", "no")

    def _is_skipped(self, key: str) -> bool:
        """M102: node 02 is skipped on Route C (nets parsed on import).

        A failed gate is never skipped (nothing was applied).
        """
        if key != "parse_ict":
            return False
        if self._design_route() != "mtk_sheet":
            return False
        nets = self.model.get_parsed_nets() or {}
        return nets.get("gate_ok") is not False

    def _is_complete(self, key: str) -> bool:
        """A node is complete when it is unused (disabled / route-skipped)
        or when the operator locked it (M128: the padlock is the
        completion contract - it validates before it locks)."""
        if not sv.is_step_enabled(key, self.ict_on(), self.fct_on()):
            return True
        if self._is_skipped(key):
            return True
        return self.model.is_locked(key)

    def set_run_active(self, active: bool) -> None:
        """M103: lock / unlock every node for the active-run window."""
        self._run_active = bool(active)

    def _is_editable(self, key: str) -> bool:
        """Editable when enabled, not skipped, not running and every
        prerequisite is complete."""
        if not sv.is_step_enabled(key, self.ict_on(), self.fct_on()):
            return False
        if self._is_skipped(key):
            return False
        if self._run_active:
            return False
        return all(self._is_complete(p) for p in flow_view.PREREQS[key])

    # --------------------------------------------------------- dialogs
    def _open_step_dialog(self, key: str) -> None:
        """Open one node's panel in a modal dialog (read-only if locked)."""
        if not sv.is_step_enabled(key, self.ict_on(), self.fct_on()):
            return
        panel = self._panels.get(key)
        if panel is None:
            return
        # clicking a node selects it (the flow view + goto rely on current)
        self.current = key
        self.visited.add(key)
        # refresh the panels whose content is derived from earlier nodes
        if key == "build_ict":
            self._seed_build_ict(panel)
        elif key == "apply_save":
            panel.refresh()
        skipped = self._is_skipped(key)
        editable = self._is_editable(key) and not skipped
        dlg = QDialog(self)
        dlg.setWindowTitle(sv.step_label(key))
        lay = QVBoxLayout(dlg)
        if editable:
            guide = QLabel(f"What this step does\n{flow_view.STEP_GUIDE[key]}")
            guide.setWordWrap(True)
            lay.addWidget(guide)
            if flow_view.STEP_NEXT.get(key):
                nxt = QLabel(flow_view.STEP_NEXT[key])
                nxt.setProperty("tone", "info")
                lay.addWidget(nxt)
        elif skipped:
            # M102: enterable + read-only, so the import can be audited
            note = QLabel(flow_view.skip_message(key))
            note.setWordWrap(True)
            note.setProperty("tone", "info")
            lay.addWidget(note)
        elif self._run_active:
            # M103: the run owns the configuration - view only
            note = QLabel(
                "A test run is active - stop it before editing the Yaml "
                "configuration.")
            note.setWordWrap(True)
            note.setProperty("tone", "warning")
            lay.addWidget(note)
        else:
            lock = QLabel(flow_view.lock_message(key))
            lock.setWordWrap(True)
            lock.setProperty("tone", "warning")
            lay.addWidget(lock)
        # m106b: the panel is tall on small screens - keep it scrollable so the
        # OK / Cancel row always stays reachable.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        lay.addWidget(scroll, 1)          # re-parent into the dialog
        # M128: the node window owns a padlock.  Default = Unlock (open);
        # clicking it validates the module behind a foreground progress
        # bar and locks it (read-only, *Completed*), which is what opens
        # ``Next``.
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        btn_lock = QPushButton()
        status = QLabel("")
        status.setProperty("tone", "info")
        btn_draft = QPushButton("Save Draft")
        btn_draft.setToolTip(
            "Write the current node values into the project draft YAML "
            "(no validation, no file is deleted)")
        btn_draft.clicked.connect(lambda: self._save_node_draft(key, status))
        next_step = self._next_node_key(key)
        btn_next = None
        if next_step:
            btn_next = QPushButton(f"Next: {sv.step_label(next_step)} →")
            btn_next.setToolTip(
                f"Lock this module, then open {sv.step_label(next_step)}")
            btn_next.clicked.connect(
                lambda: self._advance_node(key, next_step, dlg))
        actions.addWidget(btn_lock)
        actions.addWidget(btn_draft)
        actions.addWidget(status, 1)
        if btn_next is not None:
            actions.addWidget(btn_next)
        lay.addLayout(actions)

        def sync_actions() -> None:
            """Paint the window from the CURRENT lock / editability state."""
            locked_now = self.model.is_locked(key)
            if locked_now:
                btn_lock.setText("🔒 Locked")
                btn_lock.setToolTip(
                    "This module is locked (complete + validated). Click "
                    "to unlock it - every later module unlocks with it.")
            else:
                btn_lock.setText("🔓 Unlock")
                btn_lock.setToolTip(
                    "Click to check this module (validation, foreground "
                    "progress) and lock it as completed.")
            btn_lock.setEnabled(editable)
            can_edit = editable and not locked_now
            panel.setEnabled(can_edit)
            btn_draft.setEnabled(can_edit)
            if btn_next is not None:
                btn_next.setEnabled(editable and locked_now)
                btn_next.setToolTip(
                    f"Open {sv.step_label(next_step)}"
                    if locked_now else
                    "Lock this module first - Next unlocks once the "
                    "module is completed.")

        btn_lock.clicked.connect(
            lambda: self._toggle_lock(key, panel, sync_actions, status))
        sync_actions()
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = btns.button(QDialogButtonBox.Ok)
        ok.setText("Apply_Save yaml")
        ok.setToolTip("Close the node; values stay in the configuration")
        cancel = btns.button(QDialogButtonBox.Cancel)
        cancel.setText("Exit")
        cancel.setToolTip("Close the node without changing the configuration")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        # keep the whole dialog inside the screen - the action row and the
        # button box must remain visible even when the panel's sizeHint is
        # taller than the monitor.  M127: the panel's own minimum width
        # (QSS padding included) drives the dialog width, otherwise the
        # two-column node-01 layout is clipped on the right.
        # M128: measure AFTER activating the layout.  On Windows the
        # panel reported a 705 px / 562 px hint before layout ran, which
        # clipped node 01's right column; the content floor keeps the
        # two-column blocks readable on every platform.
        panel.ensurePolished()
        dlg.layout().activate()
        panel.adjustSize()
        dlg.adjustSize()
        avail = self.screen().availableGeometry()
        content_w = max(panel.minimumSizeHint().width(),
                        panel.minimumSize().width(), panel.sizeHint().width())
        content_h = max(panel.minimumSizeHint().height(),
                        panel.minimumSize().height(),
                        panel.sizeHint().height())
        hint = dlg.sizeHint()
        width = max(hint.width(), content_w + 48, 760)
        height = max(hint.height() + 44, content_h + 96, 560)
        dlg.resize(min(width, int(avail.width() * 0.9)),
                   min(height, int(avail.height() * 0.9)))
        accepted = bool(dlg.exec())        # 1 = Apply_Save yaml, 0 = Exit
        if accepted:
            # M127: the dialog's own [Apply_Save yaml] now really applies -
            # the panel's live values reach the model before the window
            # closes (``Exit`` leaves the configuration untouched).
            self._collect_panel_values(key)
        scroll.takeWidget()
        self._panel_host_lay.addWidget(panel)   # re-parent back after close
        self._refresh()

    # --------------------------------------------------------- navigation
    def _on_next(self) -> None:
        """Jump to the first validation-failed node and open its dialog.

        The project tree / draft side-effects are kept: node 01 creates
        the project tree, any other current node saves a draft.
        """
        if self.current == "design_input":
            design = self.model.get_params("design_input") or {}
            core = str(design.get("product_id") or "").strip()
            if core:
                sv.ensure_project_tree(core)
                self.tree_created = True
        else:
            sv.save_draft(self.model)
        for key in sv.enabled_step_keys(self.ict_on(), self.fct_on()):
            panel = self._panels.get(key)
            validator = getattr(panel, "validate", None)
            if callable(validator):
                ok, _msg = validator()
                if not ok:
                    self._open_step_dialog(key)
                    return

    def _on_save_draft(self) -> None:
        sv.save_draft(self.model)

    def _on_cancel(self) -> None:
        """Stop the wizard.  Nothing on disk is deleted — whatever an
        earlier [Save Draft] / [Next] already created stays."""
        self.current = "design_input"
        self.visited = {"design_input"}
        self.tree_created = False
        self.cancelled.emit()
        self._refresh()

    # ----------------------------------------------------- node actions
    def _next_node_key(self, key: str) -> str | None:
        """The successor node to offer on *key*'s window (M127).

        Auto-skipped steps (Route C node 02) are stepped over so ``Next``
        never lands on a node that is entered read-only.
        """
        ict_on, fct_on = self.ict_on(), self.fct_on()
        nxt = sv.next_key(key, ict_on, fct_on)
        while nxt and self._is_skipped(nxt):
            nxt = sv.next_key(nxt, ict_on, fct_on)
        return nxt

    def _collect_panel_values(self, key: str) -> None:
        """Push the node panel's live values into the model (M127).

        The panel stays the single source of truth while the window is
        open; without this its edits would only reach the model on
        ``Apply_Save yaml`` and a draft would store stale values.
        """
        panel = self._panels.get(key)
        values = getattr(panel, "values", None)
        if not callable(values):
            return
        try:
            payload = values()
        except Exception:   # pragma: no cover - a panel must not kill the dialog
            return
        # only plain parameter dicts are pushed here; panels returning
        # their own config object (equipment) write through by themselves
        if isinstance(payload, dict):
            self.model.set_params(key, payload)

    def _save_node_draft(self, key: str, status: QLabel | None = None) -> None:
        """``Save Draft`` inside a node window (M127).

        Writes the current (possibly incomplete) configuration to the
        project draft YAML - drafts bypass validation on purpose - and
        reports the destination inside the window.
        """
        self._collect_panel_values(key)
        if key == "design_input":
            design = self.model.get_params("design_input") or {}
            core = str(design.get("product_id") or "").strip()
            if core:
                sv.ensure_project_tree(core)
                self.tree_created = True
        try:
            path = sv.save_draft(self.model)
        except Exception as exc:   # pragma: no cover - disk failure
            if status is not None:
                status.setText(f"Draft NOT saved: {exc}")
            return
        if status is not None:
            status.setText(f"Draft saved: {path}")

    def _advance_node(self, key: str, next_key: str, dlg: QDialog) -> None:
        """``Next`` inside a node window: save, close, open next."""
        if not self.model.is_locked(key):
            return                     # Next stays closed until locked
        self._save_node_draft(key)
        dlg.accept()
        QTimer.singleShot(0, lambda target=next_key:
                          self._open_step_dialog(target))

    # ---------------------------------------------------------- locks
    def _toggle_lock(self, key: str, panel: QWidget, sync, status: QLabel) -> None:
        """Padlock click: lock (validate first) or unlock (cascade)."""
        if self.model.is_locked(key):
            self._unlock_from(key)
            status.setText(
                f"Unlocked {sv.step_label(key)} - every later module "
                "unlocked with it")
            sync()
            return
        ok, message = self._check_and_lock(key, panel)
        if ok:
            status.setText(f"{sv.step_label(key)} locked - Completed")
        else:
            status.setText("Not locked - fix the findings first")
            QMessageBox.warning(self, "Module check", message)
        sync()

    def _check_and_lock(self, key: str, panel: QWidget) -> tuple[bool, str]:
        """Validate a module behind a foreground progress bar, then lock.

        The check runs synchronously but the modal progress dialog pumps
        the event loop between stages, so the window never freezes
        (M128 user direction: "耗时操作用前置进度条，不要卡死界面").
        """
        from mtkgui.gui.progress_dialog import busy_progress

        ok = False
        message = ""
        try:
            with busy_progress(self, f"Checking {sv.step_label(key)}…") as stage:
                stage(5, "Collecting the module inputs…")
                self._collect_panel_values(key)
                stage(45, "Validating the module…")
                validator = getattr(panel, "validate", None)
                if callable(validator):
                    ok, message = validator()
                else:
                    ok, message = True, ""
                if ok:
                    stage(75, "Saving the draft…")
                    try:
                        sv.save_draft(self.model)
                    except Exception:       # draft is a bonus, not a gate
                        pass
                    stage(95, "Locking the module…")
                    self.model.set_locked(key, True)
                stage(100, "Done")
        except Exception as exc:            # noqa: BLE001 - a check must not crash
            return False, str(exc) or exc.__class__.__name__
        if ok:
            self._sync_visuals()
        return ok, message

    def _unlock_from(self, key: str) -> None:
        """Unlock *key* AND every module after it (M128 rule 4)."""
        keys = sv.enabled_step_keys(self.ict_on(), self.fct_on())
        targets = (keys[keys.index(key):]
                   if key in keys else (key,))
        for target in targets:
            self.model.set_locked(target, False)
        self._sync_visuals()

    # -------------------------------------------------------- visuals
    def _panel_has_content(self, key: str) -> bool:
        """True when the live panel holds more than its schema defaults.

        Badges must react to what the engineer has typed, not only to
        what has already been written back to the model, so this mirrors
        ``YamlBuildModel.module_has_content`` on the panel side.
        """
        panel = self._panels.get(key)
        getter = getattr(panel, "values", None)
        payload = getter() if callable(getter) else None
        if isinstance(payload, dict) and payload:
            defaults = {f.name: f.default for f in
                        model_module.MODULE_FIELDS.get(key, ())}
            for name, default in defaults.items():
                value = payload.get(name, default)
                if str(value if value is not None else "").strip() != \
                        str(default if default is not None else "").strip():
                    return True
        if key == "parse_ict":
            state = panel.state() if hasattr(panel, "state") else None
            if state is not None and (getattr(state, "rows", None)
                                      or getattr(state, "skipped", None)):
                return True
        return False

    def _sync_visuals(self) -> None:
        """Repaint every card without touching the panels (M128)."""
        ict_on, fct_on = self.ict_on(), self.fct_on()
        for key in sv.STEP_KEYS:
            self.flow.set_step_visual(
                key,
                unused=(not sv.is_step_enabled(key, ict_on, fct_on))
                or self._is_skipped(key),
                locked=self.model.is_locked(key),
                edited=(self.model.module_has_content(key)
                        or self._panel_has_content(key)))

    def refresh_from_model(self) -> None:
        """Reload every node from the model (Close Yaml / Load Yaml).

        Close Yaml unlocks and empties all modules; loading another
        project clears the previous values, fills the nodes from the
        file and restores the file's lock state.
        """
        design = self.model.get_params("design_input") or {}
        design_panel = self._panels.get("design_input")
        setter = getattr(design_panel, "set_values", None)
        if callable(setter):
            setter(design)
        firmware = self._panels.get("firmware")
        setter = getattr(firmware, "set_values", None)
        if callable(setter):
            setter(self.model.get_params("firmware") or {})
        equipment = self._panels.get("equipment")
        setter = getattr(equipment, "set_values", None)
        if callable(setter):
            setter(self.model.get_equipment_config())
        parse = self._panels.get("parse_ict")
        if parse is not None:
            from mtkgui.gui.yamlbuild.parse_nets_v2 import V2ParseState
            state = parse.state()
            if not (state.rows if state is not None else []):
                parse.set_state(V2ParseState())
        self.current = "design_input"
        self.visited = {"design_input"}
        self.tree_created = False
        self._refresh()
        self._sync_visuals()

    def _refresh(self) -> None:
        """Paint the flowchart state."""
        ict_on, fct_on = self.ict_on(), self.fct_on()
        for step in sv.YAML_STEPS:
            key = step.key
            if not sv.is_step_enabled(key, ict_on, fct_on):
                state = "disabled"
            elif self._is_skipped(key):
                # M102: checked before "editable" - Route C node 02
                state = "skipped"
            elif not self._is_editable(key):
                state = "locked"
            else:
                panel = self._panels.get(key)
                validator = getattr(panel, "validate", None)
                if not callable(validator):
                    state = "editable"
                else:
                    ok, _msg = validator()
                    state = "valid" if ok else "invalid"
            self.flow.set_step_state(key, state)
        self._sync_visuals()
        # v2-11b C: revisiting node 05 re-seeds from the latest 02/04 facts
        if self.current == "build_ict":
            panel = self._panels.get("build_ict")
            if panel is not None:
                self._seed_build_ict(panel)
        # v2-17: node 07 always previews the latest model state
        if self.current == "apply_save":
            panel = self._panels.get("apply_save")
            if panel is not None:
                panel.refresh()

    # --------------------------------------------------------- test hook
    def goto(self, key: str) -> None:
        """Programmatic navigation (tests): visit *key* directly."""
        self.current = key
        self.visited.add(key)
        self._refresh()

    # ------------------------------------------------- public entry points
    def open_step(self, key: str) -> None:
        """Open one node's dialog (read-only when the node is locked).

        The ``File ▸ Excel`` imports use this to land the operator on
        node 01 after the factory reset.
        """
        self._open_step_dialog(key)

    def select_route(self, route: str) -> None:
        """Check a Design Input route radio: ``files`` / ``excel`` /
        ``mtk_sheet``.

        Only the radio state changes here; the route is persisted by
        node 01's own ``content_changed`` when the operator edits it
        (an import through the panel does so immediately).
        """
        if route not in ("files", "excel", "mtk_sheet"):
            return
        panel = getattr(self, "_design_panel", None)
        if panel is None:
            return
        button = {"files": panel.radio_files, "excel": panel.radio_excel,
                  "mtk_sheet": panel.radio_mtk}[route]
        button.setChecked(True)
        panel._on_route_changed(None)
