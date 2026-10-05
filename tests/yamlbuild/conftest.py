# -*- coding: utf-8 -*-
"""Shared helpers for the Yaml Build tests."""

from __future__ import annotations

from mtkgui.gui.yamlbuild.model import YamlBuildModel

#: valid values for every required field of every module
REQUIRED_FILL = {
    "design_input": {
        "product_id": "P001", "part_number": "MTK12345",
        "core_id": "IMXRT700", "sw_version": "1.2.3",
        "hw_version": "A", "batch": "B9", "design_data": "",
    },
    "instruments": {
        "psu_visa": "TCPIP0::192.168.1.20::inst0",
        "daq_visa": "GPIB0::9::INSTR", "dmm_visa": "",
        "self_test": "true",
    },
    "parse_ict": {"netlist_file": "design.net"},
    "rails": {
        "on_voltage_v": "5.0", "current_limit_a": "1.0",
        "on_delay_ms": "100", "off_delay_ms": "200",
        "off_protection": "true",
        "sequence": "VDD:0.0\nVDDCORE:0.2",
        "voltage_tolerance_pct": "0.1",
        "impedance_min_ohm": "1.5",
        "sample_rate_hz": "1000",
        "pre_trigger_s": "-0.5", "post_trigger_s": "6.0",
        "anomaly_policy": "stop",
    },
    "clocks": {"clocks": "CLK1:32768:0.1", "stabilize_ms": "100",
               "drift_check": "true", "multi_domain_check": "false"},
    "gpios": {"groups": "LED1:PA0:out:none", "level_threshold_v": "1.5",
              "exception_check": "true"},
    "fct_parse": {"spec_file": "fct_spec.md"},
    "fct_build": {"flow_steps": "step1\nstep2",
                  "yield_threshold_pct": "98.0",
                  "exception_branch": "stop", "case_link": ""},
}


def make_filled_model(enabled: bool = True) -> YamlBuildModel:
    """Return a model with every required field filled (a valid,
    publishable configuration).

    Args:
        enabled: Enable all modules when True (default).

    Returns:
        The prepared :class:`YamlBuildModel`.
    """
    model = YamlBuildModel()
    if enabled:
        model.enable_all()
    for key, params in REQUIRED_FILL.items():
        model.set_params(key, {
            **model.get_params(key), **params})
    return model


def fill_required(model: YamlBuildModel) -> None:
    """Fill every required field of an existing model in place.

    Args:
        model: The model to complete.
    """
    for key, params in REQUIRED_FILL.items():
        model.set_params(key, {**model.get_params(key), **params})
