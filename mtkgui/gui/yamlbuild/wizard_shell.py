# -*- coding: utf-8 -*-
"""v2-18: the seven-step Yaml Build wizard — flowchart + per-node dialogs.

The page hosts the seven steps of ``mtkgui/gui/yamlbuild/steps_v2.py``:
a horizontal flowchart (node 01 on the left, node 07 on the right) and a
footer ``[Cancel] [Save Draft] [Next]``.  Clicking a node opens a modal
dialog that hosts that node's panel; ``Next`` jumps to the first
validation-failed node.

Routing, greying and the project tree / draft hook come from
``steps_v2`` (Qt-free, tested separately).  This widget is the thin Qt
skin over that state — it hosts the finished panels unchanged (re-parented
into a hidden host so ``findChildren`` and ``self._panels`` keep working).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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

        # ------------------------------------------------ footer
        footer = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_save_draft = QPushButton("Save Draft")
        self.btn_save_draft.clicked.connect(self._on_save_draft)
        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self._on_next)
        footer.addWidget(self.btn_cancel)
        footer.addWidget(self.btn_save_draft)
        footer.addStretch(1)
        footer.addWidget(self.btn_next)
        root.addLayout(footer)

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
            return panel
        if key == "parse_ict":
            from mtkgui.gui.yamlbuild.parse_nets_v2_panel import \
                ParseNetsV2Panel
            panel = ParseNetsV2Panel()
            # v2-4: Route B re-imports the ICT Excel recorded on node 01
            # (LOAD ONLY there); Route A is driven by an explicit parse.
            design = self.model.get_params("design_input") or {}
            if str(design.get("ict_route") or "") == "excel":
                excel = str(design.get("ict_excel_file") or "").strip()
                if excel:
                    panel.load_route_b(excel)
            # v2-12a A: the Parse button runs a Route A parse from the raw
            # NET text recorded on node 01 (load only there).
            panel.parse_requested.connect(lambda: self._parse_route_a(panel))
            # v2-12a B: node 02 writes the parsed nets back to the model,
            # and seeds it once so a Route B import is persisted immediately
            # (not only on the next category edit).
            panel.content_changed.connect(
                lambda: self.model.set_parsed_nets(
                    _parsed_nets_dict(panel.state())))
            self.model.set_parsed_nets(_parsed_nets_dict(panel.state()))
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
    def ict_on(self) -> bool:
        design = self.model.get_params("design_input") or {}
        return str(design.get("ict_block_enabled", "true")).lower() \
            not in ("false", "0", "no")

    def fct_on(self) -> bool:
        design = self.model.get_params("design_input") or {}
        return str(design.get("fct_block_enabled", "true")).lower() \
            not in ("false", "0", "no")

    def _is_complete(self, key: str) -> bool:
        """A node is complete when disabled (skipped), or when its
        ``validate()`` returns ok (nodes without one are always complete)."""
        if not sv.is_step_enabled(key, self.ict_on(), self.fct_on()):
            return True
        panel = self._panels.get(key)
        validator = getattr(panel, "validate", None)
        if callable(validator):
            ok, _msg = validator()
            return ok
        return True

    def _is_editable(self, key: str) -> bool:
        """Editable when enabled and every prerequisite is complete."""
        if not sv.is_step_enabled(key, self.ict_on(), self.fct_on()):
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
        editable = self._is_editable(key)
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
        else:
            lock = QLabel(flow_view.lock_message(key))
            lock.setWordWrap(True)
            lock.setProperty("tone", "warning")
            lay.addWidget(lock)
        lay.addWidget(panel, 1)          # re-parent into the dialog
        panel.setEnabled(editable)       # read-only when prerequisites pending
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        dlg.exec()
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
        earlier [Next] / [Save Draft] already created stays."""
        self.current = "design_input"
        self.visited = {"design_input"}
        self.tree_created = False
        self.cancelled.emit()
        self._refresh()

    def _refresh(self) -> None:
        """Paint the flowchart state and the footer."""
        ict_on, fct_on = self.ict_on(), self.fct_on()
        first_invalid: str | None = None
        for step in sv.YAML_STEPS:
            key = step.key
            if not sv.is_step_enabled(key, ict_on, fct_on):
                state = "disabled"
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
            if state == "invalid" and first_invalid is None:
                first_invalid = key
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
        self.btn_next.setText("Next")
        self.btn_next.setEnabled(first_invalid is not None)
        self.btn_next.setToolTip(
            sv.step_label(first_invalid) if first_invalid is not None else "")

    # --------------------------------------------------------- test hook
    def goto(self, key: str) -> None:
        """Programmatic navigation (tests): visit *key* directly."""
        self.current = key
        self.visited.add(key)
        self._refresh()
