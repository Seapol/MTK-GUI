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

import os
import threading
import time
from dataclasses import dataclass, field

from .fct_channels import SubprocessFctChannel, VirtualFctChannel
from .fct_channels import ChannelClosed
from ..startup_timing import begin as _span_begin, end as _span_end
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

#: M78-3 stall watchdog: a step that produced NO new bytes for this
#: long while still waiting for its positive evidence fails EARLY.
#: ONE application-level value (Tools > FCT Watchdog); 0 disables it.
DEFAULT_STALL_S = 8.0

#: M78-2 scheduling tolerance: the polling loops can overshoot their
#: deadline by one read slice.  A genuine overrun is seconds late - a
#: step inside this grace window is still on time.
BUDGET_GRACE_S = 0.25


def _over_budget(elapsed: float, budget_s: float) -> bool:
    return budget_s > 0 and elapsed > budget_s + max(
        BUDGET_GRACE_S, budget_s * 0.01)


def _step_budget(step) -> float:
    """The row's resolved wall-clock budget in seconds (0 = unlimited)."""
    try:
        return max(0.0, float(getattr(step, "timeout_s", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _watchdog_s(ctx) -> float:
    """Effective app-level stall watchdog window (0 = disabled)."""
    try:
        return max(0.0, float(getattr(ctx, "watchdog_s",
                                     DEFAULT_STALL_S) or 0.0))
    except (TypeError, ValueError):
        return DEFAULT_STALL_S


def _watchdog_reason(stall_s: float, budget_s: float) -> str:
    return (f"watchdog: no output for {stall_s:.1f}s "
            f"(budget {budget_s:g}s not reached)")


def _activity_marker(channel):
    """Monotonic traffic counter for the stall watchdog (None when the
    channel cannot report it - the loop then falls back to the batch)."""
    fn = getattr(channel, "received_len", None)
    if not callable(fn):
        return None
    try:
        return int(fn())
    except Exception:                 # noqa: BLE001 - best effort
        return None


def _expects_positive(step) -> bool:
    """True when the step waits for a POSITIVE pattern (watchdog-eligible).
    An expected=no / clean-window row has no positive evidence to
    await, so the stall watchdog must never fail it."""
    p = step.params or {}
    if not bool(p.get("capture_is_expected", True)):
        return False
    if str(p.get("expect_pass_re") or ""):
        return True
    if str(p.get("capture_end_line") or ""):
        return True
    if not (p.get("expect_fail_re") or p.get("capture_end_line")):
        return bool(step.expect_pass)
    return False


def console_line(payload: str) -> str:
    """The ONE console line payload: ``text`` + a single ``\\n``.

    No leading byte and no ``\\r``: a Linux DUT tty in canonical mode
    maps CR to NL (ICRNL), so ``"y\\r\\n"`` is delivered as TWO line
    breaks - the answer line and an empty line that the DUT script's
    next ``input()`` consumes as an empty answer (M22h earphone bug).
    Every FCT console write must go through this helper."""
    return str(payload) + "\n"


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
    #: callable(op_name, params) -> "Done" | "Error" for standard
    #: operation rows (rack PSU Power On/Off, fixture clamp/lock driven
    #: by U2355A DIO). When None an op-flagged GUI_CONFIRM is an ERROR.
    run_op: object = None
    keyword_pass: list = field(default_factory=list)
    keyword_fail: list = field(default_factory=list)
    #: DUT Report folder (str) for the ``{{dut_report}}`` template
    #: token in sftp_get / sftp_put local paths. Empty = no replacement.
    dut_report: str = ""
    #: project folder name under the projects workspace (e.g.
    #: "FRDM-IMX93") - serial-push local files resolve relative to it.
    #: Empty = local paths must be absolute.
    project_base: str = ""
    #: optional callable(title) -> context manager yielding a
    #: stage(value, label) callback (the GUI binds busy_progress); used
    #: to show a foreground bar for the long serial asset deploy. None
    #: in headless runs (the transfer proceeds without a dialog).
    progress_factory: object = None
    #: M78-3: application-level stall watchdog window in seconds
    #: (Tools > FCT Watchdog). 0 disables it. NOT a YAML field.
    watchdog_s: float = DEFAULT_STALL_S

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
    """Bounded drain (B4 §1.2): positive / negative / timeout.

    M78-3: while a POSITIVE keyword is still unmatched, a stretch of the
    app-level watchdog window without new bytes fails the step
    immediately (the PASS path is untouched - a match still wins the
    instant it arrives)."""
    deadline = time.monotonic() + max(timeout_s, 0.0)
    last_data = time.monotonic()
    marker = _activity_marker(channel)
    stall_s = _watchdog_s(ctx)
    while True:
        try:
            got = channel.read_lines(max_lines=200, timeout_s=0.1)
        except ChannelClosed as exc:
            return FctOutcome(VERDICT_ERROR, f"channel error: {exc}",
                              list(collected))
        new_marker = _activity_marker(channel)
        if new_marker is not None and new_marker != marker:
            marker = new_marker
            last_data = time.monotonic()
        elif got and marker is None:
            last_data = time.monotonic()
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
        if stall_s > 0 and pass_kw \
                and (time.monotonic() - last_data) >= stall_s:
            reason = _watchdog_reason(stall_s, timeout_s)
            ctx.log(f"{reason} -> FAIL")
            return FctOutcome(VERDICT_FAIL, reason, list(collected))
        if timeout_s and time.monotonic() > deadline:
            return FctOutcome(VERDICT_FAIL, "timeout", list(collected))
        if not got:
            time.sleep(0.02)            # engines may poll real channels


def _fat_summary_outcome(text: str) -> FctOutcome:
    """parse_summary row (GUI work-flow parity): judge the captured
    fat.py Summary table — FAIL when any item FAILs, else PASS; the
    per-status counts land in the reason.  (Per-item row expansion in
    the GUI FCT table is a follow-up; the batch harness report carries
    the full per-item rows.)"""
    from .fct_test_runner import parse_fat_summary
    rows = parse_fat_summary(text)
    if not rows:
        return FctOutcome(VERDICT_FAIL, "no fat.py Summary found", [])
    counts: dict = {}
    for _idx, _name, status, _dur in rows:
        counts[status] = counts.get(status, 0) + 1
    detail = f"{len(rows)} items: " + ", ".join(
        f"{k} {v}" for k, v in sorted(counts.items()))
    verdict = VERDICT_FAIL if counts.get("FAIL") else VERDICT_PASS
    return FctOutcome(verdict, detail, [])


def _regex_capture(channel, step: FctStep, ctx: FctContext) -> FctOutcome:
    """B5 console-command capture: REGEX judgement (spec §4.2) —
    ``expect_fail_re`` wins over ``expect_pass_re``, timeout = FAIL
    ("TIMEOUT waiting"), never blocks forever.  Falls back to the
    plain keyword tables when no regex is configured.

    M78-3: a silent stretch (the app-level watchdog window) while the
    positive pattern is still unmatched fails the step early; a match
    still wins instantly.  M78-4: the run-start clear pins the read
    offset, so only bytes from THIS run can satisfy the pattern."""
    from .fct_test_runner import match_expectation, _pattern_hit
    p = step.params
    pass_re = str(p.get("expect_pass_re", "") or "")
    fail_re = str(p.get("expect_fail_re", "") or "")
    pass_is_re = bool(p.get("expect_pass_is_regex", False))
    fail_is_re = bool(p.get("expect_fail_is_regex", False))
    case = bool(p.get("case_sensitive", True))
    end_line = str(p.get("capture_end_line", "") or "")
    is_expected = bool(p.get("capture_is_expected", True))
    # End Line shares the main pattern's Regex/Case setting
    end_is_re = pass_is_re if is_expected else fail_is_re
    stall_s = _watchdog_s(ctx)
    budget_s = _step_budget(step)
    watchdog = (stall_s > 0 and _expects_positive(step)
                and not bool(p.get("__watchdog_off")))
    collected: list = []
    deadline = time.monotonic() + max(step.timeout_s or 5.0, 0.1)
    last_data = time.monotonic()
    marker = _activity_marker(channel)

    while True:
        try:
            got = channel.read_lines(max_lines=200, timeout_s=0.1)
        except ChannelClosed as exc:
            return FctOutcome(VERDICT_ERROR, f"channel error: {exc}",
                              list(collected))
        new_marker = _activity_marker(channel)
        if new_marker is not None and new_marker != marker:
            marker = new_marker
            last_data = time.monotonic()
        elif got and marker is None:
            last_data = time.monotonic()
        if got:
            collected.extend(got)
            text = "\n".join(collected)
            if not (pass_re or fail_re or end_line):
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
                # negative keyword always wins first
                if fail_re and _pattern_hit(fail_re, fail_is_re,
                                            case, text):
                    return FctOutcome(VERDICT_FAIL,
                                      f"matched unwanted '{fail_re}'",
                                      list(collected))
                if is_expected and pass_re and _pattern_hit(
                        pass_re, pass_is_re, case, text):
                    if p.get("parse_summary"):
                        return _fat_summary_outcome(text)
                    return FctOutcome(VERDICT_PASS,
                                      f"matched '{pass_re}'",
                                      list(collected))
                if end_line and _pattern_hit(end_line, end_is_re,
                                             case, text):
                    if is_expected:
                        # range ended without the wanted message
                        return FctOutcome(
                            VERDICT_FAIL,
                            f"End Line reached without '{pass_re}'",
                            list(collected))
                    # expected=no: clean window, no unwanted message
                    return FctOutcome(
                        VERDICT_PASS,
                        "clean window up to End Line",
                        list(collected))
        if watchdog and (time.monotonic() - last_data) >= stall_s:
            reason = _watchdog_reason(stall_s, budget_s)
            ctx.log(f"{step.name}: {reason} -> FAIL")
            return FctOutcome(VERDICT_FAIL, reason, list(collected))
        if step.timeout_s and time.monotonic() > deadline:
            text = "\n".join(collected)
            if not is_expected and not end_line and not (
                    fail_re and _pattern_hit(fail_re, fail_is_re,
                                             case, text)):
                # expected=no without an End Line: surviving the whole
                # window without the bad message is a PASS
                return FctOutcome(VERDICT_PASS,
                                  "no unwanted message in window",
                                  list(collected))
            return FctOutcome(VERDICT_FAIL,
                              "TIMEOUT waiting for "
                              f"{pass_re or end_line or 'output'}",
                              list(collected))
        if not got:
            time.sleep(0.02)


def _console_wait(channel, step: FctStep, ctx: FctContext,
                  pattern: str, timeout_s: float = 0.0,
                  case_sensitive: bool = True,
                  name_suffix: str = "") -> FctOutcome:
    """WaitFor stage of an interact / dialog step (unified model).

    Bounded by ``params.wait_timeout`` (never blocks forever); the
    pattern honours the row's Regex / Case sensitivity flags.  A
    non-PASS verdict means the awaited prompt never arrived, so the
    caller must NOT send the answer."""
    p = step.params
    budget_s = _step_budget(step)
    window = float(timeout_s or p.get("wait_timeout")
                   or budget_s or 30.0)
    # M78-2: an internal sub-wait can never outlive the row's budget
    if budget_s > 0:
        window = min(window, budget_s)
    # M78-3: operator dialogs are human waits - no stall watchdog there
    dialog = bool(p.get("console_dialog")
                  or step.step_type == STEP_GUI_CONFIRM)
    wait_step = FctStep(
        name=f"{step.name} ({name_suffix or 'wait'})",
        step_type=STEP_MESSAGE_CHECK,
        channel=step.channel,
        timeout_s=window,
        params={"fct_console": True, "kind": "wait",
                "expect_pass_re": pattern,
                "expect_pass_is_regex": bool(p.get("wait_is_regex")),
                "capture_is_expected": True,
                "case_sensitive": bool(
                    case_sensitive and p.get("case_sensitive", True)),
                # M78-3: an operator dialog is a human wait - the app
                # watchdog must not fail its message-arrival phase
                "__watchdog_off": dialog})
    ctx.log(f"{step.name}: waiting for console message '{pattern}'")
    return _regex_capture(channel, wait_step, ctx)


def _mark_channel(channel) -> None:
    """M76/D4: remember "now" on a channel so a send+capture row judges
    ONLY the bytes received after its command (a pre-run boot log must
    never satisfy the capture keyword)."""
    mark = getattr(channel, "mark", None)
    if callable(mark):
        try:
            mark()
        except Exception:                 # noqa: BLE001 - never abort
            pass


def _console_login(step: FctStep, ctx: FctContext,
                   channel) -> FctOutcome:
    """M76/D3: the operator-authored DUT login row.

    Wait ``login_prompt`` -> send ``user`` -> wait the password prompt
    -> send ``password`` (an empty password still sends ONE line
    break) -> PASS only when ``shell_prompt`` arrives.  The whole
    sequence is bounded by the row's wait window."""
    p = dict(step.params.get("fct_console_login") or {})
    login_prompt = str(p.get("login_prompt") or "login:")
    user = str(p.get("user") or "")
    password = str(p.get("password") or "")
    shell_prompt = str(p.get("shell_prompt") or "#")
    pass_prompt = str(p.get("password_prompt") or "pass")
    window = max(float(p.get("timeout_s") or step.timeout_s or 30.0), 0.1)
    deadline = time.monotonic() + window

    def _wait(pattern: str, label: str) -> FctOutcome:
        left = deadline - time.monotonic()
        if left <= 0:
            return FctOutcome(VERDICT_FAIL,
                              f"TIMEOUT before {label} '{pattern}'")
        return _console_wait(
            channel, step, ctx, pattern, timeout_s=left,
            case_sensitive=False, name_suffix=label)

    _line = console_line

    outcome = _wait(login_prompt, "login prompt")
    if outcome.verdict != VERDICT_PASS:
        return outcome
    ctx.log(f"console send: {user!r} (login user)")
    _mark_channel(channel)
    # a login prompt is interactive: write the answer immediately (no
    # quiet-window drain, which would swallow the password prompt)
    channel.write(_line(user))
    outcome = _wait(pass_prompt, "password prompt")
    if outcome.verdict != VERDICT_PASS:
        return outcome
    ctx.log("console send: password (hidden)")
    _mark_channel(channel)
    channel.write(_line(password))
    outcome = _wait(shell_prompt, "shell prompt")
    if outcome.verdict != VERDICT_PASS:
        return outcome
    return FctOutcome(VERDICT_PASS,
                      f"logged in - matched '{shell_prompt}'",
                      list(outcome.lines))


def _console_dialog(step: FctStep, ctx: FctContext) -> FctOutcome:
    """A Console-domain operator dialog (MessageOKtoConsole /
    MessageYesNotoConsole / MessageGoStoptoConsole, user direction
    2026-10-18).

    Phase 1: WAIT the expected console message (``params.wait_pattern``)
    on the step channel.  Phase 2: hand over to the bound confirm hook,
    which notifies the operator and sends y / n where the METHOD calls
    for it (the runner owns the send / verdict semantics)."""
    p = step.params
    pattern = str(p.get("wait_pattern") or "")
    if pattern:
        channel = ctx.channel_for(step)
        if channel is None:
            return FctOutcome(VERDICT_ERROR,
                              f"channel '{step.channel}' not bound")
        outcome = _console_wait(channel, step, ctx, pattern)
        if outcome.verdict != VERDICT_PASS:
            return FctOutcome(outcome.verdict,
                              f"wait for '{pattern}': {outcome.reason}",
                              list(outcome.lines))
    if ctx.human_confirm is None:
        return FctOutcome(VERDICT_ERROR, "no confirm hook bound")
    go = bool(ctx.human_confirm(step))
    ctx.log(f"human answer {'GO' if go else 'STOP'}")
    return FctOutcome(VERDICT_PASS if go else VERDICT_FAIL,
                      "human GO" if go else "human STOP")


def runner_for(ctx: FctContext):
    """A HostCliRunner bound to the context identity/log (host-side
    commands such as the own-Bluetooth-address lookup)."""
    from .host_cli import HostCliRunner
    return HostCliRunner(log_sink=ctx.log, station_id=ctx.station_id,
                         user=ctx.user)


def _is_lan_ipv4(tok: str) -> bool:
    """Legacy alias -> host_platform.is_lan_ipv4 (m23 single source)."""
    from .host_platform import is_lan_ipv4
    return is_lan_ipv4(tok)


def host_lan_ip(ctx: FctContext) -> str:
    """Best-effort Host PC LAN IPv4 - DELEGATES to
    :func:`mtkgui.engine.host_platform.host_lan_ip` (m23), which adds
    the Windows PowerShell / ipconfig branch.  Kept here so existing
    callers/tests are unchanged."""
    from .host_platform import host_lan_ip as _ip
    return _ip(ctx)


def _wifi_scan_targets(cfg: dict) -> list:
    """The Wi-Fi scan targets (AP + DUT) from the step config (M49b).

    A ``targets`` list wins (each ``{role, ssid, rssi_min}``); a legacy
    single-target config falls back to the AP SSID + ``rssi_min``."""
    out: list = []
    raw = cfg.get("targets")
    if isinstance(raw, list) and raw:
        for item in raw:
            item = dict(item or {})
            ssid = str(item.get("ssid") or "").strip()
            if not ssid:
                continue
            out.append({"role": str(item.get("role") or "DUT"),
                        "ssid": ssid,
                        "rssi_min": int(item.get("rssi_min", -60))})
        return out
    ssid = str(cfg.get("expected_ssid") or cfg.get("ssid") or "").strip()
    if ssid:
        out.append({"role": "AP", "ssid": ssid,
                    "rssi_min": int(cfg.get("rssi_min", -70))})
    return out


def _wifi_scan_host(step: FctStep, cfg: dict, ctx: FctContext) -> FctOutcome:
    """Host-side dual-target Wi-Fi RSSI scan (M49b).

    ``lswifi --json`` on Windows, CoreWLAN on macOS (via host_rf).  Each
    target judges against its OWN threshold; the verdict is PASS only
    when every target is found and within its threshold."""
    from . import host_rf
    targets = _wifi_scan_targets(cfg)
    if not targets:
        return FctOutcome(VERDICT_ERROR,
                          "no Wi-Fi scan target configured (AP SSID / "
                          "DUT SSID)")
    timeout_s = float(cfg.get("scan_timeout_s")
                      or step.timeout_s or 30.0)
    try:
        found = host_rf.wifi_scan(
            [t["ssid"] for t in targets],
            virtual=bool(cfg.get("virtual")),
            virtual_rssi=cfg.get("virtual_rssi"),
            timeout_s=timeout_s)
    except host_rf.HostRfError as exc:
        ctx.log(f"wifi scan failed: {exc}")
        return FctOutcome(VERDICT_ERROR, str(exc))
    parts: list = []
    ok = True
    for target in targets:
        rssi = found.get(target["ssid"])
        passed = rssi is not None and int(rssi) >= target["rssi_min"]
        ok = ok and passed
        reading = f"{rssi} dBm" if rssi is not None else "not found"
        parts.append(f'{target["role"]} "{target["ssid"]}": {reading} '
                     f'(min {target["rssi_min"]} dBm) '
                     f'{"PASS" if passed else "FAIL"}')
    detail = "; ".join(parts)
    ctx.log(f"wifi scan: {detail}")
    return FctOutcome(VERDICT_PASS if ok else VERDICT_FAIL, detail,
                      [detail])


def _bt_rssi_host(step: FctStep, cfg: dict, ctx: FctContext) -> FctOutcome:
    """Host-side BLE RSSI scan (M49b) through ``bleak``.

    A missing target is an ERROR; a target that is configured but not
    broadcasting is a FAIL carrying the cause line."""
    from . import host_rf
    target = str(cfg.get("expected_addr")
                 or cfg.get("expected_name") or "").strip()
    if not target:
        return FctOutcome(VERDICT_ERROR,
                          "no Bluetooth target configured (DUT BT name / "
                          "BD address)")
    timeout_s = float(cfg.get("rf_timeout_s")
                      or step.timeout_s or 10.0)
    try:
        rssi = host_rf.bt_scan(
            target, virtual=bool(cfg.get("virtual")),
            virtual_rssi=cfg.get("virtual_rssi"), timeout_s=timeout_s)
    except host_rf.HostRfError as exc:
        ctx.log(f"BT scan failed: {exc}")
        return FctOutcome(VERDICT_ERROR, str(exc))
    if rssi is None:
        detail = (f'BT scan failed / DUT "{target}" not found '
                  "(is it broadcasting?)")
        ctx.log(f"BT RSSI: {detail}")
        return FctOutcome(VERDICT_FAIL, detail, [detail])
    rssi_min = int(cfg.get("rssi_min", -70))
    passed = int(rssi) >= rssi_min
    detail = (f'BT "{target}": {rssi} dBm (min {rssi_min} dBm) '
              f'{"PASS" if passed else "FAIL"}')
    ctx.log(f"BT RSSI: {detail}")
    return FctOutcome(VERDICT_PASS if passed else VERDICT_FAIL, detail,
                      [detail])


def _run_rf_tool(step: FctStep, family: str, ctx: FctContext) -> FctOutcome:
    """B5 RF tool execution (spec 3.2 / 3.3): build the B4 adapter
    from the embedded config (params.fct_rf) with the platform's
    command set (m23: mac / windows via host_platform), run it, log
    every command line, map the verdict.  a2dp_sink routes the
    operator question through the confirm hook.

    M49b: the RSSI-only scans run on the HOST PC through ``host_rf``
    (lswifi / CoreWLAN / bleak) - the old Windows percentage
    approximation is gone.  full_stack / pair_connect / a2dp_sink keep
    the existing rf_adapters path."""
    from .host_platform import (platform_key, wifi_backend_cmds,
                                bt_backend_cmds)
    from .rf_adapters import BluetoothAdapter, WifiAdapter, PlatformBackendMissing
    cfg = dict(step.params.get("fct_rf") or {})
    # M78-1/D3: the adapter's own (typed) timeout defaults to the ROW
    # budget - never a constant that silently shadows the declared row.
    if float(step.timeout_s or 0.0) > 0:
        cfg.setdefault("timeout_s", float(step.timeout_s))
        cfg.setdefault("iperf_timeout_s", float(step.timeout_s))
        cfg.setdefault("rf_timeout_s", float(step.timeout_s))
    runner = runner_for(ctx)
    try:
        if family == "wifi":
            # B5 rssi_only on a station-mode Linux DUT: the RSSI is read
            # ON THE DUT over the console (iw dev <interface> link) - a
            # host-side scan cannot see a station interface
            if step.params.get("rssi_via") == "dut_console" \
                    and cfg.get("mode") == "rssi_only":
                return _wifi_rssi_dut_console(step, cfg, ctx)
            if cfg.get("mode") == "rssi_only":
                return _wifi_scan_host(step, cfg, ctx)
            # B5 config key `ssid` -> adapter key `expected_ssid`
            rf = dict(cfg)
            rf.setdefault("expected_ssid", rf.get("ssid", ""))
            key = platform_key()
            rf_cfg = {"wifi": dict(
                rf, cmds={key: wifi_backend_cmds()})}
            out = WifiAdapter(rf_cfg, runner).run_test()
        else:
            if cfg.get("mode") == "rssi_only":
                return _bt_rssi_host(step, cfg, ctx)
            key = platform_key()
            rf_cfg = {"bluetooth": dict(
                cfg, cmds={key: bt_backend_cmds()})}
            adapter = BluetoothAdapter(rf_cfg, runner,
                                       human_confirm=ctx.human_confirm)
            out = adapter.run_test()
    except PlatformBackendMissing as exc:
        import sys
        if sys.platform == "win32":
            hint = (
                "Windows has no built-in classic-Bluetooth RSSI command; "
                "install a command-line scanner (e.g. BluetoothCL) and add "
                "a 'windows' backend, or run this RF step on macOS.")
        else:
            hint = "configure a command backend for this platform."
        ctx.log(f"{family} RF unavailable: {exc}")
        return FctOutcome(VERDICT_ERROR, f"{exc}. {hint}")
    for line in out.get("lines", [])[:20]:
        ctx.log(f"{family}: {line}")
    ctx.log(f"{family} items: {out.get('items')}")
    verdict = out.get("verdict")
    # Connect & Ping sub-test: PASS as soon as >=1 reply is received
    # (loss < 100%); the RSSI / 5%-loss gate of full_stack is not used.
    if family == "wifi" and cfg.get("any_reply"):
        loss = (out.get("items") or {}).get("loss_pct")
        if loss is not None:
            verdict = "Pass" if float(loss) < 100.0 else "Fail"
            ctx.log(f"connect&ping: loss {loss}% -> {verdict} "
                    f"(>=1 reply rule)")
    return FctOutcome(VERDICT_PASS if verdict == "Pass" else VERDICT_FAIL,
                      str(out.get("items")), out.get("lines", []))


def _wifi_rssi_dut_console(step: FctStep, cfg: dict,
                           ctx: FctContext) -> FctOutcome:
    """M66 Wi-Fi verdict via the DUT console: the DUT is a STA, so its
    RSSI is read ON THE DUT (``iw dev <interface> link`` -> ``signal:
    -X dBm``) and judged against rssi_min.  When a DUT IP is configured
    the Host must also reach it - the verdict expresses the Host <-> DUT
    link, not the router AP."""
    import re
    channel = ctx.channels.get(step.channel)
    if channel is None:
        return FctOutcome(VERDICT_ERROR,
                          f"console channel '{step.channel}' not bound")
    interface = str(cfg.get("interface", "mlan0"))
    rssi_min = float(cfg.get("rssi_min", -70))
    dut_ip = str(cfg.get("dut_ip") or "").strip()
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
            detail = f"DUT Wi-Fi RSSI {rssi} dBm vs min {rssi_min}"
            ctx.log(f"DUT Wi-Fi RSSI: {rssi} dBm (min {rssi_min})")
            if dut_ip:
                from .host_platform import ping_host
                reachable = ping_host(dut_ip)
                ctx.log(f"Host -> DUT {dut_ip}: "
                        + ("reachable" if reachable else "no reply"))
                detail += (f"; Host -> DUT {dut_ip}: "
                           + ("reachable" if reachable
                              else "NO REPLY (link FAIL)"))
                ok = ok and reachable
            return FctOutcome(
                VERDICT_PASS if ok else VERDICT_FAIL,
                detail, list(collected))
        if re.search(r"not connected|No station|Invalid", text,
                     re.IGNORECASE):
            return FctOutcome(VERDICT_FAIL, "DUT Wi-Fi not connected",
                              list(collected))
        if not got:
            time.sleep(0.02)
    return FctOutcome(VERDICT_FAIL, "TIMEOUT waiting for Wi-Fi link "
                      "info", list(collected))


def bind_sftp_channel(step: FctStep, ctx: FctContext,
                      endpoint: dict | None = None) -> bool:
    """Bind an SshFctChannel for an sftp step (M27 P8 / M77-4).

    Default (no ``endpoint``): the step carries its OWN ssh endpoint
    (``params.ssh_host`` / ``params.ssh_username``); the password comes
    from the credential layer (``fct_ssh_<host>``), never the YAML.
    M77-4: an explicit ``endpoint`` dict (``host`` / ``username`` /
    ``password``) lets the runner auto-bind to the DUT's Wi-Fi address
    (``fct_dut_ip``) with the ``equipment.dut.ssh`` values; an empty
    password is passed through as a real answer.

    Returns True when the channel was bound, False when no host is
    configured (the executor then reports a clean ERROR).
    """
    params = step.params or {}
    if endpoint is None:
        host = str(params.get("ssh_host") or "").strip()
        if not host:
            return False
        username = str(params.get("ssh_username") or "root")
        password = None                   # credential layer
    else:
        host = str(endpoint.get("host") or "").strip()
        if not host:
            return False
        username = str(endpoint.get("username") or "root")
        password = str(endpoint.get("password") or "")
    from .fct_channels import SshFctChannel
    ctx.channels[step.channel or "ssh"] = SshFctChannel(
        host=host, username=username,
        credential_ref=f"fct_ssh_{host}", password=password)
    return True


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


def _step_span_flags(step: FctStep) -> dict:
    """M51 §5: operator waits / deliberate delays are not stalls."""
    params = step.params or {}
    if "fct_delay_ms" in params:
        return {"no_slow": True}
    human = (step.step_type == STEP_GUI_CONFIRM and not params.get("op")) \
        or bool(params.get("console_dialog")) \
        or (step.step_type == STEP_MESSAGE_CHECK and not step.channel)
    return {"wait": True} if human else {}


def _transfer_span(kind: str, step: FctStep, fn) -> FctOutcome:
    """Wrap one host-side file transfer with its own timing span."""
    label = f"io: {kind} {step.name}"
    _span_begin(label, category="io")
    try:
        return fn()
    finally:
        _span_end(label)


def execute_fct_step(step: FctStep, ctx: FctContext) -> FctOutcome:
    """Execute ONE FctStep (the whole state machine incl. retries).

    Verdicts: PASS / FAIL (judged, timeout, human STOP) / ERROR
    (infrastructure) / SKIP (explicit params.skip).  EVERY outcome is
    logged with the identity fields (B4 §2 record points).
    """
    if step.params.get("skip"):
        ctx.log(f"{step.name}: SKIP (params.skip)")
        return FctOutcome(VERDICT_SKIP, "skipped by params")
    # M78-1: the ONE resolved budget, visible once per step.  A Delay is
    # a fixed wait with NO timeout of its own (M42/M35) - the wall does
    # not apply to it.
    budget_s = _step_budget(step)
    source = str(step.params.get("__budget_source") or "timeout_s")
    if "fct_delay_ms" in step.params:
        budget_s, source = 0.0, "delay (fixed wait)"
    if budget_s > 0:
        ctx.log(f"{step.name}: budget {budget_s:g}s (source {source})")
    else:
        ctx.log(f"{step.name}: budget unlimited (source {source})")
    _label = f"testflow: fct step {step.step_type} {step.name}"
    _span_begin(_label, category="testflow", **_step_span_flags(step))
    started = time.monotonic()
    try:
        ctx.log(f"{step.name}: start ({step.step_type})")
        attempts = int(step.retries) + 1
        outcome = FctOutcome(VERDICT_FAIL, "not executed")
        for attempt in range(1, attempts + 1):
            if _over_budget(time.monotonic() - started, budget_s):
                break
            if attempt > 1:
                ctx.log(f"retry {attempt}/{attempts}")
            outcome = _execute_once(step, ctx)
            if outcome.verdict in (VERDICT_PASS, VERDICT_ERROR):
                break
        # M78-2: the budget is a WALL - an overrun can never PASS
        elapsed = time.monotonic() - started
        if _over_budget(elapsed, budget_s):
            ctx.log(f"{step.name}: budget exceeded: {elapsed:.1f}s > "
                    f"{budget_s:g}s -> FAIL")
            outcome = FctOutcome(
                VERDICT_FAIL,
                f"timeout after {elapsed:.1f}s (budget {budget_s:g}s)",
                list(getattr(outcome, "lines", []) or []))
        ctx.log(f"{step.name}: verdict {outcome.verdict} ({outcome.reason})")
        return outcome
    finally:
        _span_end(_label)


def _execute_once(step: FctStep, ctx: FctContext) -> FctOutcome:
    """One attempt, dispatched by step_type (B4 §2 flows)."""
    pass_kw, fail_kw = ctx.effective_keywords(step)

    if step.step_type == STEP_GUI_CONFIRM:
        op_name = step.params.get("op")
        if op_name:
            # standard operation row (rack PSU Power On/Off, fixture
            # clamp/lock via U2355A DIO) - drive the instrument gateway,
            # not an operator dialog
            if ctx.run_op is None:
                return FctOutcome(VERDICT_ERROR,
                                  f"standard op {op_name!r}: no op runner")
            from .steps import OP_STEPS
            op_params = dict(OP_STEPS.get(op_name, {}))
            op_params.update({k: v for k, v in step.params.items()
                              if k != "op"})
            ctx.log(f"standard op: {op_name}")
            verdict = ctx.run_op(op_name, op_params)
            if verdict == "Done":
                return FctOutcome(VERDICT_PASS, f"{op_name}: {verdict}")
            if verdict == "Fail":
                # M38: a failed fixture expectation is a test FAIL
                return FctOutcome(VERDICT_FAIL, f"{op_name}: {verdict}")
            return FctOutcome(VERDICT_ERROR, f"{op_name}: {verdict}")
        if step.params.get("console_dialog"):
            # Console-domain operator dialog (user direction 2026-10-18):
            # WAIT the expected console message first, THEN ask
            return _console_dialog(step, ctx)
        if "flash_gui_path" in step.params:
            # Flash_GUI row (M33): launch (or reuse) the third-party
            # flash GUI on the HOST PC before the Go / Stop prompt.
            path = str(step.params.get("flash_gui_path") or "").strip()
            if not path:
                return FctOutcome(VERDICT_FAIL,
                                  "flash GUI path not configured")
            from .fct_test_runner import _flash_gui_process_running
            args = str(step.params.get("flash_gui_arguments") or "")
            if _flash_gui_process_running(path):
                ctx.log("flash GUI already running - reusing running GUI "
                        "(no relaunch)")
            else:
                from .flash_tool import launch_tool_gui
                started, detail = launch_tool_gui(path, args)
                if not started:
                    return FctOutcome(VERDICT_FAIL,
                                      f"flash GUI launch failed: {detail}")
                ctx.log(f"flash GUI {detail}")
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
        # M78-4: the run-start clear pins every channel read offset to
        # 0, so console expectations can only see bytes produced during
        # THIS run (never a previous run's or a manual session's text).
        # SSH file-transfer rows (sftp_put / sftp_get) run over the SSH
        # channel's SFTP endpoint.  A successful sftp_get ALSO removes
        # the DUT-side file so stale results can never leak into the
        # next run (2026-10-27 user direction: fetch fat_result.json /
        # fat.log into DUT Report, then clear them on the DUT).
        if step.params.get("kind") in ("sftp_put", "sftp_get"):
            if channel is None:
                # M77-4: no serial fallback and no silent retry - the
                # runner carries the exact bind failure reason
                reason = str(step.params.get("ssh_bind_error") or "")
                return FctOutcome(
                    VERDICT_ERROR,
                    reason or f"channel '{step.channel}' not bound")
            return _transfer_span(
                str(step.params.get("kind")), step,
                lambda: _run_sftp(step, ctx, channel))
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
            # M76/D3: the operator-authored DUT login row
            if step.params.get("fct_console_login"):
                return _console_login(step, ctx, channel)
            if step.params.get("confirm_enabled"):
                # LEGACY marker (published before the unified model):
                # the implicit popup is gone - such a row must be
                # normalized into an explicit `dialog` step at load
                # (fct_build.normalize_fct_steps).  Never pop silently.
                ctx.log("legacy implicit confirm ignored - use an "
                        "explicit dialog step")
            # ONE step, three stages (unified model 2026-10-28):
            # WaitFor (when configured) -> Send -> Capture.  The old
            # split "(wait)" pre-step is gone, so the wait stage runs
            # here before the answer is written.
            wait_pattern = str(step.params.get("wait_pattern") or "")
            if (str(step.params.get("kind") or "") != "wait"
                    and step.params.get("wait_enabled") and wait_pattern):
                outcome = _console_wait(channel, step, ctx, wait_pattern)
                if outcome.verdict != VERDICT_PASS:
                    return outcome
            if "send" in step.params:
                # Respect send_enabled and NEVER emit a bare newline for
                # send:'' rows: an empty line left in the tty input queue
                # is consumed by the DUT script's later input() (bug
                # 2026-10-28: the MQS Yes/No dialog was still open while
                # fat.py read that stray newline and ran on).
                _send_text = str(step.params.get("send") or "")
                if step.params.get("send_enabled", True) and \
                        _send_text.strip():
                    ctx.log(f"console send: {_send_text!r}")
                    # M76/D4: the capture stage must judge only bytes
                    # received AFTER this command - a pre-run boot log
                    # can never satisfy the expected keyword
                    _mark_channel(channel)
                    from .serial_transport import apply_send_hardening
                    apply_send_hardening(channel, console_line(_send_text))
                else:
                    ctx.log("console send skipped "
                            f"(send_enabled={step.params.get('send_enabled', True)}, "
                            f"send={_send_text!r})")
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
        # M76/D4: judge only the output produced by THIS command
        _mark_channel(channel)
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
        # Delay row (M42/M35): a plain fixed wait that ALWAYS waits the
        # full requested time - the Timeout column is not a budget for a
        # Delay (signed-off historic rule); M78 leaves it untouched.
        if "fct_delay_ms" in step.params:
            import time as _time
            wait_ms = max(0, int(step.params.get("fct_delay_ms") or 0))
            ctx.log(f"delay: waiting {wait_ms} ms")
            _time.sleep(wait_ms / 1000.0)
            return FctOutcome(VERDICT_PASS, f"Done - waited {wait_ms} ms")
        # B5 addendum: DUT-side connectivity / throughput / BT data-path
        # steps (run over the console via the dut_* primitives)
        channel = ctx.channels.get(step.channel)
        # Serial asset provisioning: push local scripts / the board-test
        # package to a freshly flashed DUT that has none of them, verify
        # by MD5 and unzip archives (long operation -> foreground bar).
        if step.params.get("fct_serial_push"):
            return _transfer_span(
                "serial push", step,
                lambda: _run_serial_push(step, ctx, channel))
        # M46: Serial Push/Pull over the console (chunked base64 + ACK).
        if step.params.get("fct_serial_transfer"):
            return _transfer_span(
                "serial transfer", step,
                lambda: _run_serial_transfer(step, ctx, channel))
        # host CLI row: run a command ON THE HOST PC (test station
        # shell, e.g. start/stop the local iperf3 server); PASS =
        # exit code 0.  No DUT console involved.
        if step.params.get("fct_host_cmd") is not None:
            import sys
            p = step.params["fct_host_cmd"]
            cmd = str(p.get("cmd") or "")
            if sys.platform == "win32" and str(p.get("cmd_windows") or ""):
                cmd = str(p["cmd_windows"])
            if not cmd.strip():
                return FctOutcome(VERDICT_ERROR,
                                  "host CLI row: no command configured")
            # action-registry args: a project may pin the working dir
            # (cwd) and the timeout per step; defaults = historic
            # behaviour (process CWD, step timeout)
            from ..gui.yamlbuild.fct_build import action_args
            args = action_args(step)
            res = runner_for(ctx).run(
                cmd, timeout_s=float(step.timeout_s or 30.0),
                cwd=str(args.get("cwd") or ""))
            verdict = VERDICT_PASS if res.exit_code == 0 else VERDICT_FAIL
            tail = " | ".join(l.strip() for l in res.lines[-3:]
                              if l.strip())
            detail = f"{cmd} -> rc={res.exit_code}"
            if tail:
                detail += f" | {tail}"
            ctx.log(f"host cli: {detail}")
            return FctOutcome(verdict, detail)
        if step.params.get("fct_wifi_ping") and channel is not None:
            from .fct_test_runner import ConsoleSerialShim, dut_wifi_ping
            p = step.params["fct_wifi_ping"]
            verdict, detail = dut_wifi_ping(
                ConsoleSerialShim(channel), p["gateway"], p["count"],
                p["loss_max"])
            ctx.log(f"DUT ping: {detail}")
            return FctOutcome(VERDICT_PASS if verdict == "PASS"
                              else VERDICT_FAIL, detail)
        if step.params.get("fct_wifi_iperf") and channel is not None:
            from .fct_test_runner import ConsoleSerialShim, dut_wifi_iperf
            p = step.params["fct_wifi_iperf"]
            server_ip = p.get("server_ip") or host_lan_ip(ctx)
            if not server_ip:
                return FctOutcome(
                    VERDICT_ERROR,
                    "iperf: cannot determine host server IP (set it in "
                    "the Wi-Fi iPerf config)")
            verdict, detail = dut_wifi_iperf(
                ConsoleSerialShim(channel), p["tool"], server_ip,
                p["min_mbps"], p.get("duration", 10))
            ctx.log(f"DUT iperf: {detail}")
            return FctOutcome(VERDICT_PASS if verdict == "PASS"
                              else VERDICT_FAIL, detail)
        if step.params.get("fct_bt_l2ping") and channel is not None:
            from .fct_test_runner import (ConsoleSerialShim, dut_bt_l2ping)
            verdict, detail = dut_bt_l2ping(
                ConsoleSerialShim(channel), runner_for(ctx),
                step.params["fct_bt_l2ping"]["count"])
            ctx.log(f"DUT l2ping: {detail}")
            return FctOutcome(VERDICT_PASS if verdict == "PASS"
                              else VERDICT_FAIL, detail)
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
            # M78-4: only output produced after this command may judge it
            _mark_channel(channel)
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


def _resolve_deploy_local(ctx: FctContext, local: str) -> str:
    """Resolve a deploy local path: absolute as-is; otherwise relative
    to the project folder under the projects workspace (``project_base``)
    or the CWD when no project base is bound."""
    if os.path.isabs(local):
        return os.path.normpath(local)
    if ctx.project_base:
        from ..gui.shell import resolve_tenant_base
        return os.path.normpath(os.path.join(
            resolve_tenant_base(), ctx.project_base, local))
    return os.path.normpath(local)


def _run_serial_push(step: FctStep, ctx: FctContext, channel) -> FctOutcome:
    """Serial-console asset deployment (params.fct_serial_push):

    ``files`` is a list of {local, remote, optional unzip}; local paths
    are relative to the project folder.  A foreground progress dialog
    (when the GUI bound one) covers the transfer; every file is
    MD5-verified on the DUT.
    """
    from .serial_push import PushError, push_bundle

    if channel is None:
        return FctOutcome(VERDICT_ERROR,
                          "serial push: no console channel bound")
    spec = step.params.get("fct_serial_push") or {}
    files: list = []
    total = 0
    missing: list = []
    for item in spec.get("files", []):
        local = _resolve_deploy_local(ctx, str(item.get("local", "")))
        entry = {"local": local, "remote": str(item.get("remote", ""))}
        if item.get("unzip"):
            entry["unzip"] = str(item["unzip"])
        files.append(entry)
        if os.path.isfile(local):
            total += os.path.getsize(local)
        else:
            missing.append(local)
    if not files:
        return FctOutcome(VERDICT_ERROR, "serial push: no files configured")
    if missing:
        return FctOutcome(VERDICT_ERROR,
                          "serial push: local file(s) missing: "
                          + "; ".join(missing))

    # overall progress across files (push_bundle reports per-file)
    state = {"offset": 0, "current": "", "size": 0}

    def _make_progress(stage):
        def progress(done, size, name):
            if name != state["current"]:
                if state["current"]:
                    state["offset"] += state["size"]
                state["current"], state["size"] = name, size
            overall = state["offset"] + done
            if stage is not None and total:
                pct = min(99, int(overall * 100 / total))
                stage(pct, f"Deploying {name} ({pct}%)")
        return progress

    try:
        budget_s = _step_budget(step)
        deadline = (time.monotonic() + budget_s) if budget_s > 0 else 0.0
        if ctx.progress_factory is not None:
            with ctx.progress_factory("Deploying test assets to DUT") as stage:
                results = push_bundle(
                    channel, files, log=ctx.log,
                    progress=_make_progress(stage), deadline=deadline)
        else:
            results = push_bundle(channel, files, log=ctx.log,
                                  deadline=deadline)
    except PushError as exc:
        return FctOutcome(VERDICT_FAIL, f"serial push: {exc}")
    except Exception as exc:                    # noqa: BLE001
        return FctOutcome(VERDICT_ERROR, f"serial push: {exc}")

    deployed = ", ".join(os.path.basename(r["remote"]) for r in results)
    unzipped = [r for r in results if r.get("unzip")]
    detail = f"deployed {len(results)} file(s) [{deployed}]"
    if unzipped:
        detail += "; unzipped to " + ", ".join(r["unzip"] for r in unzipped)
    return FctOutcome(VERDICT_PASS, detail)


def _run_serial_transfer(step: FctStep, ctx: FctContext, channel) -> FctOutcome:
    """Serial Push/Pull (params.fct_serial_transfer, M46).

    The transfer runs over the console channel with the chunked base64
    + ACK protocol; an optional row baudrate is negotiated up front and
    BOTH ends are restored afterwards (a restore failure is a FAIL with
    an explicit message).  A local DIRECTORY is deployed file by file
    under ``<remote>/<dir basename>``.
    """
    from .serial_transfer import SerialTransferError, transfer

    if channel is None:
        return FctOutcome(VERDICT_ERROR,
                          "serial transfer: no console channel bound")
    spec = step.params.get("fct_serial_transfer") or {}
    direction = str(spec.get("direction") or "push").lower()
    local = str(spec.get("local") or "")
    remote = str(spec.get("remote") or "").strip()
    baud = int(spec.get("baud") or 0)
    console_baud = int(spec.get("console_baud") or 115200)
    if not remote:
        return FctOutcome(VERDICT_ERROR,
                          "serial transfer: no DUT path configured")

    files: list = []            # (local_file, remote_file)
    if direction == "push":
        local = _resolve_deploy_local(ctx, local)
        if os.path.isdir(local):
            base_remote = remote.rstrip("/") or "/root"
            root_remote = f"{base_remote}/{os.path.basename(local.rstrip('/'))}"
            for root, _dirs, names in os.walk(local):
                rel = os.path.relpath(root, local)
                rel = "" if rel == "." else rel.replace(os.sep, "/")
                for name in sorted(names):
                    rpath = (f"{root_remote}/{rel}/{name}" if rel
                             else f"{root_remote}/{name}")
                    files.append((os.path.join(root, name), rpath))
        elif os.path.isfile(local):
            files.append((local, remote))
        else:
            return FctOutcome(VERDICT_FAIL,
                              f"serial push: local path not found: {local}")
    else:
        if not local:
            base = str(ctx.project_base or "")
            local = os.path.join(base, "outbox") if base else "outbox"
        local = _resolve_deploy_local(ctx, local)
        files.append((local, remote))
    if not files:
        return FctOutcome(VERDICT_FAIL,
                          "serial push: the local folder is empty")

    def _run(stage):
        def _progress(done, size, name):
            if stage is not None and size:
                pct = min(99, int(done * 100 / size))
                stage(pct, f"Transfer {name} ({pct}%)")
        try:
            for local_file, remote_file in files:
                if direction == "push":
                    parent = os.path.dirname(remote_file)
                    if parent:
                        channel.write(f"mkdir -p {parent}\n")
                transfer(channel, direction, local_file, remote_file,
                         baud=baud, console_baud=console_baud,
                         log=ctx.log, progress=_progress)
            return None
        except SerialTransferError as exc:
            return FctOutcome(VERDICT_FAIL, f"serial transfer: {exc}")
        except Exception as exc:                    # noqa: BLE001
            return FctOutcome(VERDICT_ERROR, f"serial transfer: {exc}")

    if ctx.progress_factory is not None:
        with ctx.progress_factory("Serial transfer") as stage:
            failed = _run(stage)
    else:
        failed = _run(None)
    if failed is not None:
        return failed
    if direction == "push":
        detail = f"pushed {len(files)} file(s) to {remote}"
    else:
        detail = f"pulled {remote} -> {files[0][0]}"
    return FctOutcome(VERDICT_PASS, detail)


class SftpTimeout(RuntimeError):
    """An SFTP transfer exceeded its configured timeout (M27 P10)."""


def _call_with_timeout(fn, timeout_s, *args):
    """Run ``fn(*args)`` on a daemon thread, bounded by ``timeout_s``.

    A ``timeout_s <= 0`` runs inline (wait forever, historic behaviour
    before the unified single-source timeout).  Returns the callable's
    result or raises :class:`SftpTimeout` when it did not finish."""
    timeout_s = float(timeout_s or 0.0)
    if timeout_s <= 0:
        return fn(*args)
    result: dict = {}

    def _work() -> None:
        try:
            result["value"] = fn(*args)
            result["ok"] = True
        except Exception as exc:          # noqa: BLE001 - re-raised
            result["exc"] = exc
            result["ok"] = False

    thread = threading.Thread(target=_work, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        raise SftpTimeout(
            f"sftp transfer timed out after {timeout_s:.1f}s")
    if not result.get("ok"):
        raise result.get("exc")
    return result.get("value")


def _run_sftp(step: FctStep, ctx: FctContext, channel) -> FctOutcome:
    """sftp_put / sftp_get over an SSH channel exposing put_file /
    get_file (and remove_file for the post-fetch DUT cleanup).

    Behaviour is driven by the action registry args
    (``fct_build.action_args``): ``remove_remote_file`` and
    ``create_local_dir`` default to the historic True; ``timeout_s`` is
    the row's single-source timeout and bounds the transfer (M27 P10).
    A project can override any subset per step without touching the
    executor."""
    from ..gui.yamlbuild.fct_build import action_args
    p = step.params
    args = action_args(step)
    kind = str(p.get("kind") or p.get("action") or "")
    local = str(p.get("local") or "")
    remote = str(p.get("remote") or "")
    if ctx.dut_report:
        local = local.replace("{{dut_report}}", ctx.dut_report)
    local = os.path.normpath(local)   # one spelling on every platform
    timeout_s = float(args.get("timeout_s") or 0.0)
    try:
        if kind == "sftp_put":
            if not hasattr(channel, "put_file"):
                return FctOutcome(VERDICT_ERROR,
                                  "channel has no SFTP put_file")
            _call_with_timeout(channel.put_file, timeout_s, local, remote)
            return FctOutcome(VERDICT_PASS, f"put {local} -> {remote}")
        if kind == "sftp_get":
            if not hasattr(channel, "get_file"):
                return FctOutcome(VERDICT_ERROR,
                                  "channel has no SFTP get_file")
            if args.get("create_local_dir", True):
                parent = os.path.dirname(os.path.abspath(local))
                os.makedirs(parent, exist_ok=True)
            _call_with_timeout(channel.get_file, timeout_s, remote, local)
            if args.get("remove_remote_file", True) \
                    and hasattr(channel, "remove_file"):
                try:
                    channel.remove_file(remote)
                except Exception as exc:              # noqa: BLE001
                    return FctOutcome(
                        VERDICT_PASS,
                        f"get {remote} -> {local}; DUT cleanup warn: {exc}")
                return FctOutcome(VERDICT_PASS,
                                  f"get {remote} -> {local}; "
                                  f"DUT file removed")
            return FctOutcome(VERDICT_PASS, f"get {remote} -> {local}")
        return FctOutcome(VERDICT_ERROR, f"unknown sftp kind {kind!r}")
    except SftpTimeout as exc:
        return FctOutcome(VERDICT_FAIL, f"sftp {kind} timeout: {exc}")
    except Exception as exc:                            # noqa: BLE001
        return FctOutcome(VERDICT_FAIL, f"sftp error: {exc}")


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
