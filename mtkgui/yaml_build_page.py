# -*- coding: utf-8 -*-
"""V4.0 Yaml Build page (rightmost classic-shell tab).

Full phase-B1 assembly (interface_spec.md section 31):

* top fixed buttons (item 16): Import from Excel / Export to Excel /
  Edit-Apply (uniform adaptive width; the Build Draft / Release Final
  YAML buttons were removed - redundant YAML entry),
* left: the ten fixed workflow blocks (click = dedicated config
  dialog, right click = Enable / Disable; disabled blocks gray out,
  are skipped and are not written into the effective YAML),
* right: live YAML preview - two-way synced with the block diagram
  through the model, with syntax / sequence / parameter validation
  and red error-line markers,
* Draft / Final publishing with the fixed Design Input naming
  ([Part#]_[Core ID]_[Batch#]_rev_1.x.x_Draft|Final), version
  compare and archiving,
* model state persistence per tenant project (restart-safe).

Pure increment: nothing outside this page (and its subpackage) is
touched.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.block_flow import (
    MARK_CHECK,
    MARK_NONE,
    MARK_STAR,
    BlockFlowWidget,
)
from mtkgui.ict.netparse import (
    CATEGORY_CLOCK,
    CATEGORY_CONTROL_IO_LABEL,
    CATEGORY_GPIO,
)
from mtkgui.ict.netparse.confidence import clock_freq_hz
from mtkgui.ict.netparse.priority import nominal_volts_of
from mtkgui.gui.yamlbuild.channel_allocation import ChannelAllocationPage
from mtkgui.gui.dialog_sizing import wrap_page
from mtkgui.gui.progress_dialog import ProgressBridge
from mtkgui.startup_timing import begin, end
from mtkgui.gui.yamlbuild.excel_io import export_to_excel, \
    import_from_excel
from mtkgui.gui.yamlbuild.model import YamlBuildModel, available_ops
from mtkgui.gui.yamlbuild.publish import (
    archive_copy,
    compare_plans,
    plan_filename,
    publish,
)
from mtkgui.gui.yamlbuild.stages import (
    DISPLAY_CHANNEL_ALLOC,
    DISPLAY_ICT_WORKFLOW,
    STAGE_KEYS,
)
from mtkgui.gui.yamlbuild.store import load_project_state, \
    save_project_state
from mtkgui.engine.yaml_validation import (blocking_issues, format_issues,
                                           validate_project_yaml)
from mtkgui.version_info import get_version_info

#: default output directory for published plan files (created on use)
PLANS_DIR = "config/plans"

#: Parsed-Nets-table display label -> the internal testable-net category
#: stored in the project YAML (Power / Clock / GPIO stay the data keys)
DISPLAY_TO_CATEGORY = {
    "SE Clock": CATEGORY_CLOCK,
    CATEGORY_CONTROL_IO_LABEL: CATEGORY_GPIO,
}

#: M45b: the gated ICT module chain - a module opens only when the
#: previous level has been validated (star) or a valid project load
#: starred it.  M45c: FCT (module 05) is NOT part of this chain - an
#: FCT-only project is valid, so ``fct_build`` is always openable.
GATING_CHAIN: tuple[str, ...] = ("design_input", "parse_ict",
                                 "ict_workflow")

#: M45b: display card -> chain level (the two level-03 cards - the
#: Channel Allocation nav card and the merged Build ICT card - share the
#: same gate).
GATING_DISPLAY_LEVEL: dict[str, str] = {"channel_alloc": "ict_workflow"}

#: M45b: the three design files module 01 owns (SPF / NET / BOM); if ANY
#: is missing only module 01 may be opened.
DESIGN_INPUT_FILES: tuple[str, ...] = ("spf_file", "net_file", "bom_file")

#: M45b: chain level -> operator-facing module title/mark ("module 0X").
#: M45c: fct_build is independent (not in the chain).
GATING_LEVEL_TITLE: dict[str, str] = {
    "design_input": "Design Input",
    "parse_ict": "Parse nets for ICT",
    "ict_workflow": "Channel Allocation / Build ICT Test Work Flow "
                    "Sequence",
}


def _positive_float(value) -> float | None:
    """*value* as a strictly positive float, else None (tolerant)."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parsed_nominal(category: str, rec) -> dict:
    """M8 W2: the parsed nominal of one net, as testable_nets fields.

    Power -> ``nominal_v`` (record nominal, else the net-name heuristic);
    Clock -> ``nominal_khz`` (``clock_freq_hz``).  Noise-free: an unknown
    nominal yields an empty dict, so the row stays user-editable.
    """
    if category == "Power":
        volts = _positive_float(getattr(rec, "nominal", None))
        if volts is None:
            volts = _positive_float(nominal_volts_of(rec.name))
        return {"nominal_v": volts} if volts is not None else {}
    if category == "Clock":
        hz = _positive_float(clock_freq_hz(rec.name))
        return {"nominal_khz": hz / 1000.0} if hz is not None else {}
    return {}


def testable_net_entry(rec, category: str, *, filtered: bool = False,
                       auto_generated: bool = False,
                       override: bool = False) -> dict:
    """One ``imported.testable_nets`` entry for a parsed net record.

    Carries the M7 isolation evidence (``isolated`` / ``active_drivers``)
    so the 3-tier DIO-write preflight still works after a YAML reload,
    and the M8 parsed nominal (``nominal_v`` / ``nominal_khz``) so Auto
    fills the clock / power limits without a name heuristic.
    """
    members = (list(rec.members) if not filtered
               else [t for t in rec.members
                     if "." in t or t.upper().startswith("TP")])
    entry = {"category": category,
             "members": members or list(rec.members),
             "isolated": getattr(rec, "isolated", None),
             "active_drivers": list(
                 getattr(rec, "active_drivers", []) or [])}
    entry.update(parsed_nominal(category, rec))
    if auto_generated:
        entry["auto_generated"] = True
    if override:
        entry["category_override"] = True
    return entry


class YamlBuildPage(QWidget):
    """Yaml Build tab: block-diagram workflow + live YAML preview."""

    #: (percent 0-100, label) long-task progress for the global status
    #: bar (T6): 0 = task start, 100 = task done, stages in between
    task_progress = Signal(int, str)
    #: (level, message) Event-Log mirror for the main window (T6)
    task_log = Signal(str, str)
    #: navigation: the merged "Build ICT Test Work Flow Sequence"
    #: card asked for the Test Work Flow page (main window switches
    #: the tab and focuses the ICT Test Cases table)
    test_workflow_requested = Signal()
    #: a valid Apply from the YAML preview committed into the model -
    #: the main window offers the file save (overwrite current yaml /
    #: save to a new yaml file)
    yaml_apply_committed = Signal()
    #: the "Close Yaml" button was clicked - the main window runs its
    #: File > Close Yaml reset (which also clears this page's preview)
    close_yaml_requested = Signal()
    #: M44: a configuration page's Exit prompt asked for "Save as new
    #: yaml" - the main window runs Save as Yaml on the applied values
    save_as_yaml_requested = Signal()
    #: the "Load current yaml" button was clicked - the main window
    #: pushes the model-derived ICT / FCT sequences into the Test Work
    #: Flow page and jumps there (guarded; warns when nothing is
    #: usable)
    load_yaml_requested = Signal()
    #: the block-04 sequence dialog was accepted - carries the WHOLE
    #: editor state [steps, enables, waits, timeouts] (the steps hold
    #: tests + standard operations + flash + Delay); the main window
    #: writes it verbatim on the Test Work Flow page and offers the
    #: YAML save
    ict_sequence_ready = Signal(list)
    #: P3-B5: the block-07 FCT config was accepted - carries the
    #: generated FCT case dicts (name/kind/enable/wait_ms/timeout_ms/
    #: op_params.fct_step) for the Test Work Flow page's FCT table
    fct_sequence_ready = Signal(list)
    #: M22b: the block-07 dialog's in-place "Apply & Save yaml" ran -
    #: the main window refreshes the sequence views and saves the
    #: project yaml WITHOUT closing the dialog (no save prompt)
    fct_sequence_applied = Signal(list)

    def __init__(self, parent=None) -> None:
        """Create the page (model + panes + buttons)."""
        super().__init__(parent)
        self.model = YamlBuildModel()
        #: M37: Virtual mode flag (MainWindow.set_mode -> here) - the
        #: step editors then offer every standard operation
        self._virtual = False
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # M27 P3: an editable plan-version field in the page header.  It
        # drives model.plan_version (1.x.y) so the published file name
        # rev_<version> and project.revision always agree with the field.
        header = QWidget()
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(0, 0, 0, 0)
        header_lay.setSpacing(6)
        header_lay.addWidget(QLabel("Plan version:"))
        self.plan_version_edit = QLineEdit(self.model.plan_version)
        self.plan_version_edit.setMaximumWidth(120)
        self.plan_version_edit.setToolTip(
            "Plan version used in the Draft/Final file name "
            "(format 1.x.y, e.g. 1.1.0)")
        self.plan_version_edit.editingFinished.connect(
            self._on_plan_version_edited)
        header_lay.addWidget(self.plan_version_edit)
        header_lay.addStretch(1)
        root.addWidget(header, 0)

        # the preview pane is created BEFORE the top button row: its
        # Apply button is reparented into that row (item 16; user
        # direction: no Edit mode - the editor is directly editable)

        # account permissions (defaults = supervisor until
        # set_edit_allowed); the former Yaml Preview pane + its five
        # buttons are gone (M19d) - the actions live in the File menu
        self._edit_allowed = True

        # --- single-pane body: block flow (top) | Channel Allocation
        # (below); the YAML preview pane was removed (M19d)
        self.block_flow = BlockFlowWidget()
        self.block_flow.configure_requested.connect(self._open_block)
        self.block_flow.enable_requested.connect(self._set_enabled)
        self.block_flow.enable_all_requested.connect(self._enable_all)
        self.block_flow.disable_all_requested.connect(self._disable_all)
        # single-row card strip (user direction 2026-10-13): the five
        # compact cards share ONE fixed-height row - no scroll area any
        # more (nothing can overflow vertically), the strip takes only
        # its natural height (BlockFlowWidget vertical policy = Fixed)
        # single-page vertical flow (user direction 2026-10-13): the
        # Channel Allocation tables are EMBEDDED below the block cards
        # - one page, top-to-bottom, no missed steps; the dedicated
        # Channel Allocation tab is gone
        self.channel_alloc = ChannelAllocationPage()
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)
        left_lay.addWidget(self.block_flow, 0)      # natural height only
        left_lay.addWidget(self.channel_alloc, 1)   # tables take the rest
        root.addWidget(left, 1)
        # model injected AFTER the widget is parented (PySide shiboken
        # GC bug workaround - see ChannelAllocationPage.__init__)
        self.channel_alloc.set_model(self.model)
        # (level, message) Event-Log mirror: the page funnels the
        # allocation table logs into its own task_log stream
        self.channel_alloc.task_log.connect(self.task_log)
        # NOTE: the page-level hint label was removed (user direction
        # 2026-10-13) - the card tooltips carry the guidance instead.

        # M15: every page long-task (SPF import / Excel import / YAML
        # publish / ...) drives a FOREGROUND modal progress dialog
        # instead of the status bar (user direction 2026-10-25: front
        # progress bar, no status-bar progress bar, no frozen window)
        self._task_bridge = ProgressBridge(self, "Working...")
        self.task_progress.connect(self._task_bridge.stage)

        # restore the persisted state of the current project, then
        # paint both panes from the model
        self._load_persisted()
        self.refresh_all()
        # M34: scroll-protect the page (block cards + allocation tables)
        # on very small windows; the fixed-height card strip is preserved
        wrap_page(self)

    # ------------------------------------------------------ model -> UI
    def refresh_all(self) -> None:
        """Repaint both panes from the model (single broadcast point;
        keeps the diagram <-> YAML sync loop-free)."""
        # M27 P3: keep the header version field in sync with the model
        # (e.g. after a project load restores a stored plan_version).
        edit = getattr(self, "plan_version_edit", None)
        if edit is not None and edit.text() != self.model.plan_version:
            edit.setText(self.model.plan_version)
        for key in STAGE_KEYS:
            self.block_flow.set_state(key, self.model.is_enabled(key))
            self.block_flow.set_module_mark(
                key, self.model.marks.get(key, MARK_NONE))
        # the Auto-Channel Allocation nav card carries its own mark
        self.block_flow.set_module_mark(
            "channel_alloc", self.model.marks.get(
                "channel_alloc", MARK_NONE))
        # the embedded Channel Allocation tables mirror the model
        # (parse result + saved configuration, kept configs preserved)
        self.channel_alloc.refresh_from_model()

    def _on_plan_version_edited(self) -> None:
        """Commit an edited plan version (validated ``1.x.y``).

        An invalid value is rejected: the field snaps back to the model's
        current version and a warning is logged (model.set_plan_version
        itself already applies the same dotted-triple rule)."""
        text = self.plan_version_edit.text().strip()
        if re.match(r"^\d+\.\d+\.\d+$", text):
            self.model.set_plan_version(text)
        else:
            self.plan_version_edit.setText(self.model.plan_version)
            self._tlog("WARN", f"Invalid plan version {text!r} ignored "
                               f"(expected 1.x.y); keeping "
                               f"{self.model.plan_version}")

    def _goto_channel_alloc(self) -> None:
        """Nav card 03: bring the embedded Channel Allocation tables
        into view (single-page vertical flow - no tab switch)."""
        self.channel_alloc.setVisible(True)
        self.channel_alloc.setFocus(Qt.FocusReason.OtherFocusReason)

    def clear_preview(self) -> None:
        """No-op since M19d - the YAML preview pane is gone; kept for
        defensive callers (File > Close Yaml clears the model itself)."""

    def _load_persisted(self) -> None:
        """Restore this project's persisted state (restart-safe)."""
        state = load_project_state(self.model.project_key())
        if state is not None:
            self.model.apply_state(state)

    def _persist(self) -> None:
        """Persist the model state (silent on failure - the GUI must
        never break because persistence did)."""
        save_project_state(self.model.project_key(),
                           self.model.to_dict())

    # ------------------------------------------------------ UI -> model
    def _emit_fct_sequence(self, params: dict):
        """P3-B5: block 07 params -> FCT work-flow case dicts.

        Parses ``fct_test_config_yaml``, builds the ordered FctStep list
        (console commands + Wi-Fi + Bluetooth) and maps it to the
        project-YAML case shape.  No closing row is auto-appended (M22):
        a closing operator dialog belongs to the project's
        ``post_rf_commands`` and stays visible/editable there.

        A project may contain ICT only, FCT only, or both - an FCT
        config with every tab disabled is valid and yields zero cases.

        Returns ``(cases, errors)``: ``errors`` is an empty list on
        success (cases may be empty for an ICT-only project); on a parse
        or validation failure it carries the messages and cases is None.
        """
        import yaml as _yaml
        from mtkgui.engine.fct_test_config import FctTestConfig
        from mtkgui.gui.yamlbuild.fct_build import (
            FctSequence,
            to_project_fct_cases,
        )
        # the block-07 Sequence tab carries the standard operations /
        # flash operations / Delay steps by hand - they run BEFORE the
        # generated console / Wi-Fi / Bluetooth body (single sequence
        # edit source: the Test Work Flow FCT table is a read-only result
        # view)
        seq_cases = self._sequence_cases_from_params(params)
        text = str((params or {}).get("fct_test_config_yaml", "") or "")
        if not text.strip():
            # nothing configured -> ICT-only project is fine (unless the
            # Sequence tab carries steps of its own)
            return list(seq_cases), []
        try:
            node = _yaml.safe_load(text) or {}
            cfg = FctTestConfig.from_dict(
                node.get("fct_test_config") or {})
        except _yaml.YAMLError as exc:
            return None, [f"FCT config parse failed: {exc}"]
        errors = cfg.validate()
        if errors:
            return None, list(errors)
        from mtkgui.engine.fct_test_config import build_fct_steps
        body = build_fct_steps(cfg)
        if not body:
            # all FCT tabs disabled -> the Sequence-tab steps only
            return list(seq_cases), []
        # M44: the run-time sequence is EXACTLY the user's rows - no
        # fixture / power / manual-prompt step is injected around the body
        steps = body
        seq = FctSequence(name="FCT Test Work Flow", steps=steps)
        cases = to_project_fct_cases(seq)
        # every generated case carries its full step marker so the
        # runner routes the row through fct_exec
        for case, step in zip(cases, steps):
            case.setdefault("op_params", {})["fct_step"] = step.to_dict()
        cases = list(seq_cases) + cases
        self._tlog("INFO", f"FCT sequence generated: {len(cases)} cases")
        return cases, []

    def _sequence_cases_from_params(self, params: dict) -> list:
        """The standard-op / flash / Delay steps added in the block-07
        Sequence tab (stored as a YAML list of case dicts)."""
        import yaml as _yaml
        raw = (params or {}).get("fct_sequence_cases_yaml")
        if isinstance(raw, list):
            raw = "\n".join(str(ln) for ln in raw)
        text = str(raw or "")
        if not text.strip():
            return []
        try:
            data = _yaml.safe_load(text)
        except _yaml.YAMLError:
            return []
        if not isinstance(data, list):
            return []
        return [dict(c) for c in data if isinstance(c, dict)]

    def _fct_build_params_with_live_cases(self, module_key: str) -> dict:
        """Reverse sync (user direction 2026-10-14): seed the Build FCT
        dialog params from the CURRENT FCT Test Cases rows of the Test
        Work Flow page - the page is the source of truth when the
        dialog opens; on OK the generated cases flow back through
        ``fct_sequence_ready`` (bidirectional sync).  Without a
        provider (page not wired) the stored params open unchanged."""
        current = dict(self.model.get_params(module_key) or {})
        provider = getattr(self, "current_fct_cases_provider", None)
        cases = (provider() or []) if callable(provider) else []
        if cases:
            from mtkgui.engine.fct_test_config import (
                overlay_console_commands,
            )
            current["fct_test_config_yaml"] = overlay_console_commands(
                current.get("fct_test_config_yaml"), cases)
        return current

    def _apply_save_fct_params(self, params: dict):
        """M22b: the block-07 dialog's "Apply & Save yaml" callback.

        Commits the dialog values into the model, rebuilds the FCT case
        list and broadcasts ``fct_sequence_applied`` - the main window
        repaints the Test Work Flow table and saves the project yaml on
        that one signal, so no save path can leave a stale view behind.

        Returns an error string (the dialog shows it and stays open) or
        None when the configuration applied cleanly.
        """
        self.model.set_params("fct_build", params)
        cases, errors = self._emit_fct_sequence(params)
        if errors:
            self._tlog("ERROR", "FCT config invalid: "
                                + "; ".join(errors))
            return "\n".join(errors[:10])
        # M45b: apply-save runs the M39 validation BEFORE anything is
        # written - module schema + the global project rules on the
        # generated sequence; a blocking issue keeps the dialog open
        errors = self.model.validate_module("fct_build")
        errors += [issue.as_line() for issue in blocking_issues(
            validate_project_yaml(
                {"test_workflow": {"fct_test_cases": cases}}))]
        if errors:
            self._tlog("ERROR", "FCT apply blocked: "
                                + "; ".join(errors[:10]))
            return "\n".join(errors[:10])
        self._set_mark("fct_build", MARK_STAR)
        self.fct_sequence_applied.emit(cases)
        return None

    def open_ict_sequence(self) -> None:
        """Open the "Build ICT Test Work Flow Sequence" dialog.

        Single ICT sequence edit source: reached by the block-04 card
        click AND by double-clicking an ICT result row on the Test Work
        Flow page (that table is now a read-only result view).
        """
        if not self._gate_open(DISPLAY_ICT_WORKFLOW):
            return
        # quiet sync of the embedded Channel Allocation tables into the
        # model BEFORE the pre-check reads allocated_testable
        self.model.set_channel_allocation(self.channel_alloc.collect())
        from mtkgui.gui.yamlbuild.ict_sequence import (
            IctWorkFlowSequenceDialog,
            daq_ai_rail_count,
        )
        # guidance: only channel-allocated nets reach the sequence
        # builder (auto Do-Not-Test rule) - explain BEFORE an empty
        # dialog confuses the operator.  A live result table already
        # holding a sequence (a loaded project) needs no parse run:
        # the dialog re-seeds straight from those rows.
        testable = self.model.imported.get("testable_nets") or {}
        provider = getattr(self, "current_ict_cases_provider", None)
        initial = provider() if callable(provider) else None
        if not testable and not initial:
            QMessageBox.information(
                self, "Build ICT Test Work Flow Sequence",
                "No testable nets parsed yet - run Parse Nets "
                "(block 02) first.")
            return
        allocated = self.model.allocated_testable() or {}
        if len(allocated) < len(testable):
            box = QMessageBox(QMessageBox.Icon.Question,
                              "Channel Allocation incomplete",
                              f"{len(testable) - len(allocated)} of "
                              f"{len(testable)} testable nets have "
                              "no instrument channel assigned - "
                              "unallocated nets are auto "
                              "Do-Not-Test and will NOT appear in "
                              "the sequence.\n\nOpen Channel "
                              "Allocation now?",
                              QMessageBox.StandardButton.Yes
                              | QMessageBox.StandardButton.No,
                              self)
            box.button(QMessageBox.StandardButton.Yes).setText(
                "Open Channel Allocation")
            box.button(QMessageBox.StandardButton.No).setText(
                "Continue anyway")
            if box.exec() == QMessageBox.StandardButton.Yes:
                # single-page flow: scroll to the embedded tables
                self._goto_channel_alloc()
                return
        # bidirectional sync: the live ICT result rows already seed the
        # dialog (page -> dialog); let the user edit them
        dlg = IctWorkFlowSequenceDialog(
            # user rule: nets WITHOUT an allocated instrument
            # channel are auto Do-Not-Test - only allocated nets
            # reach the Test Work Flow sequence builder
            self.model.allocated_testable,
            # bidirectional sync (user direction 2026-10-14): seed
            # the dialog from the CURRENT ICT sequence (the Test Work
            # Flow page mirrors it), so the user edits the live
            # sequence instead of a fresh one
            initial_tests=initial,
            rail_count=daq_ai_rail_count(
                self.model.channel_allocation),
            allocation=self.model.channel_allocation,
            parent=self,
            available_ops=available_ops(self.model, self._virtual))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # the WHOLE editor state travels back (steps + enables +
            # waits + timeouts) - the page writes it verbatim (single
            # sequence source; nothing is re-injected downstream)
            self.ict_sequence_ready.emit(list(dlg.result_data()))
            # configured (OK) -> star mark (user direction)
            self._set_mark(DISPLAY_ICT_WORKFLOW, MARK_STAR)

    def open_fct_sequence(self) -> None:
        """Open the "Build FCT Test Work Flow Sequence" dialog.

        Single FCT sequence edit source: reached by the block-07 card
        click AND by double-clicking an FCT result row on the Test Work
        Flow page (that table is now a read-only result view).
        """
        if not self._gate_open("fct_build"):
            return
        self.model.set_channel_allocation(self.channel_alloc.collect())
        params, _dialog = self.block_flow.open_dialog(
            "fct_build",
            self._fct_build_params_with_live_cases("fct_build"),
            self,
            log_sink=self.task_log.emit,
            progress_sink=self.task_progress.emit,
            apply_save_cb=self._apply_save_fct_params,
            yaml_model=self.model,
            virtual=self._virtual,
            save_as_cb=lambda values: self._save_as_new_yaml(
                "fct_build", values))
        if params is None:
            return
        self.model.set_params("fct_build", params)
        # P3-B5: block accepted -> generate the FCT work-flow cases from
        # the configured fct_test_config. Errors are shown explicitly (no
        # silent ignore); an all-disabled FCT is a valid ICT-only project
        # and still offers the YAML save.
        cases, fct_errors = self._emit_fct_sequence(params)
        if fct_errors:
            self._tlog("ERROR", "FCT config invalid: "
                                + "; ".join(fct_errors))
            QMessageBox.warning(
                self, "Build FCT Test Work Flow",
                "The FCT configuration is invalid - fix the "
                "following before applying:\n\n"
                + "\n".join(fct_errors[:15]))
            return
        self.fct_sequence_ready.emit(cases)
        self._set_mark("fct_build", MARK_STAR)

    # ------------------------------------------------------ M45b gating
    def _design_input_complete(self) -> bool:
        """M45b: module 01 owns three design files (SPF / NET / BOM) -
        with ANY of them missing only module 01 may be opened."""
        params = self.model.get_params("design_input") or {}
        return all(str(params.get(name, "") or "").strip()
                   for name in DESIGN_INPUT_FILES)

    def _module_starred(self, level: str) -> bool:
        """True when one chain level carries the validated star mark."""
        return self.model.marks.get(level, MARK_NONE) == MARK_STAR

    def module_openable(self, module_key: str) -> bool:
        """M45b: can this module be opened right now?

        The ICT chain is strictly sequential: a validated module (or
        the immediately-next module) is openable; module 01 is always
        open.  M45c: ``fct_build`` is independent of the chain (and of
        the design files) - it is ALWAYS openable (FCT-only projects).
        """
        level = GATING_DISPLAY_LEVEL.get(module_key, module_key)
        if level not in GATING_CHAIN:
            return True
        index = GATING_CHAIN.index(level)
        if index == 0:
            return True
        if not self._design_input_complete():
            return False
        if self._module_starred(level):
            return True
        return self._module_starred(GATING_CHAIN[index - 1])

    def _blocked_reason(self, module_key: str) -> str:
        """The "complete module 0X first" prompt text (M45b)."""
        level = GATING_DISPLAY_LEVEL.get(module_key, module_key)
        if level not in GATING_CHAIN:
            return ""                     # M45c: independent module
        index = GATING_CHAIN.index(level)
        if not self._design_input_complete():
            return ("Complete module 01 - Design Input first: load the "
                    "SPF, NET and BOM files and Apply_Save yaml, then "
                    "open " + GATING_LEVEL_TITLE[level] + ".")
        previous = GATING_CHAIN[index - 1]
        return (f"Complete module 0{index} - "
                f"{GATING_LEVEL_TITLE[previous]} first "
                "(Apply_Save yaml or a valid loaded project), then open "
                f"{GATING_LEVEL_TITLE[level]}.")

    def _gate_open(self, module_key: str) -> bool:
        """M45b: block the open with an explicit prompt when locked."""
        if self.module_openable(module_key):
            return True
        QMessageBox.information(self, "Module locked",
                                self._blocked_reason(module_key))
        return False

    def _level_valid(self, level: str) -> bool:
        """M45b: load-time validation of one chain level."""
        if level == "design_input":
            return (self._design_input_complete()
                    and not self.model.validate_module("design_input"))
        if level == "ict_workflow":
            # level 03 owns no validatable YAML module (rails / clocks /
            # gpios are NO_UI and their content belongs to the Test Work
            # Flow page) - it is complete once the project carries a
            # parsed net set / an ICT allocation
            return bool(self.model.imported.get("testable_nets")) or bool(
                self.model.allocated_testable())
        return not self.model.validate_module(level)

    def _fct_level_valid(self) -> bool:
        """M45c: fct_build validates INDEPENDENTLY of the ICT chain.

        A loaded project with FCT parameters is valid when its module
        schema passes AND the generated sequence passes the same M39
        global rules used by every save path.  A project without FCT
        content gets no star (nothing to validate).
        """
        params = self.model.get_params("fct_build") or {}
        if not any(str(params.get(key) or "").strip() for key in
                   ("fct_test_config_yaml", "fct_sequence_cases_yaml")):
            return False
        if self.model.validate_module("fct_build"):
            return False
        try:
            cases, errors = self._emit_fct_sequence(params)
        except Exception:                     # noqa: BLE001 - never crash
            return False
        if errors:
            return False
        return not blocking_issues(validate_project_yaml(
            {"test_workflow": {"fct_test_cases": cases}}))

    def apply_load_gating(self) -> None:
        """M45b: sequential re-validation after a project LOAD.

        Every mark is cleared first; each ICT level that validates gets
        its star and unlocks the next one.  The first failing level
        stops the chain - every later ICT module stays locked.  M45c:
        ``fct_build`` is re-validated INDEPENDENTLY (its own module
        schema + M39 rules), so an FCT-only project stars it without
        any ICT level.
        """
        for level in GATING_CHAIN:
            self.model.set_mark(level, "")
        self.model.set_mark(DISPLAY_CHANNEL_ALLOC, "")
        self.model.set_mark("fct_build", "")
        for level in GATING_CHAIN:
            if not self._level_valid(level):
                break
            self.model.set_mark(level, MARK_STAR)
        if self._fct_level_valid():
            self.model.set_mark("fct_build", MARK_STAR)
        self._after_model_change()

    def _open_block(self, module_key: str) -> None:
        """Open the dedicated config dialog of one module and store
        the validated result (independent save + validation)."""
        if not self._gate_open(module_key):
            return
        if module_key == "channel_alloc":
            # the "Auto-Channel Allocation" card (user direction
            # 2026-10-13): clicking runs the automatic allocation
            # (results appear in the embedded tables right below) and
            # the card gets a star once the allocation ran
            self.channel_alloc.auto_allocate()
            self._set_mark("channel_alloc", MARK_STAR)
            return
        # the two sequence builders are public entry points: the Test Work
        # Flow page's row double-click lands here (single sequence edit
        # source) exactly like the block card click
        if module_key == "ict_workflow":
            return self.open_ict_sequence()
        if module_key == "fct_build":
            return self.open_fct_sequence()
        net = self.model.imported.get("net") or {}
        # quiet sync of the embedded Channel Allocation tables into
        # the model BEFORE any dependent read (the tab-leave hideEvent
        # save logs loudly, this one is silent)
        self.model.set_channel_allocation(self.channel_alloc.collect())
        params, dialog = self.block_flow.open_dialog(
            module_key,
            self.model.get_params(module_key),
            self,
            log_sink=self.task_log.emit,
            progress_sink=self.task_progress.emit,
            net_source=(net.get("raw", ""),
                        Path(net.get("file", "")).name)
            if module_key == "parse_ict" else None,
            panel_state={
                "net_rules": self.model.net_classification_rules,
                "power_dnt": {
                    ln.strip() for ln in
                    (self.model.get_params("parse_ict") or {})
                    .get("power_dont_test", "").splitlines()
                    if ln.strip()},
                "spf_nets": self.model.imported.get("spf_nets", set()),
                "risk_thresholds": dict(
                    (self.model.path_risk or {}).get("thresholds")
                    or {}),
                "risk_scores": dict(
                    (self.model.path_risk or {}).get("scores") or {}),
            } if module_key == "parse_ict" else None,
            yaml_model=self.model if module_key == "parse_ict" else None,
            save_as_cb=lambda values: self._save_as_new_yaml(
                module_key, values))
        if params is None:
            return
        self.model.set_params(module_key, params)
        # configured (OK) -> star mark (user direction); the full
        # sequence validation runs AUTOMATICALLY before every publish
        # (the manual Validate card was retired 2026-10-13)
        if module_key == "design_input" and dialog is not None \
                and dialog.panel is not None:
            # keep the loaded NET bytes for the Parse Nets module (T8)
            panel = dialog.panel
            self.model.imported["net"] = {
                "file": panel.net_path,
                "raw": panel.net_text,
            }
        if module_key == "parse_ict" and dialog is not None \
                and dialog.nets_panel is not None \
                and dialog.nets_panel.result is not None:
            # the parse result is the single data source for the
            # Channel Allocation tables (T10); "Filtered" overrides
            # keep a net out, restored filtered nets join a category
            result = dialog.nets_panel.result
            overrides = dialog.nets_panel._category_overrides
            testable = {}
            for cat, records in (("Power", result.power),
                                 ("Clock", result.clock),
                                 ("GPIO", result.gpio)):
                for rec in records:
                    if overrides.get(rec.name) == "Filtered":
                        continue        # moved to Filtered Nets
                    chosen = overrides.get(rec.name, cat)
                    testable[rec.name] = testable_net_entry(
                        rec, DISPLAY_TO_CATEGORY.get(chosen, chosen),
                        auto_generated=bool(
                            dialog.nets_panel._auto_generated.get(rec.name)),
                        override=rec.name in overrides)
            for rec in result.filtered_records:
                cat = overrides.get(rec.name)
                if cat and cat != "Filtered":
                    testable[rec.name] = testable_net_entry(
                        rec, DISPLAY_TO_CATEGORY.get(cat, cat),
                        filtered=True, override=True)
            self.model.imported["testable_nets"] = testable
            # item 24: rules persistence (the channel assignment lives
            # in the Channel Allocation page only; the power tree draft
            # is owned by the dedicated Power Tree page)
            nets_panel = dialog.nets_panel
            self.model.net_classification_rules = \
                dict(nets_panel.net_rules)
            # Do-Not-Test flags persist into the parse_ict params
            self.model.set_params("parse_ict", {
                "power_dont_test":
                    "\n".join(nets_panel.power_dnt_nets())})
            # test path risk: thresholds + per-net advisory scores
            self.model.path_risk = {
                "thresholds": dict(nets_panel.risk_thresholds),
                "scores": dict(nets_panel.risk_scores),
            }
        errors = self.model.validate_module(module_key)
        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
        else:
            # M45b: star = validated & complete - a failing module stays
            # unstarred, so its next level stays locked
            self._set_mark(module_key, MARK_STAR)
        self._after_model_change()

    def _save_as_new_yaml(self, module_key: str, values: dict) -> None:
        """M44: a config page's Exit prompt chose "Save as new yaml" -
        apply the values to the model and hand the file pick to the main
        window's Save as Yaml entry.

        M45b: the module must pass its own schema validation first -
        an invalid module never reaches the save.
        """
        self.model.set_params(module_key, values)
        errors = self.model.validate_module(module_key)
        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors))
            return
        self._set_mark(module_key, MARK_STAR)
        self._after_model_change()
        self.save_as_yaml_requested.emit()

    def _set_enabled(self, module_key: str, enabled: bool) -> None:
        """Enable / disable one module (parameters retained; disabled
        modules leave the effective YAML and flow validation)."""
        self.model.set_enabled(module_key, enabled)
        self._after_model_change()

    def _enable_all(self) -> None:
        """Batch Enable All (right-click menu): every module joins
        the flow, YAML generation and validation."""
        self.model.enable_all()
        self._after_model_change()

    def _disable_all(self) -> None:
        """Batch Disable All (right-click menu): no module takes part
        in the flow compilation; parameters are silently retained."""
        self.model.disable_all()
        self._after_model_change()

    def _after_model_change(self) -> None:
        """Single broadcast point after every model mutation."""
        self._persist()
        self.refresh_all()

    def _set_mark(self, module_key: str, mark: str) -> None:
        """Set one module's card mark (star = edited / check =
        validated), persisted with the model (restart-safe)."""
        self.model.set_mark(module_key, mark)
        self.block_flow.set_module_mark(module_key, mark)
        self._persist()

    def apply_power_rails(self, seq: dict) -> None:
        """Sync the Test Work Flow page's power-rails capture config
        into the model (user question: configured power rails MUST
        land in the YAML): stored as its own section AND mirrored into
        the rails module's capture parameters; the preview refreshes."""
        self.model.set_power_rails(seq)
        self._persist()

    # ------------------------------------------------- long-task helpers
    def _task(self, percent: int, label: str) -> None:
        """Emit a long-task progress step to the global status bar."""
        self.task_progress.emit(percent, label)

    def _tlog(self, level: str, message: str) -> None:
        """Mirror one Event-Log line (level, message) to the window."""
        self.task_log.emit(level, message)

    # ------------------------------------------------------- Excel I/O
    def set_virtual(self, virtual: bool) -> None:
        """M37: Virtual mode (no hardware) makes every standard
        operation usable in the step editors."""
        self._virtual = bool(virtual)

    def set_edit_allowed(self, allowed: bool) -> None:
        """Operator accounts cannot edit the YAML config (T5): the
        whole action row (Excel import / export) and the preview
        Apply button follow the permission; the editor stays
        read-only for operators."""
        self._edit_allowed = bool(allowed)

    def _export_excel(self) -> None:
        """Export all module parameters / thresholds / sequence /
        enable state / remarks to an .xlsx workbook."""
        if not self._edit_allowed:
            QMessageBox.information(
                self, "Permission",
                "Operator account cannot modify the YAML configuration.")
            return
        default = (f"YamlBuild_{self.model.project_key()}.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", default, "Excel (*.xlsx)")
        if not path:
            return
        begin("yamlbuild: export excel")
        try:
            rows = export_to_excel(self.model, path)
        except OSError as exc:
            self._tlog("ERROR", f"Excel export failed: {exc}")
            QMessageBox.critical(self, "Export Failed", str(exc))
            end("yamlbuild: export excel")
            return
        # short task: one Event-Log line only (no progress machinery)
        self._tlog("INFO", f"Excel export done: {rows} rows -> "
                           f"{Path(path).name}")
        QMessageBox.information(
            self, "Export to Excel",
            f"Exported {rows} rows to {path}")
        end("yamlbuild: export excel")

    def _import_excel(self) -> None:
        """Import a workbook with full-workbook validation (invalid
        rows abort the import with the error list).  Long-task aware
        (T6): global progress + Event-Log step detail, failures with
        the exact row reasons."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import from Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        begin("yamlbuild: import excel")
        self._task(0, "import: reading workbook")
        self._tlog("INFO", f"Excel import started: {Path(path).name}")
        self._task(40, "import: validating + applying rows")
        report = import_from_excel(self.model, path)
        if report.errors:
            # precise failure reasons (first rows), no silent fail
            for err in report.errors[:5]:
                self._tlog("ERROR", f"Excel import rejected: {err}")
            self._task(0, "import: idle")
            QMessageBox.warning(
                self, "Import Rejected",
                "The workbook was not applied:\n"
                + "\n".join(report.errors[:20])
                + (f"\n... and {len(report.errors) - 20} more"
                   if len(report.errors) > 20 else ""))
            end("yamlbuild: import excel")
            return
        self._after_model_change()      # parse -> project view refresh
        self._task(100, "import: done")
        self._tlog("INFO", f"Excel import done: {report.imported} "
                           f"parameters applied from {Path(path).name}")
        QMessageBox.information(
            self, "Import from Excel",
            f"Applied {report.imported} parameters from {path}")
        end("yamlbuild: import excel")

    # ------------------------------------------------------- publishing
    def _publish(self, kind: str) -> None:
        """Build Draft / Release Final YAML - fully automatic (V4.0
        rule 5.4: the file name is composed from the Design Input
        Core ID / Project Part #, no manual input).

        The model must be valid (all enabled modules).  The file is
        written to the standard plans directory, archived under the
        project key, and the result dialog shows all paths.
        """
        # the embedded Channel Allocation tables sync into the model
        # FIRST (an in-page save is required because the tables live
        # on THIS page now - the tab-leave hideEvent alone does not
        # cover reads on the same page), then the automatic
        # full-sequence validation gates the publish (the manual
        # Validate card was retired 2026-10-13)
        self.model.set_channel_allocation(self.channel_alloc.collect())
        errors = self.model.validate_all()
        if errors:
            for err in errors[:5]:
                self._tlog("ERROR", f"{kind} blocked by validation: "
                                    f"{err}")
            QMessageBox.warning(
                self, f"Cannot build {kind}",
                "Fix the validation errors first:\n"
                + "\n".join(errors[:15]))
            return
        begin("yamlbuild: publish")
        self._task(0, f"{kind}: publishing")
        self._tlog("INFO", f"{kind} publish started "
                           f"(project {self.model.project_key()})")
        self._task(50, f"{kind}: writing YAML")
        try:
            name = plan_filename(self.model, kind)
            path = publish(self.model, kind, PLANS_DIR)
        except (ValueError, OSError) as exc:
            self._tlog("ERROR", f"{kind} publish failed: {exc}")
            self._task(0, "publish: idle")
            QMessageBox.critical(self, f"{kind.capitalize()} Failed",
                                 str(exc))
            end("yamlbuild: publish")
            return
        archived = archive_copy(path, Path.cwd(),
                                self.model.project_key())
        self._after_model_change()          # refresh the project view
        self._task(100, f"{kind}: done")
        self._tlog("INFO", f"{kind} publish done: {Path(path).name} "
                           f"(archive: {Path(archived).name})")
        QMessageBox.information(
            self, f"{kind.capitalize()} YAML published",
            f"File: {path}\n"
            f"Archive copy: {archived}\n"
            f"Plan version: {self.model.plan_version}\n"
            f"Build version: {get_version_info().suffix()}")
        end("yamlbuild: publish")

    def compare_with(self, other_path: str) -> str:
        """Unified diff of the last published file against another
        plan (version compare / archive traceability).

        Args:
            other_path: The plan file to compare with.

        Returns:
            Diff text.
        """
        path, _ = QFileDialog.getOpenFileName(
            self, "Compare with plan", "", "YAML (*.yaml *.yml)")
        if not path:
            return ""
        return compare_plans(other_path, path)

    # ---------------------------------------------------- test helpers
    def state(self) -> dict:
        """Return the persisted model state (diagnostics / tests).

        Returns:
            Model state dict.
        """
        return self.model.to_dict()

    def dump_yaml(self) -> str:
        """Return the current effective YAML text (tests / export).

        Returns:
            YAML text.
        """
        return self.model.to_effective_yaml()
