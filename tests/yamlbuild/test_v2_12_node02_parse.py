# -*- coding: utf-8 -*-
"""v2-12a: node 02 (Parse nets) Route A trigger + model write-back."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from mtkgui.gui.yamlbuild.wizard_shell import YamlBuildWizard  # noqa: E402

MINIMAL_NET = """*SIGNAL* VDD_3V3
U1.1 TP1.1
*SIGNAL* CLK_24M
U1.2 TP2.1
*SIGNAL* SOC_RST0
U1.3 TP3.1
"""


def _seed_route_a(wizard, net_path) -> None:
    wizard.model.set_params("design_input", {
        "ict_route": "files",
        "net_file": str(net_path),
        "product_id": "P001",
        "part_number": "MTK12345",
    })


def test_parse_button_triggers_route_a(tmp_path):
    net_file = tmp_path / "sample.net"
    net_file.write_text(MINIMAL_NET, encoding="utf-8")
    wizard = YamlBuildWizard()
    try:
        _seed_route_a(wizard, net_file)
        wizard.goto("parse_ict")
        panel = wizard._panels["parse_ict"]
        panel.btn_parse.click()
        state = panel.state()
        assert state.rows
        assert state.gate_ok is True
    finally:
        wizard.deleteLater()


def test_parse_writes_back_parsed_nets(tmp_path):
    net_file = tmp_path / "sample.net"
    net_file.write_text(MINIMAL_NET, encoding="utf-8")
    wizard = YamlBuildWizard()
    try:
        _seed_route_a(wizard, net_file)
        wizard.goto("parse_ict")
        panel = wizard._panels["parse_ict"]
        panel.btn_parse.click()
        parsed = wizard.model.get_parsed_nets()
        assert parsed["route"] == "files"
        assert parsed["gate_ok"] is True
        assert parsed["power_nets"] == ["VDD_3V3"]
        assert parsed["clock_nets"] == ["CLK_24M"]
        assert parsed["gnd_nets"] == []
        assert parsed["other_nets"] == ["SOC_RST0"]
    finally:
        wizard.deleteLater()


def test_parsed_nets_round_trip(tmp_path):
    from mtkgui.gui.yamlbuild.model import YamlBuildModel

    net_file = tmp_path / "sample.net"
    net_file.write_text(MINIMAL_NET, encoding="utf-8")
    wizard = YamlBuildWizard()
    try:
        _seed_route_a(wizard, net_file)
        wizard.goto("parse_ict")
        panel = wizard._panels["parse_ict"]
        panel.btn_parse.click()
        state = wizard.model.to_dict()
        assert "parsed_nets" in state
        assert state["parsed_nets"]["power_nets"] == ["VDD_3V3"]
        restored = YamlBuildModel()
        restored.apply_state(state)
        assert restored.get_parsed_nets()["clock_nets"] == ["CLK_24M"]
    finally:
        wizard.deleteLater()
