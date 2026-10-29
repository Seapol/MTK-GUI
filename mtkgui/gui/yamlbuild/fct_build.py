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

import re
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

# ---------------------------------------------------------------------------
# unified step model (owner-approved 2026-10-28)
# ---------------------------------------------------------------------------
#: every step carries ONE explicit kind:
#:   interact = serial/ssh Wait -> Send -> Capture step
#:   action   = built-in action with per-step configurable args
#:   dialog   = explicit operator dialog (only these pop a dialog)
TYPE_INTERACT = "interact"
TYPE_ACTION = "action"
TYPE_DIALOG = "dialog"
STEP_KINDS = (TYPE_INTERACT, TYPE_ACTION, TYPE_DIALOG)

#: built-in actions and their DEFAULT args.  A step overrides any subset
#: in ``params["args"]``; a missing arg keeps the historic behaviour, so
#: every old YAML runs exactly as before (fully backward compatible).
ACTION_DEFAULTS = {
    "sftp_get": {"remove_remote_file": True, "create_local_dir": True,
                 "timeout_s": 30.0, "retries": 0},
    "sftp_put": {"timeout_s": 30.0, "retries": 0},
    "host_cli": {"timeout_s": 30.0, "retries": 0, "cwd": "", "shell": ""},
    "power_on": {"timeout_s": 0.0},
    "power_off": {"timeout_s": 0.0},
    "dialog": {"style": "ok", "send_yes": "y", "send_no": "n",
               "answer_timeout_s": 0.0},
    "serial_push": {"timeout_s": 300.0},
    "rf": {"timeout_s": 30.0},
    "op": {"timeout_s": 0.0},
}
ACTION_NAMES = tuple(ACTION_DEFAULTS)

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
        """YAML-safe plain dict (full field set, stable order).

        Carries the EXPLICIT unified ``type`` (interact / action /
        dialog) plus the action name and its resolved args for action
        steps.  ``step_type`` stays for backward compatibility with
        markers published before the unified model.
        """
        kind = step_kind(self)
        out = {
            "name": self.name, "step_type": self.step_type,
            "type": kind, "channel": self.channel,
            "command": self.command,
            "expect_pass": list(self.expect_pass),
            "expect_fail": list(self.expect_fail),
            "timeout_s": float(self.timeout_s), "retries": int(self.retries),
            "on_fail": self.on_fail, "depends": list(self.depends),
            "resource": self.resource, "params": dict(self.params),
        }
        if kind == TYPE_ACTION:
            out["action"] = action_name(self)
            out["args"] = action_args(self)
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "FctStep":
        """Restore a step (tolerant: missing keys keep defaults).

        Accepts both the legacy dicts (``step_type`` only) and the
        unified ones (``type`` + ``action`` + ``args``); the unified
        values are folded back into the legacy ``step_type`` the
        executor routes on, and the args into ``params['args']``.
        """
        data = dict(data or {})
        kind = str(data.get("type", "") or "")
        params = dict(data.get("params") or {})
        if kind == TYPE_ACTION and data.get("action"):
            params.setdefault("action", str(data["action"]))
            args = data.get("args")
            if isinstance(args, dict) and args:
                params["args"] = dict(args)
        step_type = str(data.get("step_type", ""))
        if kind:
            step_type = _legacy_type_for(kind, step_type, params)
        return cls(
            name=str(data.get("name", "")),
            step_type=step_type,
            channel=str(data.get("channel", "")),
            command=str(data.get("command", "")),
            expect_pass=[str(k) for k in (data.get("expect_pass") or [])],
            expect_fail=[str(k) for k in (data.get("expect_fail") or [])],
            timeout_s=float(data.get("timeout_s", 30.0) or 0.0),
            retries=int(data.get("retries", 0) or 0),
            on_fail=str(data.get("on_fail", ON_FAIL_ABORT)),
            depends=[str(d) for d in (data.get("depends") or [])],
            resource=str(data.get("resource", "")),
            params=params,
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


# ---------------------------------------------------------------------------
# unified model helpers (type / action / args / legacy normalization)
# ---------------------------------------------------------------------------
def step_kind(step) -> str:
    """The explicit unified kind of one step: interact / action / dialog.

    `dialog` wins first (an operator popup), then any built-in action
    payload, then the legacy GUI-confirm type; everything else is a
    normal serial/ssh ``interact`` step."""
    p = dict(getattr(step, "params", None) or {})
    if p.get("console_dialog") or p.get("style") is not None:
        return TYPE_DIALOG
    if (p.get("action") in ("sftp_get", "sftp_put")
            or p.get("kind") in ("sftp_get", "sftp_put")
            or p.get("fct_host_cmd") is not None
            or p.get("fct_serial_push") is not None
            or p.get("fct_rf") is not None
            or p.get("fct_wifi_iperf") is not None
            or p.get("fct_bt_l2ping") is not None
            or p.get("op")):
        return TYPE_ACTION
    if getattr(step, "step_type", "") == STEP_GUI_CONFIRM:
        return TYPE_DIALOG
    return TYPE_INTERACT


def action_name(step) -> str:
    """The registry name of an action step (''-free fallback: 'op')."""
    p = dict(getattr(step, "params", None) or {})
    action = str(p.get("action", "") or "")
    if action in ("sftp_get", "sftp_put"):
        return action
    if p.get("fct_host_cmd") is not None:
        return "host_cli"
    if p.get("fct_serial_push") is not None:
        return "serial_push"
    if (p.get("fct_rf") is not None or p.get("fct_wifi_iperf") is not None
            or p.get("fct_bt_l2ping") is not None):
        return "rf"
    op = str(p.get("op", "") or "")
    if op:
        low = op.lower()
        if "power on" in low:
            return "power_on"
        if "power off" in low:
            return "power_off"
        return "op"
    if p.get("console_dialog") or p.get("style") is not None:
        return "dialog"
    return action or "op"


def action_args(step) -> dict:
    """The EFFECTIVE args of an action step: registry defaults overlaid
    by ``params['args']``.

    ``timeout_s`` has ONE source - the row's own ``timeout_s`` field.  A
    per-step ``params['args']['timeout_s']`` wins when set; otherwise a
    positive row timeout overrides any registry default (M27 P10: the
    visible Timeout column == the executed timeout).  ``retries`` still
    falls back to the step's own field."""
    args = dict(ACTION_DEFAULTS.get(action_name(step)) or {})
    override = (getattr(step, "params", None) or {}).get("args")
    if isinstance(override, dict):
        args.update(override)
    row_to = float(getattr(step, "timeout_s", 0.0) or 0.0)
    has_override = isinstance(override, dict) and bool(
        override.get("timeout_s"))
    if row_to > 0 and not has_override:
        args["timeout_s"] = row_to
    if args.get("retries") in (None, 0):
        args["retries"] = int(getattr(step, "retries", 0) or 0)
    return args


def _legacy_type_for(kind: str, step_type: str, params: dict) -> str:
    """Fold a unified ``type`` back into the executor's step_type.

    A marker that already carries a valid legacy ``step_type`` keeps it
    (that is the executor's routing key), so re-loading a unified dict
    never changes execution."""
    if step_type in STEP_TYPES:
        return step_type
    if kind == TYPE_DIALOG:
        return STEP_GUI_CONFIRM
    if kind == TYPE_ACTION:
        if params.get("action") in ("sftp_get", "sftp_put"):
            return STEP_MESSAGE_CHECK
        return STEP_EXTERNAL_TOOL
    return STEP_MESSAGE_CHECK


#: the legacy emitter baked ``": '<pattern>' (expected)"`` into step
#: names (e.g. ``"Console login: 'done' (expected)"``).  The pattern now
#: lives in the step params, so the suffix is pure noise and is stripped
#: on normalize (M27 P2 - one-time rename; idempotent).
_LEGACY_NAME_SUFFIX = re.compile(r":\s*'[^']*'\s*\(expected\)\s*$")


def strip_legacy_name_suffix(name: str) -> str:
    """Drop the legacy ``": '<pattern>' (expected)"`` suffix from a step
    (or case) name.  Idempotent: a clean name is returned unchanged."""
    return _LEGACY_NAME_SUFFIX.sub("", str(name or "")).rstrip()


def normalize_fct_steps(steps: list) -> list:
    """Normalize LEGACY steps into the unified model, losslessly.

    * a ``'<name> (wait)'`` pre-step is merged into the following step
      (its pattern / timeout become that step's wait stage) so ONE row
      per test survives;
    * an implicit ``params.confirm_enabled`` becomes an explicit
      ``dialog`` step placed right after it (nothing pops implicitly);
    * exact duplicates are dropped, order preserved (M22 guarantee).
    """
    merged: list = []
    pending = None
    for step in list(steps or []):
        # M27 P2: the old emitter baked the expected pattern into the
        # name - drop that suffix BEFORE the "(wait)" check so both a
        # bare "X (wait)" and "X (wait): 'kw' (expected)" are recognised
        step.name = strip_legacy_name_suffix(getattr(step, "name", ""))
        if str(step.name).endswith(" (wait)"):
            pending = step
            continue
        if pending is not None:
            wp = dict(getattr(pending, "params", None) or {})
            p = dict(getattr(step, "params", None) or {})
            p.setdefault("wait_enabled", True)
            p.setdefault("wait_pattern", str(wp.get("expect_pass_re", "") or ""))
            p.setdefault("wait_timeout",
                         float(getattr(pending, "timeout_s", 10.0) or 10.0))
            step.params = p
            pending = None
        merged.append(step)
    if pending is not None:
        p = dict(getattr(pending, "params", None) or {})
        p["kind"] = "wait"
        pending.name = str(pending.name)[:-len(" (wait)")] or pending.name
        pending.params = p
        merged.append(pending)
    out: list = []
    for step in merged:
        p = dict(getattr(step, "params", None) or {})
        if p.pop("confirm_enabled", False):
            step.params = p
            out.append(step)
            out.append(FctStep(
                name=f"Confirm: {step.name}",
                step_type=STEP_GUI_CONFIRM,
                timeout_s=0.0,
                params={"style": "yesno", "console_dialog": True,
                        "message": str(p.get("confirm_message") or step.name),
                        "wait_pattern": "", "wait_timeout": 0.0,
                        "message_timeout_s": 4.0}))
            continue
        out.append(step)
    return dedupe_steps(out)


def dedupe_steps(steps: list) -> list:
    """Drop EXACT duplicates (name + type + params), first one wins."""
    seen: set = set()
    out: list = []
    for step in steps or []:
        key = (getattr(step, "name", ""), step_kind(step),
               repr(sorted((getattr(step, "params", None) or {}).items())))
        if key in seen:
            continue
        seen.add(key)
        out.append(step)
    return out


def normalize_fct_cases(cases: list) -> list:
    """Normalize a legacy ``fct_test_cases`` list, one row per step.

    Rows carrying an ``op_params.fct_step`` marker are re-written from
    their normalized step: a ``(wait)`` case merges into the next marker
    case (so one FCT test = one row), an implicit ``confirm_enabled``
    marker gains an explicit dialog row right after it, and exact
    duplicates are dropped.  Rows without a marker (manual standard ops)
    pass through untouched."""
    cases = list(cases or [])
    if not any(((c.get("op_params") or {}) if isinstance(c, dict) else {})
               .get("fct_step") for c in cases):
        return cases
    out: list = []
    pending = None                    # (case, step) of a '(wait)' row
    seen: set = set()
    for c in cases:
        marker = ((c.get("op_params") or {}) if isinstance(c, dict) else {})
        raw = marker.get("fct_step") if isinstance(marker, dict) else None
        if not (isinstance(raw, dict) and raw):
            # manual row (no marker): keep it, but still strip the
            # legacy name suffix (op / teardown rows baked the same way)
            if isinstance(c, dict) and ": '" in str(c.get("name", "")) \
                    and "(expected)" in str(c.get("name", "")):
                c2 = dict(c)
                c2["name"] = strip_legacy_name_suffix(
                    str(c.get("name", "")))
                out.append(c2)
            else:
                out.append(c)
            continue
        step = FctStep.from_dict(raw)
        # M27 P2: strip the legacy suffix before the "(wait)" check (the
        # marker name is normally already clean, but be defensive)
        step.name = strip_legacy_name_suffix(step.name)
        if str(step.name).endswith(" (wait)"):
            pending = (c, step)
            continue                  # merged into the next marker row
        if pending is not None:
            wp = dict(pending[1].params or {})
            p = dict(step.params or {})
            p.setdefault("wait_enabled", True)
            p.setdefault("wait_pattern",
                         str(wp.get("expect_pass_re", "") or ""))
            p.setdefault("wait_timeout",
                         float(pending[1].timeout_s or 10.0))
            step.params = p
            pending = None
        dlg = None
        p = dict(step.params or {})
        if p.pop("confirm_enabled", False):
            step.params = p
            dlg = FctStep(
                name=f"Confirm: {step.name}", step_type=STEP_GUI_CONFIRM,
                timeout_s=0.0,
                params={"style": "yesno", "console_dialog": True,
                        "message": str(p.get("confirm_message") or step.name),
                        "wait_pattern": "", "wait_timeout": 0.0,
                        "message_timeout_s": 4.0})
        rows = [step] + ([dlg] if dlg is not None else [])
        for s in rows:
            key = (s.name, step_kind(s),
                   repr(sorted((s.params or {}).items())))
            if key in seen:
                continue
            seen.add(key)
            c2 = dict(c)
            c2["op_params"] = dict(marker)
            c2["op_params"]["fct_step"] = s.to_dict()
            c2["name"] = s.name           # one row = one step name
            out.append(c2)
    if pending is not None:
        # trailing '(wait)' row: keep it as a stand-alone wait step
        _c, step = pending
        p = dict(step.params or {})
        p["kind"] = "wait"
        step.name = str(step.name)[:-len(" (wait)")] or step.name
        step.params = p
        c2 = dict(_c)
        c2["op_params"] = dict(_c.get("op_params") or {})
        c2["op_params"]["fct_step"] = step.to_dict()
        c2["name"] = step.name
        out.append(c2)
    return out


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
            steps=normalize_fct_steps(
                [FctStep.from_dict(d)
                 for d in ((data or {}).get("steps") or [])]),
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
def to_project_fct_cases(sequence: FctSequence) -> list:
    """FctSequence -> the EXISTING `test_workflow.fct_test_cases` list
    shape (kind / name / enable / wait_ms / timeout_ms / op_params) —
    loads through `project_config._fct_step_from_yaml` unchanged."""
    cases: list = []
    for s in sequence.steps:
        kind = _KIND_MAP.get(s.step_type, "MessageOK")
        # the row name IS the step name (unified model): the keywords
        # travel in the step marker, never in the visible name
        name = s.name
        op_params = None
        if s.step_type == STEP_MESSAGE_CHECK:
            if s.channel:
                kind = "CapturefromConsole"
            else:
                kind = "MessageOK"
        elif s.step_type == STEP_GUI_CONFIRM:
            # dialog style travels in params ("style"): ok -> MessageOK,
            # yesno -> MessageYesNo, everything else -> MessageGoStop.
            # A Console-domain operator dialog (params.console_dialog,
            # user direction 2026-10-18) keeps the "*toConsole" kind so
            # the row waits the expected console message first.
            style = str(s.params.get("style") or "")
            if s.params.get("console_dialog"):
                kind = {"ok": "MessageOKtoConsole",
                        "yesno": "MessageYesNotoConsole"}.get(
                    style, "MessageGoStoptoConsole")
            else:
                kind = {"ok": "MessageOK", "yesno": "MessageYesNo"}.get(
                    style, "MessageGoStop")
        elif s.step_type == STEP_CLI_RUN:
            kind = "SendtoCLI"
        elif s.step_type == STEP_EXTERNAL_TOOL:
            family = str(s.params.get("tool_family", "")).lower()
            if s.params.get("fct_host_cmd") is not None:
                kind = "SendtoCLI"          # host CLI row (test PC shell)
            else:
                kind = {"wifi": "WIFI", "bluetooth": "Bluetooth"}.get(
                    family, "MessageOK")
        if s.params.get("op"):
            op_params = {"type": "op", "op": s.params["op"]}
        # B4: the full step travels with the case (op_params.fct_step)
        # so the runner routes the row to the fct_exec executor
        marker = dict(op_params or {})
        marker["fct_step"] = s.to_dict()
        cases.append({
            "name": name, "kind": kind, "enable": True,
            "wait_ms": 100, "timeout_ms": int(max(s.timeout_s, 1.0)
                                              * 1000),
            "op_params": marker,
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
