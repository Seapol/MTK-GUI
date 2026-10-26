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

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
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
from mtkgui.gui.progress_dialog import (
    SHOW_DELAY_S,
    ProgressDialog,
    guarded_run,
)
from mtkgui.startup_timing import begin, end
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


#: rows rendered before the main loop pumps the event loop once
#: (M18: a big project - 29420 parses ~600 rows - froze the window for
#: seconds; chunked pumping keeps the progress dialog alive)
RENDER_CHUNK = 40


class _ParseWorker(QThread):
    """Run the heavy parse (BOM library + netlist parse + rank) OFF the
    GUI thread (M18): the synchronous path froze the window for ~0.75 s
    in dev and ~7 s in the packaged build.  The Qt widgets are only
    touched on the main thread (``done`` / ``failed`` slots)."""

    done = Signal(object, object, str)     # result, library, bom_summary
    failed = Signal(str)

    def __init__(self, parent: QWidget | None, text: str, rules: dict | None,
                 bom_file: str) -> None:
        super().__init__(parent)
        self._text = str(text)
        self._rules = rules
        self._bom_file = str(bom_file or "").strip()

    def run(self) -> None:
        try:
            library = None
            summary = ""
            if self._bom_file:
                from mtkgui.ict.netparse.bom import load_bom_library
                library, report, bom = load_bom_library(self._bom_file)
                summary = (f"{len(bom.records)} records, "
                           f"{report.dnp} DNP, "
                           f"{len(report.conflicts)} conflicts, "
                           f"{len(bom.warnings)} warnings")
            from mtkgui.ict.netparse.parser import parse_testable_nets
            from mtkgui.ict.netparse import rank_result
            result = parse_testable_nets(
                self._text, rules=self._rules, library=library)
            rank_result(result)
            self.done.emit(result, library, summary)
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc))


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
        # M10-FIX2 F2: explicit default column widths - the EMPTY table
        # must already be readable (ResizeToContents collapsed Net to
        # ~25 px and left a ~260 px gap before the next column)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        # the last section absorbs the leftover width so the empty table
        # has no blank header band on the right
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((180, 240, 90, 90, 90, 90, 100)):
            self.table.setColumnWidth(column, width)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Expanding)
        self.table.setMinimumHeight(120)
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
        # M10-FIX2 F2: readable default widths in the empty state too
        self.table_filtered.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        self.table_filtered.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((300, 300, 100)):
            self.table_filtered.setColumnWidth(column, width)
        self.table_filtered.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_filtered.setSizePolicy(QSizePolicy.Policy.Expanding,
                                          QSizePolicy.Policy.Expanding)
        self.table_filtered.setMinimumHeight(90)
        self.table_filtered.setMaximumHeight(200)
        lay.addWidget(self.table_filtered, 1)

        # GND integrity resident hint (core-algorithm standard 5.2):
        # advisory only - never blocks the parse
        self.lbl_gnd_risk = QLabel("GND integrity: (parse first)")
        self.lbl_gnd_risk.setObjectName("muted")
        self.lbl_gnd_risk.setWordWrap(True)
        lay.addWidget(self.lbl_gnd_risk)

        self.btn_parse.clicked.connect(self._on_parse_clicked)

        # M19e: the former item-24 tool buttons (Risk Thresholds /
        # Export ICT Test Plan / Import to YAML / Export from YAML)
        # are GONE - the Test Plan sync lives in the File menu
        # (Export ICT Test plan from Yaml to Excel / Import ICT Test
        # from Excel to Yaml); the handlers stay on this panel so the
        # menu can reuse them (guarded_run accepts a None button)

        self.btn_rules.clicked.connect(self._edit_rules)

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
        project = self._project_name()
        default = f"ICT Test Plan for {project}.xlsx"
        begin("parse: export testplan pick", category="ui", wait=True)
        try:
            path, _selected = QFileDialog.getSaveFileName(
                self, "Export ICT Test Plan", default, "Excel (*.xlsx)")
        finally:
            end("parse: export testplan pick")
        if not path:
            return

        def work(stage):
            stage(0, "Export ICT Test Plan: writing workbook")
            rows, sections = export_testplan_pair(
                self.result, DEFAULT_LIMITS, path, project)
            stage(100, "Export ICT Test Plan: done")
            return rows, sections

        written = guarded_run(self, None,
                              "Export ICT Test Plan", work)
        if written is None:
            return
        rows, sections = written
        self.task_log.emit(
            "INFO",
            f"ICT Test Plan written: {path} ({rows} rows) + evidence "
            f"({sections} nets)")

    def import_to_yaml(self) -> None:
        """Workbook -> project YAML (gate: project YAML + parsed data)."""
        from PySide6.QtWidgets import QFileDialog

        from mtkgui.gui.yamlbuild.testplan_sync import testplan_to_yaml
        if not self._sync_allowed("Import to YAML"):
            return
        begin("parse: import to yaml pick", category="ui", wait=True)
        try:
            path, _selected = QFileDialog.getOpenFileName(
                self, "Import to YAML", "", "Excel (*.xlsx)")
        finally:
            end("parse: import to yaml pick")
        if not path:
            return

        def work(stage):
            stage(0, "Import to YAML: reading workbook")
            testplan_to_yaml(self.yaml_model, path, None, self.result)
            stage(100, "Import to YAML: done")
            return True

        if guarded_run(self, None, "Import to YAML", work) is not True:
            return
        self._log_report("import to YAML",
                         self.yaml_model.testplan_sync_report)

    def export_from_yaml(self) -> None:
        """Project YAML -> workbook + evidence markdown."""
        from PySide6.QtWidgets import QFileDialog

        from mtkgui.gui.yamlbuild.testplan_sync import yaml_to_testplan
        if not self._sync_allowed("Export from YAML"):
            return
        default = f"ICT Test Plan for {self._project_name()}.xlsx"
        begin("parse: export from yaml pick", category="ui", wait=True)
        try:
            path, _selected = QFileDialog.getSaveFileName(
                self, "Export from YAML", default, "Excel (*.xlsx)")
        finally:
            end("parse: export from yaml pick")
        if not path:
            return
        md_path = str(Path(path).with_name(
            Path(path).stem + "_evidence.md"))

        def work(stage):
            stage(0, "Export from YAML: writing workbook")
            yaml_to_testplan(self.yaml_model, path, md_path)
            stage(100, "Export from YAML: done")
            return True

        if guarded_run(self, None, "Export from YAML", work) is not True:
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

    def _on_parse_clicked(self) -> None:
        """Button path (M10-FIX3 F2 + M18): drive a determinate
        foreground dialog from the existing ``task_progress`` signal and
        disable the trigger button for the whole run.

        M18: the BOM read + netlist parse + rank now run in a
        :class:`_ParseWorker` thread and the table rendering pumps the
        event loop in chunks - the main window keeps repainting and the
        dialog stays visible (a 29420-class project froze the window for
        ~7 s in the packaged build; any run past SHOW_DELAY_S must show
        the bar)."""
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
        self._parse_dlg = ProgressDialog(self, "Parse Nets for ICT",
                                         0, 100)
        self.task_progress.connect(self._parse_dlg.set_stage)
        # M17 delivery guarantee: force-show once the run passes the
        # delay even when no stage arrives in between (the worker runs
        # off the GUI thread with no progress events).
        self._parse_show_timer = QTimer(self._parse_dlg)
        self._parse_show_timer.setSingleShot(True)
        self._parse_show_timer.timeout.connect(
            self._parse_dlg.force_show)
        self._parse_show_timer.start(int(SHOW_DELAY_S * 1000))
        self.btn_parse.setEnabled(False)
        self.task_progress.emit(0, "parse nets: reading raw data")
        self.task_log.emit(
            "INFO", f"parse nets started: {name or 'loaded NET file'}")
        begin("yamlbuild: parse nets for ICT")
        # Step 1: format auto-detection (SPF / NET header features) -
        # cheap, stays on the GUI thread
        self.task_progress.emit(10, "parse nets: detecting format")
        try:
            fmt = detect_netlist_format(text)
        except ValueError as exc:
            self._on_parse_failed(str(exc))
            return
        fmt_label = {"spf": "SPF", "pstxnet": "PSTXNET"}.get(
            fmt, "NET (fallback)" if fmt != "net" else "NET")
        self.task_log.emit(
            "INFO", f"netlist format detected: {fmt_label}")
        self.task_progress.emit(25, "parse nets: cleaning")
        self.task_log.emit("INFO", "netlist cleaning done")
        self.task_progress.emit(40, "parse nets: parsing")
        bom_file = ""
        if self.yaml_model is not None:
            bom_file = str((self.yaml_model.get_params("design_input")
                            or {}).get("bom_file") or "").strip()
        self._parse_worker = _ParseWorker(
            self, text, rules=self.net_rules, bom_file=bom_file)
        self._parse_worker.done.connect(self._on_parse_done)
        self._parse_worker.failed.connect(self._on_parse_failed)
        self._parse_worker.start()

    # ------------------------------------------------------- parse done
    def _on_parse_done(self, result, library, bom_summary: str) -> None:
        """Main-thread continuation: label, SPF cross-check, table
        render (chunked), risk scores - then finish."""
        try:
            if bom_summary:
                self.lbl_bom.setText(f"BOM: {bom_summary}")
                self.task_log.emit(
                    "INFO", f"BOM library loaded: {bom_summary}")
            self.task_log.emit("INFO", "netlist parse done")
            # Step 3: classification
            self.task_progress.emit(55, "parse nets: classifying nets")
            self.task_log.emit("INFO", "net classification done")
            self.result = result
            # Task 6: any net present in NET but NOT in the imported SPF
            # is an Allegro auto-generated random net -> Control IO,
            # locked Do Not Test (tag persists in YAML)
            spf_nets = getattr(self, "spf_nets", None) or set()
            if spf_nets:
                for rec in (*result.power, *result.clock,
                            *result.gpio):
                    if rec.name not in spf_nets:
                        self._auto_generated[rec.name] = True
                        self.task_log.emit(
                            "WARNING",
                            f"net {rec.name}: not found in SPF - "
                            "Allegro auto-generated net, locked Do Not "
                            "Test")
            # Step 4: test-point selection + preview (chunked render)
            self.task_progress.emit(
                70, "parse nets: selecting test points")
            self.task_log.emit(
                "INFO", "test point selection done")
            self._fill_preview(result)
            self._fill_filtered(result)
            # Step 5: path risk (advisory scores for the non-DNT nets)
            self.task_progress.emit(
                85, "parse nets: scoring path risk")
            self.task_log.emit("INFO", "path risk calculation done")
            self._evaluate_risk(result)
            self._update_gnd_risk(result)
            self.task_progress.emit(100, "parse nets: done")
            self.task_log.emit(
                "INFO", f"parse nets done: {result.summary()}")
        finally:
            self._on_parse_finish()

    def _on_parse_failed(self, message: str) -> None:
        self.task_log.emit("ERROR", f"parse nets failed: {message}")
        self.task_progress.emit(0, "parse nets: idle")
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Parse Nets Failed", message)
        self._on_parse_finish()

    def _on_parse_finish(self) -> None:
        """Shared cleanup on success / failure / exception."""
        end("yamlbuild: parse nets for ICT")
        if self._parse_show_timer is not None:
            self._parse_show_timer.stop()
            self._parse_show_timer = None
        try:
            self.task_progress.disconnect(self._parse_dlg.set_stage)
        except (RuntimeError, TypeError):
            pass
        if self._parse_dlg is not None:
            self._parse_dlg.close_done()
            self._parse_dlg = None
        self._parse_worker = None
        self.btn_parse.setEnabled(True)

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
        begin("yamlbuild: parse nets for ICT")
        try:
            # Step 1: format auto-detection (SPF / NET header features)
            self.task_progress.emit(10, "parse nets: detecting format")
            fmt = detect_netlist_format(text)
            fmt_label = {"spf": "SPF", "pstxnet": "PSTXNET"}.get(
                fmt, "NET (fallback)" if fmt != "net" else "NET")
            self.task_log.emit(
                "INFO", f"netlist format detected: {fmt_label}")
            QApplication.processEvents()
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
            QApplication.processEvents()
        except ValueError as exc:
            self.task_log.emit("ERROR", f"parse nets failed: {exc}")
            self.task_progress.emit(0, "parse nets: idle")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Parse Nets Failed", str(exc))
            end("yamlbuild: parse nets for ICT")
            return
        self.task_log.emit("INFO", "netlist parse done")
        # Step 3: classification
        self.task_progress.emit(55, "parse nets: classifying nets")
        self.task_log.emit("INFO", "net classification done")
        self.result = result
        QApplication.processEvents()
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
        QApplication.processEvents()
        # Step 5: path risk (advisory scores for the non-DNT nets)
        self.task_progress.emit(85, "parse nets: scoring path risk")
        self.task_log.emit("INFO", "path risk calculation done")
        self._evaluate_risk(result)
        self._update_gnd_risk(result)
        QApplication.processEvents()
        self.task_progress.emit(100, "parse nets: done")
        self.task_log.emit(
            "INFO", f"parse nets done: {result.summary()}")
        for net_name, reason in result.filtered:
            self.task_log.emit(
                "WARNING", f"net {net_name} filtered: {reason}")
        self.nets_parsed.emit(result)
        end("yamlbuild: parse nets for ICT")

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
            # M18: chunked render - pump so the foreground dialog stays
            # alive and the window repaints on a big project
            if (row + 1) % RENDER_CHUNK == 0:
                self.task_progress.emit(
                    70, f"parse nets: rendering table "
                    f"({row + 1}/{len(rows)})")
                QApplication.processEvents()
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
            # M18: chunked render (see _fill_preview)
            if (row + 1) % RENDER_CHUNK == 0:
                self.task_progress.emit(
                    70, f"parse nets: rendering filtered "
                    f"({row + 1}/{len(rows)})")
                QApplication.processEvents()
        self.table_filtered.resizeColumnsToContents()
