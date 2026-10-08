# -*- coding: utf-8 -*-
"""FCT step executors + message judgement engine (B4 design §1-§5).

One executor, four flows (MESSAGE_CHECK / GUI_CONFIRM / CLI_RUN /
EXTERNAL_TOOL), a shared retry loop and the negative-wins keyword
judge.  Pure engine: the Qt dialog is injected as a HOOK
(`context.human_confirm`), so everything is headless-testable and the
GUI plugs it in later (Virtual mode auto-answers in tests).

RED LINE honoured from B3: the JUDGEMENT implemented here is the
signed-off B4 scope (keyword tables + exit-code joint judgement +
human answer) — no instrument/ICT logic.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .fct_channels import SubprocessFctChannel, VirtualFctChannel
from .fct_channels import ChannelClosed
from ..gui.yamlbuild.fct_build import (
    STEP_CLI_RUN,
    STEP_EXTERNAL_TOOL,
    STEP_GUI_CONFIRM,
    STEP_MESSAGE_CHECK,
    FctStep,
)

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_ERROR = "ERROR"
VERDICT_SKIP = "SKIP"


@dataclass
class FctOutcome:
    """One step verdict (B4 §1.5)."""
    verdict: str
    reason: str = ""
    lines: list = field(default_factory=list)


def judge_keywords(lines: list, pass_kw: list, fail_kw: list) -> tuple:
    """Negative-wins keyword judgement over captured lines.

    The WHOLE captured batch is scanned for negative keywords FIRST —
    a trailing error line flips the verdict even after a positive hit
    in the same batch (B4 §1.3 negative-wins rule).

    Returns:
        (verdict, reason) - ("PASS", "<kw>") / ("FAIL", "<kw>") /
        ("", "") when nothing matched.
    """
    pl = [k.lower() for k in pass_kw]
    fl = [k.lower() for k in fail_kw]
    for line in lines:
        low = line.lower()
        for kw in fl:
            if kw and kw in low:
                return VERDICT_FAIL, kw
    for line in lines:
        low = line.lower()
        for kw in pl:
            if kw and kw in low:
                return VERDICT_PASS, kw
    return "", ""


@dataclass
class FctContext:
    """Everything an executor needs besides the step (injected —
    headless-testable; the GUI binds the real sinks)."""
    channels: dict = field(default_factory=dict)   # key -> FctChannel
    station_id: str = ""
    user: str = ""
    log_sink: object = None        # callable(str) -> None (EventLog)
    human_confirm: object = None   # callable(FctStep) -> bool (GO=True)
    keyword_pass: list = field(default_factory=list)
    keyword_fail: list = field(default_factory=list)

    def log(self, message: str) -> None:
        line = f"[{self.station_id}] [{self.user}] {message}"
        if self.log_sink is not None:
            self.log_sink(line)

    def channel_for(self, step: FctStep):
        """The bound channel or None (dialog-only steps)."""
        if step.resource.startswith("host") or (
                step.step_type == STEP_CLI_RUN and not step.channel
                and step.params.get("host_cli")):
            key = "__host__"
        else:
            key = step.channel
        return self.channels.get(key)

    def effective_keywords(self, step: FctStep) -> tuple:
        """Sequence tables extended by the per-step entries (§1.3)."""
        return (list(self.keyword_pass) + list(step.expect_pass),
                list(self.keyword_fail) + list(step.expect_fail))


def _capture_loop(channel, pass_kw: list, fail_kw: list,
                  timeout_s: float, ctx: FctContext,
                  collected: list) -> FctOutcome:
    """Bounded drain (B4 §1.2): positive / negative / timeout."""
    deadline = time.monotonic() + max(timeout_s, 0.0)
    while True:
        try:
            got = channel.read_lines(max_lines=200, timeout_s=0.1)
        except ChannelClosed as exc:
            return FctOutcome(VERDICT_ERROR, f"channel error: {exc}",
                              list(collected))
        if got:
            collected.extend(got)
            ctx.log(f"capture {len(got)} line(s)")
            verdict, hit = judge_keywords(got, pass_kw, fail_kw)
            if verdict == VERDICT_FAIL:
                return FctOutcome(VERDICT_FAIL, f"negative keyword "
                                  f"'{hit}'", list(collected))
            if verdict == VERDICT_PASS:
                # grace re-drain: a trailing ERROR flips the verdict
                time.sleep(0.05)
                try:
                    extra = channel.read_lines(max_lines=200,
                                               timeout_s=0.05)
                except ChannelClosed as exc:
                    return FctOutcome(VERDICT_ERROR, f"channel error: "
                                      f"{exc}", list(collected))
                if extra:
                    collected.extend(extra)
                    v2, hit2 = judge_keywords(extra, pass_kw, fail_kw)
                    if v2 == VERDICT_FAIL:
                        return FctOutcome(VERDICT_FAIL,
                                          f"negative keyword '{hit2}'",
                                          list(collected))
                return FctOutcome(VERDICT_PASS, f"positive keyword "
                                  f"'{hit}'", list(collected))
        if timeout_s and time.monotonic() > deadline:
            return FctOutcome(VERDICT_FAIL, "timeout", list(collected))
        if not got:
            time.sleep(0.02)            # engines may poll real channels


def _open_channel(step: FctStep, ctx: FctContext):
    """Bind the step channel; a host CLI step gets a fresh subprocess
    adapter (registered as __host__)."""
    ch = ctx.channel_for(step)
    if ch is None and step.step_type == STEP_CLI_RUN \
            and step.params.get("host_cli"):
        ch = SubprocessFctChannel(timeout_s=step.timeout_s or 30.0,
                                  cwd=str(step.params.get("cwd", "")))
        ctx.channels["__host__"] = ch
    return ch


def execute_fct_step(step: FctStep, ctx: FctContext) -> FctOutcome:
    """Execute ONE FctStep (the whole state machine incl. retries).

    Verdicts: PASS / FAIL (judged, timeout, human STOP) / ERROR
    (infrastructure) / SKIP (explicit params.skip).  EVERY outcome is
    logged with the identity fields (B4 §2 record points).
    """
    if step.params.get("skip"):
        ctx.log(f"{step.name}: SKIP (params.skip)")
        return FctOutcome(VERDICT_SKIP, "skipped by params")
    ctx.log(f"{step.name}: start ({step.step_type})")
    attempts = int(step.retries) + 1
    outcome = FctOutcome(VERDICT_FAIL, "not executed")
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            ctx.log(f"retry {attempt}/{attempts}")
        outcome = _execute_once(step, ctx)
        if outcome.verdict in (VERDICT_PASS, VERDICT_ERROR):
            break
    ctx.log(f"{step.name}: verdict {outcome.verdict} ({outcome.reason})")
    return outcome


def _execute_once(step: FctStep, ctx: FctContext) -> FctOutcome:
    """One attempt, dispatched by step_type (B4 §2 flows)."""
    pass_kw, fail_kw = ctx.effective_keywords(step)

    if step.step_type == STEP_GUI_CONFIRM:
        if ctx.human_confirm is None:
            return FctOutcome(VERDICT_ERROR, "no confirm hook bound")
        ctx.log("waiting for human confirmation")
        go = bool(ctx.human_confirm(step))
        ctx.log(f"human answer {'GO' if go else 'STOP'}")
        return FctOutcome(
            VERDICT_PASS if go else VERDICT_FAIL,
            "human GO" if go else "human STOP")

    if step.step_type == STEP_MESSAGE_CHECK:
        channel = ctx.channel_for(step)
        if channel is None:
            # channel-less message check = the operator-confirmed row
            # (MessageOK semantics through the confirm hook)
            if ctx.human_confirm is None:
                return FctOutcome(VERDICT_ERROR, f"channel "
                                  f"'{step.channel}' not bound")
            ok = bool(ctx.human_confirm(step))
            ctx.log(f"human answer {'OK' if ok else 'STOP'}")
            return FctOutcome(
                VERDICT_PASS if ok else VERDICT_FAIL,
                "human OK" if ok else "human STOP")
        if not pass_kw and not fail_kw:
            return FctOutcome(VERDICT_FAIL, "no keywords configured")
        return _capture_loop(channel, pass_kw, fail_kw,
                             step.timeout_s or 30.0, ctx, [])

    if step.step_type == STEP_CLI_RUN:
        channel = _open_channel(step, ctx)
        if channel is None:
            return FctOutcome(VERDICT_ERROR, f"channel '{step.channel}' "
                              "not bound")
        ctx.log(f"command sent: {step.command}")
        channel.write(step.command)
        outcome = _capture_loop(channel, pass_kw, fail_kw,
                                step.timeout_s or 30.0, ctx, [])
        # joint judgement with the exit code (host CLI only, B4 §4)
        exit_code = getattr(channel, "exit_code", None)
        if exit_code is not None and exit_code != 0 \
                and outcome.verdict == VERDICT_PASS:
            outcome.verdict = VERDICT_FAIL
            outcome.reason = f"exit code {exit_code}"
        return outcome

    if step.step_type == STEP_EXTERNAL_TOOL:
        # D1-A: same machinery — command (if any) then optional human
        # confirm (params.confirm) with keyword capture in between.
        if step.command:
            channel = _open_channel(step, ctx)
            if channel is None:
                return FctOutcome(VERDICT_ERROR,
                                  f"channel '{step.channel}' not bound")
            ctx.log(f"tool command sent: {step.command}")
            channel.write(step.command)
            outcome = _capture_loop(channel, pass_kw, fail_kw,
                                    step.timeout_s or 30.0, ctx, [])
            if outcome.verdict != VERDICT_PASS:
                return outcome
        if step.params.get("confirm"):
            if ctx.human_confirm is None:
                return FctOutcome(VERDICT_ERROR, "no confirm hook bound")
            go = bool(ctx.human_confirm(step))
            ctx.log(f"human answer {'GO' if go else 'STOP'}")
            return FctOutcome(
                VERDICT_PASS if go else VERDICT_FAIL,
                "human GO" if go else "human STOP")
        return FctOutcome(VERDICT_FAIL, "no capture keywords and no "
                          "confirm configured")

    return FctOutcome(VERDICT_ERROR, f"unknown step_type "
                      f"{step.step_type!r}")


def attempt_retry(step: FctStep, ctx: FctContext) -> bool:
    """Retry bookkeeping hook (log point); the loop lives in
    execute_fct_step — this documents the record point only."""
    return False


def make_virtual_context(scripted: dict | None = None,
                         human_answers: list | None = None,
                         station: str = "STATION-A",
                         user: str = "op") -> tuple:
    """Convenience for Virtual/tests: (context, channels) — a virtual
    channel per requested key with injectable output.  The context
    keyword tables start EMPTY: tests set exactly the keywords the
    step under test declares (no default-table cross-talk)."""
    channels = {key: VirtualFctChannel() for key in (scripted or {})}
    answers = list(human_answers or [])

    def confirm(step) -> bool:
        return answers.pop(0) if answers else True

    def sink(message: str) -> None:
        pass                                    # tests assert via outcome

    ctx = FctContext(channels=channels, station_id=station, user=user,
                     log_sink=sink, human_confirm=confirm)
    for key, lines in (scripted or {}).items():
        channels[key].inject_output(lines)
    return ctx, channels
