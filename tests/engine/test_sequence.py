# -*- coding: utf-8 -*-
"""YAML config -> sequence (mtkgui.engine.sequence)."""
from __future__ import annotations

from mtkgui.engine.sequence import iter_steps, load_sequence


class TestStageFlow:
    def test_two_stage_yaml_keeps_ict_and_fct(self):
        stages = load_sequence(make_cfg())
        names = [s.name for s in stages]
        # M33: legacy flash stages are retired - ICT -> FCT only
        assert names == ["ICT", "FCT"]

    def test_explicit_four_stage_flow_filters_flash(self):
        cfg = make_cfg()
        cfg["test_workflow"]["overall_flow"] = [
            {"stage": "ICT", "enable": True},
            {"stage": "Flash FAT Firmware", "enable": True},
            {"stage": "FCT", "enable": True},
            {"stage": "Flash OOBE Firmware", "enable": False},
        ]
        stages = load_sequence(cfg)
        assert [s.name for s in stages] == ["ICT", "FCT"]
        assert [s.enable for s in stages] == [True, True]


class TestStepLoading:
    def test_ict_rows_keep_limits_and_unit(self):
        stages = load_sequence(make_cfg())
        rows = stages[0].steps
        volt = next(s for s in rows if s.kind == "Power Voltage")
        assert volt.unit == "V"
        assert volt.lo == "3.201" and volt.hi == "3.399"

    def test_fct_kind_derivation_and_params(self):
        stages = load_sequence(make_cfg())
        fct = stages[1].steps
        kinds = [s.kind for s in fct]
        assert kinds == ["SendtoCLI", "WIFI"]

    def test_legacy_wait_s_tolerated(self):
        cfg = make_cfg()
        cfg["test_workflow"]["ict_test_cases"][0]["wait_s"] = 0.5
        (step,) = [s for s in load_sequence(cfg)[0].steps
                   if s.kind == "op" and s.name == "Init Instruments"]
        assert step.wait_ms == 500

    def test_defaults_for_missing_keys(self):
        cfg = make_cfg()
        cfg["test_workflow"]["fct_test_cases"].append(
            {"name": "CapturefromCLI: 'OK' (expected)"})
        step = load_sequence(cfg)[1].steps[-1]
        assert step.kind == "CapturefromCLI"
        assert step.wait_ms == 100 and step.timeout_ms == 5000
        assert step.enable is True

    def test_as_ict_tuple_shape(self):
        stages = load_sequence(make_cfg())
        op_row = stages[0].steps[0]
        t = op_row.as_ict_tuple()
        assert t[0] == "op" and t[1] == "Init Instruments"
        assert t[6] == op_row.op_params
        meas_row = stages[0].steps[1]
        t2 = meas_row.as_ict_tuple()
        assert len(t2) == 6 and t2[3] == "—"


class TestIterSteps:
    def test_disabled_stage_and_steps_skipped(self):
        stages = load_sequence(make_cfg())
        stages[0].enable = False
        stages[1].steps[0].enable = False
        kinds = [s.kind for s in iter_steps(stages)]
        assert "SendtoCLI" not in kinds
        assert "WIFI" in kinds
        names = [s.name for s in iter_steps(stages)]
        assert "Init Instruments" not in names


def make_cfg() -> dict:
    return {
        "test_workflow": {
            "overall_flow": [
                {"stage": "ICT", "enable": True},
                {"stage": "FCT", "enable": True},
            ],
            "ict_test_cases": [
                {"name": "Init Instruments", "kind": "op",
                 "op_params": {"type": "instruments",
                               "instruments": ["DAQM"]}},
                {"name": "Power Voltage (80 pts)",
                 "kind": "Power Voltage", "unit": "V",
                 "threshold_min": "3.201", "threshold_max": "3.399"},
            ],
            "fct_test_cases": [
                {"name": "SendtoCLI: \"cmd\", 'Pass' (expected)",
                 "kind": "SendtoCLI"},
                {"name": "WIFI: scan and associate", "kind": "WIFI"},
            ],
        },
    }
