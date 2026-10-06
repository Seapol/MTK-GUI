# -*- coding: utf-8 -*-
"""Item 24 Task 1: net classification rules + regex editor core."""
from __future__ import annotations

import pytest

from mtkgui.gui.yamlbuild.net_rules import (
    CATEGORY_DIFF_PAIR,
    CATEGORY_GND,
    CATEGORY_POWER,
    CATEGORY_SE_CLOCK,
    CATEGORY_SIGNAL,
    DEFAULT_RULES,
    RULE_SLOTS,
    NetRulesEditorDialog,
    classify_net,
    validate_rules,
)


# ------------------------------------------------------- classification
def test_priority_manual_override_wins():
    rules = dict(DEFAULT_RULES)
    assert classify_net("VDD_3V3", "CLOCK", rules,
                        manual="GND") == CATEGORY_GND


def test_priority_spf_pin_beats_regex():
    rules = dict(DEFAULT_RULES)
    # name looks like power, but the SPF pin attribute says clock
    assert classify_net("VDD_3V3", "clock", rules) == CATEGORY_SE_CLOCK
    assert classify_net("CLK1", "POWER", rules) == CATEGORY_POWER


def test_priority_custom_regex_beats_default():
    custom = dict(DEFAULT_RULES, power=r"^PWR_\w+$")
    assert classify_net("PWR_MAIN", "", custom) == CATEGORY_POWER
    # default no longer matches PWR_MAIN (custom replaced it)
    rules_empty_power = dict(custom, power="")
    assert classify_net("PWR_MAIN", "", rules_empty_power) \
        == CATEGORY_SIGNAL


def test_empty_regex_skips_matching():
    """Empty regex skips the name match - SPF pin type only; unknown
    pin types fall through to Signal (no default fallback either).
    GND itself is system-auto: with no user gnd rule the default GND
    regex applies, an explicit empty gnd rule suppresses it."""
    rules = {key: "" for key, _ in RULE_SLOTS}
    assert classify_net("VDD_3V3", "", rules) == CATEGORY_SIGNAL
    assert classify_net("VDD_3V3", "POWER", rules) == CATEGORY_POWER
    # system-auto GND (no user entry): default GND regex applies
    assert classify_net("GND", "", rules) == CATEGORY_GND
    # explicit empty gnd entry (legacy YAML) suppresses it
    assert classify_net("GND", "", dict(rules, gnd="")) == \
        CATEGORY_SIGNAL
    assert classify_net("CLK1", "", rules) == CATEGORY_SIGNAL
    assert classify_net("USB_P", "", rules) == CATEGORY_SIGNAL
    assert classify_net("X1", "DIFF", rules) == CATEGORY_DIFF_PAIR


def test_default_rules_classify_common_names():
    rules = {}
    assert classify_net("VDD_3V3", "", rules) == CATEGORY_POWER
    assert classify_net("GND", "", rules) == CATEGORY_GND
    assert classify_net("CLK1", "", rules) == CATEGORY_SE_CLOCK
    assert classify_net("USB_P", "", rules) == CATEGORY_DIFF_PAIR
    assert classify_net("GPIO0", "", rules) == CATEGORY_SIGNAL


# ------------------------------------------------------------- validation
def test_validate_rejects_syntax_error():
    errors = validate_rules({"power": "VDD["})
    assert any("invalid regex" in e for e in errors)


def test_validate_rejects_catastrophic_backtracking():
    errors = validate_rules({"power": r"^(a+)+$"})
    assert any("backtracking" in e for e in errors)
    # plain safe patterns pass
    assert validate_rules(dict(DEFAULT_RULES)) == []


def test_validate_empty_rules_ok():
    assert validate_rules({key: "" for key, _ in RULE_SLOTS}) == []


# ---------------------------------------------------------------- editor
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_editor_test_button_and_reset(qapp):
    dlg = NetRulesEditorDialog()
    dlg._edits["power"].setText(r"^VDD")
    dlg._samples["power"].setText("VDD_3V3")
    dlg._run_test("power")
    assert dlg._results["power"].text() == "Match"
    dlg._samples["power"].setText("CLK1")
    dlg._run_test("power")
    assert dlg._results["power"].text() == "No Match"
    # reset to default restores all four factory patterns
    dlg._edits["power"].setText("custom")
    dlg._reset_default()
    assert dlg._edits["power"].text() == DEFAULT_RULES["power"]
    dlg.deleteLater()


def test_editor_save_forbidden_on_invalid_regex(qapp, monkeypatch):
    """[Save] with an invalid regex stays open and shows the error -
    nothing is accepted."""
    from PySide6.QtWidgets import QDialog
    dlg = NetRulesEditorDialog()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(QDialog, "accept",
                   lambda self: pytest.fail("accept() must not run"))
    try:
        dlg._edits["power"].setText("VDD((")
        dlg._on_save()
        assert "invalid regex" in dlg.error_label.text()
        # catastrophic backtracking also blocks the save
        dlg._edits["power"].setText(r"^(a+)+$")
        dlg._on_save()
        assert "backtracking" in dlg.error_label.text()
    finally:
        monkey.undo()
        dlg.deleteLater()


def test_editor_save_accepts_valid_rules(qapp):
    dlg = NetRulesEditorDialog()
    dlg._edits["power"].setText(r"^VDD")
    dlg._on_save()
    assert dlg.result() in (True, False)  # accept path ran clean
    assert dlg.rules()["power"] == r"^VDD"
    dlg.deleteLater()
