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
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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
from mtkgui.gui.yamlbuild.net_rules import (
    DEFAULT_RULES,
    GPIO_EXCLUDE_RE,
    validate_rules,
)
from mtkgui.gui.yamlbuild.parser import parse_netlist
from mtkgui.gui.yamlbuild.test_points import select_test_points
from mtkgui.gui.yamlbuild.path_risk import (
    DEFAULT_THRESHOLDS,
    LEVEL_HIGH,
    LEVEL_MEDIUM,
    WARNING_MESSAGE,
    evaluate_paths,
)
from mtkgui.gui.yamlbuild.power_alloc import (
    ASSIGNED,
    DONT_TEST,
    GPIO_DIO_CHANNELS,
)

#: the three ICT test-object categories (Channel Allocation order)
CATEGORY_POWER = "Power"
CATEGORY_CLOCK = "Clock"
CATEGORY_GPIO = "GPIO"
CATEGORIES = (CATEGORY_POWER, CATEGORY_CLOCK, CATEGORY_GPIO)

#: placeholder of the Power-table Yes/No assignment combos
UNSET_YESNO = "—"

_FILTER_REASONS = {
    NET_TYPE_GND_REF: "reference ground (measurement loop)",
    NET_TYPE_DIFF_PAIR: "differential pair (not an ICT test object)",
    NET_TYPE_SIGNAL: "",          # placeholder, never filtered as such
}

#: user-rule category -> kernel net type (Step 2 override mapping)
_USER_RULE_TYPES = {
    "power": NET_TYPE_POWER,
    "se_clock": NET_TYPE_CLOCK_SINGLE,
    "signal": NET_TYPE_SIGNAL,
    "diff_pair": NET_TYPE_DIFF_PAIR,
}


def _apply_user_rules(name: str, net_type: str,
                      rules: dict | None) -> str:
    """Step 2 user-regex override (user rules > system defaults).

    For every user-configured category (Power / SE Clock / Signal /
    Diff Pair - GND is system-auto and never overridden): a non-empty
    user pattern that matches the name re-classifies the net; an
    explicit EMPTY pattern suppresses the kernel's name-based default
    for that category (the net falls to Signal).  Categories without
    a user key keep the kernel classification unchanged.
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
                    and net_type == net_cls and key != "signal":
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
    filtered: list[tuple[str, str]] = field(default_factory=list)
    total: int = 0
    invalid_lines: list[str] = field(default_factory=list)

    def category(self, name: str) -> str:
        """Category of one net ("" when not testable)."""
        for cat, records in ((CATEGORY_POWER, self.power),
                             (CATEGORY_CLOCK, self.clock),
                             (CATEGORY_GPIO, self.gpio)):
            if any(r.name == name for r in records):
                return cat
        return ""

    def summary(self) -> str:
        """One-line counts summary for the Event Log."""
        return (f"power={len(self.power)} clock={len(self.clock)} "
                f"gpio={len(self.gpio)} "
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
        members = [t for t in rec.members if "." in t or
                   t.upper().startswith("TP")]
        # Step 2: user regex override (user rules > system defaults;
        # explicit-empty key = no name matching for that category)
        rec.net_type = _apply_user_rules(rec.name, rec.net_type, rules)
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
        else:
            # gnd_ref / diff_pair: documented, non-testable objects
            result.filtered.append(
                (rec.name, _FILTER_REASONS.get(
                    rec.net_type, "not an ICT test object")))
    return result


_RULE_LABELS = {"power": "Power Nets", "se_clock": "SE Clock Nets",
                "signal": "Signal Nets"}


class _RuleEditDialog(QDialog):
    """Edit ONE classification rule (double-click on the read-only
    display field).  Buttons: Restore to default | Apply and Save |
    Cancel and Exit.  Apply pre-validates the regex (syntax +
    catastrophic backtracking) before saving."""

    def __init__(self, key: str, user_value: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        label = _RULE_LABELS.get(key, key)
        self.key = key
        self.setWindowTitle(f"Edit {label} Regex")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        default_text = DEFAULT_RULES.get(key) or \
            "(system default - kernel classification)"
        info = QLabel(
            "Current effective rule:\n  " + default_text +
            "\nUser override: " + (user_value or "(none)"))
        info.setObjectName("muted")
        info.setWordWrap(True)
        lay.addWidget(info)
        form = QFormLayout()
        self.edit_value = QLineEdit(user_value)
        self.edit_value.setPlaceholderText(
            "new regex (empty / default = back to the system rule)")
        self.edit_value.setMinimumWidth(420)
        form.addRow(f"{label} regex:", self.edit_value)
        lay.addLayout(form)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b91c1c;")
        self.error_label.setWordWrap(True)
        lay.addWidget(self.error_label)
        buttons = QHBoxLayout()
        btn_restore = QPushButton("Restore to default")
        btn_restore.setToolTip("Reset the text box to the system "
                               "default regex (Apply to persist)")
        btn_restore.clicked.connect(self._restore_default)
        btn_apply = QPushButton("Apply and Save")
        btn_apply.setDefault(True)
        btn_apply.clicked.connect(self._apply)
        btn_cancel = QPushButton("Cancel and Exit")
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_restore)
        buttons.addStretch(1)
        buttons.addWidget(btn_apply)
        buttons.addWidget(btn_cancel)
        lay.addLayout(buttons)

    def _restore_default(self) -> None:
        self.edit_value.setText(DEFAULT_RULES.get(self.key, ""))
        self.error_label.setText("")

    def _apply(self) -> None:
        value = self.edit_value.text().strip()
        if not value:
            self.accept()               # empty = back to default
            return
        errors = validate_rules({self.key: value})
        if errors:
            self.error_label.setText("\n".join(errors))
            return
        self.accept()

    def current_value(self) -> str:
        return self.edit_value.text()


class ParseNetsPanel(QWidget):
    """Block 02 embedded panel: Parse button + net list preview."""

    #: (level, message) Event-Log mirror (T6)
    task_log = Signal(str, str)
    #: (percent, label) long-task progress mirror (T6)
    task_progress = Signal(int, str)
    #: emitted after a successful parse (Channel Allocation refresh)
    nets_parsed = Signal(object)     # ParseNetsResult
    #: item 24: (level, message-free) payload mirrors for persistence
    rules_changed = Signal(dict)         # custom classification rules
    allocations_changed = Signal(dict)   # {"se_clock": rows, "gpio": rows}
    #: test path risk evaluation result (thresholds + per-net scores)
    path_risk_changed = Signal(dict)
    #: navigation request: open the dedicated Power Tree page
    power_tree_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result: ParseNetsResult | None = None
        self._net_text = ""          # raw NET bytes (Design Input)
        self._net_name = ""          # NET file name (log display)
        # item 24: manual overrides + SPF-anonymous net tags survive
        # re-parses (manual override > auto algorithm)
        self._auto_generated: dict[str, bool] = {}
        self._clock_overrides: dict[str, str] = {}
        self._gpio_overrides: dict[str, str] = {}
        self.spf_nets: set = set()   # SPF net names (Task 6 rule)
        # test path complexity risk (topology-based, advisory only):
        # GUI-configurable thresholds + per-net scores (both persisted)
        self.risk_thresholds: dict = dict(DEFAULT_THRESHOLDS)
        self.risk_scores: dict = {}
        # Power-table state: per-net Do-Not-Test flags + the Yes/No
        # assignments (impedance / voltage / power rails); persisted
        # via the parse_ict params and the channel_allocation rows
        self._power_dnt: dict[str, bool] = {}
        self._power_assign: dict[str, dict[str, str]] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # the three wide tables need room - never squeeze the columns
        # into overlapping text
        self.setMinimumWidth(860)

        # --------------------------------- inline classification rules
        # core standard section 6: Power / SE Clock / Signal regex
        # displays ABOVE the Parse button (GND is system-auto - no
        # config entry).  The fields are READ-ONLY and show the
        # EFFECTIVE regex (user rule first, system default otherwise);
        # a double-click opens the edit dialog (Restore to default |
        # Apply and Save | Cancel and Exit).  Rules land in
        # panel.net_rules (project YAML).
        self.net_rules: dict = {}          # custom regexes (persisted)
        rules_form = QFormLayout()
        rules_form.setHorizontalSpacing(12)
        self.rule_edits: dict[str, "QLineEdit"] = {}
        for key, label in (("power", "Power Nets regex:"),
                           ("se_clock", "SE Clock Nets regex:"),
                           ("signal", "Signal Nets regex:")):
            edit = QLineEdit()
            edit.setReadOnly(True)      # display only - edit via the
            edit.setCursor(Qt.CursorShape.PointingHandCursor)  # dialog
            edit.setToolTip(
                f"Effective {label[:-1]} (user rule first, system "
                "default otherwise; persisted with the project). "
                "Double-click to edit.")
            edit.setContextMenuPolicy(
                Qt.ContextMenuPolicy.NoContextMenu)
            edit.mouseDoubleClickEvent = (
                lambda _ev, k=key: self._open_rule_dialog(k))
            self.rule_edits[key] = edit
            rules_form.addRow(label, edit)
        self._refresh_rule_edits()
        lay.addLayout(rules_form)

        row = QHBoxLayout()
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

        # ------------------------------ table 1: Power Nets (core
        # standard section 6: Net | Test Points | Do Not Test |
        # Assign Impedance | Assign Voltage | Assign Power rails)
        lbl_power = QLabel("Power Nets:")
        lbl_power.setObjectName("strong")
        lay.addWidget(lbl_power)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Net", "Test Points", "Do Not Test", "Assign Impedance",
             "Assign Voltage", "Assign Power rails"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(150)
        lay.addWidget(self.table, 1)

        self.lbl_filtered = QLabel("")
        self.lbl_filtered.setWordWrap(True)
        lay.addWidget(self.lbl_filtered)

        # GND integrity resident hint (core-algorithm standard 5.2):
        # advisory only - never blocks the parse
        self.lbl_gnd_risk = QLabel("GND integrity: (parse first)")
        self.lbl_gnd_risk.setObjectName("muted")
        self.lbl_gnd_risk.setWordWrap(True)
        lay.addWidget(self.lbl_gnd_risk)

        self.btn_parse.clicked.connect(self.parse_nets)

        # ------------------------------------------------ item 24 tools
        # Edit Net Classification Rules + Power Tree navigation, SE
        # clock / GPIO allocation tables (auto-filled on parse)
        tools = QHBoxLayout()
        self.btn_rules = QPushButton("Edit Net Classification Rules")
        self.btn_rules.setToolTip(
            "Edit the net name regex rules: Power / SE Clock / "
            "Signal / Differential pair, with instant test, factory "
            "reset and save-time regex validation (GND is "
            "system-auto)")
        self.btn_open_tree = QPushButton("Open Power Tree Editor")
        self.btn_open_tree.setToolTip(
            "Jump to the dedicated Power Tree page: interactive "
            "topology graph, node editing, stage grouping, pruning "
            "with audit log")
        self.btn_open_tree.clicked.connect(
            self.power_tree_requested.emit)
        tools.addWidget(self.btn_rules)
        tools.addWidget(self.btn_open_tree)
        self.btn_risk_thresholds = QPushButton("Risk Thresholds")
        self.btn_risk_thresholds.setToolTip(
            "Configure the test path complexity score thresholds "
            "(Medium / High lower bounds). The warning is advisory "
            "only and never blocks a channel assignment")
        tools.addWidget(self.btn_risk_thresholds)
        tools.addStretch(1)
        lay.addLayout(tools)

        self.lbl_clock_alloc = QLabel("SE Clock Channels:")
        self.lbl_clock_alloc.setObjectName("strong")
        lay.addWidget(self.lbl_clock_alloc)
        self.clock_table = self._build_alloc_table(
            ["SE Clock Net Name", "Assign Clock Hz"])
        lay.addWidget(self.clock_table)
        self.lbl_gpio_alloc = QLabel(
            "GPIO DAQM907A DIO Channels (U2355A DIO is reserved for "
            "fixture IO):")
        self.lbl_gpio_alloc.setObjectName("strong")
        lay.addWidget(self.lbl_gpio_alloc)
        self.gpio_table = self._build_alloc_table(
            ["GPIO Net Name", "Assign DAQM907A DIO Channel"])
        lay.addWidget(self.gpio_table)

        # manual Signal Net add row (the Signal table starts empty)
        add_row = QHBoxLayout()
        self.gpio_candidate_combo = QComboBox()
        self.gpio_candidate_combo.setToolTip(
            "Eligible signal nets (invalid signals - differential / "
            "enable / interrupt / feedback / analog - are excluded "
            "automatically)")
        add_row.addWidget(self.gpio_candidate_combo, 1)
        self.btn_add_signal = QPushButton("Add Signal Net")
        self.btn_add_signal.setToolTip(
            "Add the selected signal net to the GPIO allocation "
            "table (first free DAQM907A DIO channel)")
        self.btn_add_signal.clicked.connect(self._add_signal_net)
        add_row.addWidget(self.btn_add_signal)
        lay.addLayout(add_row)
        self._gpio_candidates: list[str] = []

        self.btn_rules.clicked.connect(self._edit_rules)
        self.btn_risk_thresholds.clicked.connect(
            self._edit_risk_thresholds)

    # ---------------------------------------------------------- item 24
    def set_power_state(self, dnt_nets: set[str] | None,
                        assignments: dict | None) -> None:
        """Restore the persisted Power-table state (Do-Not-Test net
        set + Yes/No assignments from the channel allocation)."""
        self._power_dnt = {n: True for n in (dnt_nets or set())}
        self._power_assign = {
            net: dict(assigns)
            for net, assigns in (assignments or {}).items()}

    def power_dnt_nets(self) -> list[str]:
        """The power nets currently flagged Do Not Test."""
        return sorted(n for n, v in self._power_dnt.items() if v)

    def power_assignments(self) -> dict:
        """The Power-table Yes/No assignments (net -> impedance /
        voltage / power_rails) - merged into the channel allocation
        power rows by the page."""
        return {net: dict(assigns) for net, assigns
                in self._power_assign.items()
                if any(v and v != UNSET_YESNO for v in assigns.values())}

    def _power_dnt_set(self, name: str, checked: bool) -> None:
        self._power_dnt[name] = checked
        self.task_log.emit(
            "INFO",
            f"power net {name} marked "
            f"{'Do Not Test' if checked else 'testable'}")

    def _power_assign_set(self, name: str, key: str,
                          value: str) -> None:
        assigns = self._power_assign.setdefault(name, {})
        assigns[key] = value
        self.task_log.emit(
            "INFO",
            f"power net {name}: {key} assignment = {value}")

    def set_rules(self, rules: dict) -> None:
        """Load the persisted classification rules (project YAML) and
        refresh the read-only effective-value displays."""
        self.net_rules = dict(rules or {})
        self._refresh_rule_edits()

    def _effective_rule(self, key: str) -> str:
        """The regex currently in effect: the user rule when set, the
        system default otherwise (Signal has no default - the kernel
        classification applies)."""
        if key in self.net_rules and (self.net_rules.get(key) or "").strip():
            return self.net_rules[key]
        return DEFAULT_RULES.get(key, "")

    def _refresh_rule_edits(self) -> None:
        """Render the effective regex into the read-only displays."""
        for key, edit in self.rule_edits.items():
            value = self._effective_rule(key)
            edit.setText(value or "(system default)")

    def _open_rule_dialog(self, key: str) -> None:
        """Double-click: open the edit dialog for one rule (Restore to
        default | Apply and Save | Cancel and Exit).  Apply validates
        the regex, persists it and re-parses live."""
        dlg = _RuleEditDialog(key, self.net_rules.get(key, ""), self)
        if dlg.exec() != _RuleEditDialog.DialogCode.Accepted:
            return
        value = dlg.current_value().strip()
        default = DEFAULT_RULES.get(key, "")
        if value and value != default:
            self.net_rules[key] = value
        else:
            self.net_rules.pop(key, None)   # back to system default
        self._refresh_rule_edits()
        self.rules_changed.emit(dict(self.net_rules))
        self.task_log.emit(
            "INFO",
            f"net classification rule saved: {key} = "
            f"{self.net_rules.get(key) or '(system default)'}")
        if self.result is not None:
            self.parse_nets()               # rules take effect live

    def _build_alloc_table(self, headers: list[str]):
        """One allocation table (core standard section 6): Net |
        Assign <channel> | Do Not Test - status and risk columns are
        gone (the status is derived from the checkbox, the risk lives
        in the Power Tree summary)."""
        from PySide6.QtWidgets import (
            QCheckBox,
            QComboBox,
        )
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels([*headers, "Do Not Test"])
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setMinimumHeight(110)
        table._channel_pool: tuple[str, ...] = ()
        table._dnt_boxes: list[QCheckBox] = []
        table._combo_pool = QComboBox
        return table

    def _fill_alloc_table(self, table, rows: list[dict],
                          pool: tuple[str, ...]) -> None:
        """Render allocation rows; the channel cell is a dropdown of
        the pool (manual override wins over the auto assignment) and
        the Do-Not-Test checkbox marks the net Not Test."""
        from PySide6.QtWidgets import QCheckBox, QComboBox
        table._channel_pool = pool
        table.setRowCount(len(rows))
        table._dnt_boxes = []
        for r, row_data in enumerate(rows):
            table.setItem(r, 0, QTableWidgetItem(row_data["net"]))
            combo = QComboBox()
            combo.addItem(row_data["channel"] or "-")
            combo.addItems([c for c in pool
                            if c != row_data["channel"]])
            combo.setCurrentText(row_data["channel"] or "-")
            combo.currentTextChanged.connect(
                lambda value, t=table, rr=r: self._alloc_changed(
                    t, rr, value))
            table.setCellWidget(r, 1, combo)
            dnt = QCheckBox()
            dnt.setChecked(row_data["status"] == DONT_TEST)
            dnt.toggled.connect(
                lambda checked, t=table, rr=r: self._dnt_toggled(
                    t, rr, checked))
            table.setCellWidget(r, 2, dnt)
            table._dnt_boxes.append(dnt)

    def _alloc_rows(self, table) -> list[dict]:
        """Read the table back into allocation row dicts (the status
        is derived from the Do-Not-Test checkbox)."""
        rows = []
        for r in range(table.rowCount()):
            channel_item = table.cellWidget(r, 1)
            channel = channel_item.currentText() if channel_item else ""
            dnt = table._dnt_boxes[r].isChecked()
            rows.append({
                "net": table.item(r, 0).text(),
                "channel": "" if dnt else
                (channel if channel != "-" else ""),
                "status": DONT_TEST if dnt else ASSIGNED,
            })
        return rows

    def _alloc_changed(self, table, row: int, value: str) -> None:
        """Manual channel override: the manual choice always wins and
        clears the Do-Not-Test flag."""
        dnt = table._dnt_boxes[row]
        if value == "-":
            dnt.setChecked(True)
            return
        dnt.setChecked(False)
        self._persist_allocations()

    def _dnt_toggled(self, table, row: int, checked: bool) -> None:
        """Do-Not-Test toggle (the assigned channel is cleared)."""
        self._persist_allocations()

    def _persist_allocations(self) -> None:
        # manual overrides survive re-parses (manual > auto algorithm)
        self._clock_overrides = {
            row["net"]: (row["channel"] or DONT_TEST)
            for row in self._alloc_rows(self.clock_table)
            if row["status"] == DONT_TEST or row["channel"]}
        self._gpio_overrides = {
            row["net"]: (row["channel"] or DONT_TEST)
            for row in self._alloc_rows(self.gpio_table)
            if row["status"] == DONT_TEST or row["channel"]}
        self.allocations_changed.emit({
            "se_clock": self._alloc_rows(self.clock_table),
            "gpio": self._alloc_rows(self.gpio_table),
        })

    def _auto_allocate(self, result: ParseNetsResult) -> None:
        """Auto-assign the SE clock / GPIO channels from the parse
        result; differential clocks and auto-generated (SPF-anonymous)
        nets never reach the tables.  After the assignment the
        topology-based test path risk is evaluated for every
        channel-carrying net (advisory column)."""
        from mtkgui.gui.yamlbuild.power_alloc import (
            CLOCK_CHANNELS,
            allocate_channels,
        )
        clock_nets = [r.name for r in result.clock
                      if not self._auto_generated.get(r.name)]
        clock_rows = allocate_channels(clock_nets, CLOCK_CHANNELS,
                                       self._clock_overrides)
        # Signal Nets table: starts EMPTY (core standard section 6) -
        # invalid signals are auto-excluded, the engineer manually adds
        # the target nets; manual overrides always survive a re-parse
        gpio_rows = allocate_channels(
            sorted(self._gpio_overrides), GPIO_DIO_CHANNELS,
            self._gpio_overrides)
        self._evaluate_risk(result, clock_rows, gpio_rows)
        self._fill_alloc_table(
            self.clock_table, clock_rows, CLOCK_CHANNELS)
        self._fill_alloc_table(
            self.gpio_table, gpio_rows, GPIO_DIO_CHANNELS)
        self._refresh_gpio_candidates(result, gpio_rows)

    def _signal_candidates(self, result: ParseNetsResult) -> list[str]:
        """Eligible manual-add signal nets: the parse Signal category
        minus auto-generated nets, the fixed invalid-signal exclusion
        regex and nets already present in the table."""
        signal_rules = self.net_rules.get("signal")
        rows_present = {row["net"] for row in self._alloc_rows(
            self.gpio_table)}
        candidates = []
        for r in result.gpio:
            if self._auto_generated.get(r.name):
                continue
            if GPIO_EXCLUDE_RE.search(r.name):
                continue
            if signal_rules and not re.match(signal_rules, r.name):
                continue        # user signal inclusion regex
            if r.name in rows_present:
                continue
            candidates.append(r.name)
        return candidates

    def _refresh_gpio_candidates(self, result: ParseNetsResult,
                                 gpio_rows: list[dict]) -> None:
        """Refill the manual 'Add Signal Net' dropdown (eligible
        candidates only)."""
        self._gpio_candidates = self._signal_candidates(result)
        self.gpio_candidate_combo.clear()
        if self._gpio_candidates:
            self.gpio_candidate_combo.addItems(self._gpio_candidates)
        else:
            self.gpio_candidate_combo.addItem("(no eligible signal nets)")
        self._gpio_rows_cache = gpio_rows

    def _add_signal_net(self) -> None:
        """Manually add one signal net to the GPIO allocation table
        (first free DAQM907A DIO channel; Not Test when exhausted)."""
        name = self.gpio_candidate_combo.currentText()
        if not name or name.startswith("("):
            return
        if self.result is None:
            return
        used = {row["channel"] for row in
                self._alloc_rows(self.gpio_table) if row["channel"]}
        free = [c for c in GPIO_DIO_CHANNELS if c not in used]
        self._gpio_overrides[name] = free[0] if free else DONT_TEST
        self.task_log.emit(
            "INFO",
            f"signal net {name} added: "
            f"{self._gpio_overrides[name]}")
        self._auto_allocate(self.result)

    # ------------------------------------------------------ path risk
    def _gnd_nets(self, result: ParseNetsResult) -> set[str]:
        """GND reference nets (never scored - common star only): the
        filtered reference grounds plus the GND regex matches (custom
        rule when set, factory default otherwise)."""
        import re as _re
        gnd = {name for name, reason in result.filtered
               if "reference ground" in reason}
        rules_gnd = self.net_rules.get("gnd")
        pattern = rules_gnd if rules_gnd else DEFAULT_RULES["gnd"]
        if pattern:
            try:
                gnd |= {name for name in self._net_members()
                        if _re.search(pattern, name)}
            except _re.error:
                pass
        return gnd

    def _evaluate_risk(self, result: ParseNetsResult,
                       clock_rows: list[dict],
                       gpio_rows: list[dict]) -> None:
        """Evaluate the loop risk for every channel-carrying net and
        attach the advisory result to the allocation rows.

        Scored targets: power nets (rail voltage test) plus the SE
        clock / GPIO nets actually ASSIGNED a channel.  GND nets are
        excluded (requirement 7).  Advisory only - the assignment is
        never blocked (requirement 5)."""
        from mtkgui.gui.yamlbuild.path_risk import LEVEL_LOW
        gnd_nets = self._gnd_nets(result)
        power_nets = [r.name for r in result.power
                      if not self._auto_generated.get(r.name)]
        scored = set(power_nets)
        for rows in (clock_rows, gpio_rows):
            scored |= {row["net"] for row in rows
                       if row["status"] == ASSIGNED and row["channel"]}
        scores = evaluate_paths(sorted(scored), self._net_members(),
                                gnd_nets, self.risk_thresholds)
        self.risk_scores = scores
        for row in (*clock_rows, *gpio_rows):
            row["risk"] = scores.get(row["net"], {
                "score": 0, "level": LEVEL_LOW, "warning": False})
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
            self._auto_allocate(self.result)
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
        self._auto_allocate(result)     # item 24: SE clock / GPIO
        # Step 5: path risk (runs inside _auto_allocate)
        self.task_progress.emit(85, "parse nets: scoring path risk")
        self.task_log.emit("INFO", "path risk calculation done")
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
        """Render the POWER NETS table (Net | Test Points | Do Not
        Test | Assign Impedance | Assign Voltage | Assign Power
        rails); Step-4 best test point first, redundant alternatives
        dropped from the display."""
        rows = list(result.power)
        self.table.setRowCount(len(rows))
        yes_no = (UNSET_YESNO, "Yes", "No")
        for row, rec in enumerate(rows):
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
            dnt = QCheckBox()
            dnt.setChecked(bool(self._power_dnt.get(rec.name)))
            dnt.toggled.connect(
                lambda checked, name=rec.name: self._power_dnt_set(
                    name, checked))
            self.table.setCellWidget(row, 2, dnt)
            for col, key in ((3, "impedance"), (4, "voltage"),
                             (5, "power_rails")):
                combo = QComboBox()
                combo.addItems(yes_no)
                current = (self._power_assign.get(rec.name) or {}) \
                    .get(key) or UNSET_YESNO
                combo.setCurrentText(current)
                combo.currentTextChanged.connect(
                    lambda value, name=rec.name, k=key:
                        self._power_assign_set(name, k, value))
                self.table.setCellWidget(row, col, combo)
        self.lbl_summary.setText(
            f"{result.total} nets parsed: {result.summary()}")
        filtered = "; ".join(f"{n} ({r})"
                             for n, r in result.filtered) or "-"
        self.lbl_filtered.setText(f"Filtered: {filtered}")
