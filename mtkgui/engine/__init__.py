# -*- coding: utf-8 -*-
"""Test flow engine package (mtkgui.engine).

Owns the run state machine, step definitions, result model and the
rail waveform data services - extracted from the workflow page (task
T2, interface_spec.md §3).  The UI layer consumes this package via its
public API only; it never re-implements step logic.

Public surface (consumed by mtkgui.test_workflow_page):

    TestRunner          run state machine (QObject, signals)
    StepStatus          step verdict enum (RUNNING/PASS/FAIL/ERROR/...)
    StepResult          one executed step (results.py)
    OP_STEPS            standard operation catalog (name -> params)
    FCT_METHODS         FCT test method list (YAML kind column)
    CONSOLE_KINDS       console-driving FCT methods
    steps_template      run-step list for the enabled stages
    fct_kind_from_name  FCT step name -> test method
    op_step / op_summary / is_impedance_short / display_text
    console_keyword_fallback
    generate_rails / capture_samples / rail_plot_data / write_csv
    ai_wave_review
    DURATION_S / SAMPLE_HZ (mtkgui.engine.rails)

Submodules: results, steps, rails, policies, instruments, sequence,
runner, demo (headless: python -m mtkgui.engine.demo).
"""
from .rails import (DURATION_S, SAMPLE_HZ, ai_wave_review,
                    capture_samples, generate_rails, rail_plot_data,
                    write_csv)
from .results import StepResult, StepStatus
from .runner import TestRunner
from .steps import (CONSOLE_KINDS, DIO_OPS, FCT_METHODS, FIXTURE_OPS,
                    INSTRUMENT_OPS, MESSAGE_CONSOLE_KINDS,
                    METHOD_R_GND, METHOD_R_GND_LEGACY,
                    OP_STEPS, console_keyword_fallback, display_text,
                    fct_kind_from_name, is_impedance_short,
                    is_r_gnd_method, normalize_ict_method,
                    normalize_ict_step_name, op_step, op_summary,
                    steps_template)

__all__ = [
    "CONSOLE_KINDS",
    "DIO_OPS",
    "DURATION_S",
    "FCT_METHODS",
    "FIXTURE_OPS",
    "INSTRUMENT_OPS",
    "MESSAGE_CONSOLE_KINDS",
    "METHOD_R_GND",
    "METHOD_R_GND_LEGACY",
    "OP_STEPS",
    "SAMPLE_HZ",
    "StepResult",
    "StepStatus",
    "TestRunner",
    "ai_wave_review",
    "capture_samples",
    "console_keyword_fallback",
    "display_text",
    "fct_kind_from_name",
    "generate_rails",
    "is_impedance_short",
    "is_r_gnd_method",
    "normalize_ict_method",
    "normalize_ict_step_name",
    "op_step",
    "op_summary",
    "rail_plot_data",
    "steps_template",
    "write_csv",
]
