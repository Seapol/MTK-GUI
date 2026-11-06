# -*- coding: utf-8 -*-
"""M81/C4: "Config DUT Console" jump from the FCT sequence dialog."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mtkgui.engine.fct_test_config import ConsoleCommand  # noqa: E402
from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    FCTTestConfigPanel,
)
from mtkgui.main_window import MainWindow  # noqa: E402

MainWindow.__test__ = False

PORT_MSG = ("console.port must not be empty "
            "(serial console rows need a port)")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp):
    w = MainWindow(role="Supervisor", mode="Real", fixture="ATE")
    yield w
    w.close()
    w.deleteLater()


def _panel(handler=None) -> FCTTestConfigPanel:
    panel = FCTTestConfigPanel()
    panel.set_values({})
    if handler is not None:
        panel.set_console_config_handler(handler)
    return panel


def test_m81_button_sits_right_of_dut_os_combo(qapp):
    panel = _panel(lambda values: None)
    head = panel.layout().itemAt(0).layout()
    widgets = [head.itemAt(i).widget() for i in range(head.count())]
    assert panel.dut_type in widgets
    assert panel.btn_console in widgets
    assert widgets.index(panel.dut_type) < widgets.index(panel.btn_console)
    panel.deleteLater()


def test_m81_button_hidden_without_handler(qapp):
    panel = _panel()
    assert panel.btn_console.isHidden()
    panel.deleteLater()


def test_m81_button_emits_panel_values(qapp):
    got: list = []
    panel = _panel(got.append)
    panel.console_config_requested.connect(got.append)
    panel._insert_row(ConsoleCommand(kind="send", name="Kernel check",
                                     channel="ser1", send="uname -r"))
    panel.btn_console.click()
    assert got
    assert "Kernel check" in got[0]["fct_steps_yaml"]
    panel.deleteLater()


def test_m81_edits_survive_the_jump(qapp):
    got: list = []

    def handler(values):
        got.append(values)

    dlg = BlockConfigDialog("fct_build", None,
                            console_config_cb=handler)
    panel = dlg.panel
    panel._insert_row(ConsoleCommand(kind="send", name="Edited row",
                                     channel="ser1", send="uname -r"))
    panel.btn_console.click()
    assert got and "Edited row" in got[0]["fct_steps_yaml"]
    assert dlg.result() == QDialog.DialogCode.Rejected


def test_m81_jump_switches_to_workflow_page(qapp, window):
    window.yaml_build_page.console_config_requested.emit()
    assert window.tabs.currentWidget() is window.workflow_page


def test_m81_jump_focuses_console_without_adding_channel(qapp, window):
    mc = window.workflow_page.multi_console
    before = list(mc.channels)
    window.yaml_build_page.console_config_requested.emit()
    assert list(mc.channels) == before
    assert mc.isVisibleTo(window)
    assert mc.btn_add_serial.focusPolicy() != 0


def test_m81_jump_writes_no_yaml(qapp, window, tmp_path, monkeypatch):
    import mtkgui.project_config as pc

    def boom(*_a, **_k):      # pragma: no cover - must never run
        raise AssertionError("the console jump wrote a YAML")

    monkeypatch.setattr(pc, "save_config", boom)
    window._project_path = None
    window.yaml_build_page._fct_console_config_jump(
        {"fct_steps_yaml": yaml.safe_dump(
            {"fct": {"dut_type": "linux", "steps": []}})})
    assert window._project_path is None
    assert window.yaml_build_page.model.get_params("fct_build")
    assert not list(tmp_path.iterdir())


def test_m81_console_port_validation_unchanged(qapp, window):
    from mtkgui.engine.fct_test_config import FctTestConfig

    cfg = FctTestConfig.from_dict({
        "dut_type": "linux",
        "console": {"port": "", "baudrate": 115200,
                    "test_commands": [
                        {"kind": "send", "name": "Kernel check",
                         "channel": "ser1", "send": "uname -r"}]},
    })
    assert PORT_MSG in cfg.validate()
    text = yaml.safe_dump({"fct_test_config": {
        "dut_type": "linux",
        "console": {"port": "", "baudrate": 115200,
                    "test_commands": [
                        {"kind": "send", "name": "Kernel check",
                         "channel": "ser1", "send": "uname -r"}]},
    }}, sort_keys=False)
    cases, errors = window.yaml_build_page._emit_fct_sequence(
        {"fct_test_config_yaml": text})
    assert cases is None
    assert any(PORT_MSG in error for error in errors)
