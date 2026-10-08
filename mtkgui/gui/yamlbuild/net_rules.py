# -*- coding: utf-8 -*-
"""Net classification rules + regex editor core (item 24, Task 1).

Classification priority (highest -> lowest):

1. Manual single-net override
2. SPF pin attribute (POWER / GND / CLOCK / DIFF pin types)
3. User custom regex (project YAML ``net_classification_rules``)
4. Factory default regex

An EMPTY user regex skips the name matching step for that category -
classification then relies fully on the SPF pin attribute (and the
default regex for the remaining categories still applies; an empty
DEFAULT is treated the same way).  Headless core, unit-testable
without Qt; the dialog lives at the bottom of this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from PySide6.QtWidgets import QDialog, QWidget

CATEGORY_POWER = "Power"
CATEGORY_GND = "GND"
CATEGORY_SE_CLOCK = "SE Clock"
CATEGORY_DIFF_PAIR = "Diff Pair"
CATEGORY_SIGNAL = "Signal"

#: the editable rule slots (key -> (label, factory default regex)).
#: GND is a SYSTEM-auto category (no user config entry - core standard
#: 5.2); its default regex stays internal for the GND integrity check.
RULE_SLOTS: tuple[tuple[str, str], ...] = (
    ("power", "Power Nets regex"),
    ("se_clock", "SE Clock Nets regex"),
    ("exclude", "Exclude Parse Nets regex"),
)

DEFAULT_RULES: dict[str, str] = {
    "power": r"^(?!.+INTB)(?:V(DD|CC|IN|OUT|PRE|SYS|BAT|BUS|AUX|CORE|IO|A|D)([0-9_].*)?|[0-9]+([.][0-9]+)?V([0-9A-Z_]*)?|P[35][V_][0-9A-Z_]*|(DCDC|DC)_([0-9]+([.][0-9]+)?V)([0-9A-Z_]*)?|[0-9A-Z_]*V(OUT|REF|SW|PWR|FB)[0-9A-Z_]*|[0-9A-Z_]+_(1V0|1V2|1V5|1V8|2V5|3V3|5V|12V|24V)([0-9A-Z_]*)?)$",
    "gnd": r"^(GND\w*|AGND\w*|DGND\w*|PGND\w*|VSS\w*)$",
    "se_clock": r"^(CLK\w*|OSC\w*|XTAL\w*|MCLK\w*|\d+MH?Z\w*)$",
    # nets matching the Exclude regex NEVER become ICT test objects
    # (differential pairs, Reset / Enable / UART / WAKE / I2C / SPI /
    # JTAG / DBGIF / DATA / ADC buses and Allegro system random
    # numeric names); an EMPTY value disables the exclusion entirely.
    # The differential PAIR DETECTION stays a kernel-internal rule
    # (no user config entry).
    "exclude": (r"(?i)(DIFF|RESET|ENABLE|UART|WAKE|I2C|SPI|JTAG|"
                r"DBGIF|DATA|ADC|_EN(_|$)|_(P|N)$|^\$?N?\d+$)"),
    "diff_pair": r"^\w+_(P|N)$",
}

# SPF pin attribute words -> category (higher priority than regex)
_PIN_TYPE_MAP: dict[str, str] = {
    "POWER": CATEGORY_POWER,
    "PWR": CATEGORY_POWER,
    "GND": CATEGORY_GND,
    "GROUND": CATEGORY_GND,
    "CLOCK": CATEGORY_SE_CLOCK,
    "CLK": CATEGORY_SE_CLOCK,
    "DIFF": CATEGORY_DIFF_PAIR,
    "DIFFERENTIAL": CATEGORY_DIFF_PAIR,
}

#: fixed exclusion patterns for the GPIO candidate extraction (Task 5)
GPIO_EXCLUDE_RE = re.compile(
    r"(RESET|SENSE|FEEDBACK|_EN\b|ENABLE|INT\b|INTERRUPT|ANALOG|"
    r"AGND|DIFF|_P$|_N$|TEST_|TP\d)", re.IGNORECASE)


@dataclass
class NetClassification:
    """The classification outcome for one net."""

    category: str
    auto_generated: bool = False
    dont_test_locked: bool = False
    reason: str = ""


def validate_rules(rules: dict[str, str]) -> list[str]:
    """Pre-save validation of the four regex fields.

    Checks syntax AND catastrophic backtracking risk (nested
    quantifiers such as ``(a+)+`` / ``(a|aa)+``).

    Returns:
        List of human readable error strings (empty = safe to save).
    """
    errors: list[str] = []
    for key, label in RULE_SLOTS:
        pattern = (rules.get(key) or "").strip()
        if not pattern:
            continue                    # empty = skip name matching
        try:
            parsed = re.compile(pattern)
        except re.error as exc:
            errors.append(f"{label}: invalid regex syntax ({exc})")
            continue
        if _has_nested_quantifier(parsed):
            errors.append(
                f"{label}: catastrophic backtracking risk (nested "
                "quantifier) - simplify the pattern")
    return errors


def _has_nested_quantifier(parsed) -> bool:
    """True when a repeated group contains another unbounded repeat
    (the classic catastrophic backtracking shape)."""
    import sre_parse
    if isinstance(parsed, re.Pattern):
        parsed = parsed.pattern and sre_parse.parse(parsed.pattern)
    SUBPATTERN, MAX_REPEAT = sre_parse.SUBPATTERN, sre_parse.MAX_REPEAT

    def walk(nodes, inside_repeat: bool) -> bool:
        for op, av in nodes:
            if op is MAX_REPEAT:
                lo, hi, item = av
                unbounded = hi == sre_parse.MAXREPEAT or hi > 1
                if inside_repeat and unbounded:
                    return True
                if walk(item, inside_repeat or unbounded):
                    return True
            elif op is SUBPATTERN:
                if walk(av[-1], inside_repeat):
                    return True
            elif op is sre_parse.BRANCH:
                for branch in av[1]:
                    if walk(branch, inside_repeat):
                        return True
            elif op is sre_parse.IN:
                if walk(av, inside_repeat):
                    return True
        return False

    try:
        return walk(parsed, False)
    except Exception:                   # pragma: no cover - parse guard
        return False


def classify_net(name: str,
                 spf_pin_type: str = "",
                 rules: dict[str, str] | None = None,
                 manual: str = "") -> str:
    """Classify one net name by the priority chain.

    Args:
        name:         Net name.
        spf_pin_type: SPF pin attribute ("" when unknown).
        rules:        User custom regexes ("" / missing key = skip).
        manual:       Manual single-net override (category name; wins
                      over everything).

    Returns:
        One of Power / GND / SE Clock / Diff Pair / Signal.
    """
    if manual:
        return manual
    pin = (spf_pin_type or "").strip().upper()
    if pin in _PIN_TYPE_MAP:
        return _PIN_TYPE_MAP[pin]
    rules = rules or {}
    for key, category in (("power", CATEGORY_POWER),
                          ("gnd", CATEGORY_GND),
                          ("se_clock", CATEGORY_SE_CLOCK),
                          ("signal", CATEGORY_SIGNAL),
                          ("diff_pair", CATEGORY_DIFF_PAIR)):
        if key in rules:
            # item 24 Task 1: an EXPLICITLY EMPTY custom regex skips
            # the name matching entirely for this category (no
            # factory fallback) - classification relies on the SPF
            # pin attribute then
            pattern = (rules.get(key) or "").strip()
            if pattern:
                try:
                    if re.match(pattern, name):
                        return category
                except re.error:
                    continue
        else:
            pattern = DEFAULT_RULES.get(key, "")
            if pattern and re.match(pattern, name):
                return category
    return CATEGORY_SIGNAL


# ------------------------------------------------------------- editor GUI
def _open_editor(parent, rules: dict[str, str]) -> dict | None:
    """Open the regex editor dialog (Qt part split out so the core
    stays importable headless)."""
    dlg = NetRulesEditorDialog(rules, parent)
    if dlg.exec() == NetRulesEditorDialog.DialogCode.Accepted:
        return dlg.rules()
    return None


class NetRulesEditorDialog(QDialog):
    """'Edit Net Classification Rules' dialog (Task 1).

    Four independent regex fields, each with a [Test] box; [Reset to
    Default] restores the factory preset; [Save] pre-validates every
    regex (syntax + catastrophic backtracking) and refuses to close
    on error; [Cancel] discards the changes."""

    def __init__(self, rules: dict[str, str] | None = None,
                 parent=None) -> None:
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
        )
        super().__init__(parent)
        self.setWindowTitle("Edit Net Classification Rules")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        head = QLabel(
            "Priority: manual override > SPF pin attribute > custom "
            "regex > factory default.  An empty regex skips the name "
            "match (SPF pin type only); an empty Exclude regex "
            "disables the exclusion.  Nets matching the Exclude "
            "Parse Nets regex (differential pairs, Reset / Enable / "
            "UART / WAKE / I2C / SPI / JTAG / DBGIF / DATA / ADC, "
            "system random numeric names ...) never become ICT test "
            "objects.  Differential pair detection is kernel-internal.")
        head.setObjectName("muted")
        head.setWordWrap(True)
        lay.addWidget(head)

        self._edits: dict[str, QLineEdit] = {}
        self._samples: dict[str, QLineEdit] = {}
        self._results: dict[str, QLabel] = {}
        form = QFormLayout()
        form.setVerticalSpacing(10)
        for key, label in RULE_SLOTS:
            row = QHBoxLayout()
            edit = QLineEdit((rules or {}).get(key, DEFAULT_RULES[key]))
            edit.setMinimumWidth(280)
            row.addWidget(edit, 1)
            sample = QLineEdit()
            sample.setPlaceholderText("sample net name")
            sample.setMaximumWidth(180)
            row.addWidget(sample)
            test_btn = QPushButton("Test")
            test_btn.setMaximumWidth(56)
            row.addWidget(test_btn)
            result = QLabel("")
            result.setMinimumWidth(80)
            row.addWidget(result)
            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(f"{label}:", wrap)
            self._edits[key] = edit
            self._samples[key] = sample
            self._results[key] = result
            test_btn.clicked.connect(
                lambda _c=False, k=key: self._run_test(k))
        lay.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b91c1c;")
        self.error_label.setWordWrap(True)
        lay.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Save).setText("Save")
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_default)
        buttons.addButton(reset_btn,
                          QDialogButtonBox.ActionRole.ResetRole)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    # ------------------------------------------------------------ actions
    def _run_test(self, key: str) -> None:
        """[Test]: instantly show Match / No Match for the sample."""
        result = self._results[key]
        pattern = self._edits[key].text()
        sample = self._samples[key].text()
        try:
            hit = bool(re.match(pattern, sample))
            result.setText("Match" if hit else "No Match")
            result.setStyleSheet(
                f"color: {'#16a34a' if hit else '#6b7280'}; "
                "font-weight: bold;")
        except re.error as exc:
            result.setText("Invalid")
            result.setStyleSheet("color: #dc2626; font-weight: bold;")
            result.setToolTip(str(exc))

    def _reset_default(self) -> None:
        """[Reset to Default]: restore all four factory presets."""
        for key, _label in RULE_SLOTS:
            self._edits[key].setText(DEFAULT_RULES[key])
        self.error_label.setText("")

    def _on_save(self) -> None:
        """[Save]: compile + backtracking pre-validation; invalid
        regex forbids saving (error popup text stays in the dialog)."""
        errors = validate_rules(self.rules())
        if errors:
            self.error_label.setText("\n".join(errors))
            return
        self.accept()

    def rules(self) -> dict[str, str]:
        """The current (possibly unsaved) rule patterns."""
        return {key: self._edits[key].text().strip()
                for key, _label in RULE_SLOTS}
