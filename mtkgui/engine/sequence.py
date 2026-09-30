# -*- coding: utf-8 -*-
"""YAML config -> engine test sequence (mtkgui.engine.sequence).

Turns the config dict produced by the Common loader
(mtkgui.project_config.load_config - the engine never parses YAML
itself, interface_spec.md §1.1) into the staged production sequence:

    ICT -> Flash FAT Firmware -> FCT (WiFi / BT RF) -> Flash OOBE Firmware

Stage layout comes from ``test_workflow.overall_flow``; when the
project defines no flash stages (new-schema 2-stage files), the flash
stages are inserted at their production positions.  Stage names that
contain "flash" map to J-Link firmware-flash op steps whose image path
comes from ``firmware.<slot>_image`` in the project YAML (no default
path - a missing image is a config error at execution time).

Legacy project files (no enable / wait_ms / kind keys) are tolerated
with the same defaults the workflow page applies.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .steps import OP_STEPS, fct_kind_from_name, op_step

# production sequence when the project defines no explicit flow
DEFAULT_FLOW: list[str] = [
    "ICT",
    "Flash FAT Firmware",
    "FCT",
    "Flash OOBE Firmware",
]


@dataclass
class TestStep:
    """One sequence step loaded from YAML (engine-neutral form)."""

    stage: str
    kind: str                       # "op" | ICT kind | FCT method
    name: str
    unit: str = "—"
    lo: str = "—"
    hi: str = "—"
    op_params: dict | None = None
    wait_ms: int = 100
    timeout_ms: int = 5000
    enable: bool = True

    def as_ict_tuple(self) -> tuple:
        """ICT row tuple shape used by the page / runner."""
        base = [self.kind, self.name, self.unit, "—", self.lo, self.hi]
        if self.kind == "op":
            base.append(dict(self.op_params or {}))
        return tuple(base)


@dataclass
class SequenceStage:
    """One Overall Flow stage with its ordered steps."""

    name: str
    enable: bool = True
    steps: list[TestStep] = field(default_factory=list)


def _stage_flow(config: dict) -> list[dict]:
    """Overall Flow stage entries: [{stage, enable}]; synthesizes the
    production 4-stage flow when the project has no flash stage."""
    wf = config.get("test_workflow") or {}
    raw = list(wf.get("overall_flow") or [])
    flow = [{"stage": str(e.get("stage", "")),
             "enable": bool(e.get("enable", True))}
            for e in raw if e.get("stage")]
    if not any("flash" in e["stage"].lower() for e in flow):
        # insert the firmware-flash stages at their production spots
        named = {e["stage"].strip().lower(): e for e in flow}
        merged: list[dict] = []
        for name in DEFAULT_FLOW:
            key = name.lower()
            if key in named:
                merged.append(named[key])
            elif "flash" in key:
                merged.append({"stage": name, "enable": True})
            elif "ict" in key and "ict" in named:
                merged.append(named["ict"])
            elif "fct" in key and "fct" in named:
                merged.append(named["fct"])
        flow = merged
    return flow


def _wait_ms(case: dict) -> int:
    """Per-step wait: wait_ms (new schema) or wait_s * 1000 (legacy)."""
    raw = case.get("wait_ms")
    if raw is not None:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    raw = case.get("wait_s")
    if raw is not None:
        try:
            return max(0, int(float(raw) * 1000))
        except (TypeError, ValueError):
            pass
    return 100


def _timeout_ms(case: dict) -> int:
    try:
        return max(1000, min(99999, int(case.get("timeout_ms", 5000))))
    except (TypeError, ValueError):
        return 5000


def _ict_steps(config: dict, stage: str) -> list[TestStep]:
    """ict_test_cases -> TestStep list (new + legacy rows)."""
    wf = config.get("test_workflow") or {}
    steps: list[TestStep] = []
    for case in wf.get("ict_test_cases") or []:
        kind = str(case.get("kind", "test"))
        name = str(case.get("name", ""))
        if kind == "op":
            params = dict(case.get("op_params")
                          or OP_STEPS.get(name, {}))
            steps.append(TestStep(
                stage, "op", name, op_params=params,
                wait_ms=_wait_ms(case), timeout_ms=_timeout_ms(case),
                enable=bool(case.get("enable", True))))
            continue
        steps.append(TestStep(
            stage, kind, name,
            unit=str(case.get("unit", "—")),
            lo=str(case.get("threshold_min", "—")),
            hi=str(case.get("threshold_max", "—")),
            wait_ms=_wait_ms(case), timeout_ms=_timeout_ms(case),
            enable=bool(case.get("enable", True))))
    return steps


def _fct_steps(config: dict, stage: str) -> list[TestStep]:
    """fct_test_cases -> TestStep list (kind derived for legacy rows)."""
    wf = config.get("test_workflow") or {}
    steps: list[TestStep] = []
    for case in wf.get("fct_test_cases") or []:
        name = str(case.get("name", ""))
        kind = str(case.get("kind") or fct_kind_from_name(name))
        params = (dict(case.get("op_params"))
                  if case.get("op_params") else None)
        steps.append(TestStep(
            stage, kind, name, op_params=params,
            wait_ms=_wait_ms(case), timeout_ms=_timeout_ms(case),
            enable=bool(case.get("enable", True))))
    return steps


def _flash_steps(config: dict, stage: str) -> list[TestStep]:
    """One J-Link flash op step for a 'Flash ... Firmware' stage."""
    slot = "oobe" if "oobe" in stage.lower() else "fat"
    image = ((config.get("firmware") or {}).get(f"{slot}_image"))
    params: dict = {"type": "flash", "slot": slot}
    if image:
        params["image"] = str(image)
    name = f"Flash {slot.upper()} Firmware"
    return [TestStep(stage, "op", name, op_params=params,
                     wait_ms=100, timeout_ms=5000, enable=True)]


def load_sequence(config: dict) -> list[SequenceStage]:
    """Config dict (Common loader output) -> staged test sequence."""
    stages: list[SequenceStage] = []
    for entry in _stage_flow(config):
        name = entry["stage"]
        stage = SequenceStage(name, enable=entry["enable"])
        low = name.lower()
        if "flash" in low:
            stage.steps = _flash_steps(config, name)
        elif "ict" in low:
            stage.steps = _ict_steps(config, name)
        elif "fct" in low:
            stage.steps = _fct_steps(config, name)
        stages.append(stage)
    return stages


def iter_steps(stages: list[SequenceStage]):
    """Yield the enabled steps of the enabled stages in flow order."""
    for stage in stages:
        if not stage.enable:
            continue
        for step in stage.steps:
            if step.enable:
                yield step


# re-export for callers that build demo rows straight from the catalog
__all__ = ["DEFAULT_FLOW", "SequenceStage", "TestStep",
           "iter_steps", "load_sequence", "op_step"]
