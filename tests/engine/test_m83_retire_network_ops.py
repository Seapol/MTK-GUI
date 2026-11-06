# -*- coding: utf-8 -*-
"""M83 C2: the two M41 network-setup standard operations are retired.

``Wi-Fi: Connect DUT to AP`` and ``LAN: Setup DUT Ethernet`` encoded one
NXP i.MX board's eth0 / mlan0 + wpa_supplicant + DHCP choreography.  The
general mechanism is one ``Console_serial`` row running an ``assets/``
script.  The catalog entries, plans, runner branches, menu group, editor
and template injection are gone; a legacy project YAML row is an ERROR
that names the replacement (never converted, never dropped).
"""
from __future__ import annotations

import pytest

from mtkgui.engine import host_platform as hp
from mtkgui.engine import steps
from mtkgui.engine.yaml_validation import (
    SEVERITY_ERROR,
    blocking_issues,
    validate_project_yaml,
)

WIFI = "Wi-Fi: Connect DUT to AP"
LAN = "LAN: Setup DUT Ethernet"


def _message(name: str) -> str:
    return (f"standard operation '{name}' was retired — replace it with a "
            "Console_serial row that runs the assets script")


def _wifi_doc() -> dict:
    return {"test_workflow": {"fct_test_cases": [{
        "name": WIFI, "kind": "op",
        "op_params": {"type": "op", "op": WIFI},
    }]}}


def _lan_doc() -> dict:
    return {"test_workflow": {"fct_test_cases": [{
        "name": LAN, "kind": "op",
        "op_params": {"type": "lan_setup", "iface": "eth0",
                      "mode": "dhcp"},
    }]}}


# ---------------------------------------------------------------- catalog
def test_m83_network_ops_absent_from_catalog():
    for name in (WIFI, LAN):
        assert name not in steps.OP_STEPS
    assert not hasattr(steps, "WIFI_CONNECT_OP")
    assert not hasattr(steps, "LAN_SETUP_OP")
    assert steps.op_summary({"type": "wifi_connect"}) == ""
    assert steps.op_summary({"type": "lan_setup"}) == ""
    assert steps.op_instrument_abbr({"type": "wifi_connect"}) == "DAQM"


def test_m83_network_op_types_absent():
    assert not hasattr(steps, "NETWORK_OP_TYPES")
    assert not hasattr(steps, "NETWORK_OPS")
    assert not hasattr(steps, "NETWORK_STACKS")
    assert not hasattr(steps, "wpa_conf_text")
    assert tuple(steps.RETIRED_NETWORK_OPS) == (WIFI, LAN)


def test_m83_add_menu_has_no_network_group():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])   # noqa: F841
    from mtkgui.gui.add_menu import ADD_ENTRIES, MENU_TITLES
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel

    assert "Network" not in MENU_TITLES
    assert "Network" not in [entry.group for entry in ADD_ENTRIES]
    assert WIFI not in [entry.label for entry in ADD_ENTRIES]
    assert LAN not in [entry.label for entry in ADD_ENTRIES]
    panel = FCTTestConfigPanel()
    panel.set_values({})
    assert "Network" not in panel._add_menu_groups
    assert not hasattr(panel, "_network_add_actions")


def test_m83_host_platform_has_no_wifi_connect_plan():
    assert not hasattr(hp, "wifi_connect_plan")
    assert not hasattr(hp, "lan_setup_plan")
    assert not hasattr(hp, "network_ip_commands")
    assert not hasattr(hp, "netmask_to_prefix")
    assert "wifi_connect_plan" not in hp.__all__
    assert "lan_setup_plan" not in hp.__all__


# ------------------------------------------------------------ load / error
def test_m83_legacy_lan_row_is_error():
    errors = blocking_issues(validate_project_yaml(_lan_doc()))
    matches = [issue for issue in errors if issue.message == _message(LAN)]
    assert len(matches) == 1
    assert matches[0].severity == SEVERITY_ERROR
    assert matches[0].location == "fct_test_cases[0].name"


def test_m83_legacy_wifi_connect_row_is_error():
    errors = blocking_issues(validate_project_yaml(_wifi_doc()))
    matches = [issue for issue in errors if issue.message == _message(WIFI)]
    assert len(matches) == 1
    assert matches[0].severity == SEVERITY_ERROR
    # the row is reported, never rewritten by the rule
    row = _wifi_doc()["test_workflow"]["fct_test_cases"][0]
    assert row["op_params"]["op"] == WIFI


def test_m83_templates_do_not_reference_network_ops():
    from pathlib import Path

    from mtkgui.engine import fct_templates

    source = Path(fct_templates.__file__).read_text(encoding="utf-8")
    assert WIFI not in source
    assert LAN not in source
    assert "wifi_connect" not in source
    assert "lan_setup" not in source
    for label in fct_templates.TEMPLATE_LABELS:
        text = Path(fct_templates.template_path(label)).read_text(
            encoding="utf-8")
        assert WIFI not in text, label
        assert LAN not in text, label
