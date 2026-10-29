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
    plain keyword tables when no regex is configured."""
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
                  pattern: str) -> FctOutcome:
    """WaitFor stage of an interact / dialog step (unified model).

    Bounded by ``params.wait_timeout`` (never blocks forever); the
    pattern honours the row's Regex / Case sensitivity flags.  A
    non-PASS verdict means the awaited prompt never arrived, so the
    caller must NOT send the answer."""
    p = step.params
    wait_step = FctStep(
        name=f"{step.name} (wait)", step_type=STEP_MESSAGE_CHECK,
        channel=step.channel,
        timeout_s=float(p.get("wait_timeout") or step.timeout_s or 30.0),
        params={"fct_console": True, "kind": "wait",
                "expect_pass_re": pattern,
                "expect_pass_is_regex": bool(p.get("wait_is_regex")),
                "capture_is_expected": True,
                "case_sensitive": bool(p.get("case_sensitive", True))})
    ctx.log(f"{step.name}: waiting for console message '{pattern}'")
    return _regex_capture(channel, wait_step, ctx)


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
    parts = tok.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return False
    a, b = int(parts[0]), int(parts[1])
    if a == 127 or (a == 169 and b == 254) or a == 0:
        return False
    return True


def host_lan_ip(ctx: FctContext) -> str:
    """Best-effort Host PC LAN IPv4 (the iperf server address the DUT
    client connects to). Tries the active Wi-Fi/Ethernet interfaces;
    macOS first (ipconfig getifaddr), Linux fallback (hostname -I)."""
    import platform
    import subprocess
    if platform.system() == "Darwin":
        tries = [["ipconfig", "getifaddr", ifc]
                 for ifc in ("en0", "en1", "en2")]
    else:
        tries = [["hostname", "-I"], ["ip", "-4", "addr"]]
    for cmd in tries:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=5).stdout.split()
        except Exception:                   # noqa: BLE001
            continue
        for tok in out:
            if _is_lan_ipv4(tok):
                ctx.log(f"host iperf server IP: {tok} ({' '.join(cmd)})")
                return tok
    return ""


def _run_rf_tool(step: FctStep, family: str, ctx: FctContext) -> FctOutcome:
    """B5 RF tool execution (spec 3.2 / 3.3): build the B4 adapter
    from the embedded config (params.fct_rf) with the B4-verified mac
    command set, run it, log every command line, map the verdict.
    a2dp_sink routes the operator question through the confirm hook."""
    from .fct_test_runner import BT_MAC_CMDS, WIFI_MAC_CMDS
    from .rf_adapters import BluetoothAdapter, WifiAdapter, PlatformBackendMissing
    cfg = dict(step.params.get("fct_rf") or {})
    runner = runner_for(ctx)
    try:
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


def bind_sftp_channel(step: FctStep, ctx: FctContext) -> bool:
    """Bind an SshFctChannel for an sftp step (M27 P8).

    The step carries its OWN ssh endpoint (``params.ssh_host`` /
    ``params.ssh_username``); the password comes from the credential
    layer (``fct_ssh_<host>``), never the YAML.  Returns True when the
    channel was bound, False when no host is configured (the executor
    then reports a clean "channel not bound" ERROR).
    """
    host = str((step.params or {}).get("ssh_host") or "").strip()
    if not host:
        return False
    from .fct_channels import SshFctChannel
    ctx.channels[step.channel or "ssh"] = SshFctChannel(
        host=host,
        username=str((step.params or {}).get("ssh_username") or "root"),
        credential_ref=f"fct_ssh_{host}")
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
            return FctOutcome(
                VERDICT_PASS if verdict == "Done" else VERDICT_ERROR,
                f"{op_name}: {verdict}")
        if step.params.get("console_dialog"):
            # Console-domain operator dialog (user direction 2026-10-18):
            # WAIT the expected console message first, THEN ask
            return _console_dialog(step, ctx)
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
        # SSH file-transfer rows (sftp_put / sftp_get) run over the SSH
        # channel's SFTP endpoint.  A successful sftp_get ALSO removes
        # the DUT-side file so stale results can never leak into the
        # next run (2026-10-27 user direction: fetch fat_result.json /
        # fat.log into DUT Report, then clear them on the DUT).
        if step.params.get("kind") in ("sftp_put", "sftp_get"):
            return _run_sftp(step, ctx, channel)
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
                    channel.write(console_line(_send_text))
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
        # B5 addendum: DUT-side connectivity / throughput / BT data-path
        # steps (run over the console via the dut_* primitives)
        channel = ctx.channels.get(step.channel)
        # Serial asset provisioning: push local scripts / the board-test
        # package to a freshly flashed DUT that has none of them, verify
        # by MD5 and unzip archives (long operation -> foreground bar).
        if step.params.get("fct_serial_push"):
            return _run_serial_push(step, ctx, channel)
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
        if ctx.progress_factory is not None:
            with ctx.progress_factory("Deploying test assets to DUT") as stage:
                results = push_bundle(
                    channel, files, log=ctx.log,
                    progress=_make_progress(stage))
        else:
            results = push_bundle(channel, files, log=ctx.log)
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
