# -*- coding: utf-8 -*-
"""Third-party flash tool CLI driver (R2 of the dual-path flash).

user direction 2026-10-17: the "auto" path of a Flash op step drives
the third-party CLI tool (powershell / cmd style invocation) and
judges the captured output on keywords: a ``fail_regex`` hit or a
missing ``ok_regex`` / ``verify_regex`` fails the step - the verdict
is machine-parsed, never guessed.

The tool profile lives in the project YAML under
``equipment.probes.device_params[<tool>]`` (edited on the Equipment
page Flash / Debug Probes row, R1) and carries the executable, the
per-action command templates and the output patterns.  Command
templates substitute ``{image}`` ``{device}`` ``{interface}``
``{speed_khz}`` ``{slot}``.

Execution reuses the RF test tooling abstraction
(:class:`mtkgui.drivers.rf_common.CommandExecutor`): the real runner
is :class:`~mtkgui.drivers.rf_common.SubprocessExecutor`, tests and
the demo inject :class:`~mtkgui.drivers.rf_common.ScriptedExecutor`
(the driver is never faked - only the executor is, same pattern as
the bluetooth / wifi RF drivers).

Fault tolerance (segmented retry budget, rollback on failure, slot
dirty marking) is delegated to :mod:`.flash_ft` - the CLI path raises
the same :class:`FlashWriteFailed` / :class:`FlashVerifyFailed` the
J-Link driver path raises, so the failure taxonomy is unchanged.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

DEFAULT_TOOL = "J-Link"
DEFAULT_TIMEOUT_S = 120.0


@dataclass
class ProgrammerProfile:
    """One third-party flash tool's CLI profile (project YAML)."""

    tool: str = DEFAULT_TOOL
    exe: str = ""
    device: str = ""
    interface: str = "SWD"
    speed_khz: str = "4000"
    write_cmd: str = "loadfile {image}"
    verify_cmd: str = "verifyfile {image}"
    reset_cmd: str = "r|g|exit"
    ok_regex: str = r"O\.K\."
    verify_regex: str = r"O\.K\."
    fail_regex: str = "Error|Cannot connect|FAILED"
    timeout_s: float = DEFAULT_TIMEOUT_S
    # raw options the profile was built from (audit / re-dump)
    options: dict = field(default_factory=dict)

    @classmethod
    def from_options(cls, tool: str, opts: dict) -> "ProgrammerProfile":
        """Build a profile from the YAML device_params mapping.

        The output patterns accept a single regex string (the editor
        form) or a list of alternatives (joined with ``|``) - both
        shapes are accepted so hand-edited YAML keeps working."""
        opts = dict(opts or {})

        def _pattern(key: str) -> str:
            val = opts.get(key, "")
            if isinstance(val, (list, tuple)):
                return "|".join(str(v) for v in val
                                if v is not None and str(v))
            return str(val or "")

        known = ("exe", "device", "interface", "speed_khz", "write_cmd",
                 "verify_cmd", "reset_cmd", "ok_regex", "verify_regex",
                 "fail_regex", "timeout_s")
        try:
            timeout = float(opts.get("timeout_s") or DEFAULT_TIMEOUT_S)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT_S
        return cls(
            tool=str(tool or DEFAULT_TOOL),
            exe=str(opts.get("exe") or "").strip(),
            device=str(opts.get("device") or "").strip(),
            interface=str(opts.get("interface") or "SWD").strip(),
            speed_khz=str(opts.get("speed_khz") or "4000").strip(),
            write_cmd=str(opts.get("write_cmd") or "loadfile {image}"),
            verify_cmd=str(opts.get("verify_cmd")
                           or "verifyfile {image}"),
            reset_cmd=str(opts.get("reset_cmd") or "r|g|exit"),
            ok_regex=_pattern("ok_regex"),
            verify_regex=_pattern("verify_regex"),
            fail_regex=_pattern("fail_regex"),
            timeout_s=timeout,
            options={k: opts[k] for k in opts if k in known},
        )

    def command(self, action_cmd: str, image: str) -> list[str]:
        """Build the argv for one action: the executable plus the
        substituted, shell-split command template."""
        values = {
            "image": image,
            "device": self.device,
            "interface": self.interface,
            "speed_khz": self.speed_khz,
            "slot": "",
        }
        tokens = shlex.split(action_cmd.format(**values))
        return [self.exe] + tokens


def load_flash_profile(equipment: dict | None,
                       tool: str) -> ProgrammerProfile | None:
    """Pick one tool profile from the equipment configs.

    Returns ``None`` (caller falls back to the J-Link driver path)
    when the block, the tool or the executable is missing."""
    opts = (((equipment or {}).get("probes") or {})
            .get("device_params") or {}).get(tool)
    if not opts:
        return None
    profile = ProgrammerProfile.from_options(tool, opts)
    return profile if profile.exe else None


def launch_tool_gui(exe: str) -> tuple[bool, str]:
    """Best-effort detached launch of the third-party GUI tool (R3
    manual path).

    Returns ``(started, detail)``.  NEVER raises - a GUI that cannot
    be started is logged and the operator may still flash by hand.
    Prefers ``QProcess.startDetached`` (the Qt-safe way to hand a
    process to the desktop) and falls back to a detached
    ``subprocess.Popen`` when Qt is unavailable (headless engine)."""
    exe = str(exe or "").strip()
    if not exe:
        return False, "no GUI path configured (not launched)"
    try:
        from PySide6.QtCore import QProcess
        result = QProcess.startDetached(exe, [])
        started = result[0] if isinstance(result, tuple) else bool(result)
        if started:
            return True, "launched (detached)"
    except Exception:                    # noqa: BLE001 - fallback below
        pass
    try:
        import subprocess
        import sys
        kwargs = ({"creationflags": 0x00000008}      # DETACHED_PROCESS
                  if sys.platform.startswith("win")
                  else {"start_new_session": True})
        subprocess.Popen([exe], **kwargs)
        return True, "launched (detached)"
    except Exception as exc:             # noqa: BLE001 - logged only
        return False, f"launch failed: {type(exc).__name__}: {exc}"


def judge_output(text: str, ok_regex: str,
                 fail_regex: str) -> tuple[bool, str]:
    """Keyword verdict on one captured tool output.

    A fail-pattern hit always fails; otherwise a configured OK
    pattern must match.  Returns (ok, reason)."""
    if fail_regex:
        try:
            hit = re.search(fail_regex, text)
        except re.error as exc:
            return False, f"invalid fail pattern {fail_regex!r}: {exc}"
        if hit:
            return False, f"fail pattern matched: {hit.group(0)!r}"
    if ok_regex:
        try:
            ok = re.search(ok_regex, text)
        except re.error as exc:
            return False, f"invalid OK pattern {ok_regex!r}: {exc}"
        if not ok:
            return False, f"OK pattern {ok_regex!r} not found"
    return True, ""


def run_cli_flash(profile: ProgrammerProfile,
                  image: str,
                  executor=None,
                  verify: bool = True,
                  reset_run: bool = True,
                  log_fn=None) -> str:
    """Drive one third-party CLI flash: write -> verify -> reset.

    Verdicts come from the captured output keywords only (user
    direction: the tool output decides success or failure).  Raises
    :class:`FlashWriteFailed` / :class:`FlashVerifyFailed` (the same
    taxonomy the J-Link driver path uses); transient executor
    timeouts propagate so the FlashTolerance retry budget applies.

    Returns the write-phase detail string (the FlashTolerance logs
    it as the write outcome)."""
    from ..drivers.errors import InstrumentIOError
    from ..drivers.rf_common import SubprocessExecutor
    from .flash_ft import (FlashVerifyFailed, FlashWriteFailed,
                           PhaseOutcome)

    log = log_fn or (lambda line: None)
    executor = executor or SubprocessExecutor()

    def _run(action: str, template: str) -> str:
        argv = profile.command(template, image)
        log(f"[FLASH_TOOL] {action}: {' '.join(argv)}")
        out = executor.run(argv, profile.timeout_s)
        text = "\n".join(part for part in (out.stdout, out.stderr)
                         if part)
        log(f"[FLASH_TOOL] {action} exit={out.returncode}: "
            f"{text.strip()[:200] or '(no output)'}")
        return text

    # write phase - the outcome decides via ok/fail patterns
    text = _run("write", profile.write_cmd)
    ok, reason = judge_output(text, profile.ok_regex,
                              profile.fail_regex)
    if not ok:
        raise FlashWriteFailed(
            PhaseOutcome("write", ok=False, detail=reason))
    log(f"[FLASH_TOOL] write OK ({profile.tool})")

    # verify phase - verify pattern falls back to the OK pattern
    if verify:
        text = _run("verify", profile.verify_cmd)
        ok, reason = judge_output(
            text, profile.verify_regex or profile.ok_regex,
            profile.fail_regex)
        if not ok:
            raise FlashVerifyFailed(
                PhaseOutcome("verify", ok=False, detail=reason))
        log(f"[FLASH_TOOL] verify OK ({profile.tool})")

    # reset & run - best effort: the image is already written and
    # verified, a reset hiccup must not roll the slot back
    if reset_run:
        try:
            _run("reset", profile.reset_cmd)
            log(f"[FLASH_TOOL] reset & run done ({profile.tool})")
        except Exception as exc:  # noqa: BLE001 - logged, never raised
            log(f"[FLASH_TOOL] reset & run failed (non-blocking): "
                f"{type(exc).__name__}: {exc}")
    return f"CLI flash OK ({profile.tool})"
