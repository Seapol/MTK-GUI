# -*- coding: utf-8 -*-
"""M43: the main FCT Sequence Add menu nests the Operation entries.

The "Operation" entry is a SUBMENU; clicking an entry adds the matching
row DIRECTLY (no nested sequence-editor dialog).  M48 unified the
structure with the ICT editor: Operation now holds 13 entries (9
standard operations + Delay + the three plain operator messages) and
the ICT-only / FCT-only groups are separate submenus.
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
    STEP_TYPE_MESSAGE_GOSTOP,
    STEP_TYPE_MESSAGE_OK,
    STEP_TYPE_MESSAGE_YESNO,
    STEP_TYPE_OPERATION,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_SERIAL_PUT,
)
from mtkgui.engine.steps import LAN_SETUP_OP, WIFI_CONNECT_OP  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _COL_CMD,
    _COL_TIMEOUT,
    _COL_TYPE,
)

DELAY_LABEL = "Delay — plain wait (ms)"
MESSAGE_LABELS = (STEP_TYPE_MESSAGE_OK, STEP_TYPE_MESSAGE_YESNO,
                  STEP_TYPE_MESSAGE_GOSTOP)
#: M48: the 9 standard operations (DIO / the two network setups moved
#: into the ICT-only / FCT-only groups)
STANDARD_OPS = tuple(n for n in OP_STEPS
                     if n not in DIO_OPS
                     and n not in (WIFI_CONNECT_OP, LAN_SETUP_OP))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    p = FCTTestConfigPanel()
    p.set_values({})
    return p


def _op_labels() -> list:
    return [f"Operation: {n}" for n in STANDARD_OPS]


class TestOperationSubmenu:
    def test_submenu_has_exactly_thirteen_entries(self, panel):
        texts = list(panel._op_add_actions)
        assert texts == _op_labels() + [DELAY_LABEL] + list(MESSAGE_LABELS)
        # M48: 9 standard operations + Delay + the three plain messages
        assert len(texts) == 13
        assert "Operation: Custom" not in texts
        for moved in DIO_OPS + (WIFI_CONNECT_OP, LAN_SETUP_OP):
            assert f"Operation: {moved}" not in texts, moved
        assert STEP_TYPE_SERIAL_PUT not in texts
        assert STEP_TYPE_SERIAL_PULL not in texts
        # it really is a submenu of the Add dropdown
        first = next(iter(panel._op_add_actions.values()))
        sub = first.parent()
        assert isinstance(sub, QMenu)
        assert sub.title() == "Operation"

    def test_each_standard_op_adds_its_row_directly(self, panel):
        for name in STANDARD_OPS:
            panel._op_add_actions[f"Operation: {name}"].trigger()
            row = panel.cmd_table.rowCount() - 1
            cmd = panel._get_row_cmd(row)
            assert cmd.kind == KIND_OP
            assert cmd.name == name
            assert cmd.op_params == dict(OP_STEPS[name])
            assert panel.cmd_table.item(row, _COL_TYPE).text() \
                == STEP_TYPE_OPERATION

    def test_plain_message_entries_add_message_rows(self, panel):
        """M48: the three plain operator dialogs are STANDARD steps."""
        from mtkgui.engine.fct_test_config import KIND_MESSAGE
        for label in MESSAGE_LABELS:
            before = panel.cmd_table.rowCount()
            panel._op_add_actions[label].trigger()
            assert panel.cmd_table.rowCount() == before + 1, label
            cmd = panel._get_row_cmd(before)
            assert cmd.kind == KIND_MESSAGE, label
            assert panel.cmd_table.item(before, _COL_TYPE).text() == label

    def test_serial_entries_add_their_rows_directly(self, panel):
        """M46: the two serial transfers add a serial row with the
        documented defaults (Push: local assets dir; Pull: project
        outbox; both remote /root/)."""
        for label, kind in ((STEP_TYPE_SERIAL_PUT, KIND_SERIAL_PUT),
                            (STEP_TYPE_SERIAL_PULL, KIND_SERIAL_PULL)):
            before = panel.cmd_table.rowCount()
            panel._add_actions[label].trigger()
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
        direct = ((set(STEP_TYPE_LABELS) - {STEP_TYPE_OPERATION})
                  | {STEP_TYPE_SERIAL_PUT, STEP_TYPE_SERIAL_PULL}
                  | {f"Operation: {n}" for n in STANDARD_OPS}
                  | set(MESSAGE_LABELS)
                  | {WIFI_CONNECT_OP, LAN_SETUP_OP}
                  | {DELAY_LABEL})
        assert set(panel._add_actions) == direct
        assert len(panel._add_actions) == 32   # M83: DUT login retired
        assert STEP_TYPE_DELAY not in panel._add_actions
        assert "Delay" not in panel._add_actions
        # Operation is not a direct item any more - it is the submenu
        assert STEP_TYPE_OPERATION not in panel._add_actions


class TestOperationSubmenuGate:
    def test_available_ops_disables_blocked_entries(self, panel):
        inst = sorted(INSTRUMENT_OPS)[0]
        fixture = sorted(FIXTURE_OPS)[0]
        blocked = set(INSTRUMENT_OPS) | set(FIXTURE_OPS)
        allowed = "Power On DUT" if "Power On DUT" not in blocked \
            else sorted(set(OP_STEPS) - blocked)[0]
        panel.set_available_ops({allowed})
        acts = panel._op_add_actions
        for name, tip in ((inst, "Configure instruments (Equipment page) "
                                "first"),
                          (fixture, "Configure fixture (Equipment page) "
                                    "first")):
            act = acts[f"Operation: {name}"]
            assert not act.isEnabled()
            assert act.toolTip() == tip
        assert acts[f"Operation: {allowed}"].isEnabled()
        # M48: the DIO operations moved to the ICT-only submenu - it is
        # always grayed in an FCT sequence
        ict = panel._add_menu_groups["ICT Measurements"]
        assert not ict.isEnabled()
        for name in DIO_OPS:
            assert f"Operation: {name}" not in acts
        # the serial transfers are File Transfer entries now (M45d)
        assert panel._add_actions[STEP_TYPE_SERIAL_PUT].isEnabled()
        assert panel._add_actions[STEP_TYPE_SERIAL_PULL].isEnabled()
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
    def test_double_click_opens_the_single_row_form(self, panel,
                                                    monkeypatch):
        """The main table edits ONE row at a time.  M53: the row opens the
        shared per-type parameter FORM - no multi-step sequence editor."""
        from mtkgui.gui.steps_editor import StepsEditorDialog
        panel._op_add_actions["Operation: Power On DUT"].trigger()
        row = panel.cmd_table.rowCount() - 1
        seen = {}

        def fake_exec(dlg):
            seen["nested"] = isinstance(dlg, StepsEditorDialog)
            seen["title"] = dlg.windowTitle()
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        panel._edit_current_row(row)
        assert seen["nested"] is False
        assert "Edit (Operation)" in seen["title"]
