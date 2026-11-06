# -*- coding: utf-8 -*-
"""YAML config -> engine test sequence (mtkgui.engine.sequence).

Turns the config dict produced by the Common loader
(mtkgui.project_config.load_config - the engine never parses YAML
itself, interface_spec.md §1.1) into the staged production sequence:

    ICT -> FCT (WiFi / BT RF)

Stage layout comes from ``test_workflow.overall_flow``; legacy project
files that still list "Flash ... Firmware" stages are tolerated - the
flash stages are filtered out (M33 retired the J-Link flash ops;
flashing is now an operator-driven Flash_GUI FCT step).  When the
project defines no flow, the two production stages are used.

Legacy project files (no enable / wait_ms / kind keys) are tolerated
with the same defaults the workflow page applies.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .steps import OP_STEPS, fct_kind_from_name, op_step

# production sequence when the project defines no explicit flow
DEFAULT_FLOW: list[str] = [
    "ICT",
    "FCT",
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
    """Overall Flow stage entries: [{stage, enable}]; legacy flash
    stages are retired (M33) - the sequence is ICT -> FCT only."""
    wf = config.get("test_workflow") or {}
    raw = list(wf.get("overall_flow") or [])
    flow = [{"stage": str(e.get("stage", "")),
             "enable": bool(e.get("enable", True))}
            for e in raw if e.get("stage")]
    flow = [e for e in flow if "flash" not in e["stage"].lower()]
    if not flow:
        flow = [{"stage": name, "enable": True} for name in DEFAULT_FLOW]
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


#: M78-1: one wall-clock budget per step.  op rows fall back to 60 s,
#: every other row to 30 s (the documented defaults).
DEFAULT_OP_BUDGET_S = 60.0
DEFAULT_STEP_BUDGET_S = 30.0

#: typed sub-timeouts that used to shadow the row's own budget (M78-1
#: requirement 3).  They only apply when the row carries no explicit
#: ``timeout_s`` / ``timeout_ms``.
TYPED_TIMEOUT_FIELDS = ("rf_timeout_s", "iperf_timeout_s", "pair_timeout",
                        "rssi_timeout", "scan_timeout", "tone_timeout")


def _budget_seconds(field: str, value):
    """A raw candidate value -> seconds (None = not a usable candidate).

    ``timeout_ms`` is converted to seconds; an explicit ``0`` is a valid
    answer (0 = wait forever / unlimited, the historic dialog rule)."""
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw < 0:
        return None
    return raw / 1000.0 if field.endswith("_ms") else raw


def _find_typed(params: dict, key: str):
    """First configured value of a typed sub-timeout in any params
    layer (step params, the embedded RF config, the rendered args)."""
    if not isinstance(params, dict):
        return None
    sources = (params, params.get("fct_rf"), params.get("args"),
               (params.get("fct_step") or {}).get("params"))
    for source in sources:
        if isinstance(source, dict) and source.get(key) not in (None, ""):
            return source.get(key)
    return None


def resolve_step_budget(case: dict, op: bool = False,
                        log=None) -> tuple:
    """The ONE wall-clock budget (seconds) of one step (M78-1).

    Precedence:
    * op rows: ``op_params.timeout_s`` -> ``timeout_s`` ->
      ``timeout_ms``/1000 -> ``args.timeout_s`` -> 60
    * every other row: ``timeout_s`` -> ``timeout_ms``/1000 -> a typed
      sub-timeout (``rf_timeout_s`` / ``iperf_timeout_s`` /
      ``pair_timeout`` / ``rssi_timeout`` / ...) -> 30

    When two candidates are present and disagree by more than 10 %, ONE
    warning names both fields and the winner (a conflict is never
    resolved silently).  Returns ``(budget_s, source, warning)``;
    ``log`` (optional callable) receives the warning."""
    case = dict(case or {})
    op_params = dict(case.get("op_params") or {})
    params = dict(case.get("params") or {})
    args = dict(params.get("args") or case.get("args") or {})
    items: list = []
    if op:
        items = [("op_params.timeout_s", op_params.get("timeout_s")),
                 ("timeout_s", case.get("timeout_s")),
                 ("timeout_ms", case.get("timeout_ms")),
                 ("args.timeout_s", args.get("timeout_s"))]
    else:
        items = [("timeout_s", case.get("timeout_s")),
                 ("timeout_ms", case.get("timeout_ms"))]
        for key in TYPED_TIMEOUT_FIELDS:
            value = _find_typed({**params, "fct_step": case},
                                key)
            if value is None:
                value = case.get(key)
            if value is not None:
                items.append((key, value))
    present: list = []
    for field, value in items:
        seconds = _budget_seconds(field, value)
        if seconds is not None:
            present.append((field, seconds))
    # an explicit 0 (= wait forever) only wins when NOTHING positive is
    # declared; a positive row budget always outranks a 0 marker default
    positive = [item for item in present if item[1] > 0]
    if positive:
        present = positive
    default = DEFAULT_OP_BUDGET_S if op else DEFAULT_STEP_BUDGET_S
    if not present:
        return default, "default", ""
    winner_field, winner_s = present[0]
    warning = ""
    if winner_s > 0:
        for field, seconds in present[1:]:
            if seconds <= 0:
                continue
            if abs(seconds - winner_s) > winner_s * 0.1:
                warning = (f"WARNING: conflicting timeout fields - "
                           f"{winner_field}={winner_s:g}s wins over "
                           f"{field}={seconds:g}s (>10% difference)")
                break
    if warning and callable(log):
        log(warning)
    return winner_s, winner_field, warning


def _timeout_ms(case: dict, op: bool = False) -> int:
    """Row timeout in milliseconds from the single budget resolver
    (M78-1: the old ``min(99999, ...)`` silent clamp is gone - a
    declared 600000 ms budget reaches the step unchanged)."""
    budget, _source, _warning = resolve_step_budget(case, op=op)
    if budget <= 0:
        return 0
    # 0.1 ms resolution; no artificial ceiling (D1)
    return int(round(budget * 1000))


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
                wait_ms=_wait_ms(case), timeout_ms=_timeout_ms(case, op=True),
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
            wait_ms=_wait_ms(case),
            timeout_ms=_timeout_ms(case, op=kind == "op"),
            enable=bool(case.get("enable", True))))
    return steps


def load_sequence(config: dict) -> list[SequenceStage]:
    """Config dict (Common loader output) -> staged test sequence."""
    stages: list[SequenceStage] = []
    for entry in _stage_flow(config):
        name = entry["stage"]
        stage = SequenceStage(name, enable=entry["enable"])
        low = name.lower()
        if "ict" in low:
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
