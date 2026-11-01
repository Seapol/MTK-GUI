# -*- coding: utf-8 -*-
"""M48: ONE unified ICT / FCT Add menu with domain gating.

Both the ICT step editor and the FCT sequence table render the same
grouped structure (Operation first with 13 entries, ICT Measurements,
File Transfer, Network, Console, Message (Console), Wi-Fi Tests,
Bluetooth Tests, Flash).  The non-applicable domain stays visible but
grayed with a domain tooltip.  "Operation: Custom" is gone everywhere;
MessageOK / YesNo / GoStop are STANDARD steps (usable in ICT too) and
the DIO operations live in ICT-only.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from mtkgui.engine.steps import (  # noqa: E402
    DIO_OPS,
    LAN_SETUP_OP,
    OP_STEPS,
    WIFI_CONNECT_OP,
)
from mtkgui.gui.add_menu import MENU_TITLES, build_add_menu  # noqa: E402
from mtkgui.gui.steps_editor import StepsEditorDialog  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)

DELAY_LABEL = "Delay — plain wait (ms)"
MESSAGES = ("MessageOK", "MessageYesNo", "MessageGoStop")
ICT_GROUP = "ICT Measurements"
FCT_GROUPS = ("File Transfer", "Network", "Console", "Message (Console)",
              "Wi-Fi Tests", "Bluetooth Tests", "Flash")
ICT_TIP = "ICT-only step — not available in an FCT sequence"
FCT_TIP = "FCT-only step — not available in an ICT sequence"

STANDARD_OPS = tuple(n for n in OP_STEPS
                     if n not in DIO_OPS
                     and n not in (WIFI_CONNECT_OP, LAN_SETUP_OP))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def ict_dlg(qapp):
    dlg = StepsEditorDialog(
        "ict", [("op", "Power On DUT", "—", "—", "—", "—")],
        [True], [100], [5000])
    yield dlg
    dlg.deleteLater()


@pytest.fixture()
def fct_panel(qapp):
    p = FCTTestConfigPanel()
    p.set_values({})
    return p


def _menu_of(obj):
    """The Add dropdown of an editor dialog or an FCT panel."""
    menu = getattr(obj, "btn_add", None)
    return obj._add_menu if menu is None else menu.menu()


def _top_titles(menu) -> list:
    return [a.text() for a in menu.actions() if a.text()]


def _submenu(menu, title: str) -> QMenu:
    for act in menu.actions():
        if act.menu() is not None and act.menu().title() == title:
            return act.menu()
    raise AssertionError(f"submenu {title!r} not found")


def _texts(menu) -> list:
    return [a.text() for a in menu.actions() if a.text()]


class TestUnifiedStructure:
    @pytest.mark.parametrize("menu_of", ["ict_dlg", "fct_panel"])
    def test_nine_grouped_submenus_in_order(self, request, menu_of):
        menu = _menu_of(request.getfixturevalue(menu_of))
        assert _top_titles(menu) == list(MENU_TITLES)

    @pytest.mark.parametrize("menu_of", ["ict_dlg", "fct_panel"])
    def test_operation_first_with_thirteen_entries(self, request, menu_of):
        menu = _menu_of(request.getfixturevalue(menu_of))
        op = _submenu(menu, "Operation")
        assert _texts(op) == ([f"Operation: {n}" for n in STANDARD_OPS]
                              + [DELAY_LABEL] + list(MESSAGES))

    @pytest.mark.parametrize("menu_of", ["ict_dlg", "fct_panel"])
    def test_no_operation_custom_anywhere(self, request, menu_of):
        menu = _menu_of(request.getfixturevalue(menu_of))
        for act in menu.actions():
            if act.menu() is not None:
                assert "Operation: Custom" not in _texts(act.menu())

    @pytest.mark.parametrize("menu_of", ["ict_dlg", "fct_panel"])
    def test_operation_holds_no_dio_and_no_network_ops(self, request,
                                                       menu_of):
        menu = _menu_of(request.getfixturevalue(menu_of))
        texts = _texts(_submenu(menu, "Operation"))
        for moved in DIO_OPS + (WIFI_CONNECT_OP, LAN_SETUP_OP):
            assert f"Operation: {moved}" not in texts, moved

    @pytest.mark.parametrize("menu_of", ["ict_dlg", "fct_panel"])
    def test_ict_measurements_has_six_entries(self, request, menu_of):
        menu = _menu_of(request.getfixturevalue(menu_of))
        texts = _texts(_submenu(menu, ICT_GROUP))
        assert len(texts) == 6
        assert any(t.startswith("R-GND") for t in texts)
        assert set(DIO_OPS) <= set(texts)

    @pytest.mark.parametrize("menu_of", ["ict_dlg", "fct_panel"])
    def test_fct_group_sizes(self, request, menu_of):
        menu = _menu_of(request.getfixturevalue(menu_of))
        sizes = {"File Transfer": 4, "Network": 2, "Console": 3,
                 "Message (Console)": 3, "Wi-Fi Tests": 3,
                 "Bluetooth Tests": 3, "Flash": 1}
        for title, n in sizes.items():
            texts = _texts(_submenu(menu, title))
            assert len(texts) == n, title
        assert set(_texts(_submenu(menu, "Network"))) == \
            {WIFI_CONNECT_OP, LAN_SETUP_OP}


class TestDomainGating:
    def test_ict_menu_grays_the_fct_only_groups(self, ict_dlg):
        menu = _menu_of(ict_dlg)
        for title in FCT_GROUPS:
            sub = _submenu(menu, title)
            assert not sub.isEnabled(), title
            assert FCT_TIP in sub.menuAction().toolTip(), title
        for title in ("Operation", ICT_GROUP):
            assert _submenu(menu, title).isEnabled(), title

    def test_fct_menu_grays_the_ict_group(self, fct_panel):
        menu = _menu_of(fct_panel)
        sub = _submenu(menu, ICT_GROUP)
        assert not sub.isEnabled()
        assert ICT_TIP in sub.menuAction().toolTip()
        for title in ("Operation",) + FCT_GROUPS:
            assert _submenu(menu, title).isEnabled(), title

    def test_builder_directly(self, qapp):
        captured = []
        built = build_add_menu(None, "ict", captured.append)
        assert _top_titles(built.menu) == list(MENU_TITLES)
        assert not built.submenus["Flash"].isEnabled()
        assert built.submenus[ICT_GROUP].isEnabled()


class TestEntriesAddDirectly:
    def test_ict_operation_entries_add_step_tuples(self, ict_dlg,
                                                   monkeypatch):
        """M43 rule: no nested editor dialog on Add."""
        for name in STANDARD_OPS[:3]:
            before = len(ict_dlg._steps)
            act = next(a for a in
                       ict_dlg._add_menu_groups["Operation"].actions()
                       if a.text() == f"Operation: {name}")
            # _on_add opens the edit dialog - reject it (the row is added)
            monkeypatch.setattr(StepsEditorDialog, "_on_edit",
                                lambda self: None)
            act.trigger()
            assert len(ict_dlg._steps) == before + 1
            step = ict_dlg._steps[-1]
            assert step[0] == "op" and step[1] == name

    def test_ict_message_entries_add_message_tuples(self, ict_dlg,
                                                    monkeypatch):
        monkeypatch.setattr(StepsEditorDialog, "_on_edit",
                            lambda self: None)
        menu = ict_dlg._add_menu_groups["Operation"]
        for label in MESSAGES:
            before = len(ict_dlg._steps)
            act = next(a for a in menu.actions() if a.text() == label)
            act.trigger()
            step = ict_dlg._steps[-1]
            assert step[0] == label
            assert step[2] == "—" and step[3] == "—"

    def test_ict_measurement_entries_add_measure_tuples(self, ict_dlg,
                                                        monkeypatch):
        monkeypatch.setattr(StepsEditorDialog, "_on_edit",
                            lambda self: None)
        menu = ict_dlg._add_menu_groups[ICT_GROUP]
        r_gnd = next(a for a in menu.actions()
                     if a.text().startswith("R-GND"))
        r_gnd.trigger()
        step = ict_dlg._steps[-1]
        assert step[0] == "R-GND" and step[2] == "Ω"

    def test_fct_message_and_transfer_entries_add_rows(self, fct_panel):
        menu = fct_panel._add_menu
        for label, group in (("MessageOK", "Operation"),
                             ("SSH SFTP: Push file to DUT",
                              "File Transfer"),
                             ("Console_serial", "Console"),
                             ("Wifi_Scan", "Wi-Fi Tests"),
                             ("BT_RSSI", "Bluetooth Tests"),
                             ("Flash_GUI", "Flash")):
            before = fct_panel.cmd_table.rowCount()
            act = next(a for a in _submenu(menu, group).actions()
                       if a.text() == label)
            act.trigger()
            assert fct_panel.cmd_table.rowCount() == before + 1, label


class TestIctMessageEditing:
    def test_edit_ict_message_step_edits_name_and_flags(self, ict_dlg,
                                                        monkeypatch):
        from PySide6.QtWidgets import QDialog, QCheckBox, QLineEdit, \
            QSpinBox
        ict_dlg._steps.append(("MessageGoStop", "Continue?",
                               "—", "—", "—", "—"))
        ict_dlg._enables.append(True)
        ict_dlg._waits.append(100)
        ict_dlg._timeouts.append(5000)
        r = len(ict_dlg._steps) - 1

        # auto-accept the editor and change the message text through
        # the form fields (Monkeypatched QDialog.exec runs the real
        # show logic? no - the fields are edited before exec is called)
        real_exec = QDialog.exec

        def fake_exec(self):
            # the form children exist already: edit then accept
            for child in self.findChildren(QLineEdit):
                child.setText("Proceed with test?")
            for child in self.findChildren(QCheckBox):
                child.setChecked(False)
            for child in self.findChildren(QSpinBox):
                child.setValue(250)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        assert ict_dlg._edit_ict_message_step(r, ict_dlg._steps[r])
        monkeypatch.setattr(QDialog, "exec", real_exec)
        step = ict_dlg._steps[r]
        assert step[0] == "MessageGoStop"
        assert step[1] == "Proceed with test?"
        assert step[2:] == ("—", "—", "—", "—")
        assert ict_dlg._enables[r] is False
        assert ict_dlg._waits[r] == 250
