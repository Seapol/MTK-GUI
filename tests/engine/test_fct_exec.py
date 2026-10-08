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
