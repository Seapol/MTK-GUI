# -*- coding: utf-8 -*-
"""M83 C1: the "Console: Login to the DUT" step type is retired.

The row encoded one board's login choreography; the general mechanism
is 2-3 ``Console_serial`` rows.  The type / kind / Add-menu entry /
editor / builder are gone, and a project YAML still carrying the row
is reported as an ERROR that names the replacement (never converted,
never dropped).
"""
from __future__ import annotations

import copy

import pytest

from mtkgui.engine import fct_test_config as fc
from mtkgui.engine.fct_test_config import (
    CONSOLE_KINDS,
    STEP_TYPE_LABELS,
    FctTestConfig,
    build_fct_steps,
)
from mtkgui.engine.yaml_validation import (
    SEVERITY_ERROR,
    blocking_issues,
    validate_project_yaml,
)

RETIRED_TYPE = "Console: Login to the DUT"
RETIRED_KIND = "console_login"
EXPECTED = (
    "step 'Login to the DUT': step type 'Console: Login to the DUT' was "
    "retired — replace it with Console_serial rows (login prompt → send "
    "user → send password → shell prompt)")


# --------------------------------------------------------------- fixtures
def _legacy_marker_doc() -> dict:
    """A project YAML row published by an M76 build."""
    return {"test_workflow": {"fct_test_cases": [{
        "name": "Login to the DUT",
        "kind": "MessageOK",
        "op_params": {"fct_step": {
            "name": "Login to the DUT",
            "step_type": "MESSAGE_CHECK",
            "type": "interact",
            "params": {
                "fct_console": True,
                "kind": "login",
                "fct_console_login": {
                    "login_prompt": "login:", "user": "root",
                    "password": "", "shell_prompt": "#",
                    "password_prompt": "pass", "timeout_s": 30.0},
            },
        }},
    }]}}


def _legacy_cfg() -> dict:
    """A legacy ``fct_test_config`` node carrying the login row."""
    return {
        "dut_type": "linux",
        "console": {
            "port": "COM1",
            "baudrate": 115200,
            "test_commands": [{"kind": RETIRED_KIND,
                               "name": "Login to the DUT"}],
        },
    }


# ---------------------------------------------------------------- catalog
def test_m83_kind_console_login_removed_from_catalog():
    assert RETIRED_KIND not in CONSOLE_KINDS
    assert RETIRED_TYPE not in STEP_TYPE_LABELS
    assert not hasattr(fc, "KIND_CONSOLE_LOGIN")
    assert not hasattr(fc, "STEP_TYPE_CONSOLE_LOGIN")


def test_m83_add_menu_has_no_login_entry():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])   # noqa: F841
    from mtkgui.gui.add_menu import ADD_ENTRIES
    from mtkgui.gui.yamlbuild.FCTTestConfigWidget import FCTTestConfigPanel

    assert RETIRED_TYPE not in [entry.label for entry in ADD_ENTRIES]
    assert f"step:{RETIRED_TYPE}" not in [entry.key for entry in ADD_ENTRIES]
    panel = FCTTestConfigPanel()
    panel.set_values({})
    assert RETIRED_TYPE not in panel._add_actions


# ------------------------------------------------------------ load / error
def test_m83_legacy_yaml_row_is_error_naming_the_replacement():
    issues = validate_project_yaml(_legacy_marker_doc())
    errors = blocking_issues(issues)
    matches = [issue for issue in errors if issue.message == EXPECTED]
    assert len(matches) == 1
    assert matches[0].severity == SEVERITY_ERROR
    assert matches[0].location == "fct_test_cases[0].name"

    cfg = FctTestConfig.from_dict(_legacy_cfg())
    assert cfg.validate() == [EXPECTED]


def test_m83_legacy_row_is_not_converted_or_dropped():
    doc = _legacy_marker_doc()
    before = copy.deepcopy(doc)
    validate_project_yaml(doc)
    # the rule is read-only: the operator's row is untouched
    assert doc == before
    marker = doc["test_workflow"]["fct_test_cases"][0]["op_params"]["fct_step"]
    assert marker["params"]["kind"] == "login"
    assert marker["params"]["fct_console_login"]["login_prompt"] == "login:"

    cfg = FctTestConfig.from_dict(_legacy_cfg())
    assert len(cfg.console.test_commands) == 1
    assert cfg.console.test_commands[0].kind == RETIRED_KIND


def test_m83_build_without_the_type_is_unchanged():
    cfg = FctTestConfig.from_dict({
        "dut_type": "linux",
        "console": {
            "port": "COM1",
            "baudrate": 115200,
            "test_commands": [{
                "kind": "send", "name": "Console - kernel version",
                "wait_enabled": False, "send_enabled": True,
                "capture_enabled": False, "send": "uname -r",
                "timeout": 6.0},
            ],
        },
    })
    assert cfg.validate() == []
    steps = build_fct_steps(cfg, include_fallback=False,
                            include_teardown=False)
    assert len(steps) == 1
    assert steps[0].name == "Console - kernel version"
    assert steps[0].channel == "ser1"
