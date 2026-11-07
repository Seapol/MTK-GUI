# -*- coding: utf-8 -*-
"""M55: step config dialogs carry ONLY test parameters.

Every hardware / connection setting (serial port / baud / parity, SSH
credentials, J-Link path, Wi-Fi SSID / interface / password, IP /
netmask / gateway) is configured on the Equipment page and referenced
at run time.  The step dialogs no longer show connection fields or
override boxes; the ``refs`` map is seeded on save (legacy overrides
still survive).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import (QApplication,  # noqa: E402
                               QComboBox, QDialog, QLabel, QLineEdit)

import yaml  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    STEP_TYPE_CONSOLE_SERIAL,
    STEP_TYPE_CONSOLE_SSH,
    STEP_TYPE_FLASH_GUI,
    STEP_TYPE_SFTP_GET,
    STEP_TYPE_SFTP_PUT,
    STEP_TYPE_WIFI_SCAN,
    console_command_for_label,
)
from mtkgui.engine.ref_resolver import effective, resolve  # noqa: E402
from mtkgui.equipment_page import GROUP_FIELDS  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


EQUIPMENT = {"equipment": {
    "dut": {"ssh": {"ip": "192.168.1.20", "username": "root",
                    "password": "pw"},
            "console": {"port": "/dev/cu.test", "baud": 115200,
                        "parity": "None"},
            "wifi": {"ssid": "MTK-DUT-AP", "interface": "wlan0"},
            "bluetooth": {"name": "MTK-DUT", "bd_addr": "AA:BB:CC:DD:EE:FF"}},
    "peripherals": {"wifi": {"ap_ssid": "MTK-AP",
                             "ap_password": "secret"},
                    "router": {"dut_ip": "192.168.1.100",
                               "netmask": "255.255.255.0",
                               "gateway": "192.168.1.1"}},
}}


def _steps(panel) -> list:
    node = yaml.safe_load(panel.values()["fct_steps_yaml"]) or {}
    return (node.get("fct") or {}).get("steps") or []


def _labels(dlg) -> list:
    return [label.text() for label in dlg.findChildren(QLabel)]


def _overrides(dlg) -> list:
    return [edit for edit in dlg.findChildren(QLineEdit)
            if "override" in edit.placeholderText()]


def _reject(_dlg):
    return QDialog.DialogCode.Rejected


def _accept(_dlg):
    return QDialog.DialogCode.Accepted


def _panel(equipment=EQUIPMENT) -> FCTTestConfigPanel:
    return FCTTestConfigPanel(equipment_provider=lambda: equipment)


# ---------------------------------------- §2.1 console serial / ssh / sftp
def test_console_serial_dialog_has_only_test_parameters(qapp, monkeypatch):
    panel = _panel()
    panel._add_row_for_label(STEP_TYPE_CONSOLE_SERIAL)
    seen = {}

    def fake_exec(dlg):
        seen["labels"] = _labels(dlg)
        seen["overrides"] = _overrides(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(0)
    for gone in ("Serial port:", "Baud rate:", "Parity:",
                 "Connection (runtime reference):"):
        assert not any(gone in t for t in seen["labels"]), gone
    assert seen["overrides"] == []
    for kept in ("Pattern:", "Wait timeout:", "SendTo:",
                 "Capture Expected:", "Capture Unexpected:", "Timeout:"):
        assert any(kept in t for t in seen["labels"]), kept


def test_console_serial_save_seeds_refs_and_keeps_legacy_overrides(
        qapp, monkeypatch):
    panel = _panel()
    cmd = console_command_for_label(STEP_TYPE_CONSOLE_SERIAL)
    cmd.overrides = {"port": "COM9"}          # legacy yaml row
    panel._insert_row(cmd)
    monkeypatch.setattr(QDialog, "exec", _accept)
    panel._edit_current_row(0)
    saved = panel._get_row_cmd(0)
    assert saved.refs == {"port": "equipment.dut.console.port",
                          "baud": "equipment.dut.console.baud",
                          "parity": "equipment.dut.console.parity"}
    assert saved.overrides == {"port": "COM9"}
    assert _steps(panel)[0]["override"] == {"port": "COM9"}


def test_ssh_and_sftp_dialogs_hide_the_login_fields(qapp, monkeypatch):
    for label, kept in ((STEP_TYPE_CONSOLE_SSH, "Pattern:"),
                        (STEP_TYPE_SFTP_PUT, "Local (Host):"),
                        (STEP_TYPE_SFTP_GET, "Remote (DUT):")):
        panel = _panel()
        panel._add_row_for_label(label)
        seen = {}

        def fake_exec(dlg, _seen=seen):
            _seen["labels"] = _labels(dlg)
            _seen["overrides"] = _overrides(dlg)
            return QDialog.DialogCode.Rejected

        monkeypatch.setattr(QDialog, "exec", fake_exec)
        panel._edit_current_row(0)
        for gone in ("SSH host:", "SSH username:", "SSH password:"):
            assert not any(gone in t for t in seen["labels"]), (label, gone)
        assert not any("ref: equipment.dut.ssh" in t
                       for t in seen["labels"]), label
        assert seen["overrides"] == []
        assert any(kept in t for t in seen["labels"]), (label, kept)
        panel.deleteLater()


def test_ssh_save_seeds_the_equipment_login_refs(qapp, monkeypatch):
    panel = _panel()
    panel._add_row_for_label(STEP_TYPE_CONSOLE_SSH)
    monkeypatch.setattr(QDialog, "exec", _accept)
    panel._edit_current_row(0)
    assert panel._get_row_cmd(0).refs == {
        "host": "equipment.dut.ssh.ip",
        "username": "equipment.dut.ssh.username",
        "password": "equipment.dut.ssh.password"}


# --------------------------------------------- §2.2 serial push / pull
def test_serial_transfer_dialog_has_no_baudrate_choice(qapp, monkeypatch):
    panel = _panel()
    panel._add_serial_transfer_row("push")
    seen = {}

    def fake_exec(dlg):
        seen["labels"] = _labels(dlg)
        seen["combos"] = dlg.findChildren(QComboBox)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(0)
    assert not any("Baudrate" in t for t in seen["labels"])
    assert seen["combos"] == []
    assert any("Local (Host PC):" in t for t in seen["labels"])
    assert any("Remote (DUT):" in t for t in seen["labels"])
    panel.deleteLater()


# ------------------------------------------------------ §2.3 Flash_GUI
def test_flash_gui_dialog_shows_the_equipment_hint_only(qapp, monkeypatch):
    panel = _panel()
    panel._add_row_for_label(STEP_TYPE_FLASH_GUI)
    seen = {}

    def fake_exec(dlg):
        seen["labels"] = _labels(dlg)
        seen["overrides"] = _overrides(dlg)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(0)
    assert any("configured in Equipment (Flash Tool/Programmer)" in t
               for t in seen["labels"])
    assert not any("ref: equipment.jlink" in t for t in seen["labels"])
    assert seen["overrides"] == []
    assert panel._get_row_cmd(0).refs["jlink"] == \
        "equipment.jlink.executable_path"
    panel.deleteLater()


# ---------------------------------------------------------- §2.4 RF rows
def test_rf_dialog_hides_every_referenced_field(qapp, monkeypatch):
    """M83/C11: referenced fields are shown READ-ONLY (never editable)."""
    panel = _panel()
    panel._add_row_for_label(STEP_TYPE_WIFI_SCAN)
    seen = {}

    def fake_exec(dlg):
        seen["labels"] = _labels(dlg)
        seen["overrides"] = _overrides(dlg)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel._edit_current_row(0)
    # referenced AP / DUT SSID: a read-only truth row, no override box
    read_only = [t for t in seen["labels"] if "Equipment ▸" in t]
    assert len(read_only) >= 2            # AP SSID + DUT SSID rows
    # the legacy per-Wi-Fi AP SSID still resolves as a fallback
    assert any("MTK-AP" in t
               and "Equipment ▸ Wired & Wireless Network" in t
               for t in read_only)
    assert any("MTK-DUT-AP" in t and "Equipment ▸ DUT" in t
               for t in read_only)
    assert not any("effective:" in t for t in seen["labels"])
    assert seen["overrides"] == []
    # step-owned fields stay editable
    assert any("AP RSSI min (dBm):" in t for t in seen["labels"])
    assert any("Scan via (host / dut_console):" in t
               for t in seen["labels"])
    assert panel._get_row_cmd(0).refs == {
        "ap_ssid": "equipment.peripherals.router.router_ap_ssid",
        "dut_ssid": "equipment.dut.wifi.ssid"}
    panel.deleteLater()


# -------------------------------------- §2.5 Equipment router fields
def test_equipment_router_group_exposes_netmask_and_gateway(qapp):
    fields = {key: default for key, _label, default
              in GROUP_FIELDS[("peripherals", "router")]}
    assert fields["netmask"] == "255.255.255.0"
    assert fields["gateway"] == ""


# --------------------------------------------- engine resolution unchanged
def test_engine_resolution_reads_equipment_and_overrides_win(qapp):
    panel = _panel()
    serial = console_command_for_label(STEP_TYPE_CONSOLE_SERIAL)
    refs = panel._default_refs(serial)
    assert resolve(refs["port"], EQUIPMENT) == "/dev/cu.test"
    assert resolve(refs["baud"], EQUIPMENT) == 115200
    # a legacy override still takes precedence at run time
    assert effective(refs["port"], "COM9", EQUIPMENT) == "COM9"
    panel.deleteLater()
