# -*- coding: utf-8 -*-
"""M72: TC-02 Stage C BLOCKERs + secondary fixes.

BLOCKER 1  ``_emit_fct_steps`` keeps the user row order (an Operation in
           the middle stays there; fct_steps / fct_steps_yaml 1:1).
BLOCKER 2  retired with the network-setup operations (M83).
Secondary  configurable SN format, LF-only console ending, _TonePreview
           ``finished`` signal, virtual DUT interface mlan0, no injected
           BT piscan step.
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import yaml  # noqa: E402
from PySide6.QtGui import QValidator  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    BluetoothCfg,
    FctTestConfig,
    build_fct_steps,
)
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    _TonePreview,
)
from mtkgui.test_workflow_page import TestWorkFlowPage  # noqa: E402
from mtkgui.virtual_dut import DEFAULT_PROFILE  # noqa: E402
from mtkgui.widgets.multi_console import MultiConsoleWidget  # noqa: E402
from mtkgui.widgets.send_panel import SendPanel  # noqa: E402
from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def page(qapp):
    widget = YamlBuildPage()
    yield widget
    widget.deleteLater()


# ------------------------------------------------------ BLOCKER 1 order
def _ordered_steps() -> list:
    return [
        {"type": "Delay", "name": "Delay - boot wait", "wait_ms": 800},
        {"type": "Operation", "name": "Power On DUT",
         "op_kind": "op",
         "op_params": {"type": "op", "op": "Power On DUT"}},
        {"type": "Console_serial", "name": "Kernel check",
         "override": {"port": "COM1"}, "send": "uname -r",
         "send_enabled": True, "wait_enabled": False,
         "capture_enabled": True, "capture_expected": "Linux",
         "timeout": 6.0},
        {"type": "Operation", "name": "Power Off DUT", "op_kind": "op",
         "op_params": {"type": "op", "op": "Power Off DUT"}},
    ]


def test_operation_keeps_its_user_position_after_apply(page):
    steps = _ordered_steps()
    cases, errors = page._emit_fct_sequence(
        {"fct_steps_yaml": yaml.safe_dump(
            {"fct": {"dut_type": "linux", "steps": steps}},
            sort_keys=False)})
    assert errors == []
    names = [c["name"] for c in cases]
    # the row order exactly as configured - the old code put both
    # Operation rows in front of the Delay / Console rows
    assert names == [s["name"] for s in steps]
    assert names[0] != "Power On DUT"


def test_emitted_steps_and_source_region_are_one_to_one(page):
    steps = _ordered_steps()
    cases, errors = page._emit_fct_sequence(
        {"fct_steps_yaml": yaml.safe_dump(
            {"fct": {"dut_type": "linux", "steps": steps}},
            sort_keys=False)})
    assert errors == []
    # no auto-add / auto-delete: one emitted case per user row
    assert len(cases) == len(steps)
    op_cases = [c for c in cases if "fct_step" not in (c["op_params"] or {})]
    generated = [c for c in cases if "fct_step" in (c["op_params"] or {})]
    assert len(op_cases) == 2          # the two Operation rows
    # every generated case carries its own source step (lossless
    # round trip between the two YAML step regions)
    for case in generated:
        assert isinstance(case["op_params"]["fct_step"], dict)


# ------------------------------------------------ #5 configurable SN
def test_serial_number_accepts_directive_style_values(qapp):
    page = TestWorkFlowPage()
    try:
        validator = page.serial_edit.validator()
        for value in ("FRDM-IMX93-1104", "FS1234567890", "A1-B2"):
            state, _text, _pos = validator.validate(value, 0)
            assert state == QValidator.State.Acceptable, value
        state, _text, _pos = validator.validate("FRDM IMX93", 0)
        assert state == QValidator.State.Invalid
    finally:
        page.deleteLater()


# --------------------------------------------------- #7 LF-only mode
def test_send_panel_has_an_explicit_lf_only_mode(qapp):
    panel = SendPanel("ser1", "Send")
    try:
        assert panel.line_ending() == "crlf"        # default unchanged
        panel.check_lf.setChecked(True)
        assert not panel.check_crlf.isChecked()     # mutually exclusive
        assert panel.line_ending() == "lf"
        panel.check_crlf.setChecked(True)
        assert not panel.check_lf.isChecked()
        panel.check_crlf.setChecked(False)
        assert panel.line_ending() == ""
    finally:
        panel.deleteLater()


def test_encode_payload_supports_lf_and_legacy_bool():
    assert MultiConsoleWidget.encode_payload("AT", False, "lf") == b"AT\n"
    assert MultiConsoleWidget.encode_payload("AT", False, "crlf") \
        == b"AT\r\n"
    assert MultiConsoleWidget.encode_payload("AT", False, "") == b"AT"
    # legacy bool callers keep working
    assert MultiConsoleWidget.encode_payload("AT", False, True) \
        == b"AT\r\n"
    assert MultiConsoleWidget.encode_payload("41 54", True, False) == b"AT"


# --------------------------------------------- #8 _TonePreview.finished
def test_tone_preview_exposes_a_finished_signal(qapp):
    preview = _TonePreview()
    seen = []
    preview.finished.connect(lambda: seen.append(True))
    preview._timer.start()              # simulate a running preview
    preview.stop()
    assert seen == [True]


# ------------------------------------------------ #10 virtual DUT mlan0
def test_virtual_dut_reports_mlan0():
    text = " ".join(DEFAULT_PROFILE["rules"][0]["response"])
    assert "wlan0" not in text
    assert "mlan0" in text


# ----------------------------------------------- #6 no injected piscan
def test_engine_injects_no_bt_piscan_step():
    cfg = FctTestConfig(
        dut_type="linux",
        bluetooth=BluetoothCfg(rssi_enabled=True,
                               expected_name="DUT-BT"))
    names = [s.name for s in build_fct_steps(cfg)]
    assert names == ["Bluetooth RSSI"]
