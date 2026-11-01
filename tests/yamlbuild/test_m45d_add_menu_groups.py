# -*- coding: utf-8 -*-
"""M45d: the FCT Sequence Add menu is grouped into category submenus.

Owner request 2026-11-01: the flat Message / SFTP / Wi-Fi / Bluetooth
sections become SUBMENUS - Message (6), File Transfer (4: the renamed
SSH SFTP Push / Pull + the two serial transfers), Wi-Fi Tests (3),
Bluetooth Tests (3).  Every entry still adds its row DIRECTLY (M43 rule)
and an old YAML carrying ``step_type: SFTP_put`` / ``SFTP_get`` keeps
loading / executing as before while displaying the new names.
"""
from __future__ import annotations

import yaml

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    KIND_BT_TEST,
    KIND_MESSAGE,
    KIND_SERIAL_PULL,
    KIND_SERIAL_PUT,
    KIND_SFTP_GET,
    KIND_SFTP_PUT,
    KIND_WIFI_TEST,
    STEP_TYPE_BT_PAIR,
    STEP_TYPE_BT_RSSI,
    STEP_TYPE_BT_TONE,
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_MESSAGE_GOSTOP,
    STEP_TYPE_MESSAGE_GOSTOP_WAIT,
    STEP_TYPE_MESSAGE_OK,
    STEP_TYPE_MESSAGE_OK_WAIT,
    STEP_TYPE_MESSAGE_YESNO,
    STEP_TYPE_MESSAGE_YESNO_WAIT,
    STEP_TYPE_SERIAL_PULL,
    STEP_TYPE_SERIAL_PUT,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_SFTP_PUT,
    STEP_TYPE_WIFI_IPERF,
    STEP_TYPE_WIFI_PING,
    STEP_TYPE_WIFI_SCAN,
    normalize_step_type_label,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
    _COL_TYPE,
)

MESSAGE_LABELS = (STEP_TYPE_MESSAGE_OK, STEP_TYPE_MESSAGE_YESNO,
                  STEP_TYPE_MESSAGE_GOSTOP, STEP_TYPE_MESSAGE_OK_WAIT,
                  STEP_TYPE_MESSAGE_YESNO_WAIT,
                  STEP_TYPE_MESSAGE_GOSTOP_WAIT)
TRANSFER_LABELS = (STEP_TYPE_SFTP_PUT, STEP_TYPE_SFTP_GET,
                   STEP_TYPE_SERIAL_PUT, STEP_TYPE_SERIAL_PULL)
WIFI_LABELS = (STEP_TYPE_WIFI_SCAN, STEP_TYPE_WIFI_PING,
               STEP_TYPE_WIFI_IPERF)
BT_LABELS = (STEP_TYPE_BT_RSSI, STEP_TYPE_BT_PAIR, STEP_TYPE_BT_TONE)
OLD_SECTION_TITLES = ("SFTP", "Dialogs", "Wi-Fi tests", "Bluetooth tests")

#: a pre-rename YAML: the old Type label sits in step_type, no kind
LEGACY_SFTP_YAML = yaml.safe_dump({"fct_test_config": {
    "dut_type": "linux",
    "console": {"port": "/dev/cu.test", "test_commands": [
        {"name": "Push old", "step_type": "SFTP_put",
         "local": "load.sh", "remote": "/root/load.sh"},
        {"name": "Pull old", "step_type": "SFTP_get",
         "local": "out.json", "remote": "/root/out.json"}]},
    "wifi": {"enabled": False},
    "bluetooth": {"enabled": False},
}}, sort_keys=False)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def panel(qapp):
    p = FCTTestConfigPanel()
    p.set_values({})
    return p


def _add_menu(panel) -> QMenu:
    """The Add dropdown (top of the grouped submenu tree, M48)."""
    return panel._add_menu


def _submenu(panel, title: str) -> QMenu:
    for menu in _add_menu(panel).findChildren(QMenu):
        if menu.title() == title:
            return menu
    raise AssertionError(f"submenu {title!r} not found in the Add menu")


def _entries(panel, title: str) -> list:
    return [a.text() for a in _submenu(panel, title).actions() if a.text()]


class TestSubmenuStructure:
    def test_message_submenu_has_three_console_entries(self, panel):
        """M48: the three plain operator dialogs moved to the STANDARD
        Operation group; Message (Console) keeps the three _to_Console
        variants."""
        assert _entries(panel, "Message (Console)") == [
            STEP_TYPE_MESSAGE_OK_WAIT, STEP_TYPE_MESSAGE_YESNO_WAIT,
            STEP_TYPE_MESSAGE_GOSTOP_WAIT]

    def test_plain_message_entries_sit_in_operation(self, panel):
        for label in (STEP_TYPE_MESSAGE_OK, STEP_TYPE_MESSAGE_YESNO,
                      STEP_TYPE_MESSAGE_GOSTOP):
            assert label in panel._op_add_actions, label

    def test_ict_measurements_submenu_is_ict_only(self, panel):
        """M48: the ICT-only group stays visible but grayed in FCT."""
        ict = _submenu(panel, "ICT Measurements")
        assert not ict.isEnabled()
        assert "ICT-only step" in ict.menuAction().toolTip()
        assert len(_entries(panel, "ICT Measurements")) == 6

    def test_file_transfer_submenu_has_four_entries(self, panel):
        assert _entries(panel, "File Transfer") == list(TRANSFER_LABELS)

    def test_wifi_submenu_has_three_entries(self, panel):
        assert _entries(panel, "Wi-Fi Tests") == list(WIFI_LABELS)

    def test_bluetooth_submenu_has_three_entries(self, panel):
        assert _entries(panel, "Bluetooth Tests") == list(BT_LABELS)

    def test_operation_submenu_keeps_the_standard_ops_only(self, panel):
        entries = [t for t in panel._op_add_actions]
        # M48: 9 ops + Delay + the three plain operator messages
        assert entries[-4] == "Delay — plain wait (ms)"
        assert entries[-3:] == [STEP_TYPE_MESSAGE_OK,
                                STEP_TYPE_MESSAGE_YESNO,
                                STEP_TYPE_MESSAGE_GOSTOP]
        assert STEP_TYPE_SERIAL_PUT not in entries
        assert STEP_TYPE_SERIAL_PULL not in entries

    def test_old_flat_sections_are_gone(self, panel):
        titles = [m.title() for m in _add_menu(panel).findChildren(QMenu)]
        for old in OLD_SECTION_TITLES:
            assert old not in titles, old
        for new in ("Operation", "Message (Console)", "File Transfer",
                    "Network", "Wi-Fi Tests", "Bluetooth Tests"):
            assert new in titles, new


class TestSubmenuEntriesAddDirectly:
    def test_message_entries_add_message_rows(self, panel):
        for label in MESSAGE_LABELS:
            before = panel.cmd_table.rowCount()
            panel._add_actions[label].trigger()
            assert panel.cmd_table.rowCount() == before + 1, label
            cmd = panel._get_row_cmd(before)
            assert cmd.kind == KIND_MESSAGE, label
            assert panel.cmd_table.item(before, _COL_TYPE).text() == label

    def test_file_transfer_entries_add_transfer_rows(self, panel):
        kinds = (KIND_SFTP_PUT, KIND_SFTP_GET,
                 KIND_SERIAL_PUT, KIND_SERIAL_PULL)
        for label, kind in zip(TRANSFER_LABELS, kinds):
            before = panel.cmd_table.rowCount()
            panel._add_actions[label].trigger()
            assert panel.cmd_table.rowCount() == before + 1, label
            cmd = panel._get_row_cmd(before)
            assert cmd.kind == kind, label
            assert panel.cmd_table.item(before, _COL_TYPE).text() == label

    def test_wifi_entries_add_wifi_rows(self, panel):
        for label, subtest in zip(WIFI_LABELS, ("scan", "ping", "iperf")):
            before = panel.cmd_table.rowCount()
            panel._add_actions[label].trigger()
            cmd = panel._get_row_cmd(before)
            assert cmd.kind == KIND_WIFI_TEST, label
            assert cmd.rf_subtest == subtest, label
            assert panel.cmd_table.item(before, _COL_TYPE).text() == label

    def test_bluetooth_entries_add_bt_rows(self, panel):
        for label, subtest in zip(BT_LABELS, ("rssi", "pair", "tone")):
            before = panel.cmd_table.rowCount()
            panel._add_actions[label].trigger()
            cmd = panel._get_row_cmd(before)
            assert cmd.kind == KIND_BT_TEST, label
            assert cmd.rf_subtest == subtest, label
            assert panel.cmd_table.item(before, _COL_TYPE).text() == label


class TestSftpRenameAndLegacyLoad:
    def test_new_type_names(self):
        assert STEP_TYPE_SFTP_PUT == "SSH SFTP: Push file to DUT"
        assert STEP_TYPE_SFTP_GET == "SSH SFTP: Pull file from DUT"

    def test_legacy_labels_fold_onto_the_new_names(self):
        assert normalize_step_type_label("SFTP_put") == STEP_TYPE_SFTP_PUT
        assert normalize_step_type_label("SFTP_get") == STEP_TYPE_SFTP_GET
        assert normalize_step_type_label(STEP_TYPE_SFTP_PUT) == \
            STEP_TYPE_SFTP_PUT

    def test_legacy_yaml_displays_new_names_and_keeps_execution(self, qapp):
        """An old ``step_type: SFTP_put`` row shows the new Type name and
        still routes as an SFTP transfer."""
        panel = FCTTestConfigPanel()
        panel.set_values({"fct_test_config_yaml": LEGACY_SFTP_YAML})
        t = panel.cmd_table
        assert t.item(0, _COL_TYPE).text() == STEP_TYPE_SFTP_PUT
        assert t.item(1, _COL_TYPE).text() == STEP_TYPE_SFTP_GET
        assert panel._get_row_cmd(0).kind == KIND_SFTP_PUT
        assert panel._get_row_cmd(1).kind == KIND_SFTP_GET
        assert panel._get_row_cmd(0).remote == "/root/load.sh"
        assert panel._get_row_cmd(1).local == "out.json"
