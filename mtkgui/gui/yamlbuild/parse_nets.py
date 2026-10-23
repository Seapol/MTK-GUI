# -*- coding: utf-8 -*-
"""Parse Nets for ICT (P3-B2 T8): netlist pre-analysis module.

Takes the raw NET file loaded by the Design Input panel (load only
there - this module performs the FORMAL parse) and extracts every
valid ICT-testable net, categorized into the three test objects:

* **Power nets**  - supply rails (VDD / VCC / nVn / VPRE ...);
* **Clock nets**  - single-ended clock nets (CLK / XTAL / OSC ...);
* **GPIO nets**   - remaining signal nets (GPIO channel candidates).

Filtered out (invalid / non-testable, with the reason kept for the
Event Log):

* reference grounds (``gnd_ref``) - measurement loop reference, not a
  net under test;
* differential pairs (``diff_pair``) - not a single-ended ICT object
  (excluded from the clock set by the classification rules);
* nets without any valid member pin - no test point possible.

The parse core lives in the headless :mod:`mtkgui.ict.netparse`
package - this module only provides the Block 02 Qt panel.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mtkgui.ict.netparse import (
    CATEGORY_CONTROL_IO_LABEL,
    CATEGORY_GND,
    CATEGORY_OTHERS,
    CATEGORY_POWER,
    ParseNetsResult,
    detect_netlist_format,
    parse_netlist_auto,
    parse_testable_nets,
    rank_result,
    select_test_points,
)
from mtkgui.gui.yamlbuild.path_risk import (
    DEFAULT_THRESHOLDS,
    LEVEL_HIGH,
    LEVEL_MEDIUM,
    WARNING_MESSAGE,
    evaluate_paths,
)

#: Parsed-Nets-table category labels (the combo the user can change;
#: "Filtered" moves a net into the Filtered Nets table)
TABLE_CATEGORIES = ("Power", "SE Clock", CATEGORY_CONTROL_IO_LABEL,
                    CATEGORY_OTHERS, "GND", "Filtered")

#: the Filtered-Nets-table category (moved back by picking a real one)
CATEGORY_FILTERED = "Filtered"

#: nets of these categories default to Do Not Test (user direction:
#: control IO is testable, others are not)
DNT_DEFAULT_CATEGORIES = (CATEGORY_OTHERS, "GND")


class ParseNetsPanel(QWidget):
    """Block 02 embedded panel: Parse button + net list preview."""

    #: (level, message) Event-Log mirror (T6)
    task_log = Signal(str, str)
    #: (percent, label) long-task progress mirror (T6)
    task_progress = Signal(int, str)
    #: emitted after a successful parse (Channel Allocation refresh)
    nets_parsed = Signal(object)     # ParseNetsResult
    #: custom classification rules saved via the editor dialog
    rules_changed = Signal(dict)
    #: test path risk evaluation result (thresholds + per-net scores)
    path_risk_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result: ParseNetsResult | None = None
        self._net_text = ""          # raw NET bytes (Design Input)
        self._net_name = ""          # NET file name (log display)
        # item 24: SPF-anonymous net tags survive re-parses
        self._auto_generated: dict[str, bool] = {}
        self.spf_nets: set = set()   # SPF net names (Task 6 rule)
        # test path complexity risk (topology-based, advisory only):
        # GUI-configurable thresholds + per-net scores (both persisted)
        self.risk_thresholds: dict = dict(DEFAULT_THRESHOLDS)
        self.risk_scores: dict = {}
        # Parsed-Nets-table state: per-net Do-Not-Test flags (explicit
        # user toggles, they win over the category defaults) and the
        # user category overrides (combo changes)
        self._dnt_flags: dict[str, bool] = {}
        self._category_overrides: dict[str, str] = {}
        # M5 ICT Test Plan sync: the project YamlBuildModel (injected by
        # the block dialog) and the commit gate - importing a workbook
        # into the production YAML is only allowed once the block was
        # applied (OK saved)
        self.yaml_model = None
        self._applied = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # the three wide tables need room - never squeeze the columns
        # into overlapping text
        self.setMinimumWidth(860)

        # --------------------------------- classification rules entry
        # the THREE inline regex fields are gone (redundant with the
        # Edit Net Classification Rules dialog); the dialog button
        # sits LEFT of the Parse button (user direction).  GND stays
        # system-auto - no config entry anywhere.
        self.net_rules: dict = {}          # custom regexes (persisted)

        row = QHBoxLayout()
        self.btn_rules = QPushButton("Edit Net Classification Rules")
        self.btn_rules.setToolTip(
            "Edit the net name regex rules: Power / SE Clock / "
            "Control IO / Differential pair, with instant test, factory "
            "reset and save-time regex validation (GND is "
            "system-auto)")
        row.addWidget(self.btn_rules)
        self.btn_parse = QPushButton("Parse Nets for ICT")
        self.btn_parse.setToolTip(
            "Formally parse the NET file imported on the Design Input "
            "page: extract all testable Power / Clock / GPIO nets and "
            "filter the non-testable ones (grounds, diff pairs, "
            "pin-less nets)")
        row.addWidget(self.btn_parse)
        self.lbl_summary = QLabel("no parse yet")
        row.addWidget(self.lbl_summary, 1)
        lay.addLayout(row)
        # optional BOM evidence summary (M6 W1): the library is built
        # from design_input.bom_file with the same pipeline as the CLI
        self.lbl_bom = QLabel("BOM: (not imported)")
        self.lbl_bom.setObjectName("muted")
        lay.addWidget(self.lbl_bom)

        # ------------------------------ table 1: Parsed Nets (user
        # direction: the SE Clock / GPIO allocation tables are GONE -
        # the channel assignment lives in Channel Allocation only.
        # Columns: Net | Test Points | Category (user-changeable) |
        # Do Not Test + the M4 read-only facts Confidence / Input Rail
        # / Sub-class; Others and GND default to Do Not Test)
        lbl_nets = QLabel("Parsed Nets:")
        lbl_nets.setObjectName("strong")
        lay.addWidget(lbl_nets)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Net", "Test Points", "Category", "Do Not Test",
             "Confidence", "Input Rail", "Sub-class"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        # the slack goes to the TEST POINTS column (user direction:
        # a Net-stretch starved the other columns)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(220)
        lay.addWidget(self.table, 1)

        # ------------------------------ table 2: Filtered Nets (user
        # direction: the excluded nets stay visible with their reason;
        # the Category combo defaults to "Filtered" - picking Power /
        # SE Clock / Control IO / GND moves the net BACK into the Parsed
        # Nets table, and picking "Filtered" in the Parsed Nets table
        # moves it here)
        lbl_filtered = QLabel("Filtered Nets:")
        lbl_filtered.setObjectName("strong")
        lay.addWidget(lbl_filtered)
        self.table_filtered = QTableWidget(0, 3)
        self.table_filtered.setHorizontalHeaderLabels(
            ["Net", "Reason", "Category"])
        self.table_filtered.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        # the slack goes to the REASON column (user direction)
        self.table_filtered.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.table_filtered.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_filtered.setMaximumHeight(160)
        lay.addWidget(self.table_filtered)

        # GND integrity resident hint (core-algorithm standard 5.2):
        # advisory only - never blocks the parse
        self.lbl_gnd_risk = QLabel("GND integrity: (parse first)")
        self.lbl_gnd_risk.setObjectName("muted")
        self.lbl_gnd_risk.setWordWrap(True)
        lay.addWidget(self.lbl_gnd_risk)

        self.btn_parse.clicked.connect(self.parse_nets)

        # ------------------------------------------------ item 24 tools
        # risk thresholds (the rules dialog button sits next to Parse)
        tools = QHBoxLayout()
        self.btn_risk_thresholds = QPushButton("Risk Thresholds")
        self.btn_risk_thresholds.setToolTip(
            "Configure the test path complexity score thresholds "
            "(Medium / High lower bounds). The warning is advisory "
            "only and never blocks a channel assignment")
        tools.addWidget(self.btn_risk_thresholds)
        # M5 ICT Test Plan output files + YAML bidirectional sync
        self.btn_export_plan = QPushButton("Export ICT Test Plan")
        self.btn_export_plan.setToolTip(
            "Write the six-sheet ICT Test Plan workbook (Power / "
            "SE-Clock / Control IO / GND / Others) plus its evidence "
            "markdown")
        tools.addWidget(self.btn_export_plan)
        self.btn_import_yaml = QPushButton("Import to YAML")
        self.btn_import_yaml.setToolTip(
            "Import an ICT Test Plan workbook into the project YAML: "
            "existing YAML values always win, blank cells are filled, "
            "new nets are appended (never deleted)")
        tools.addWidget(self.btn_import_yaml)
        self.btn_export_yaml = QPushButton("Export from YAML")
        self.btn_export_yaml.setToolTip(
            "Re-export the ICT Test Plan workbook + evidence from the "
            "project YAML (YAML production values win, blanks are "
            "filled by the algorithm)")
        tools.addWidget(self.btn_export_yaml)
        tools.addStretch(1)
        lay.addLayout(tools)

        self.btn_rules.clicked.connect(self._edit_rules)
        self.btn_risk_thresholds.clicked.connect(
            self._edit_risk_thresholds)
        self.btn_export_plan.clicked.connect(self.export_test_plan)
        self.btn_import_yaml.clicked.connect(self.import_to_yaml)
        self.btn_export_yaml.clicked.connect(self.export_from_yaml)

    # ------------------------------------------------- ICT Test Plan sync
    def set_yaml_model(self, model) -> None:
        """Inject the project YamlBuildModel (Test Plan sync target)."""
        self.yaml_model = model

    def mark_applied(self) -> None:
        """Open the commit gate for this dialog instance (fallback; the
        sync buttons gate on the MODEL, not on this instance flag)."""
        self._applied = True

    def _model_has_applied_plan(self) -> bool:
        """True when the project YAML already holds an applied parse
        result: testable nets or a filled channel allocation.  This is
        the sync gate - a per-dialog 'applied' flag can never survive
        the OK-click that closes the dialog (GUI-FIX2 F1)."""
        model = self.yaml_model
        if model is None:
            return False
        if self._applied:
            return True
        if (model.imported or {}).get("testable_nets"):
            return True
        allocation = model.get_channel_allocation() or {}
        return any(bool(allocation.get(kind))
                   for kind in ("power", "clock", "gpio"))

    def _plan_source_result(self):
        """Parse result for the workbook sync: the dialog's own parse,
        else a fresh run of the SAME headless pipeline - never an
        'apply first' round-trip."""
        if self.result is not None:
            return self.result
        if (self._net_text or "").strip():
            self.parse_nets()
        return self.result

    def _sync_allowed(self, title: str) -> bool:
        """Sync precondition: a project YAML plus parsed ICT data
        (from the dialog or from an earlier applied block)."""
        from PySide6.QtWidgets import QMessageBox

        if self.yaml_model is None:
            QMessageBox.warning(self, title, "No project YAML is loaded.")
            return False
        if self._model_has_applied_plan():
            return True
        if self._plan_source_result() is not None:
            return True
        QMessageBox.warning(
            self, title,
            "No parsed ICT data yet - parse the nets (or apply this "
            "block once) before syncing with the YAML.")
        return False

    def _project_name(self) -> str:
        from mtkgui.ict.netparse.export_testplan import (
            project_name_from_path,
        )
        product = ""
        if self.yaml_model is not None:
            product = str(self.yaml_model.get_params("design_input")
                          .get("product_id") or "").strip()
        return product or project_name_from_path(self._net_name or "")

    def _log_report(self, title: str, report: list) -> None:
        for line in report:
            self.task_log.emit("INFO", f"{title}: {line}")

    def export_test_plan(self) -> None:
        """Write the workbook + evidence markdown from the current
        parse (allowed in DRAFT - it is a design artifact)."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from mtkgui.ict.netparse.capacity import DEFAULT_LIMITS
        from mtkgui.ict.netparse.export_testplan import (
            export_testplan_pair,
        )
        if self.result is None:
            QMessageBox.warning(self, "Export ICT Test Plan",
                                "Parse the nets first.")
            return
        default = f"ICT Test Plan for {self._project_name()}.xlsx"
        path, _selected = QFileDialog.getSaveFileName(
            self, "Export ICT Test Plan", default, "Excel (*.xlsx)")
        if not path:
            return
        rows, sections = export_testplan_pair(
            self.result, DEFAULT_LIMITS, path, self._project_name())
        self.task_log.emit(
            "INFO",
            f"ICT Test Plan written: {path} ({rows} rows) + evidence "
            f"({sections} nets)")

    def import_to_yaml(self) -> None:
        """Workbook -> project YAML (gate: project YAML + parsed data)."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from mtkgui.gui.yamlbuild.testplan_sync import testplan_to_yaml
        if not self._sync_allowed("Import to YAML"):
            return
        path, _selected = QFileDialog.getOpenFileName(
            self, "Import to YAML", "", "Excel (*.xlsx)")
        if not path:
            return
        try:
            testplan_to_yaml(self.yaml_model, path, None, self.result)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Import to YAML",
                                f"Could not import the workbook:\n{exc}")
            return
        self._log_report("import to YAML",
                         self.yaml_model.testplan_sync_report)

    def export_from_yaml(self) -> None:
        """Project YAML -> workbook + evidence markdown."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from mtkgui.gui.yamlbuild.testplan_sync import yaml_to_testplan
        if not self._sync_allowed("Export from YAML"):
            return
        default = f"ICT Test Plan for {self._project_name()}.xlsx"
        path, _selected = QFileDialog.getSaveFileName(
            self, "Export from YAML", default, "Excel (*.xlsx)")
        if not path:
            return
        md_path = str(Path(path).with_name(
            Path(path).stem + "_evidence.md"))
        try:
            yaml_to_testplan(self.yaml_model, path, md_path)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Export from YAML",
                                f"Could not export the workbook:\n{exc}")
            return
        self._log_report("export from YAML",
                         self.yaml_model.testplan_sync_report)

    # ---------------------------------------------------------- item 24
    def set_dnt_state(self, dnt_nets: set[str] | None) -> None:
        """Restore the persisted Do-Not-Test net set (the explicit
        user flags - they win over the Control IO/GND category defaults)."""
        self._dnt_flags = {n: True for n in (dnt_nets or set())}

    def power_dnt_nets(self) -> list[str]:
        """All nets currently flagged Do Not Test (any category)."""
        return sorted(n for n, v in self._dnt_flags.items() if v)

    def _dnt_default(self, category: str) -> bool:
        """Category default: Others and GND default Do Not Test
        (control IO stays testable)."""
        return category in DNT_DEFAULT_CATEGORIES

    def _dnt_set(self, name: str, checked: bool) -> None:
        self._dnt_flags[name] = checked
        self.task_log.emit(
            "INFO",
            f"net {name} marked "
            f"{'Do Not Test' if checked else 'testable'}")

    def _category_changed(self, name: str, category: str) -> None:
        """User re-categorization: the override survives re-parses and
        the Do-Not-Test flag follows the new category default.  The
        "Filtered" choice MOVES the net into the Filtered Nets table."""
        self._category_overrides[name] = category
        if category == CATEGORY_FILTERED:
            self.task_log.emit(
                "INFO", f"net {name} moved to the Filtered Nets table")
            self._refresh_tables()
            return
        default = self._dnt_default(category)
        self._dnt_flags[name] = default
        # keep the row's DNT checkbox in sync (no double log)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item is not None and item.text() == name:
                box = self.table.cellWidget(r, 3)
                if box is not None:
                    box.blockSignals(True)
                    box.setChecked(default)
                    box.blockSignals(False)
                break
        self.task_log.emit(
            "INFO", f"net {name} re-categorized as {category}"
            + (" (Do Not Test)" if default else ""))

    def _filtered_category_changed(self, name: str,
                                   category: str) -> None:
        """Filtered-Nets-table combo: picking a REAL category moves
        the net back into the Parsed Nets table ("Filtered" keeps it
        here)."""
        self._category_overrides[name] = category
        if category == CATEGORY_FILTERED:
            self._dnt_flags.pop(name, None)
            self.task_log.emit(
                "INFO", f"net {name} stays filtered")
            self._refresh_tables()
            return
        self._dnt_flags[name] = self._dnt_default(category)
        self.task_log.emit(
            "INFO", f"net {name} restored from Filtered as {category}")
        self._refresh_tables()

    def _refresh_tables(self) -> None:
        """Re-render both tables from the current result + overrides
        (the move between the tables is a re-render)."""
        if self.result is None:
            return
        self._fill_preview(self.result)
        self._fill_filtered(self.result)

    def set_rules(self, rules: dict) -> None:
        """Load the persisted classification rules (project YAML)."""
        self.net_rules = dict(rules or {})

    # ------------------------------------------------------ path risk
    def _gnd_nets(self, result: ParseNetsResult) -> set[str]:
        """GND reference nets (never scored - common star only): the
        parsed GND rows plus any remaining filtered reference grounds."""
        gnd = {r.name for r in result.gnd}
        gnd |= {name for name, reason in result.filtered
                if "reference ground" in reason}
        return gnd

    def _evaluate_risk(self, result: ParseNetsResult) -> None:
        """Evaluate the loop risk for every non-DNT testable net.

        Scored targets: the Power / SE Clock / Control IO nets NOT flagged
        Do Not Test (the channel assignment itself lives in the
        Channel Allocation page).  GND nets are excluded.  Advisory
        only - never blocks a channel assignment."""
        gnd_nets = self._gnd_nets(result)
        scored = set()
        for records, category in ((result.power, "Power"),
                                  (result.clock, "SE Clock"),
                                  (result.control_io,
                                   CATEGORY_CONTROL_IO_LABEL)):
            for rec in records:
                if self._auto_generated.get(rec.name):
                    continue
                if self._dnt_flags.get(
                        rec.name, self._dnt_default(category)):
                    continue
                scored.add(rec.name)
        scores = evaluate_paths(sorted(scored), self._net_members(),
                                gnd_nets, self.risk_thresholds)
        self.risk_scores = scores
        self.path_risk_changed.emit({
            "thresholds": dict(self.risk_thresholds),
            "scores": dict(scores),
        })
        warned = [n for n, s in scores.items() if s["warning"]]
        if warned:
            self.task_log.emit(
                "WARNING",
                f"test path risk: {', '.join(sorted(warned))} - "
                + WARNING_MESSAGE)

    def _edit_risk_thresholds(self) -> None:
        """Open the score threshold editor; accepted thresholds are
        re-applied to the current parse immediately (still advisory
        only) and persist into the project YAML."""
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QSpinBox,
            QVBoxLayout,
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("Test Path Risk Thresholds")
        lay = QVBoxLayout(dlg)
        form = QFormLayout()
        spin_medium = QSpinBox()
        spin_medium.setRange(1, 9)
        spin_medium.setValue(self.risk_thresholds.get("medium_min", 4))
        spin_high = QSpinBox()
        spin_high.setRange(2, 10)
        spin_high.setValue(self.risk_thresholds.get("high_min", 7))
        form.addRow("Medium risk from score:", spin_medium)
        form.addRow("High risk from score:", spin_high)
        lay.addLayout(form)
        note = QLabel(
            "Score 0-3 Low / 4-6 Medium / 7-10 High (factory "
            "defaults). The warning is advisory only and never "
            "blocks a channel assignment.")
        note.setWordWrap(True)
        lay.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        from mtkgui.gui.yamlbuild.path_risk import normalize_thresholds
        self.risk_thresholds = normalize_thresholds({
            "medium_min": spin_medium.value(),
            "high_min": spin_high.value(),
        })
        # re-evaluate against the current parse (thresholds live)
        if self.result is not None:
            self._evaluate_risk(self.result)
        self.task_log.emit(
            "INFO",
            "test path risk thresholds saved: "
            f"{self.risk_thresholds}")

    def _edit_rules(self) -> None:
        """Open the net classification rules editor; accepted rules
        are stored for the project YAML persistence."""
        from mtkgui.gui.yamlbuild.net_rules import (
            NetRulesEditorDialog,
        )
        dlg = NetRulesEditorDialog(self.net_rules, self)
        if dlg.exec() == NetRulesEditorDialog.DialogCode.Accepted:
            self.net_rules = dlg.rules()
            self.set_rules(self.net_rules)   # sync the inline edits
            self.rules_changed.emit(dict(self.net_rules))
            self.task_log.emit(
                "INFO", "net classification rules saved")
            if self.result is not None:
                self.parse_nets()            # live effect

    def _net_members(self) -> dict:
        """Net member pins from the raw netlist text (bridge detection;
        dual-format aware - SPF and NET members map identically)."""
        try:
            return parse_netlist_auto(self._net_text).nets
        except Exception:
            return {}

    # -------------------------------------------------------------- parse
    def set_net_source(self, text: str, file_name: str = "") -> None:
        """Provide the raw NET bytes (from the Design Input import)."""
        self._net_text = text or ""
        self._net_name = file_name or ""

    def _bom_library(self) -> dict | None:
        """Build the netparse library from ``design_input.bom_file``.

        Same :func:`mtkgui.ict.netparse.bom.load_bom_library` entry
        point the CLI uses (GUI == CLI parity).  A missing / broken
        BOM is a WARNING only - the NET-only parse keeps running.
        """
        model = self.yaml_model
        bom_file = ""
        if model is not None:
            bom_file = str((model.get_params("design_input") or {})
                           .get("bom_file") or "").strip()
        if not bom_file:
            self.lbl_bom.setText("BOM: (not imported)")
            return None
        try:
            from mtkgui.ict.netparse.bom import load_bom_library
            library, report, bom = load_bom_library(bom_file)
        except (OSError, ValueError) as exc:
            self.lbl_bom.setText("BOM: ignored (import failed)")
            self.task_log.emit(
                "WARNING",
                f"BOM ignored: {exc} - parsing the NET without BOM "
                "evidence")
            return None
        summary = (f"{len(bom.records)} records, {report.dnp} DNP, "
                   f"{len(report.conflicts)} conflicts, "
                   f"{len(bom.warnings)} warnings")
        self.lbl_bom.setText(f"BOM: {summary}")
        self.task_log.emit("INFO", f"BOM library loaded: {summary}")
        return library

    def parse_nets(self) -> None:
        """Run the formal parse with per-step progress + Event-Log
        detail (core-algorithm standard section 6: every pipeline
        stage is logged, the 100% progress endpoint binds the real
        steps, any failure resets to 0 with the failing stage
        named)."""
        text = self._net_text or ""
        name = self._net_name or "loaded NET file"
        if not text.strip():
            reason = ("no NET file loaded - import a NET file on the "
                      "Design Input page first")
            self.task_log.emit("ERROR", f"parse nets failed: {reason}")
            self.task_progress.emit(0, "parse nets: idle")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Parse Nets", reason)
            return
        self.task_progress.emit(0, "parse nets: reading raw data")
        self.task_log.emit(
            "INFO",
            f"parse nets started: {name or 'loaded NET file'}")
        try:
            # Step 1: format auto-detection (SPF / NET header features)
            self.task_progress.emit(10, "parse nets: detecting format")
            fmt = detect_netlist_format(text)
            fmt_label = {"spf": "SPF", "pstxnet": "PSTXNET"}.get(
                fmt, "NET (fallback)" if fmt != "net" else "NET")
            self.task_log.emit(
                "INFO", f"netlist format detected: {fmt_label}")
            # Step 2: cleaning + parse (dual-format branch)
            self.task_progress.emit(25, "parse nets: cleaning")
            self.task_log.emit("INFO", "netlist cleaning done")
            self.task_progress.emit(40, "parse nets: parsing")
            library = self._bom_library()
            result = parse_testable_nets(text, rules=self.net_rules,
                                         library=library)
            # GUI == CLI ordering (user rule M3): rank BEFORE the
            # preview / testable_nets / channel_allocation materialise
            # so input rails come first - never the netlist (name) order
            rank_result(result)
        except ValueError as exc:
            self.task_log.emit("ERROR", f"parse nets failed: {exc}")
            self.task_progress.emit(0, "parse nets: idle")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Parse Nets Failed", str(exc))
            return
        self.task_log.emit("INFO", "netlist parse done")
        # Step 3: classification
        self.task_progress.emit(55, "parse nets: classifying nets")
        self.task_log.emit("INFO", "net classification done")
        self.result = result
        # Task 6: any net present in NET but NOT in the imported SPF
        # is an Allegro auto-generated random net -> Control IO, locked
        # Do Not Test (tag persists in YAML)
        spf_nets = getattr(self, "spf_nets", None) or set()
        if spf_nets:
            for rec in (*result.power, *result.clock, *result.gpio):
                if rec.name not in spf_nets:
                    self._auto_generated[rec.name] = True
                    self.task_log.emit(
                        "WARNING",
                        f"net {rec.name}: not found in SPF - Allegro "
                        "auto-generated net, locked Do Not Test")
        # Step 4: test-point selection + preview
        self.task_progress.emit(70, "parse nets: selecting test points")
        self.task_log.emit("INFO", "test point selection done")
        self._fill_preview(result)
        self._fill_filtered(result)
        # Step 5: path risk (advisory scores for the non-DNT nets)
        self.task_progress.emit(85, "parse nets: scoring path risk")
        self.task_log.emit("INFO", "path risk calculation done")
        self._evaluate_risk(result)
        self._update_gnd_risk(result)
        self.task_progress.emit(100, "parse nets: done")
        self.task_log.emit(
            "INFO", f"parse nets done: {result.summary()}")
        for net_name, reason in result.filtered:
            self.task_log.emit(
                "WARNING", f"net {net_name} filtered: {reason}")
        self.nets_parsed.emit(result)

    def _update_gnd_risk(self, result: ParseNetsResult) -> None:
        """GND integrity advisory (core-algorithm standard 5.2): a
        single global GND reads healthy; several distinct reference
        grounds hint at multi-point / segmented (isolated) grounds.
        Never blocks the parse flow."""
        gnd_nets = sorted(self._gnd_nets(result))
        if not gnd_nets:
            self.lbl_gnd_risk.setText(
                "GND integrity: no GND reference net detected - "
                "check the ground connectivity of the design")
            self.task_log.emit(
                "WARNING",
                "GND integrity risk: no GND reference net detected")
        elif len(gnd_nets) == 1:
            self.lbl_gnd_risk.setText(
                f"GND integrity: single global reference "
                f"({gnd_nets[0]}) - OK")
        else:
            self.lbl_gnd_risk.setText(
                f"GND integrity: {len(gnd_nets)} reference grounds "
                f"({', '.join(gnd_nets[:5])}"
                f"{'' if len(gnd_nets) <= 5 else ', ...'}) - possible "
                "multi-point / segmented ground, review the "
                "star-ground topology")
            self.task_log.emit(
                "WARNING",
                f"GND integrity risk: {len(gnd_nets)} distinct GND "
                "reference nets (possible multi-point / segmented "
                "ground)")

    # ------------------------------------------------------------ preview
    def _fill_preview(self, result: ParseNetsResult) -> None:
        """Render the PARSED NETS table (Net | Test Points | Category |
        Do Not Test | Confidence | Input Rail | Sub-class): the Power /
        SE Clock / Control IO / Others / GND nets MINUS
        the ones overridden to "Filtered", PLUS the filtered nets
        overridden back to a real category; the Category combo (with
        the "Filtered" choice) drives the moves."""
        groups = ((CATEGORY_POWER, result.power),
                  ("SE Clock", result.clock),
                  (CATEGORY_CONTROL_IO_LABEL, result.control_io),
                  (CATEGORY_OTHERS, result.others),
                  (CATEGORY_GND, result.gnd))
        rows = [(rec, cat) for cat, records in groups for rec in records
                if self._category_overrides.get(rec.name)
                != CATEGORY_FILTERED]
        # filtered nets restored by the user to a real category
        for rec in result.filtered_records:
            override = self._category_overrides.get(rec.name)
            if override is not None \
                    and override != CATEGORY_FILTERED:
                rows.append((rec, override))
        # drop the previous row widgets FIRST: setCellWidget does not
        # delete the replaced widget in every Qt build - the old combos
        # / DNT checkboxes stay parented to the viewport and stack as
        # ghosts over row 0 (every re-parse / category change re-fills)
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                old = self.table.cellWidget(r, c)
                if old is not None:
                    self.table.removeCellWidget(r, c)
                    old.hide()
                    old.deleteLater()
        self.table.setRowCount(len(rows))
        for row, (rec, auto_cat) in enumerate(rows):
            category = self._category_overrides.get(rec.name, auto_cat)
            if category == CATEGORY_FILTERED:
                category = auto_cat
            self._dnt_flags.setdefault(
                rec.name, self._dnt_default(category))
            members = [t for t in rec.members if "." in t or
                       t.upper().startswith("TP")]
            best, kept = select_test_points(
                members or rec.members)
            points = best if best else ""
            if len(kept) > 1:
                points += f" (+{len(kept) - 1} alt)"
            net_item = QTableWidgetItem(rec.name)
            net_item.setFlags(net_item.flags()
                              & ~Qt.ItemFlag.ItemIsEditable)
            tp_item = QTableWidgetItem(points)
            tp_item.setFlags(tp_item.flags()
                             & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, net_item)
            self.table.setItem(row, 1, tp_item)
            combo = QComboBox()
            # the column width adapts to the combo content (user
            # direction: both tables' column widths self-fit - without
            # this policy the ResizeToContents header ignores the
            # widget and clips "SE Clock" to "SE Cloc")
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToContents)
            combo.addItems(TABLE_CATEGORIES)
            combo.setCurrentText(
                category if category in TABLE_CATEGORIES else CATEGORY_CONTROL_IO_LABEL)
            combo.currentTextChanged.connect(
                lambda value, name=rec.name: self._category_changed(
                    name, value))
            self.table.setCellWidget(row, 2, combo)
            dnt = QCheckBox()
            dnt.setChecked(bool(self._dnt_flags.get(rec.name)))
            dnt.toggled.connect(
                lambda checked, name=rec.name: self._dnt_set(
                    name, checked))
            self.table.setCellWidget(row, 3, dnt)
            # M4 PART 6: read-only netparse facts (confidence /
            # input_rail marker / GND or Others sub-class)
            for col, text in ((4, rec.confidence or ""),
                              (5, "yes" if rec.input_rail else ""),
                              (6, rec.sub_class or "")):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags()
                              & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.lbl_summary.setText(
            f"{result.total} nets parsed: {result.summary()}")
        # re-fit the columns AFTER the combos are in place (their
        # sizeHint drives the category column width)
        self.table.resizeColumnsToContents()

    def _fill_filtered(self, result: ParseNetsResult) -> None:
        """Render the FILTERED NETS table (Net | Reason | Category):
        every dropped net with its reason PLUS the parsed nets the
        user moved down ("Filtered" in the Parsed Nets table); the
        Category combo defaults to "Filtered" - a real category moves
        the net back into the Parsed Nets table."""
        reasons = dict(result.filtered)
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        for rec in result.filtered_records:
            if self._category_overrides.get(
                    rec.name, CATEGORY_FILTERED) == CATEGORY_FILTERED:
                rows.append((rec.name,
                             reasons.get(rec.name, ""), ))
                seen.add(rec.name)
        for records in (result.power, result.clock, result.control_io,
                        result.others, result.gnd):
            for rec in records:
                if rec.name not in seen and \
                        self._category_overrides.get(rec.name) \
                        == CATEGORY_FILTERED:
                    rows.append(
                        (rec.name, "manually moved to Filtered"))
        # same ghost-widget guard as _fill_preview (this table re-fills
        # on every re-parse and category move as well)
        for r in range(self.table_filtered.rowCount()):
            for c in range(self.table_filtered.columnCount()):
                old = self.table_filtered.cellWidget(r, c)
                if old is not None:
                    self.table_filtered.removeCellWidget(r, c)
                    old.hide()
                    old.deleteLater()
        self.table_filtered.setRowCount(len(rows))
        for row, (name, reason) in enumerate(rows):
            net_item = QTableWidgetItem(name)
            net_item.setFlags(net_item.flags()
                              & ~Qt.ItemFlag.ItemIsEditable)
            reason_item = QTableWidgetItem(reason)
            reason_item.setFlags(reason_item.flags()
                                 & ~Qt.ItemFlag.ItemIsEditable)
            self.table_filtered.setItem(row, 0, net_item)
            self.table_filtered.setItem(row, 1, reason_item)
            combo = QComboBox()
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToContents)
            combo.addItems(TABLE_CATEGORIES)
            combo.setCurrentText(CATEGORY_FILTERED)
            combo.currentTextChanged.connect(
                lambda value, net=name:
                    self._filtered_category_changed(net, value))
            self.table_filtered.setCellWidget(row, 2, combo)
        self.table_filtered.resizeColumnsToContents()
