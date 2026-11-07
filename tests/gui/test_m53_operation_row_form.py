"""M53: a standard Operation row opens the per-type parameter FORM
directly - never a nested sequence editor carrying a single row."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QPushButton,
    QSpinBox,
)

from mtkgui.gui import steps_editor as steps_editor_module  # noqa: E402
from mtkgui.gui.steps_editor import (  # noqa: E402
    StepsEditorDialog,
    edit_op_step_dialog,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    KIND_OP,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    p = FCTTestConfigPanel()
    p.set_values({})
    yield p
    p.deleteLater()


def _add_op(panel, name):
    panel._add_operation_row(name)
    return panel.cmd_table.rowCount() - 1


def _combo_with(widget, items):
    for cb in widget.findChildren(QComboBox):
        texts = [cb.itemText(i) for i in range(cb.count())]
        if texts == list(items):
            return cb
    raise AssertionError(f"combo {items!r} not found")


def test_operation_row_opens_the_parameter_form(panel, monkeypatch):
    """The row editor is the shared FORM - no step list / reorder buttons."""
    row = _add_op(panel, "Power On DUT")
    seen = {}

    def fake_exec(widget):
        seen["dlg"] = widget
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_operation_row(row)
    dlg = seen["dlg"]
    assert not isinstance(dlg, StepsEditorDialog)
    assert "Edit (Operation)" in dlg.windowTitle()
    texts = {btn.text() for btn in dlg.findChildren(QPushButton)}
    assert not texts & {"Move Up", "Move Down", "Add", "Remove",
                        "Duplicate"}
    dlg.deleteLater()


def test_power_setpoints_round_trip(panel, monkeypatch):
    """M83/C9: a power row saves its STATE only - no setpoints, and the
    Enable / Wait / Timeout echoes stay unchanged."""
    row = _add_op(panel, "Power On DUT")

    def fake_exec(widget):
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_operation_row(row)
    cmd = panel._row_cmd(row)
    assert cmd.name == "Power On DUT"
    assert cmd.kind == KIND_OP
    assert cmd.op_kind == "op"
    assert cmd.enabled is True
    assert (cmd.op_wait_ms, cmd.op_timeout_ms) == (100, 5000)
    assert cmd.op_params == {"type": "power", "state": "on"}


def test_fixture_params_round_trip(panel, monkeypatch):
    row = _add_op(panel, "Fixture Clamp Down")

    def fake_exec(widget):
        _combo_with(widget, ["press", "inpos", "estop"]).setCurrentText(
            "inpos")
        _combo_with(widget, ["H", "L"]).setCurrentText("L")
        _combo_with(widget, ["", "High", "Low"]).setCurrentText("High")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_operation_row(row)
    cmd = panel._row_cmd(row)
    assert cmd.op_params == {"type": "fixture", "signal": "inpos",
                             "level": "L", "expect": "High"}


def test_instruments_multi_select_round_trip(panel, monkeypatch):
    row = _add_op(panel, "Init Instruments")

    def fake_exec(widget):
        for cb in widget.findChildren(QCheckBox):
            key = cb.property("instrument_key")
            if key in ("daq973a", "u2355a", "psu"):
                cb.setChecked(key in ("daq973a", "psu"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_operation_row(row)
    assert panel._row_cmd(row).op_params == {
        "type": "instruments", "instruments": ["daq973a", "psu"]}


def test_legacy_unknown_name_is_preserved(panel, monkeypatch):
    row = _add_op(panel, "Power Off DUT")
    cmd = panel._row_cmd(row)
    cmd.name = "Legacy Vendor Step"
    cmd.op_params = None
    panel._save_row_cmd(row, cmd)

    def fake_exec(widget):
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_operation_row(row)
    assert panel._row_cmd(row).name == "Legacy Vendor Step"


def test_empty_name_falls_back_to_the_previous_one(panel, monkeypatch):
    row = _add_op(panel, "Power On DUT")

    def fake_exec(widget):
        combo = [cb for cb in widget.findChildren(QComboBox)
                 if cb.isEditable()][0]
        combo.setCurrentText("")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_operation_row(row)
    assert panel._row_cmd(row).name == "Power On DUT"


def test_cancel_leaves_the_row_unchanged(panel, monkeypatch):
    row = _add_op(panel, "Power On DUT")
    before = panel._row_cmd(row)
    before_params = dict(before.op_params or {})

    def fake_exec(widget):
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_operation_row(row)
    cmd = panel._row_cmd(row)
    assert cmd.name == before.name
    assert cmd.op_params == before_params


def test_shared_form_is_a_module_level_function():
    """ICT / FCT legacy editors and the panel share ONE form."""
    assert callable(edit_op_step_dialog)
    assert edit_op_step_dialog.__module__ == "mtkgui.gui.steps_editor"


def test_legacy_fct_editor_still_uses_the_shared_form(qapp, monkeypatch):
    """Regression: the legacy FCT sequence editor delegates to the same
    form and keeps its name / kind / op-params result_data."""
    dlg = StepsEditorDialog(
        "fct", ["Power On DUT"], [True], [100], [5000],
        kinds=["op"], op_params=[{"type": "power"}])
    calls = {}

    def fake_form(parent, name, params, enable, wait, timeout, title=None):
        calls.update(name=name, params=params, enable=enable, wait=wait,
                     timeout=timeout, title=title)
        return (name, {"type": "power", "voltage": 9.0, "current": 1.5},
                False, 250, 9000)

    monkeypatch.setattr(steps_editor_module, "edit_op_step_dialog",
                        fake_form)
    try:
        assert dlg._edit_op_step(0, dlg._steps[0]) is True
        assert calls["name"] == "Power On DUT"
        assert calls["params"] == {"type": "power"}
        assert "Edit (Operation)" in calls["title"]
        # (result_data re-syncs the checkboxes: assert the stored flag
        # before asking for the full result)
        assert dlg._enables == [False]
        steps, _enables, waits, timeouts, kinds, op_params = \
            dlg.result_data()
        assert steps == ["Power On DUT"]
        assert (waits, timeouts) == ([250], [9000])
        assert kinds == ["op"]
        assert op_params == [{"type": "power", "voltage": 9.0,
                              "current": 1.5}]
    finally:
        dlg.deleteLater()
