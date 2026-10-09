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


def _regex_capture(channel, step: FctStep, ctx: FctContext) -> FctOutcome:
    """B5 console-command capture: REGEX judgement (spec §4.2) —
    ``expect_fail_re`` wins over ``expect_pass_re``, timeout = FAIL
    ("TIMEOUT waiting"), never blocks forever.  Falls back to the
    plain keyword tables when no regex is configured."""
    from .fct_test_runner import match_expectation
    pass_re = str(step.params.get("expect_pass_re", "") or "")
    fail_re = str(step.params.get("expect_fail_re", "") or "")
    collected: list = []
    deadline = time.monotonic() + max(step.timeout_s or 5.0, 0.1)
    while True:
        try:
            got = channel.read_lines(max_lines=200, timeout_s=0.1)
        except ChannelClosed as exc:
            return FctOutcome(VERDICT_ERROR, f"channel error: {exc}",
                              list(collected))
        if got:
            collected.extend(got)
            text = "\n".join(collected)
            if not (pass_re or fail_re):
                if not (step.expect_pass or step.expect_fail):
                    # no expectations at all (e.g. the BT piscan setup
                    # step): ANY output means the command reached the
                    # DUT - the caller's timeout still bounds silence
                    if text.strip():
                        return FctOutcome(VERDICT_PASS,
                                          "output present",
                                          list(collected))
                else:
                    verdict, hit = judge_keywords(
                        got, list(step.expect_pass), list(step.expect_fail))
                    if verdict:
                        return FctOutcome(verdict, f"keyword '{hit}'",
                                          list(collected))
            else:
                verdict, detail = match_expectation(text, pass_re,
                                                    fail_re)
                if verdict == "FAIL":
                    return FctOutcome(VERDICT_FAIL, detail,
                                      list(collected))
                if verdict == "PASS":
                    return FctOutcome(VERDICT_PASS, detail,
                                      list(collected))
        if step.timeout_s and time.monotonic() > deadline:
            return FctOutcome(VERDICT_FAIL,
                              "TIMEOUT waiting for "
                              f"{pass_re or step.expect_pass}",
                              list(collected))
        if not got:
            time.sleep(0.02)


def _run_rf_tool(step: FctStep, family: str, ctx: FctContext) -> FctOutcome:
    """B5 RF tool execution (spec 3.2 / 3.3): build the B4 adapter
    from the embedded config (params.fct_rf) with the B4-verified mac
    command set, run it, log every command line, map the verdict.
    a2dp_sink routes the operator question through the confirm hook."""
    from .host_cli import HostCliRunner
    from .fct_test_runner import BT_MAC_CMDS, WIFI_MAC_CMDS
    from .rf_adapters import BluetoothAdapter, WifiAdapter
    cfg = dict(step.params.get("fct_rf") or {})
    runner = HostCliRunner(log_sink=ctx.log,
                           station_id=ctx.station_id, user=ctx.user)
    if family == "wifi":
        # B5 rssi_only on a station-mode Linux DUT: the RSSI is read
        # ON THE DUT over the console (iw dev <interface> link) - a
        # host-side scan cannot see a station interface
        if step.params.get("rssi_via") == "dut_console" \
                and cfg.get("mode") == "rssi_only":
            return _wifi_rssi_dut_console(step, cfg, ctx)
        # B5 config key `ssid` -> adapter key `expected_ssid`
        rf = dict(cfg)
        rf.setdefault("expected_ssid", rf.get("ssid", ""))
        rf_cfg = {"wifi": dict(rf, cmds={"mac": dict(WIFI_MAC_CMDS)})}
        out = WifiAdapter(rf_cfg, runner).run_test()
    else:
        rf_cfg = {"bluetooth": dict(
            cfg, cmds={"mac": dict(BT_MAC_CMDS)})}
        adapter = BluetoothAdapter(rf_cfg, runner,
                                   human_confirm=ctx.human_confirm)
        out = adapter.run_test()
    for line in out.get("lines", [])[:20]:
        ctx.log(f"{family}: {line}")
    ctx.log(f"{family} items: {out.get('items')}")
    verdict = out.get("verdict")
    return FctOutcome(VERDICT_PASS if verdict == "Pass" else VERDICT_FAIL,
                      str(out.get("items")), out.get("lines", []))


def _wifi_rssi_dut_console(step: FctStep, cfg: dict,
                           ctx: FctContext) -> FctOutcome:
    """B5 Wi-Fi rssi_only via the DUT console: send
    ``iw dev <interface> link``, parse ``signal: -X dBm`` (REGEX from
    the board's FCT_SETUP interface), judge against rssi_min."""
    import re
    channel = ctx.channels.get(step.channel)
    if channel is None:
        return FctOutcome(VERDICT_ERROR,
                          f"console channel '{step.channel}' not bound")
    interface = str(cfg.get("interface", "mlan0"))
    rssi_min = float(cfg.get("rssi_min", -70))
    ctx.log(f"DUT: iw dev {interface} link")
    channel.write(f"iw dev {interface} link\n")
    deadline = time.monotonic() + max(step.timeout_s or 15.0, 1.0)
    collected: list = []
    while time.monotonic() < deadline:
        try:
            got = channel.read_lines(max_lines=200, timeout_s=0.1)
        except ChannelClosed as exc:
            return FctOutcome(VERDICT_ERROR, f"channel error: {exc}",
                              list(collected))
        collected.extend(got)
        text = "\n".join(collected)
        m = re.search(r"signal:\s*(-?[\d.]+)\s*dBm", text)
        if m:
            rssi = float(m.group(1))
            ok = rssi >= rssi_min
            ctx.log(f"DUT Wi-Fi RSSI: {rssi} dBm (min {rssi_min})")
            return FctOutcome(
                VERDICT_PASS if ok else VERDICT_FAIL,
                f"RSSI {rssi} dBm vs min {rssi_min}", list(collected))
        if re.search(r"not connected|No station|Invalid", text,
                     re.IGNORECASE):
            return FctOutcome(VERDICT_FAIL, "DUT Wi-Fi not connected",
                              list(collected))
        if not got:
            time.sleep(0.02)
    return FctOutcome(VERDICT_FAIL, "TIMEOUT waiting for Wi-Fi link "
                      "info", list(collected))


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
        # B5: console steps use the REGEX/own-keyword judge - the
        # global keyword tables must NOT judge raw DUT output (a boot
        # log contains 'timeout'/'error' words -> false negatives)
        if step.params.get("fct_console"):
            if "send" in step.params:
                ctx.log(f"console send: {step.params.get('send')!r}")
                channel.write(str(step.params.get("send") or "") + "\n")
            return _regex_capture(channel, step, ctx)
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
        # B5: RF tool steps (wifi / bluetooth) run through the B4
        # adapters - the sub-config travels in params.fct_rf
        family = str(step.params.get("tool_family", "")).lower()
        if family in ("wifi", "bluetooth") and step.params.get("fct_rf"):
            return _run_rf_tool(step, family, ctx)
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
