# -*- coding: utf-8 -*-
"""M83 C5: Console_serial / Console_ssh editor rework."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTextEdit,
)

from mtkgui.engine.fct_test_config import (  # noqa: E402
    STEP_TYPE_CONSOLE_SSH,
    ConsoleCommand,
    console_command_for_label,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)

CHANNELS = [
    {"key": "ser1", "kind": "serial", "connected": True},
    {"key": "ssh1", "kind": "ssh", "connected": True},
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _panel(equipment=None) -> FCTTestConfigPanel:
    provider = (lambda: equipment) if equipment else None
    panel = FCTTestConfigPanel(console_channels_provider=lambda: CHANNELS,
                               equipment_provider=provider)
    panel.set_values({})
    return panel


def _add(panel, **fields) -> int:
    cmd = ConsoleCommand(**fields)
    panel._insert_row(cmd)
    return panel.cmd_table.rowCount() - 1


def _open(panel, row, monkeypatch, action=None,
          result=QDialog.DialogCode.Rejected):
    logs: list = []

    def fake_exec(dlg):
        dlg._test_logs = logs
        if action is not None:
            action(dlg)
        return result

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    panel.task_log.connect(lambda level, msg: logs.append((level, msg)))
    panel._edit_current_row(row)
    return logs


def _box(dlg, title):
    for box in dlg.findChildren(QGroupBox):
        if box.title() == title:
            return box
    raise AssertionError(f"group box {title!r} not found")


def _edits(widget):
    return widget.findChildren(QTextEdit) + widget.findChildren(QLineEdit)


def test_m83_enable_checkboxes_gone(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="ser1",
               send_enabled=True, send="uname -r")
    seen: list = []

    def grab(dlg):
        seen.extend(cb.text() for cb in dlg.findChildren(QCheckBox))

    _open(panel, row, monkeypatch, grab)
    assert not any("Enable WaitFor" in text for text in seen)
    assert not any("Enable Send" in text for text in seen)
    panel.deleteLater()


def test_m83_wait_and_send_blocks_are_separate_group_boxes(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="ser1",
               send_enabled=True, send="uname -r")
    titles: list = []

    def grab(dlg):
        titles.extend(box.title() for box in dlg.findChildren(QGroupBox))

    _open(panel, row, monkeypatch, grab)
    assert titles == ["Wait for", "Send / Capture"]
    panel.deleteLater()


def test_m83_empty_wait_means_no_wait_stage(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="ser1",
               wait_enabled=True, expect_pass="login:",
               send_enabled=True, send="uname -r")

    def clear(dlg):
        wait_box = _box(dlg, "Wait for")
        wait_box.findChildren(QLineEdit)[0].clear()

    _open(panel, row, monkeypatch, clear, QDialog.DialogCode.Accepted)
    cmd = panel._get_row_cmd(row)
    assert cmd.wait_enabled is False and cmd.expect_pass == ""
    assert cmd.kind == "send"
    panel.deleteLater()


def test_m83_empty_send_means_no_send_stage(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="ser1",
               send_enabled=True, send="uname -r")

    def clear(dlg):
        _box(dlg, "Send / Capture").findChildren(QTextEdit)[0].clear()

    _open(panel, row, monkeypatch, clear, QDialog.DialogCode.Accepted)
    cmd = panel._get_row_cmd(row)
    assert cmd.send_enabled is False and cmd.send == ""
    panel.deleteLater()


def test_m83_regex_checkboxes_persist_both_capture_fields(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="ser1",
               send_enabled=True, send="uname -r")

    def check(dlg):
        regexes = _box(dlg, "Send / Capture").findChildren(QCheckBox)
        for cb in regexes:
            if cb.text() == "Regex":
                cb.setChecked(True)

    _open(panel, row, monkeypatch, check, QDialog.DialogCode.Accepted)
    assert panel._get_row_cmd(row).expect_fail_is_regex is True
    panel.deleteLater()


def test_m83_legacy_unchecked_but_nonempty_warns(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="Kernel", channel="ser1",
               wait_enabled=False, expect_pass="login:",
               send_enabled=False, send="uname -r")
    logs = _open(panel, row, monkeypatch)
    joined = " ".join(msg for _level, msg in logs)
    assert "'Enable WaitFor' was off but a wait pattern is stored" in joined
    assert "'Enable Send' was off but a send payload is stored" in joined
    # the stored values are never auto-cleared
    assert panel._get_row_cmd(row).expect_pass == "login:"
    panel.deleteLater()


def test_m83_ssh_endpoint_row_is_read_only_and_resolved(qapp, monkeypatch):
    node = {"equipment": {"dut": {"ssh": {
        "host": "192.168.1.20", "port": 22, "username": "root"}}}}
    panel = _panel(node)
    row = _add(panel, kind="send", name="SSH cmd", transport="ssh",
               channel="ssh1", send_enabled=True, send="uname -r")
    texts: list = []

    def grab(dlg):
        texts.extend(lab.text() for lab in dlg.findChildren(QLabel))

    _open(panel, row, monkeypatch, grab)
    assert any(text.startswith("Remote: 192.168.1.20:22")
               and "user: root" in text for text in texts)
    panel.deleteLater()


def test_m83_ssh_new_row_default_timeout_is_30(qapp):
    cmd = console_command_for_label(STEP_TYPE_CONSOLE_SSH)
    assert cmd.timeout == 30.0
    panel = _panel()
    panel._add_row_for_label(STEP_TYPE_CONSOLE_SSH)
    assert panel._get_row_cmd(panel.cmd_table.rowCount() - 1).timeout == 30.0
    panel.deleteLater()


def test_m83_ssh_order_warning_is_warning_not_error(qapp, monkeypatch):
    panel = _panel()
    row = _add(panel, kind="send", name="SSH first", transport="ssh",
               channel="ssh1", send_enabled=True, send="uname -r")
    logs = _open(panel, row, monkeypatch,
                 result=QDialog.DialogCode.Accepted)
    joined = " ".join(msg for _level, msg in logs)
    assert "SSH depends on the DUT network being up" in joined
    assert not any(level == "ERROR" for level, _msg in logs)
    # the warning never blocks: the row was saved
    assert panel._get_row_cmd(row).channel == "ssh1"
    panel.deleteLater()
