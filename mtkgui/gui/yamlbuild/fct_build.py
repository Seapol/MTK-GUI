# -*- coding: utf-8 -*-
"""fct_build — Build FCT Test Work Flow Sequence (block 07, P3-B3
PREPARATION phase: DATA MODEL + INTERFACE LAYER ONLY).

This module defines the FCT sequence STRUCTURE per
docs/fct/B3-FCT-Preparation-Spec.md (§5):

* the four step types (MESSAGE_CHECK / GUI_CONFIRM / CLI_RUN /
  EXTERNAL_TOOL) and their fields;
* the configurable keyword tables (positive = pass-class, negative =
  fail-class, negative-wins rule DOCUMENTED here, APPLIED by a later
  execution phase);
* the pure skeleton generator for the fixed production spine
  ICT -> Flash FAT -> FCT body -> Flash OOBE -> teardown;
* YAML (de)serialization for standalone sequence documents;
* the mapping to the EXISTING project YAML ``fct_test_cases`` shape so
  published sequences load through the current chain unchanged
  (`project_config._fct_step_from_yaml`).

RED LINE (P3-B3): this module contains NO execution logic — no
channel I/O, no message judging, no verdict computation, no Qt.  The
execution engine is a later phase built on top of these structures.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

# ---------------------------------------------------------------------------
# vocabulary (spec §5.1)
# ---------------------------------------------------------------------------

#: the four FCT step types
STEP_MESSAGE_CHECK = "MESSAGE_CHECK"
STEP_GUI_CONFIRM = "GUI_CONFIRM"
STEP_CLI_RUN = "CLI_RUN"
STEP_EXTERNAL_TOOL = "EXTERNAL_TOOL"
STEP_TYPES = (STEP_MESSAGE_CHECK, STEP_GUI_CONFIRM, STEP_CLI_RUN,
              STEP_EXTERNAL_TOOL)

#: flash path modes (spec §3)
FLASH_GUI = "gui"      # third-party flash GUI + human confirm
FLASH_CLI = "cli"      # CLI flash + automatic keyword parse
FLASH_MODES = (FLASH_GUI, FLASH_CLI)

#: failure handling after the final retry
ON_FAIL_ABORT = "abort"
ON_FAIL_CONTINUE = "continue"
ON_FAIL_POLICIES = (ON_FAIL_ABORT, ON_FAIL_CONTINUE)

#: sequence-level configurable keyword tables (spec §5.3) — the
#: positive / negative match lists a later execution phase applies
#: (case-insensitive substring match, negative-wins rule)
DEFAULT_KEYWORD_PASS = ("pass", "passed", "success", "succeed", "ok",
                        "done", "complete")
DEFAULT_KEYWORD_FAIL = ("fail", "failed", "failure", "error", "timeout",
                        "abort", "exception", "refused")

#: module param key -> existing FCT_METHOD kind (project YAML `kind`)
_KIND_MAP = {
    STEP_MESSAGE_CHECK: "MessageOK",       # refined per channel below
    STEP_GUI_CONFIRM: "MessageGoStop",
    STEP_CLI_RUN: "SendtoCLI",
    STEP_EXTERNAL_TOOL: "MessageOK",       # refined per tool_family below
}

#: op step names reused from the engine catalog (spine anchors)
OP_FLASH_FAT = "Flash FAT Firmware"
OP_FLASH_OOBE = "Flash OOBE Firmware"
OP_POWER_OFF = "Power Off DUT"
OP_FIXTURE_UNLOCK = "Fixture Unlock"
OP_FIXTURE_RELEASE = "Fixture Release"
OP_RESET_INSTRUMENTS = "Reset Instruments"


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------
@dataclass
class FctStep:
    """One FCT sequence step (spec §5.2).  Pure data — no behavior."""

    name: str
    step_type: str
    channel: str = ""                 # console channel key ("" = dialog/host)
    command: str = ""                 # CLI_RUN / EXTERNAL_TOOL payload
    expect_pass: list = field(default_factory=list)
    expect_fail: list = field(default_factory=list)
    timeout_s: float = 30.0           # 0 = wait forever
    retries: int = 0
    on_fail: str = ON_FAIL_ABORT
    depends: list = field(default_factory=list)
    resource: str = ""                # Channel-Allocation / inventory ref
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """YAML-safe plain dict (full field set, stable order)."""
        return {
            "name": self.name, "step_type": self.step_type,
            "channel": self.channel, "command": self.command,
            "expect_pass": list(self.expect_pass),
            "expect_fail": list(self.expect_fail),
            "timeout_s": float(self.timeout_s), "retries": int(self.retries),
            "on_fail": self.on_fail, "depends": list(self.depends),
            "resource": self.resource, "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FctStep":
        """Restore a step (tolerant: missing keys keep defaults)."""
        return cls(
            name=str(data.get("name", "")),
            step_type=str(data.get("step_type", "")),
            channel=str(data.get("channel", "")),
            command=str(data.get("command", "")),
            expect_pass=[str(k) for k in (data.get("expect_pass") or [])],
            expect_fail=[str(k) for k in (data.get("expect_fail") or [])],
            timeout_s=float(data.get("timeout_s", 30.0) or 0.0),
            retries=int(data.get("retries", 0) or 0),
            on_fail=str(data.get("on_fail", ON_FAIL_ABORT)),
            depends=[str(d) for d in (data.get("depends") or [])],
            resource=str(data.get("resource", "")),
            params=dict(data.get("params") or {}),
        )

    def validate(self, sibling_names: set | None = None) -> list:
        """Spec §5.2 validation -> list of error strings (empty=ok)."""
        errors: list = []
        if not self.name.strip():
            errors.append("step name must not be empty")
        if self.step_type not in STEP_TYPES:
            errors.append(f"step {self.name!r}: unknown step_type "
                          f"{self.step_type!r}")
        if self.timeout_s < 0:
            errors.append(f"step {self.name!r}: timeout_s must be >= 0")
        if self.retries < 0:
            errors.append(f"step {self.name!r}: retries must be >= 0")
        if self.on_fail not in ON_FAIL_POLICIES:
            errors.append(f"step {self.name!r}: on_fail must be one of "
                          f"{ON_FAIL_POLICIES}")
        if self.step_type == STEP_CLI_RUN and not self.command.strip():
            errors.append(f"step {self.name!r}: {self.step_type} requires "
                          "a command")
        known = sibling_names or set()
        for dep in self.depends:
            if dep not in known:
                errors.append(f"step {self.name!r}: unknown dependency "
                              f"{dep!r}")
        return errors


@dataclass
class FctSequence:
    """One FCT sequence (spec §5.3): keyword tables + ordered steps."""

    name: str
    flash_mode: str = FLASH_GUI
    keyword_pass: list = field(
        default_factory=lambda: list(DEFAULT_KEYWORD_PASS))
    keyword_fail: list = field(
        default_factory=lambda: list(DEFAULT_KEYWORD_FAIL))
    steps: list = field(default_factory=list)   # list[FctStep]

    def validate(self) -> list:
        """Whole-sequence validation (duplicate names, per-step rules,
        dependency targets)."""
        errors: list = []
        if not self.name.strip():
            errors.append("sequence name must not be empty")
        if self.flash_mode not in FLASH_MODES:
            errors.append(f"flash_mode must be one of {FLASH_MODES}")
        names = {s.name for s in self.steps if s.name.strip()}
        if len(names) != len(self.steps):
            errors.append("duplicate step names in the sequence")
        for step in self.steps:
            errors.extend(step.validate(names))
        return errors

    # ----------------------------------------------------------- YAML IO
    def to_dict(self) -> dict:
        """The `fct_sequence:` document body."""
        return {
            "name": self.name, "flash_mode": self.flash_mode,
            "keyword_pass": list(self.keyword_pass),
            "keyword_fail": list(self.keyword_fail),
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_yaml(self) -> str:
        """Serialize as a standalone sequence document."""
        return yaml.safe_dump({"fct_sequence": self.to_dict()},
                              sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict) -> "FctSequence":
        """Restore from the `fct_sequence` body (tolerant)."""
        return cls(
            name=str((data or {}).get("name", "")),
            flash_mode=str((data or {}).get("flash_mode", FLASH_GUI)),
            keyword_pass=[str(k) for k in
                          ((data or {}).get("keyword_pass")
                           or DEFAULT_KEYWORD_PASS)],
            keyword_fail=[str(k) for k in
                          ((data or {}).get("keyword_fail")
                           or DEFAULT_KEYWORD_FAIL)],
            steps=[FctStep.from_dict(d)
                   for d in ((data or {}).get("steps") or [])],
        )

    @classmethod
    def from_yaml(cls, text: str) -> "FctSequence":
        """Parse a standalone sequence document (missing section ->
        empty-name sequence, validation reports it)."""
        data = yaml.safe_load(text or "") or {}
        return cls.from_dict(data.get("fct_sequence") or {})


# ---------------------------------------------------------------------------
# skeleton generation (spec §5.4) — PURE: data in, sequence out
# ---------------------------------------------------------------------------
def _flash_step(slot: str, flash_mode: str, channel: str,
                command: str, done_kw: str) -> FctStep:
    """The flash stage step for one path (spec §3.1 / §3.2)."""
    name = f"Flash {slot.upper()} Firmware"
    if flash_mode == FLASH_GUI:
        return FctStep(
            name=name, step_type=STEP_GUI_CONFIRM, channel="",
            timeout_s=0.0,            # wait for the operator forever
            resource="operator", params={"slot": slot})
    return FctStep(
        name=name, step_type=STEP_CLI_RUN, channel=channel,
        command=command, expect_pass=[done_kw],
        expect_fail=list(DEFAULT_KEYWORD_FAIL), resource="operator",
        params={"slot": slot})


def build_fct_sequence(name: str, flash_mode: str = FLASH_GUI,
                       channel: str = "", cli_command: str = "",
                       cli_done_keyword: str = "done",
                       body_steps: list | None = None) -> FctSequence:
    """Generate the fixed production spine (spec §5.4):

    flash stage (GUI_CONFIRM or CLI_RUN per flash_mode) -> FCT body
    (default one MESSAGE_CHECK "All Tests done.") -> OOBE flash ->
    teardown ops.  PURE — nothing here touches a channel.

    Args:
        name:             sequence title.
        flash_mode:       `gui` (human confirm) or `cli` (auto parse).
        channel:          console channel key for the CLI flash path.
        cli_command:      flash command for the CLI path.
        cli_done_keyword: positive keyword marking flash completion.
        body_steps:       optional extra FctStep list between the flash
                          stages (default: one MESSAGE_CHECK).
    """
    body = list(body_steps) if body_steps else [
        FctStep(name="All Tests done.", step_type=STEP_MESSAGE_CHECK,
                expect_pass=["done"], timeout_s=0.0),
    ]
    steps = [
        _flash_step("fat", flash_mode, channel, cli_command,
                    cli_done_keyword),
        *body,
        _flash_step("oobe", flash_mode, channel, cli_command,
                    cli_done_keyword),
        FctStep(name=OP_POWER_OFF, step_type=STEP_GUI_CONFIRM,
                timeout_s=0.0, params={"op": OP_POWER_OFF}),
        FctStep(name=OP_FIXTURE_UNLOCK, step_type=STEP_GUI_CONFIRM,
                timeout_s=0.0, params={"op": OP_FIXTURE_UNLOCK}),
        FctStep(name=OP_FIXTURE_RELEASE, step_type=STEP_GUI_CONFIRM,
                timeout_s=0.0, params={"op": OP_FIXTURE_RELEASE}),
        FctStep(name=OP_RESET_INSTRUMENTS, step_type=STEP_GUI_CONFIRM,
                timeout_s=0.0, params={"op": OP_RESET_INSTRUMENTS}),
    ]
    return FctSequence(name=name, flash_mode=flash_mode, steps=steps)


# ---------------------------------------------------------------------------
# mapping to the EXISTING project YAML fct_test_cases shape (spec §5.6)
# ---------------------------------------------------------------------------
def _kw_name(prefix: str, keywords: list) -> str:
    """Step name carrying the keywords the engine's name parser reads
    (`'<kw1> ...' (expected)` convention)."""
    kws = " ".join(keywords) if keywords else "done"
    return f"{prefix}: '{kws}' (expected)"


def to_project_fct_cases(sequence: FctSequence) -> list:
    """FctSequence -> the EXISTING `test_workflow.fct_test_cases` list
    shape (kind / name / enable / wait_ms / timeout_ms / op_params) —
    loads through `project_config._fct_step_from_yaml` unchanged."""
    cases: list = []
    for s in sequence.steps:
        kind = _KIND_MAP.get(s.step_type, "MessageOK")
        name = s.name
        op_params = None
        if s.step_type == STEP_MESSAGE_CHECK:
            if s.channel:
                kind = "CapturefromConsole"
                name = _kw_name(s.name, s.expect_pass)
            else:
                kind = "MessageOK"
        elif s.step_type == STEP_GUI_CONFIRM:
            kind = "MessageGoStop"
        elif s.step_type == STEP_CLI_RUN:
            kind = "SendtoCLI"
            name = _kw_name(f"{s.name}: '{s.command}'", s.expect_pass)
        elif s.step_type == STEP_EXTERNAL_TOOL:
            family = str(s.params.get("tool_family", "")).lower()
            kind = {"wifi": "WIFI", "bluetooth": "Bluetooth"}.get(
                family, "MessageOK")
        if s.params.get("op"):
            op_params = {"type": "op", "op": s.params["op"]}
        cases.append({
            "name": name, "kind": kind, "enable": True,
            "wait_ms": 100, "timeout_ms": int(max(s.timeout_s, 1.0)
                                              * 1000),
            **({"op_params": op_params} if op_params else {}),
        })
    return cases


def from_project_fct_cases(cases: list, name: str = "",
                           flash_mode: str = FLASH_GUI) -> FctSequence:
    """Reverse mapping (round-trip support): the legacy fct_test_cases
    list -> FctSequence.  Lossless for the fields the legacy shape
    carries; `wait_ms` granularity is preserved in params.legacy."""
    steps: list = []
    for c in (cases or []):
        kind = str(c.get("kind", "MessageOK"))
        timeout_s = max(int(c.get("timeout_ms", 5000)) / 1000.0, 0.0)
        step = FctStep(name=str(c.get("name", "")), step_type=kind,
                       timeout_s=timeout_s,
                       params={"legacy": True,
                               "legacy_wait_ms": c.get("wait_ms", 100)})
        steps.append(step)
    return FctSequence(name=name, flash_mode=flash_mode, steps=steps)
