# -*- coding: utf-8 -*-
"""M43: the main FCT Sequence Add menu nests the Operation entries.

The "Operation" entry is a SUBMENU with 16 entries (13 standard
operations + the two M46 serial transfers + "Delay — plain wait (ms)");
clicking an entry adds the matching row DIRECTLY (no nested
sequence-editor dialog).  The standalone Delay Type item is gone: the
main menu holds 18 direct Type items + the Operation submenu.  (M41 grew
the catalog from 11 to 13 standard operations; M46 removed the no-op
"Operation: Custom" entry and added Serial Push / Pull.)
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog, QMenu  # noqa: E402

from mtkgui.engine import DIO_OPS, FIXTURE_OPS, INSTRUMENT_OPS, \
    OP_STEPS  # noqa: E402
from mtkgui.engine.fct_test_config import (  # noqa: E402
    KIND_DELAY,
    KIND_OP,
    KIND_SERIAL_PULL,
    KIND_SERIAL_PUT,
    STEP_TYPE_DELAY,
    STEP_TYPE_LABELS,
    STEP_TYPE_OPERATION,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_SERIAL_PUT,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _COL_CMD,
    _COL_TIMEOUT,
    _COL_TYPE,
)

DELAY_LABEL = "Delay — plain wait (ms)"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    p = FCTTestConfigPanel()
    p.set_values({})
    return p


def _op_labels() -> list:
    return [f"Operation: {n}" for n in OP_STEPS]


class TestOperationSubmenu:
    def test_submenu_has_exactly_sixteen_entries(self, panel):
        texts = list(panel._op_add_actions)
        assert texts == _op_labels() + [
            STEP_TYPE_SERIAL_PUT, STEP_TYPE_SERIAL_PULL, DELAY_LABEL]
        # 13 standard operations (M41 added the two network-setup ops)
        # + 2 serial transfers (M46) + Delay; Custom is gone
        assert len(texts) == 16
        assert "Operation: Custom" not in texts
        # it really is a submenu of the Add dropdown
        first = next(iter(panel._op_add_actions.values()))
        sub = first.parent()
        assert isinstance(sub, QMenu)
        assert sub.title() == "Operation"

    def test_each_standard_op_adds_its_row_directly(self, panel):
        for name in OP_STEPS:
            panel._op_add_actions[f"Operation: {name}"].trigger()
            row = panel.cmd_table.rowCount() - 1
            cmd = panel._get_row_cmd(row)
            assert cmd.kind == KIND_OP
            assert cmd.name == name
            assert cmd.op_params == dict(OP_STEPS[name])
            assert panel.cmd_table.item(row, _COL_TYPE).text() \
                == STEP_TYPE_OPERATION

    def test_serial_entries_add_their_rows_directly(self, panel):
        """M46: the two serial transfers add a serial row with the
        documented defaults (Push: local assets dir; Pull: project
        outbox; both remote /root/)."""
        for label, kind in ((STEP_TYPE_SERIAL_PUT, KIND_SERIAL_PUT),
                            (STEP_TYPE_SERIAL_PULL, KIND_SERIAL_PULL)):
            before = panel.cmd_table.rowCount()
            panel._op_add_actions[label].trigger()
            assert panel.cmd_table.rowCount() == before + 1
            cmd = panel._get_row_cmd(before)
            assert cmd.kind == kind
            assert cmd.remote == "/root/"
            assert cmd.transport == "serial"
            assert cmd.serial_baud == 0

    def test_delay_entry_adds_a_delay_row(self, panel):
        before = panel.cmd_table.rowCount()
        panel._op_add_actions[DELAY_LABEL].trigger()
        assert panel.cmd_table.rowCount() == before + 1
        cmd = panel._get_row_cmd(before)
        assert cmd.kind == KIND_DELAY
        assert cmd.wait_ms == 1000
        assert cmd.timeout == 0.0
        assert panel.cmd_table.item(before, _COL_TYPE).text() \
            == STEP_TYPE_DELAY
        assert panel.cmd_table.item(before, _COL_CMD).text() == "1000 ms"
        assert panel.cmd_table.item(before, _COL_TIMEOUT).text() == "0"

    def test_no_editor_dialog_opens_on_add(self, panel, monkeypatch):
        """Adding from the submenu never instantiates the sequence
        editor dialog."""
        from mtkgui.gui import steps_editor as se

        def _boom(*_a, **_k):       # pragma: no cover - must not run
            raise AssertionError("StepsEditorDialog opened on Add")

        monkeypatch.setattr(se, "StepsEditorDialog", _boom)
        for text in list(panel._op_add_actions):
            panel._op_add_actions[text].trigger()

    def test_standalone_delay_and_operation_items_are_gone(self, panel):
        direct = set(STEP_TYPE_LABELS) - {STEP_TYPE_OPERATION}
        assert set(panel._add_actions) == direct
        assert len(panel._add_actions) == 18
        assert STEP_TYPE_DELAY not in panel._add_actions
        assert "Delay" not in panel._add_actions
        # Operation is not a direct item any more - it is the submenu
        assert STEP_TYPE_OPERATION not in panel._add_actions


class TestOperationSubmenuGate:
    def test_available_ops_disables_blocked_entries(self, panel):
        dio = sorted(DIO_OPS)[0]
        inst = sorted(INSTRUMENT_OPS)[0]
        fixture = sorted(FIXTURE_OPS)[0]
        blocked = set(DIO_OPS) | set(INSTRUMENT_OPS) | set(FIXTURE_OPS)
        allowed = "Power On DUT" if "Power On DUT" not in blocked \
            else sorted(set(OP_STEPS) - blocked)[0]
        panel.set_available_ops({allowed})
        acts = panel._op_add_actions
        for name, tip in ((dio, "Configure Control IO Nets (ICT module) "
                                "first"),
                          (inst, "Configure instruments (Equipment page) "
                                 "first"),
                          (fixture, "Configure fixture (Equipment page) "
                                    "first")):
            act = acts[f"Operation: {name}"]
            assert not act.isEnabled()
            assert act.toolTip() == tip
        assert acts[f"Operation: {allowed}"].isEnabled()
        assert acts[STEP_TYPE_SERIAL_PUT].isEnabled()
        assert acts[STEP_TYPE_SERIAL_PULL].isEnabled()
        assert acts[DELAY_LABEL].isEnabled()

    def test_none_available_ops_enables_everything(self, panel):
        panel.set_available_ops(None)
        for text, act in panel._op_add_actions.items():
            assert act.isEnabled(), text
            assert "Configure" not in act.toolTip(), text

    def test_gate_can_be_relaxed_again(self, panel):
        panel.set_available_ops(set())
        assert not panel._op_add_actions["Operation: Power On DUT"] \
            .isEnabled()
        panel.set_available_ops(None)
        assert panel._op_add_actions["Operation: Power On DUT"].isEnabled()


class TestRowEditingStaysSingle:
    def test_double_click_opens_the_single_row_editor(self, panel,
                                                      monkeypatch):
        """The main table still edits ONE row at a time - no multi-step
        sequence editor."""
        from mtkgui.gui.steps_editor import StepsEditorDialog
        panel._op_add_actions["Operation: Power On DUT"].trigger()
        row = panel.cmd_table.rowCount() - 1
        seen = {}

        def fake_exec(self):
            seen["steps"] = list(self._steps)
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(StepsEditorDialog, "exec", fake_exec)
        panel._edit_current_row(row)
        assert seen["steps"] == ["Power On DUT"]
