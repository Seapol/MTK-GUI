# -*- coding: utf-8 -*-
"""B4 FCT execution tests: keyword judge (negative-wins), the four
step executors over virtual channels, retry / timeout / skip paths,
credential layer fallback rules and the runner integration (Virtual
end-to-end through TestRunner.run_demo)."""
from __future__ import annotations

import pytest

from mtkgui.engine.credentials import (
    CredentialUnavailable,
    get_credential,
)
from mtkgui.gui.yamlbuild.fct_build import (
    FLASH_CLI,
    FLASH_GUI,
    build_fct_sequence,
    to_project_fct_cases,
)
from mtkgui.engine.fct_channels import SubprocessFctChannel
from mtkgui.engine.fct_exec import (
    VERDICT_ERROR,
    VERDICT_FAIL,
    VERDICT_PASS,
    VERDICT_SKIP,
    FctContext,
    FctStep,
    bind_sftp_channel,
    execute_fct_step,
    judge_keywords,
    make_virtual_context,
)


# ------------------------------------------------------------ keyword judge
def test_judge_positive_and_negative():
    assert judge_keywords(["Boot OK", "scan done"],
                          ["done"], ["error"]) == ("PASS", "done")
    assert judge_keywords(["Boot failed"], ["done"], ["fail"]) == \
        ("FAIL", "fail")


def test_judge_negative_wins():
    """A negative keyword BEFORE the positive one fails the step even
    when both appear in the same capture (B4 §1.3)."""
    lines = ["starting", "error: lamp broken", "then success"]
    assert judge_keywords(lines, ["success"], ["error"]) == ("FAIL",
                                                             "error")
    # positive first, negative later in the SAME batch -> still FAIL
    # (the whole drained batch is judged line by line, negative wins)
    assert judge_keywords(["success now", "error later"],
                          ["success"], ["error"]) == ("FAIL", "error")


def test_judge_case_insensitive_and_empty():
    assert judge_keywords(["PASSED"], ["pass"], []) == ("PASS", "pass")
    assert judge_keywords(["nothing here"], [], []) == ("", "")


# ------------------------------------------------------------- executors
def test_message_check_positive_over_virtual_channel():
    ctx, channels = make_virtual_context({"ser1": ["boot", "TEST PASSED"]})
    step = FctStep(name="m", step_type="MESSAGE_CHECK", channel="ser1",
                   expect_pass=["passed"], timeout_s=2)
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert "passed" in out.reason


def test_message_check_negative_keyword_fails():
    ctx, _ = make_virtual_context({"ser1": ["ERROR: boom", "success"]})
    step = FctStep(name="m", step_type="MESSAGE_CHECK", channel="ser1",
                   expect_pass=["success"], expect_fail=["error"],
                   timeout_s=2)
    assert execute_fct_step(step, ctx).verdict == VERDICT_FAIL


def test_message_check_timeout_and_retry_then_pass():
    """First attempt times out (silenced channel), the retry sees the
    injected output -> PASS after retry 2/2."""
    from mtkgui.engine.fct_channels import VirtualFctChannel
    ctx, _ = make_virtual_context()
    ch = VirtualFctChannel()
    ctx.channels["ser1"] = ch
    step = FctStep(name="m", step_type="MESSAGE_CHECK", channel="ser1",
                   expect_pass=["pass"], timeout_s=0.3, retries=1)

    flips = {"n": 0}

    def late_inject(_message=""):
        flips["n"] += 1
        if flips["n"] == 2:               # after the first timeout
            ch.inject_output("PASS at last")

    ctx.log_sink = late_inject
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert flips["n"] >= 2


def test_message_check_unbound_channel_is_error():
    ctx, _ = make_virtual_context()
    ctx.human_confirm = None              # no dialog hook -> hard error
    step = FctStep(name="m", step_type="MESSAGE_CHECK", channel="nope",
                   expect_pass=["x"], timeout_s=1)
    assert execute_fct_step(step, ctx).verdict == VERDICT_ERROR


def test_message_check_without_keywords_fails_explicitly():
    ctx, channels = make_virtual_context({"ser1": ["hello"]})
    step = FctStep(name="m", step_type="MESSAGE_CHECK", channel="ser1",
                   timeout_s=1)
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_FAIL
    assert "no keywords" in out.reason


def _console_step(**params):
    base = {"fct_console": True}
    base.update(params)
    return FctStep(name="m", step_type="MESSAGE_CHECK", channel="ser1",
                   timeout_s=0.6, params=base)


def test_fct_console_expected_yes_pattern_before_endline_passes():
    ctx, _ = make_virtual_context({"ser1": ["FW v3.2 ready", "PROMPT"]})
    step = _console_step(expect_pass_re=r"FW v[\d.]+ ready",
                         expect_pass_is_regex=True,
                         capture_is_expected=True,
                         capture_end_line="PROMPT")
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS


def test_fct_console_expected_yes_endline_without_pattern_fails():
    ctx, _ = make_virtual_context({"ser1": ["some noise", "PROMPT"]})
    step = _console_step(expect_pass_re="READY",
                         capture_is_expected=True,
                         capture_end_line="PROMPT")
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_FAIL
    assert "End Line" in out.reason


def test_fct_console_expected_no_bad_message_fails():
    ctx, _ = make_virtual_context({"ser1": ["starting", "ERROR boom"]})
    step = _console_step(expect_fail_re="ERROR",
                         capture_is_expected=False,
                         capture_end_line="PROMPT")
    assert execute_fct_step(step, ctx).verdict == VERDICT_FAIL


def test_fct_console_expected_no_clean_window_to_endline_passes():
    ctx, _ = make_virtual_context({"ser1": ["all good", "PROMPT"]})
    step = _console_step(expect_fail_re="ERROR",
                         capture_is_expected=False,
                         capture_end_line="PROMPT")
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS


def test_fct_console_expected_no_no_endline_clean_timeout_passes():
    # expected=no without an End Line: a whole window with no bad
    # message is a PASS (bounded by timeout)
    ctx, _ = make_virtual_context({"ser1": ["booting", "still fine"]})
    step = _console_step(expect_fail_re="FATAL",
                         capture_is_expected=False)
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS


def test_fct_console_regex_flag_is_honoured():
    # regex pattern must not be treated as a literal substring
    ctx, _ = make_virtual_context({"ser1": ["FW v3.2 ready"]})
    step = _console_step(expect_pass_re=r"FW v[\d.]+ ready",
                         expect_pass_is_regex=True,
                         capture_is_expected=True)
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS
    # same text, but treated as exact literal -> no match -> timeout FAIL
    ctx2, _ = make_virtual_context({"ser1": ["FW v3.2 ready"]})
    step_lit = _console_step(expect_pass_re=r"FW v[\d.]+ ready",
                             expect_pass_is_regex=False,
                             capture_is_expected=True)
    assert execute_fct_step(step_lit, ctx2).verdict == VERDICT_FAIL


# ------------------------------------------- M22h wait -> send clean bytes
def test_console_line_is_payload_plus_one_newline():
    """The shared console writer emits the payload and ONE '\n' - a
    leading byte (or '\r\n') would make the DUT's input() read an
    empty answer."""
    from mtkgui.engine.fct_exec import console_line
    assert console_line("y") == "y\n"
    assert console_line("") == "\n"
    assert not console_line("y").startswith(("\r", "\n"))


def test_console_confirm_then_send_is_exactly_y_newline():
    """Wait matched -> operator Yes -> mock serial receives EXACTLY
    b'y\\n' with NO leading bytes (M22h earphone regression)."""
    ctx, channels = make_virtual_context(
        {"ser1": [r"Did you hear the 1000 Hz tone from the 3.5 mm "
                  r"earphone?"]})
    step = _console_step(
        send="y", send_enabled=True, confirm_enabled=True,
        confirm_message="MQS audio: did you hear the tone?",
        expect_pass_re=r"Did you hear the \d+ Hz tone",
        expect_pass_is_regex=True, capture_is_expected=True)
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert channels["ser1"].written == ["y\n"]


def test_console_wait_only_row_never_writes_bytes():
    """A wait-only row must NOT leave a bare newline in the tty queue
    (the bf4723b rule): the mock serial receives nothing at all."""
    ctx, channels = make_virtual_context({"ser1": ["login:"]})
    step = _console_step(kind="wait", expect_pass_re="login:",
                         capture_is_expected=True)
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS
    assert channels["ser1"].written == []


def test_skip_marker():
    ctx, _ = make_virtual_context()
    step = FctStep(name="s", step_type="MESSAGE_CHECK", channel="ser1",
                   params={"skip": True})
    assert execute_fct_step(step, ctx).verdict == VERDICT_SKIP


def test_gui_confirm_human_answers():
    # GO -> PASS
    ctx, _ = make_virtual_context(human_answers=[True])
    step = FctStep(name="Flash FAT Firmware", step_type="GUI_CONFIRM",
                   timeout_s=0)
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS
    # STOP -> FAIL
    ctx, _ = make_virtual_context(human_answers=[False])
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_FAIL and "STOP" in out.reason
    # no hook bound -> ERROR
    ctx = FctContext()
    assert execute_fct_step(step, ctx).verdict == VERDICT_ERROR


def test_cli_run_channel_keyword_and_command_evidence():
    ctx, channels = make_virtual_context(
        {"ser1": ["blhost: success, image written"]})
    step = FctStep(name="flash", step_type="CLI_RUN", channel="ser1",
                   command="blhost flash-image fat.bin",
                   expect_pass=["success"], timeout_s=2)
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert channels["ser1"].written == ["blhost flash-image fat.bin"]


def test_cli_run_host_subprocess_joint_judgement():
    """Host CLI: positive keyword + exit code 0 -> PASS; a non-zero
    exit flips the verdict to FAIL even with a positive keyword."""
    import sys
    win = sys.platform == "win32"
    step = FctStep(name="host", step_type="CLI_RUN",
                   command="echo success", expect_pass=["success"],
                   timeout_s=10, params={"host_cli": True})
    ctx = FctContext(station_id="S", user="u")
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS

    # print a positive keyword then exit non-zero (platform shell syntax)
    bad_cmd = ("echo success & exit 3" if win
               else "echo success; exit 3")
    bad = FctStep(name="host", step_type="CLI_RUN",
                  command=bad_cmd, expect_pass=["success"],
                  timeout_s=10, params={"host_cli": True})
    out = execute_fct_step(bad, ctx)
    assert out.verdict == VERDICT_FAIL and "exit code" in out.reason


def test_subprocess_channel_captures_lines():
    ch = SubprocessFctChannel(timeout_s=10)
    ch.write("echo hello-world")
    assert any("hello-world" in line for line in ch.read_lines())
    assert ch.exit_code == 0


def test_external_tool_command_then_confirm():
    """D1-A RF adaptation: CLI capture PASSes, then the human confirm
    decides (params.confirm)."""
    ctx, _ = make_virtual_context(
        {"ser1": ["iperf3: 92.4 Mbits/sec"]}, human_answers=[True])
    step = FctStep(name="wifi", step_type="EXTERNAL_TOOL",
                   channel="ser1", command="iperf3 -c x",
                   expect_pass=["mbits/sec"], timeout_s=2,
                   params={"tool_family": "wifi", "confirm": True})
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS
    # STOP after a good capture still FAILs
    ctx, _ = make_virtual_context(
        {"ser1": ["iperf3: 92.4 Mbits/sec"]}, human_answers=[False])
    assert execute_fct_step(step, ctx).verdict == VERDICT_FAIL


def test_eventlog_lines_carry_identity():
    logged = []
    ctx, channels = make_virtual_context({"ser1": ["PASSED"]})
    ctx.log_sink = logged.append
    execute_fct_step(FctStep(name="m", step_type="MESSAGE_CHECK",
                             channel="ser1", expect_pass=["passed"],
                             timeout_s=2), ctx)
    assert all(line.startswith("[STATION-A] [op]") for line in logged)
    assert any("verdict PASS" in line for line in logged)


# --------------------------------------------------------- credentials
def test_credentials_env_fallback_with_explicit_warning(monkeypatch):
    monkeypatch.setenv("MTK_CRED_SSH1", "s3cret")
    value, warning = get_credential("ssh1")
    assert value == "s3cret"
    assert "fallback" in warning.lower()      # NEVER silent


def test_credentials_missing_raises(monkeypatch):
    monkeypatch.delenv("MTK_CRED_GHOST", raising=False)
    with pytest.raises(CredentialUnavailable):
        get_credential("ghost")


def test_credentials_refuse_empty_ref():
    with pytest.raises(CredentialUnavailable):
        get_credential("")


# ------------------------------------------- runner integration (virtual)
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _load_fct_sequence_into(page, seq):
    cases = to_project_fct_cases(seq)
    page.fct_rows = [str(c["name"]) for c in cases]
    page.fct_enables = [bool(c.get("enable", True)) for c in cases]
    page.fct_waits = [int(c.get("wait_ms", 100)) for c in cases]
    page.fct_timeouts = [int(c.get("timeout_ms", 5000)) for c in cases]
    page.fct_kinds = [str(c.get("kind", "MessageOK")) for c in cases]
    page.fct_op_params = [dict(c.get("op_params") or {}) for c in cases]
    page.fct.setRowCount(len(cases))
    page.fct_comments = [""] * len(cases)
    page.fct_breakpoints = set()


def test_runner_executes_fct_build_sequence_virtual(qapp):
    """End-to-end (CLI path): the published sequence runs through the
    runner; the CLI flash step reads the injected virtual output and
    the message rows answer via the simulated human hook."""
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    page.set_mode("Virtual")     # the flash simulation is Virtual-only
    seq = build_fct_sequence("e2e-cli", flash_mode=FLASH_CLI,
                             channel="ser1",
                             cli_command="blhost flash-image fat.bin",
                             cli_done_keyword="success")
    _load_fct_sequence_into(page, seq)
    page.fct_virtual_script = {
        "ser1": ["blhost: success, image written"]}
    page.project_path = "virtual-dummy.yaml"
    page.run_demo()
    results = [page.fct.item(r, 4).text()
               for r in range(page.fct.rowCount())]
    assert results, "no FCT results rendered"
    assert all(r in ("PASS", "Done") for r in results), results
    page.deleteLater()


def test_runner_gui_flash_path_virtual(qapp):
    """End-to-end (GUI path): every GUI_CONFIRM answers GO via the
    simulated human hook; the whole sequence PASSes."""
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    page.set_mode("Virtual")     # the flash simulation is Virtual-only
    seq = build_fct_sequence("e2e-gui", flash_mode=FLASH_GUI)
    _load_fct_sequence_into(page, seq)
    page.project_path = "virtual-dummy.yaml"
    page.run_demo()
    results = [page.fct.item(r, 4).text()
               for r in range(page.fct.rowCount())]
    assert all(r in ("PASS", "Done") for r in results), results
    page.deleteLater()


def test_runner_fct_fail_blocks_overall(qapp):
    """A CLI step whose injected output contains a negative keyword
    FAILs the row (and a failed FCT row keeps Overall honest)."""
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    seq = build_fct_sequence("e2e-fail", flash_mode=FLASH_CLI,
                             channel="ser1", cli_command="blhost x",
                             cli_done_keyword="success")
    _load_fct_sequence_into(page, seq)
    page.fct_virtual_script = {"ser1": ["error: flash refused"]}
    page.project_path = "virtual-dummy.yaml"
    page.run_demo()
    assert page.fct.item(0, 4).text() == "FAIL"
    page.deleteLater()


def test_load_fct_cases_keeps_manual_standard_ops(qapp):
    """P3-B7 merge protection: standard operator dialogs added by hand
    on the Test Work Flow page (MessageOK/YesNo/GoStop rows without a
    generated fct_step marker) survive a sequence rebuild - they are
    appended after the generated cases, never silently wiped."""
    from mtkgui.test_workflow_page import TestWorkFlowPage
    page = TestWorkFlowPage()
    # the page constructor preloads demo rows (manual standard ops) -
    # start from an empty table so the assertions stay deterministic
    page.fct_rows = []
    page.fct_kinds = []
    page.fct_enables = []
    page.fct_waits = []
    page.fct_timeouts = []
    page.fct_op_params = []
    cases = to_project_fct_cases(
        build_fct_sequence("e2e-merge", flash_mode=FLASH_GUI))
    page.load_fct_cases(cases)
    n_generated = len(page.fct_rows)
    # the operator adds standard ops by hand on the page
    page.fct_kinds = list(page.fct_kinds) + ["MessageYesNo", "MessageOK"]
    page.fct_rows = list(page.fct_rows) + ["Swap DUT fixture", "Check power"]
    page.fct_enables = list(page.fct_enables) + [True, True]
    page.fct_waits = list(page.fct_waits) + [100, 100]
    page.fct_timeouts = list(page.fct_timeouts) + [30000, 10000]
    page.fct_op_params = list(page.fct_op_params) + [None, None]
    # rebuild the SAME sequence: manual rows are kept at the end
    page.load_fct_cases(cases)
    assert page.fct_rows[:n_generated] == [str(c["name"]) for c in cases]
    assert page.fct_rows[-2:] == ["Swap DUT fixture", "Check power"]
    assert page.fct_kinds[-2:] == ["MessageYesNo", "MessageOK"]
    # a manual row whose name matches a generated row is NOT duplicated
    page.fct_rows[-1] = page.fct_rows[0]
    page.load_fct_cases(cases)
    assert page.fct_rows.count(page.fct_rows[0]) == 1
    page.deleteLater()


def test_standard_op_row_runs_instrument_op_not_dialog():
    """P3-B5 FCT setup: a GUI_CONFIRM carrying params.op drives the
    rack PSU / fixture (run_op hook), not an operator MessageGoStop."""
    calls = []

    def run_op(name, params):
        calls.append((name, params))
        return "Done"

    def must_not_call(_s):
        raise AssertionError("op rows must not open a confirm dialog")

    ctx = FctContext(run_op=run_op, human_confirm=must_not_call)
    step = FctStep(name="Power On DUT", step_type="GUI_CONFIRM",
                   timeout_s=0, params={"op": "Power On DUT"})
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert calls and calls[0][0] == "Power On DUT"
    # catalog defaults (power type / voltage) are supplied to the runner
    assert calls[0][1].get("type") == "power"


def test_standard_op_error_verdict():
    ctx = FctContext(run_op=lambda n, p: "Error")
    step = FctStep(name="Fixture Clamp Down", step_type="GUI_CONFIRM",
                   timeout_s=0, params={"op": "Fixture Clamp Down"})
    assert execute_fct_step(step, ctx).verdict == VERDICT_ERROR


def test_standard_op_without_runner_is_error():
    ctx = FctContext()   # no run_op hook bound
    step = FctStep(name="Power On DUT", step_type="GUI_CONFIRM",
                   timeout_s=0, params={"op": "Power On DUT"})
    assert execute_fct_step(step, ctx).verdict == VERDICT_ERROR


# ----------------------------------------------- RF per-sub-test execution
import mtkgui.engine.fct_exec as fe
import mtkgui.engine.rf_adapters as rf_adapters


def test_is_lan_ipv4_classification():
    assert fe._is_lan_ipv4("192.168.10.141")
    assert fe._is_lan_ipv4("172.20.10.1")
    assert fe._is_lan_ipv4("10.0.0.5")
    assert not fe._is_lan_ipv4("127.0.0.1")
    assert not fe._is_lan_ipv4("169.254.10.2")
    assert not fe._is_lan_ipv4("0.0.0.0")
    assert not fe._is_lan_ipv4("not-an-ip")


def test_host_lan_ip_auto_detect(monkeypatch):
    import platform
    import subprocess

    class _R:
        def __init__(self, out):
            self.stdout = out

    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **k: _R("192.168.10.141\n"
                            if cmd[:2] == ["ipconfig", "getifaddr"]
                            else ""))
    ctx = FctContext()
    assert fe.host_lan_ip(ctx) == "192.168.10.141"


def _wifi_step():
    return fe.FctStep(
        name="Wi-Fi Connect & Ping", step_type="EXTERNAL_TOOL",
        channel="", timeout_s=15.0,
        params={"tool_family": "wifi",
                "fct_rf": {"mode": "full_stack", "any_reply": True}})


def test_connect_ping_passes_on_single_reply(monkeypatch):
    # adapter would FAIL on its strict 5%-loss gate, but the >=1-reply
    # rule overrides it (loss < 100%)
    class FakeWifi:
        def __init__(self, cfg, runner):
            pass

        def run_test(self):
            return {"verdict": "Fail",
                    "items": {"loss_pct": 99.0, "rssi_dbm": -45},
                    "lines": ["1 received, 99 lost"]}
    monkeypatch.setattr(rf_adapters, "WifiAdapter", FakeWifi)
    out = fe._run_rf_tool(_wifi_step(), "wifi", FctContext())
    assert out.verdict == VERDICT_PASS


def test_connect_ping_fails_when_no_reply(monkeypatch):
    class FakeWifi:
        def __init__(self, cfg, runner):
            pass

        def run_test(self):
            return {"verdict": "Fail", "items": {"loss_pct": 100.0},
                    "lines": ["0 received, 20 lost"]}
    monkeypatch.setattr(rf_adapters, "WifiAdapter", FakeWifi)
    out = fe._run_rf_tool(_wifi_step(), "wifi", FctContext())
    assert out.verdict == VERDICT_FAIL


def test_iperf_missing_server_ip_is_error(monkeypatch):
    # empty configured IP and undetectable host IP -> explicit ERROR
    monkeypatch.setattr(fe, "host_lan_ip", lambda ctx: "")
    step = fe.FctStep(
        name="iperf", step_type="EXTERNAL_TOOL", channel="ser1",
        timeout_s=15.0,
        params={"tool_family": "wifi",
                "fct_wifi_iperf": {"tool": "iperf3", "server_ip": "",
                                   "min_mbps": 10.0, "duration": 10}})
    ctx = FctContext()
    ctx.channels = {"ser1": object()}      # a console channel exists
    out = fe._execute_once(step, ctx)
    assert out.verdict == VERDICT_ERROR


# ---------------------------------------------------- SFTP transfer rows
class _SftpChannel:
    """Fake SSH channel exposing the SFTP surface fct_exec uses."""

    def __init__(self):
        self.downloaded = []
        self.removed = []

    def get_file(self, remote, local):
        self.downloaded.append((remote, local))

    def put_file(self, local, remote):
        self.uploaded = (local, remote)

    def remove_file(self, remote):
        self.removed.append(remote)


class _PlainChannel:
    """Channel WITHOUT the SFTP surface (e.g. a serial console)."""


def _sftp_step(kind, local, remote):
    return FctStep(name=f"sftp {kind}", step_type="MESSAGE_CHECK",
                   channel="ser1",
                   params={"kind": kind, "action": kind, "local": local,
                           "remote": remote}, timeout_s=5)


def test_sftp_get_fetches_into_dut_report_and_removes_remote(tmp_path):
    chan = _SftpChannel()
    ctx = FctContext(channels={"ser1": chan}, station_id="S", user="u",
                     dut_report=str(tmp_path))
    out = execute_fct_step(
        _sftp_step("sftp_get", "{{dut_report}}/fat_result.json",
                   "/root/fat_result.json"), ctx)
    assert out.verdict == VERDICT_PASS
    assert chan.downloaded == [("/root/fat_result.json",
                                str(tmp_path / "fat_result.json"))]
    assert chan.removed == ["/root/fat_result.json"]
    assert "DUT file removed" in out.reason


def test_sftp_get_without_dut_report_token_uses_local_as_is(tmp_path):
    chan = _SftpChannel()
    ctx = FctContext(channels={"ser1": chan}, station_id="S", user="u")
    out = execute_fct_step(
        _sftp_step("sftp_get", str(tmp_path / "plain.json"),
                   "/root/plain.json"), ctx)
    assert out.verdict == VERDICT_PASS
    assert chan.removed == ["/root/plain.json"]


def test_sftp_get_fails_when_channel_has_no_sftp():
    ctx = FctContext(channels={"ser1": _PlainChannel()},
                     station_id="S", user="u", dut_report="C:\\tmp")
    out = execute_fct_step(
        _sftp_step("sftp_get", "{{dut_report}}/fat.json", "/root/fat.json"),
        ctx)
    assert out.verdict == VERDICT_ERROR
    assert "no SFTP get_file" in out.reason


def test_sftp_put_passes_over_sftp_channel(tmp_path):
    chan = _SftpChannel()
    ctx = FctContext(channels={"ser1": chan}, station_id="S", user="u",
                     dut_report=str(tmp_path))
    out = execute_fct_step(
        _sftp_step("sftp_put", "{{dut_report}}/script.sh",
                   "/root/script.sh"), ctx)
    assert out.verdict == VERDICT_PASS
    assert chan.uploaded == (str(tmp_path / "script.sh"), "/root/script.sh")


def test_sftp_get_action_args_may_keep_the_remote_file(tmp_path):
    """Unified action registry: ``remove_remote_file`` is a per-step arg;
    a project opts out without touching the executor (default = the
    historic remove-after-fetch behaviour)."""
    chan = _SftpChannel()
    ctx = FctContext(channels={"ser1": chan}, station_id="S", user="u",
                     dut_report=str(tmp_path))
    step = _sftp_step("sftp_get", "{{dut_report}}/sub/fat.json",
                      "/root/fat.json")
    step.params["args"] = {"remove_remote_file": False}
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert chan.removed == []
    assert (tmp_path / "sub" / "fat.json").parent.is_dir()


def test_sftp_get_action_args_may_skip_local_dir_creation(tmp_path):
    chan = _SftpChannel()
    ctx = FctContext(channels={"ser1": chan}, station_id="S", user="u")
    missing = tmp_path / "no-such-dir" / "fat.json"
    step = _sftp_step("sftp_get", str(missing), "/root/fat.json")
    step.params["args"] = {"create_local_dir": False}
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert not missing.parent.exists()


# ------------------------------------------------------------- M27 P8
def test_bind_sftp_channel_builds_ssh_channel_from_step_endpoint(monkeypatch):
    """bind_sftp_channel binds an SshFctChannel (credential layer) under
    the step's own 'ssh' channel key; without a host it binds nothing."""
    import mtkgui.engine.fct_channels as fct_channels
    built = []
    class _FakeSsh:
        kind = "ssh"
        def __init__(self, host, username, credential_ref, **kw):
            built.append((host, username, credential_ref))
    monkeypatch.setattr(fct_channels, "SshFctChannel", _FakeSsh)

    step = FctStep(name="Get fat", step_type="MESSAGE_CHECK", channel="ssh",
                   params={"kind": "sftp_get", "ssh_host": "192.168.1.20",
                           "ssh_username": "root"})
    ctx = FctContext()
    assert bind_sftp_channel(step, ctx) is True
    assert "ssh" in ctx.channels
    assert built == [("192.168.1.20", "root", "fct_ssh_192.168.1.20")]

    # no host -> not bound
    step2 = FctStep(name="Get fat", step_type="MESSAGE_CHECK", channel="ssh",
                    params={"kind": "sftp_get", "ssh_host": ""})
    ctx2 = FctContext()
    assert bind_sftp_channel(step2, ctx2) is False
    assert "ssh" not in ctx2.channels


def test_sftp_get_runs_over_an_ssh_kind_channel(tmp_path):
    """The sftp executor uses the bound ssh channel's get_file/remove_file
    (kind == 'ssh'), matching a real SshFctChannel surface."""
    class _SshKind:
        kind = "ssh"
        def __init__(self):
            self.downloaded = []
            self.removed = []
        def get_file(self, remote, local):
            self.downloaded.append((remote, local))
        def remove_file(self, remote):
            self.removed.append(remote)

    chan = _SshKind()
    ctx = FctContext(channels={"ssh": chan}, station_id="S", user="u",
                     dut_report=str(tmp_path))
    step = FctStep(name="Get fat", step_type="MESSAGE_CHECK", channel="ssh",
                   timeout_s=5,
                   params={"kind": "sftp_get", "action": "sftp_get",
                           "local": "{{dut_report}}/fat.json",
                           "remote": "/root/fat.json"})
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert chan.downloaded == [("/root/fat.json", str(tmp_path / "fat.json"))]
    assert chan.removed == ["/root/fat.json"]


# ------------------------------------------ unified model (2026-10-28)
def test_one_interact_step_waits_then_sends_then_captures():
    """ONE step = ONE row: the WaitFor stage runs BEFORE the answer is
    written, then the send, then the capture (no '(wait)' pre-step)."""
    from mtkgui.engine.fct_channels import VirtualFctChannel
    ctx, _ = make_virtual_context()
    ch = VirtualFctChannel()
    ctx.channels["ser1"] = ch
    ch.inject_output("PRESS BUTTON 1 THEN CONFIRM")

    def _on_log(msg):
        if "console send" in msg:
            ch.inject_output("LED1 OK")

    ctx.log_sink = _on_log
    step = FctStep(name="Button 1 / LED", step_type="MESSAGE_CHECK",
                   channel="ser1", timeout_s=2,
                   params={"fct_console": True, "kind": "send",
                           "wait_enabled": True,
                           "wait_pattern": "PRESS BUTTON 1 THEN CONFIRM",
                           "wait_timeout": 2.0, "wait_is_regex": False,
                           "send_enabled": True, "send": "y",
                           "capture_enabled": True,
                           "expect_pass_re": "LED1 OK",
                           "capture_is_expected": True})
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    # exactly the configured terminator, no leading stray byte
    assert ch.written == ["y\n"]


def test_interact_step_does_not_send_when_the_wait_times_out():
    """The answer must never be written when the awaited prompt did not
    arrive (it would leak into the DUT's next input())."""
    from mtkgui.engine.fct_channels import VirtualFctChannel
    ctx, _ = make_virtual_context()
    ch = VirtualFctChannel()             # silence: prompt never arrives
    ctx.channels["ser1"] = ch
    step = FctStep(name="Button 1 / LED", step_type="MESSAGE_CHECK",
                   channel="ser1", timeout_s=0.3,
                   params={"fct_console": True, "kind": "send",
                           "wait_enabled": True,
                           "wait_pattern": "PRESS BUTTON 1 THEN CONFIRM",
                           "wait_timeout": 0.3,
                           "send_enabled": True, "send": "y",
                           "capture_enabled": False})
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_FAIL
    assert ch.written == []


def test_legacy_confirm_marker_never_pops_a_dialog():
    """Unified model item 3: only an explicit ``dialog`` step pops a
    dialog.  A stale params.confirm_enabled marker runs dialog-free."""
    ctx, _ = make_virtual_context({"ser1": ["OK"]})

    def _no_dialog(_step):
        raise AssertionError("implicit dialog popped")

    ctx.human_confirm = _no_dialog
    step = FctStep(name="legacy", step_type="MESSAGE_CHECK", channel="ser1",
                   timeout_s=2,
                   params={"fct_console": True, "kind": "send",
                           "confirm_enabled": True,
                           "wait_enabled": False, "send_enabled": False,
                           "capture_enabled": False,
                           "expect_pass_re": "OK",
                           "capture_is_expected": True})
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS


def test_explicit_dialog_step_pops_exactly_once():
    """An explicit console_dialog step is the ONLY path that asks the
    operator (the runner-owned hook delivers the answer)."""
    from mtkgui.engine.fct_channels import VirtualFctChannel
    ctx, _ = make_virtual_context()
    ch = VirtualFctChannel()
    ctx.channels["ser1"] = ch
    asked: list = []

    def _answer(step):
        asked.append(step.name)
        return True

    ctx.human_confirm = _answer
    step = FctStep(name="Confirm: Earphone", step_type="GUI_CONFIRM",
                   channel="ser1", timeout_s=0.0,
                   params={"style": "yesno", "console_dialog": True,
                           "message": "Did you hear it?",
                           "wait_pattern": "", "wait_timeout": 0.0,
                           "send_yes": "y", "send_no": "n"})
    out = execute_fct_step(step, ctx)
    assert out.verdict == VERDICT_PASS
    assert asked == ["Confirm: Earphone"]
