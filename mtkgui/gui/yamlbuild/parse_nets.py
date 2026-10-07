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

The parse result is the single data source for the Channel
Allocation tables (T10).  Classification rules come from the shared
:class:`mtkgui.gui.designinput.netlist.classify_nets` kernel - this
module only orchestrates GUI-side; the kernel is untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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

from mtkgui.gui.designinput.netlist import (
    NET_TYPE_CLOCK_SINGLE,
    NET_TYPE_DIFF_PAIR,
    NET_TYPE_GND_REF,
    NET_TYPE_POWER,
    NET_TYPE_SIGNAL,
    NetRecord,
    classify_nets,
)
from mtkgui.gui.yamlbuild.dual_format import parse_netlist_auto
from mtkgui.gui.yamlbuild.net_rules import DEFAULT_RULES
from mtkgui.gui.yamlbuild.parser import parse_netlist
from mtkgui.gui.yamlbuild.test_points import select_test_points
from mtkgui.gui.yamlbuild.path_risk import (
    DEFAULT_THRESHOLDS,
    LEVEL_HIGH,
    LEVEL_MEDIUM,
    WARNING_MESSAGE,
    evaluate_paths,
)

#: the ICT test-object categories (Channel Allocation order)
CATEGORY_POWER = "Power"
CATEGORY_CLOCK = "Clock"
CATEGORY_GPIO = "GPIO"
CATEGORY_GND = "GND"
CATEGORIES = (CATEGORY_POWER, CATEGORY_CLOCK, CATEGORY_GPIO)

#: Parsed-Nets-table category labels (the combo the user can change)
TABLE_CATEGORIES = ("Power", "SE Clock", "Signal", "GND")

#: nets of these categories default to Do Not Test (user direction)
DNT_DEFAULT_CATEGORIES = ("Signal", "GND")

_FILTER_REASONS = {
    NET_TYPE_GND_REF: "reference ground (measurement loop)",
    NET_TYPE_DIFF_PAIR: "differential pair (not an ICT test object)",
    NET_TYPE_SIGNAL: "",          # placeholder, never filtered as such
}

#: user-rule category -> kernel net type (Step 2 override mapping)
_USER_RULE_TYPES = {
    "power": NET_TYPE_POWER,
    "se_clock": NET_TYPE_CLOCK_SINGLE,
    "diff_pair": NET_TYPE_DIFF_PAIR,
}

#: exclusion reason wording (Exclude Parse Nets regex matches)
EXCLUDED_REASON = "excluded by Exclude Parse Nets regex"


def _exclude_pattern(rules: dict | None) -> str:
    """The active exclusion pattern: the user's Exclude Parse Nets
    regex when configured, the factory default otherwise; an explicit
    EMPTY user value disables the exclusion entirely."""
    rules = rules or {}
    if "exclude" in rules:
        return (rules.get("exclude") or "").strip()
    return DEFAULT_RULES["exclude"]


def _apply_user_rules(name: str, net_type: str,
                      rules: dict | None) -> str:
    """Step 2 user-regex override (user rules > system defaults).

    For every user-configured category (Power / SE Clock / Diff Pair
    - GND is system-auto and never overridden): a non-empty user
    pattern that matches the name re-classifies the net; an explicit
    EMPTY pattern suppresses the kernel's name-based default for that
    category (the net falls to Signal).  Categories without a user
    key keep the kernel classification unchanged.
    """
    rules = rules or {}
    matched_user = False
    for key, net_cls in _USER_RULE_TYPES.items():
        if key not in rules:
            continue
        pattern = (rules.get(key) or "").strip()
        if not pattern:
            continue
        try:
            if re.match(pattern, name):
                return net_cls
        except re.error:
            continue
        matched_user = True     # this category HAS a working pattern
    if not matched_user:
        # explicit-empty categories suppress the kernel name default
        for key, net_cls in _USER_RULE_TYPES.items():
            if key in rules and not (rules.get(key) or "").strip() \
                    and net_type == net_cls:
                return NET_TYPE_SIGNAL
    return net_type


@dataclass
class ParseNetsResult:
    """Formal net parse result (the T10 data source).

    Attributes:
        power / clock / gpio: NetRecord lists per category.
        filtered:             (net name, reason) of every dropped net.
        total:                Net count in the raw file.
        invalid_lines:        Malformed raw lines (report only).
    """

    power: list[NetRecord] = field(default_factory=list)
    clock: list[NetRecord] = field(default_factory=list)
    gpio: list[NetRecord] = field(default_factory=list)
    gnd: list[NetRecord] = field(default_factory=list)
    filtered: list[tuple[str, str]] = field(default_factory=list)
    total: int = 0
    invalid_lines: list[str] = field(default_factory=list)

    def category(self, name: str) -> str:
        """Category of one net ("" when not testable)."""
        for cat, records in ((CATEGORY_POWER, self.power),
                             (CATEGORY_CLOCK, self.clock),
                             (CATEGORY_GPIO, self.gpio),
                             (CATEGORY_GND, self.gnd)):
            if any(r.name == name for r in records):
                return cat
        return ""

    def summary(self) -> str:
        """One-line counts summary for the Event Log."""
        return (f"power={len(self.power)} clock={len(self.clock)} "
                f"gpio={len(self.gpio)} gnd={len(self.gnd)} "
                f"filtered={len(self.filtered)}")


def parse_testable_nets(net_text: str,
                        rules: dict | None = None) -> ParseNetsResult:
    """Formally parse the raw netlist text and extract the testable
    nets (headless core - unit-testable without Qt).

    Args:
        net_text: Raw netlist text (SPF or NET - auto-detected).
        rules:    User custom classification regexes (core standard
                  Step 2: user rules > system defaults; an explicit
                  empty key suppresses the name-based default for that
                  category).  GND is system-auto, never user-configured.

    Returns:
        :class:`ParseNetsResult` with the three categories.

    Raises:
        ValueError: The text contains no recognizable netlist content
                    (no nets at all) - a clear, non-silent error.
    """
    netlist = parse_netlist_auto(net_text)
    if not netlist.nets:
        raise ValueError(
            "no nets found - the file has no recognizable netlist "
            "content (wrong file or unsupported format)")
    collection = classify_nets(netlist)
    result = ParseNetsResult(total=len(collection.nets))
    for rec in collection.nets:
        # Step 2: user regex override (user rules > system defaults;
        # explicit-empty key = no name matching for that category)
        rec.net_type = _apply_user_rules(rec.name, rec.net_type, rules)
        # Exclude Parse Nets regex: matching SIGNAL nets never become
        # ICT test objects (user regex when configured, factory
        # default otherwise; an explicit empty value disables it)
        pattern = _exclude_pattern(rules)
        if pattern and rec.net_type == NET_TYPE_SIGNAL:
            try:
                if re.search(pattern, rec.name):
                    result.filtered.append(
                        (rec.name, EXCLUDED_REASON))
                    continue
            except re.error:
                pass
        members = [t for t in rec.members if "." in t or
                   t.upper().startswith("TP")]
        if not members:
            # invalid: a net without any testable member pin cannot
            # get a test point -> filtered with the reason
            result.filtered.append(
                (rec.name, "no valid member pin (no test point)"))
            continue
        if rec.net_type == NET_TYPE_POWER:
            rec.members = members
            result.power.append(rec)
        elif rec.net_type == NET_TYPE_CLOCK_SINGLE:
            rec.members = members
            result.clock.append(rec)
        elif rec.net_type == NET_TYPE_SIGNAL:
            rec.members = members
            result.gpio.append(rec)
        elif rec.net_type == NET_TYPE_GND_REF:
            # reference grounds: measurement-loop references, default
            # Do Not Test (they appear in the Parsed Nets table)
            rec.members = members
            result.gnd.append(rec)
        else:
            # diff_pair: documented, non-testable object
            result.filtered.append(
                (rec.name, _FILTER_REASONS.get(
                    rec.net_type, "not an ICT test object")))
    return result


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
    #: navigation request: open the dedicated Power Tree page
    power_tree_requested = Signal()

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
            "Signal / Differential pair, with instant test, factory "
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

        # ------------------------------ table 1: Parsed Nets (user
        # direction: the SE Clock / GPIO allocation tables are GONE -
        # the channel assignment lives in Channel Allocation only.
        # Columns: Net | Test Points | Category (user-changeable) |
        # Do Not Test, Signal and GND default to Do Not Test)
        lbl_nets = QLabel("Parsed Nets:")
        lbl_nets.setObjectName("strong")
        lay.addWidget(lbl_nets)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Net", "Test Points", "Category", "Do Not Test"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(260)
        lay.addWidget(self.table, 1)

        # GND integrity resident hint (core-algorithm standard 5.2):
        # advisory only - never blocks the parse
        self.lbl_gnd_risk = QLabel("GND integrity: (parse first)")
        self.lbl_gnd_risk.setObjectName("muted")
        self.lbl_gnd_risk.setWordWrap(True)
        lay.addWidget(self.lbl_gnd_risk)

        self.btn_parse.clicked.connect(self.parse_nets)

        # ------------------------------------------------ item 24 tools
        # Power Tree navigation + risk thresholds (the rules dialog
        # button sits next to Parse)
        tools = QHBoxLayout()
        self.btn_open_tree = QPushButton("Open Power Tree Editor")
        self.btn_open_tree.setToolTip(
            "Jump to the dedicated Power Tree page: interactive "
            "topology graph, node editing, stage grouping, pruning "
            "with audit log")
        self.btn_open_tree.clicked.connect(
            self.power_tree_requested.emit)
        tools.addWidget(self.btn_open_tree)
        self.btn_risk_thresholds = QPushButton("Risk Thresholds")
        self.btn_risk_thresholds.setToolTip(
            "Configure the test path complexity score thresholds "
            "(Medium / High lower bounds). The warning is advisory "
            "only and never blocks a channel assignment")
        tools.addWidget(self.btn_risk_thresholds)
        tools.addStretch(1)
        lay.addLayout(tools)

        self.btn_rules.clicked.connect(self._edit_rules)
        self.btn_risk_thresholds.clicked.connect(
            self._edit_risk_thresholds)

    # ---------------------------------------------------------- item 24
    def set_dnt_state(self, dnt_nets: set[str] | None) -> None:
        """Restore the persisted Do-Not-Test net set (the explicit
        user flags - they win over the Signal/GND category defaults)."""
        self._dnt_flags = {n: True for n in (dnt_nets or set())}

    def power_dnt_nets(self) -> list[str]:
        """All nets currently flagged Do Not Test (any category)."""
        return sorted(n for n, v in self._dnt_flags.items() if v)

    def _dnt_default(self, category: str) -> bool:
        """Category default: Signal and GND default Do Not Test."""
        return category in DNT_DEFAULT_CATEGORIES

    def _dnt_set(self, name: str, checked: bool) -> None:
        self._dnt_flags[name] = checked
        self.task_log.emit(
            "INFO",
            f"net {name} marked "
            f"{'Do Not Test' if checked else 'testable'}")

    def _category_changed(self, name: str, category: str) -> None:
        """User re-categorization: the override survives re-parses and
        the Do-Not-Test flag follows the new category default."""
        self._category_overrides[name] = category
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

        Scored targets: the Power / SE Clock / Signal nets NOT flagged
        Do Not Test (the channel assignment itself lives in the
        Channel Allocation page).  GND nets are excluded.  Advisory
        only - never blocks a channel assignment."""
        gnd_nets = self._gnd_nets(result)
        scored = set()
        for records, category in ((result.power, "Power"),
                                  (result.clock, "SE Clock"),
                                  (result.gpio, "Signal")):
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
            from mtkgui.gui.yamlbuild.dual_format import (
                detect_netlist_format,
            )
            fmt = detect_netlist_format(text)
            fmt_label = {"spf": "SPF", "pstxnet": "PSTXNET"}.get(
                fmt, "NET (fallback)" if fmt != "net" else "NET")
            self.task_log.emit(
                "INFO", f"netlist format detected: {fmt_label}")
            # Step 2: cleaning + parse (dual-format branch)
            self.task_progress.emit(25, "parse nets: cleaning")
            self.task_log.emit("INFO", "netlist cleaning done")
            self.task_progress.emit(40, "parse nets: parsing")
            result = parse_testable_nets(text, rules=self.net_rules)
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
        # is an Allegro auto-generated random net -> Signal, locked
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
        Do Not Test): every parsed net is listed - Power / SE Clock /
        Signal / GND rows; the Category combo is user-changeable and
        Signal / GND rows default to Do Not Test (explicit user flags
        survive re-parses and win over the category defaults)."""
        groups = ((CATEGORY_POWER, result.power),
                  ("SE Clock", result.clock),
                  ("Signal", result.gpio),
                  (CATEGORY_GND, result.gnd))
        rows = [(rec, cat) for cat, records in groups for rec in records]
        self.table.setRowCount(len(rows))
        for row, (rec, auto_cat) in enumerate(rows):
            category = self._category_overrides.get(rec.name, auto_cat)
            self._dnt_flags.setdefault(
                rec.name, self._dnt_default(category))
            best, kept = select_test_points(rec.members)
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
            combo.addItems(TABLE_CATEGORIES)
            combo.setCurrentText(
                category if category in TABLE_CATEGORIES else "Signal")
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
        self.lbl_summary.setText(
            f"{result.total} nets parsed: {result.summary()}")
