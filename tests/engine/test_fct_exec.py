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
    step = FctStep(name="host", step_type="CLI_RUN",
                   command="echo success", expect_pass=["success"],
                   timeout_s=10, params={"host_cli": True})
    ctx = FctContext(station_id="S", user="u")
    assert execute_fct_step(step, ctx).verdict == VERDICT_PASS

    bad = FctStep(name="host", step_type="CLI_RUN",
                  command="echo success; exit 3", expect_pass=["success"],
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
