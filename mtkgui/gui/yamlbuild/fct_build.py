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

from mtkgui.engine.step_types import (
    CATEGORY_CONSOLE,
    CATEGORY_EXTERNAL_GUI,
    CATEGORY_MESSAGE,
    CATEGORY_OPERATION,
    CATEGORY_ORDER,
    CATEGORY_TRANSFER,
    STEP_CATEGORIES,
    STEP_TYPE_TO_KIND,
    valid_type,
)

# ---------------------------------------------------------------------------
# vocabulary (M160 unified category + type taxonomy)
# ---------------------------------------------------------------------------
#: failure handling after the final retry
ON_FAIL_ABORT = "abort"
ON_FAIL_CONTINUE = "continue"
ON_FAIL_POLICIES = (ON_FAIL_ABORT, ON_FAIL_CONTINUE)

#: legacy sequence marker kept on FctSequence only (the document header);
#: a step no longer carries a flash mode - ``ExternalGui.flash`` and
#: ``Console.cli`` replace the old FLASH step.
SEQUENCE_FLASH_MODES = ("gui", "cli")

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
    "serial_put": {"timeout_s": 600.0},
    "serial_pull": {"timeout_s": 600.0},
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

#: op step names reused from the engine catalog (spine anchors)
OP_POWER_OFF = "Power Off DUT"
OP_RESET_INSTRUMENTS = "Reset Instruments"

#: Operation sub-type -> the OP_STEPS name the executor routes on
OP_TYPE_NAMES = {
    "init_instruments": "Init Instruments",
    "reset_instruments": "Reset Instruments",
    "fixture_ready": "Fixture Ready",
    "power_on": "Power On DUT",
    "power_off": "Power Off DUT",
    "daq_ai_start": "DAQ AI Start",
    "daq_ai_end": "DAQ AI End",
    "delay": "Delay",
}


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------
@dataclass
class FctStep:
    """One FCT sequence step (spec §5.2).  Pure data — no behavior."""

    name: str
    category: str = CATEGORY_MESSAGE
    type: str = "ok"
    channel: str = ""                 # console channel key ("" = dialog/host)
    command: str = ""                 # Console.cli / host payload
    expect_pass: list = field(default_factory=list)
    expect_fail: list = field(default_factory=list)
    timeout_s: float = 30.0           # 0 = wait forever
    retries: int = 0
    on_fail: str = ON_FAIL_ABORT
    depends: list = field(default_factory=list)
    resource: str = ""                # Channel-Allocation / inventory ref
    params: dict = field(default_factory=dict)
    #: M50: shared parameters are NOT copied into the step - they are
    #: referenced at runtime (``equipment.dut.ssh.ip`` ...); a step-level
    #: override wins when set (see :mod:`mtkgui.engine.ref_resolver`).
    ref: dict = field(default_factory=dict)
    override: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """YAML-safe plain dict (full field set, stable order).

        The step is published as ``category`` + ``type`` only: the
        legacy ``step_type`` / ``interact|action|dialog`` vocabulary is
        gone (M160).
        """
        out = {
            "name": self.name,
            "category": self.category, "type": self.type,
            "channel": self.channel,
            "command": self.command,
            "expect_pass": list(self.expect_pass),
            "expect_fail": list(self.expect_fail),
            "timeout_s": float(self.timeout_s), "retries": int(self.retries),
            "on_fail": self.on_fail, "depends": list(self.depends),
            "resource": self.resource, "params": dict(self.params),
        }
        if self.ref:
            out["ref"] = dict(self.ref)
        if self.override:
            out["override"] = dict(self.override)
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "FctStep":
        """Restore a step (tolerant: missing keys keep the defaults).

        Only ``category`` / ``type`` are read; a legacy ``step_type``
        key is ignored (the loader rejects such documents instead of
        silently migrating them).
        """
        data = dict(data or {})
        params = dict(data.get("params") or {})
        return cls(
            name=str(data.get("name", "")),
            category=str(data.get("category", "") or ""),
            type=str(data.get("type", "") or ""),
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
            ref=dict(data.get("ref") or {}),
            override=dict(data.get("override") or {}),
        )

    def validate(self, sibling_names: set | None = None) -> list:
        """Spec §5.2 validation -> list of error strings (empty=ok)."""
        errors: list = []
        if not self.name.strip():
            errors.append("step name must not be empty")
        if self.category not in CATEGORY_ORDER:
            errors.append(f"step {self.name!r}: unknown category "
                          f"{self.category!r}")
        elif not valid_type(self.category, self.type):
            errors.append(f"step {self.name!r}: type {self.type!r} is not "
                          f"valid for category {self.category!r}")
        if self.timeout_s < 0:
            errors.append(f"step {self.name!r}: timeout_s must be >= 0")
        if self.retries < 0:
            errors.append(f"step {self.name!r}: retries must be >= 0")
        if self.on_fail not in ON_FAIL_POLICIES:
            errors.append(f"step {self.name!r}: on_fail must be one of "
                          f"{ON_FAIL_POLICIES}")
        if (self.category == CATEGORY_CONSOLE and self.type == "cli"
                and not self.command.strip()):
            errors.append(f"step {self.name!r}: Console.cli requires a "
                          "command")
        if (self.category == CATEGORY_EXTERNAL_GUI
                and self.type == "flash"):
            slot = str((self.params or {}).get("slot", ""))
            if slot not in ("fat", "oobe"):
                errors.append(f"step {self.name!r}: ExternalGui.flash "
                              "requires params.slot in ('fat', 'oobe')")
        known = sibling_names or set()
        for dep in self.depends:
            if dep not in known:
                errors.append(f"step {self.name!r}: unknown dependency "
                              f"{dep!r}")
        # M50: every reference must be a dotted ``equipment.`` path that
        # matches the Equipment schema (value checks need the project yaml
        # and run in :func:`ref_resolver.validate_refs`).
        from mtkgui.engine.ref_resolver import EQUIPMENT_PATHS, is_ref
        for field_key, path in (self.ref or {}).items():
            text = str(path or "").strip()
            if not text:
                errors.append(f"step {self.name!r}: empty reference for "
                              f"{field_key!r}")
            elif not is_ref(text):
                errors.append(f"step {self.name!r}: {field_key} {text!r} is "
                              "not an equipment reference")
            elif text not in EQUIPMENT_PATHS:
                errors.append(f"step {self.name!r}: unknown reference "
                              f"{text!r}")
        return errors


# ---------------------------------------------------------------------------
# unified model helpers (type / action / args / legacy normalization)
# ---------------------------------------------------------------------------
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
    xfer = p.get("fct_serial_transfer")
    if xfer is not None:
        direction = str((xfer or {}).get("direction") or "push").lower()
        return "serial_pull" if direction == "pull" else "serial_put"
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
                category=CATEGORY_MESSAGE, type="yesno_console",
                timeout_s=0.0,
                params={"style": "yesno", "console_dialog": True,
                        "message": str(p.get("confirm_message") or step.name),
                        "wait_pattern": "", "wait_timeout": 0.0,
                        "message_timeout_s": 4.0}))
            continue
        out.append(step)
    return dedupe_steps(out)


def dedupe_steps(steps: list) -> list:
    """Drop EXACT duplicates (name + category/type + params), first
    one wins."""
    seen: set = set()
    out: list = []
    for step in steps or []:
        key = (getattr(step, "name", ""), getattr(step, "category", ""),
               getattr(step, "type", ""),
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
                name=f"Confirm: {step.name}",
                category=CATEGORY_MESSAGE, type="yesno_console",
                timeout_s=0.0,
                params={"style": "yesno", "console_dialog": True,
                        "message": str(p.get("confirm_message") or step.name),
                        "wait_pattern": "", "wait_timeout": 0.0,
                        "message_timeout_s": 4.0})
        rows = [step] + ([dlg] if dlg is not None else [])
        for s in rows:
            key = (s.name, s.category, s.type,
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


#: M159: who the sequence runs on - the main DUT (today's behaviour) or
#: one slave / daughter board probed through a shared console.
BOARD_ROLE_MAIN = "main"
BOARD_ROLE_SLAVES = ("sensor", "power", "ssd", "wifi", "ble")
BOARD_ROLES = (BOARD_ROLE_MAIN,) + tuple(f"slave:{name}"
                                         for name in BOARD_ROLE_SLAVES)


@dataclass
class FctSequence:
    """One FCT sequence (spec §5.3): keyword tables + ordered steps."""

    name: str
    flash_mode: str = "gui"
    #: M159: main DUT (default) or a slave / daughter board probe
    board_role: str = BOARD_ROLE_MAIN
    keyword_pass: list = field(
        default_factory=lambda: list(DEFAULT_KEYWORD_PASS))
    keyword_fail: list = field(
        default_factory=lambda: list(DEFAULT_KEYWORD_FAIL))
    steps: list = field(default_factory=list)   # list[FctStep]

    def validate(self, equipment=None) -> list:
        """Whole-sequence validation (duplicate names, per-step rules,
        dependency targets, M50 equipment references).

        Args:
            equipment: optional project yaml dict (or its ``equipment``
                       node) used to resolve every step reference; None
                       checks the reference syntax only.
        """
        errors: list = []
        if not self.name.strip():
            errors.append("sequence name must not be empty")
        if self.flash_mode not in SEQUENCE_FLASH_MODES:
            errors.append("flash_mode must be one of "
                          f"{SEQUENCE_FLASH_MODES}")
        if self.board_role not in BOARD_ROLES:
            errors.append(f"board_role must be one of {BOARD_ROLES}")
        names = {s.name for s in self.steps if s.name.strip()}
        if len(names) != len(self.steps):
            errors.append("duplicate step names in the sequence")
        for step in self.steps:
            errors.extend(step.validate(names))
        if equipment is not None:
            from mtkgui.engine.ref_resolver import validate_refs
            errors.extend(validate_refs(self.steps, equipment))
        return errors

    # ----------------------------------------------------------- YAML IO
    def to_dict(self) -> dict:
        """The `fct_sequence:` document body."""
        return {
            "name": self.name, "flash_mode": self.flash_mode,
            "board_role": self.board_role,
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
            flash_mode=str((data or {}).get("flash_mode", "gui")),
            board_role=str((data or {}).get("board_role",
                                            BOARD_ROLE_MAIN)),
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
    """The flash stage step for one path.

    ``gui`` is the third-party flash GUI (ExternalGui.flash); ``cli`` is
    the CLI burn path (Console.cli, e.g. uuu.exe).
    """
    name = f"Flash {slot.upper()} Firmware"
    if flash_mode == "gui":
        return FctStep(
            name=name, category=CATEGORY_EXTERNAL_GUI, type="flash",
            channel="", timeout_s=0.0,   # wait for the operator forever
            resource="operator", params={"slot": slot})
    return FctStep(
        name=name, category=CATEGORY_CONSOLE, type="cli", channel=channel,
        command=command, expect_pass=[done_kw],
        expect_fail=list(DEFAULT_KEYWORD_FAIL), resource="operator",
        params={"slot": slot})


def build_fct_sequence(name: str, flash_mode: str = "gui",
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
        FctStep(name="All Tests done.", category=CATEGORY_MESSAGE, type="ok",
                timeout_s=0.0, params={"message": "All Tests done."}),
    ]
    steps = [
        _flash_step("fat", flash_mode, channel, cli_command,
                    cli_done_keyword),
        *body,
        _flash_step("oobe", flash_mode, channel, cli_command,
                    cli_done_keyword),
        FctStep(name=OP_POWER_OFF, category=CATEGORY_OPERATION,
                type="power_off", timeout_s=0.0,
                params={"op": OP_POWER_OFF}),
        FctStep(name=OP_RESET_INSTRUMENTS, category=CATEGORY_OPERATION,
                type="reset_instruments", timeout_s=0.0,
                params={"op": OP_RESET_INSTRUMENTS}),
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
        kind = STEP_TYPE_TO_KIND.get((s.category, s.type), "MessageOK")
        if s.category == CATEGORY_OPERATION and s.type == "delay":
            kind = "Delay"
        elif (s.category == CATEGORY_CONSOLE and s.type == "cli"
              and (s.params or {}).get("fct_host_cmd") is not None):
            # host CLI row (test PC shell): keep the historic SendtoCLI
            # kind so the console round-trip keeps it in post-RF commands
            kind = "SendtoCLI"
        # the row name IS the step name (unified model): the keywords
        # travel in the step marker, never in the visible name
        name = s.name
        op_params = None
        if s.category == CATEGORY_OPERATION and s.type != "delay":
            op_name = (str((s.params or {}).get("op") or "")
                       or OP_TYPE_NAMES.get(s.type, s.name))
            op_params = {"type": "op", "op": op_name}
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
                           flash_mode: str = "gui") -> FctSequence:
    """Reverse mapping: ``fct_test_cases`` -> FctSequence.

    Only the ``op_params.fct_step`` marker is read (M160).  A row
    without a marker, or with an unknown category/type, is REJECTED -
    a legacy document is never silently migrated; the caller turns the
    ``ValueError`` into a load error.
    """
    steps: list = []
    for index, case in enumerate(cases or []):
        marker = (case.get("op_params") or {}).get("fct_step") \
            if isinstance(case, dict) else None
        label = str(case.get("name", "")) if isinstance(case, dict) else ""
        if not isinstance(marker, dict) or not marker:
            raise ValueError(
                f"FCT case {index} ({label!r}) carries no "
                "op_params.fct_step marker — rebuild the sequence in the "
                "FCT builder")
        category = str(marker.get("category") or "")
        sub_type = str(marker.get("type") or "")
        if category not in CATEGORY_ORDER or not valid_type(category,
                                                           sub_type):
            raise ValueError(
                f"FCT case {index} ({label!r}) carries the unknown "
                f"category/type {category!r}/{sub_type!r} — rebuild the "
                "sequence in the FCT builder")
        steps.append(FctStep.from_dict(marker))
    return FctSequence(name=name, flash_mode=flash_mode, steps=steps)
