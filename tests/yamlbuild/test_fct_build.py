# -*- coding: utf-8 -*-
"""fct_build (M160): category + type model, YAML round trips, the
skeleton generator and the project-YAML fct_test_cases mapping.

RED LINE mirrors the module's: these tests cover STRUCTURE only — no
execution engine, no channel I/O, no message judging.
"""
from __future__ import annotations

import pytest
import yaml

from mtkgui.engine.step_types import (
    CATEGORY_CONSOLE,
    CATEGORY_EXTERNAL_GUI,
    CATEGORY_MESSAGE,
    CATEGORY_OPERATION,
    CATEGORY_TRANSFER,
    CATEGORY_WIFI,
)
from mtkgui.gui.yamlbuild.fct_build import (
    DEFAULT_KEYWORD_FAIL,
    DEFAULT_KEYWORD_PASS,
    FctSequence,
    FctStep,
    action_args,
    build_fct_sequence,
    from_project_fct_cases,
    normalize_fct_cases,
    normalize_fct_steps,
    strip_legacy_name_suffix,
    to_project_fct_cases,
)

EXAMPLES = (
    "docs/fct/examples/fct_sequence_gui_flash.yaml",
    "docs/fct/examples/fct_sequence_cli_flash.yaml",
)


def _step(name, category=CATEGORY_CONSOLE, sub_type="serial", **kwargs):
    return FctStep(name=name, category=category, type=sub_type, **kwargs)


# ------------------------------------------------------------- data model
def test_step_validation_rules():
    ok = _step("s1")
    assert ok.validate({"s1"}) == []
    bad = FctStep(name="", category="NOPE", type="nope", timeout_s=-1,
                  retries=-2, on_fail="whatever", depends=["ghost"])
    errors = " ".join(bad.validate({"s1"}))
    for fragment in ("name must not be empty", "unknown category",
                     "timeout_s", "retries", "on_fail", "unknown dependency"):
        assert fragment in errors, fragment
    bad_type = FctStep(name="s", category=CATEGORY_CONSOLE, type="flash")
    assert "not valid for category" in " ".join(bad_type.validate({"s"}))
    no_cmd = FctStep(name="c", category=CATEGORY_CONSOLE, type="cli")
    assert "requires a command" in " ".join(no_cmd.validate({"c"}))


def test_sequence_validation_duplicates_and_defaults():
    seq = FctSequence(name="dup", steps=[_step("a"), _step("a")])
    assert "duplicate step names" in " ".join(seq.validate())
    seq2 = FctSequence(name="x", steps=[_step("a")])
    assert seq2.keyword_pass == list(DEFAULT_KEYWORD_PASS)
    assert seq2.keyword_fail == list(DEFAULT_KEYWORD_FAIL)


# ------------------------------------------------------- YAML round trip
@pytest.mark.parametrize("seq", [
    build_fct_sequence("gui-path", flash_mode="gui"),
    build_fct_sequence("cli-path", flash_mode="cli", channel="ser1",
                       cli_command="blhost flash-image fat.bin",
                       cli_done_keyword="success",
                       body_steps=[_step(
                           "iperf", category=CATEGORY_CONSOLE,
                           sub_type="cli", channel="ser1",
                           command="iperf3 -c x",
                           expect_pass=["Mbits/sec"], retries=1)]),
])
def test_yaml_round_trip_identity(seq):
    back = FctSequence.from_yaml(seq.to_yaml())
    assert back.validate() == []
    again = FctSequence.from_yaml(back.to_yaml())
    assert again.to_dict() == back.to_dict()
    for step in back.to_dict()["steps"]:
        assert "category" in step and "type" in step
        assert "step_type" not in step


def test_from_yaml_missing_section_reports_invalid():
    seq = FctSequence.from_yaml("something: else")
    assert seq.name == ""
    assert seq.validate()  # non-empty error list


# ------------------------------------------------------------- generation
def test_skeleton_spine_order_and_modes():
    gui = build_fct_sequence("g", flash_mode="gui")
    assert gui.steps[0].category == CATEGORY_EXTERNAL_GUI
    assert gui.steps[0].type == "flash"
    assert gui.steps[0].params["slot"] == "fat"
    assert gui.steps[0].timeout_s == 0.0
    assert gui.steps[2].category == CATEGORY_EXTERNAL_GUI
    assert gui.steps[2].params["slot"] == "oobe"
    assert all(s.category == CATEGORY_OPERATION for s in gui.steps[-2:])

    cli = build_fct_sequence("c", flash_mode="cli", channel="ser1",
                             cli_command="blhost -p COM5 x",
                             cli_done_keyword="success")
    fat = cli.steps[0]
    assert (fat.category, fat.type) == (CATEGORY_CONSOLE, "cli")
    assert fat.params["slot"] == "fat"
    assert fat.command == "blhost -p COM5 x"
    assert "success" in fat.expect_pass
    assert fat.expect_fail == list(DEFAULT_KEYWORD_FAIL)


def test_generation_is_pure_structure():
    import mtkgui.gui.yamlbuild.fct_build as fb
    public = [n for n in dir(fb) if not n.startswith("_")
              and callable(getattr(fb, n))]
    assert all(not any(stem in n.lower()
                       for stem in ("execute", "connect", "judge"))
               for n in public)


# ------------------------------------------------- loader compatibility
def test_to_project_fct_cases_shape_matches_existing_loader():
    from mtkgui.engine.fct_test_config import STEP_TYPE_LABELS
    from mtkgui.engine.steps import FCT_METHODS

    seq = build_fct_sequence("compat", flash_mode="cli", channel="ser1",
                             cli_command="blhost -p COM5 x",
                             cli_done_keyword="success")
    cases = to_project_fct_cases(seq)
    known = set(FCT_METHODS) | set(STEP_TYPE_LABELS) | {"op"}
    for case in cases:
        assert case["kind"] in known, case["kind"]
        assert case["name"] and case["enable"] is True
        assert int(case["timeout_ms"]) >= 1000
        marker = case["op_params"]["fct_step"]
        assert marker["category"] and marker["type"]
        assert "step_type" not in marker
    assert cases[0]["kind"] == "Console_cli"
    assert any(c["kind"] == "op" for c in cases)


def test_gui_path_maps_to_messagegostop():
    seq = build_fct_sequence("g", flash_mode="gui")
    kinds = [c["kind"] for c in to_project_fct_cases(seq)]
    assert kinds[0] == "MessageGoStop"           # ExternalGui.flash


def test_wifi_rows_map_to_wifi_kinds():
    seq = FctSequence(name="rf", steps=[
        FctStep(name="wifi", category=CATEGORY_WIFI, type="scan"),
        FctStep(name="bt", category=CATEGORY_WIFI, type="iperf"),
    ])
    kinds = [c["kind"] for c in to_project_fct_cases(seq)]
    assert kinds == ["Wifi_Scan", "Wifi_Iperf"]


def test_serial_transfer_rows_map_to_transfer_kinds():
    seq = FctSequence(name="transfer", steps=[
        FctStep(name="SerialPush: fct_probe.sh",
                category=CATEGORY_TRANSFER, type="serial_put",
                channel="ser1",
                params={"fct_serial_transfer": {
                    "direction": "push", "local": "a.sh",
                    "remote": "/root/a.sh"}}),
        FctStep(name="SerialPull: probe_out.txt",
                category=CATEGORY_TRANSFER, type="serial_pull",
                channel="ser1",
                params={"fct_serial_transfer": {
                    "direction": "pull", "local": "out/probe_out.txt",
                    "remote": "/root/probe_out.txt"}}),
    ])
    cases = to_project_fct_cases(seq)
    assert [c["kind"] for c in cases] == ["SerialPush", "SerialPull"]
    marker = (cases[1]["op_params"]["fct_step"]["params"]
              ["fct_serial_transfer"])
    assert marker["local"] == "out/probe_out.txt"
    assert marker["remote"] == "/root/probe_out.txt"


def test_serial_transfer_kinds_round_trip():
    transfer = {"direction": "pull", "local": "out/probe_out.txt",
                "remote": "/root/fct_assets/probe_out.txt",
                "baud": 0, "console_baud": 115200}
    cases = [{"name": "SerialPull: probe_out.txt",
              "kind": "SerialPull", "enable": True, "wait_ms": 100,
              "timeout_ms": 2000,
              "op_params": {"fct_step": {
                  "name": "SerialPull: probe_out.txt",
                  "category": CATEGORY_TRANSFER, "type": "serial_pull",
                  "params": {"fct_serial_transfer": transfer}}}}]
    step = from_project_fct_cases(cases).steps[0]
    assert (step.category, step.type) == (CATEGORY_TRANSFER, "serial_pull")
    assert step.params["fct_serial_transfer"] == transfer


def test_from_project_fct_cases_rejects_legacy_rows():
    with pytest.raises(ValueError, match="no op_params.fct_step"):
        from_project_fct_cases([{"name": "old", "kind": "MessageOK"}])
    with pytest.raises(ValueError, match="unknown category/type"):
        from_project_fct_cases([{
            "name": "bad", "kind": "MessageOK",
            "op_params": {"fct_step": {"name": "bad",
                                       "category": "Console",
                                       "type": "flash"}}}])


def test_round_trip_through_project_shape_is_lossless():
    seq = build_fct_sequence("rt", flash_mode="gui")
    cases = to_project_fct_cases(seq)
    back = from_project_fct_cases(cases, name="rt")
    assert [s.name for s in back.steps] == [s.name for s in seq.steps]
    assert [s.to_dict() for s in back.steps] == \
        [s.to_dict() for s in seq.steps]


# ------------------------------------------------------------- examples
@pytest.mark.parametrize("path", EXAMPLES)
def test_example_documents_load_and_validate(path):
    seq = FctSequence.from_yaml(open(path, encoding="utf-8").read())
    assert seq.validate() == [], path
    assert seq.flash_mode in ("gui", "cli")
    assert seq.steps, path
    cases = to_project_fct_cases(seq)
    assert cases and all(c.get("kind") for c in cases)


def test_examples_have_no_credentials():
    for path in EXAMPLES:
        text = open(path, encoding="utf-8").read()
        doc = yaml.safe_load(text)
        flat = str(doc).lower()
        for forbidden in ("password", "secret", "token", "credential:"):
            assert forbidden not in flat, (path, forbidden)


# ------------------------------------------------------- action helpers
def test_action_args_defaults_and_per_step_override():
    step = FctStep(name="Get fat", category=CATEGORY_TRANSFER,
                   type="sftp_get", channel="ser1",
                   params={"kind": "sftp_get", "action": "sftp_get",
                           "local": "{{dut_report}}/fat_result.json",
                           "remote": "/root/fat_result.json"})
    defaults = action_args(step)
    assert defaults["remove_remote_file"] is True
    assert defaults["create_local_dir"] is True
    step.params["args"] = {"remove_remote_file": False}
    effective = action_args(step)
    assert effective["remove_remote_file"] is False
    assert effective["create_local_dir"] is True
    assert FctStep.from_dict(step.to_dict()).params["args"] == \
        {"remove_remote_file": False}


def test_action_args_row_timeout_is_the_single_source():
    step = FctStep(name="Get fat", category=CATEGORY_TRANSFER,
                   type="sftp_get", channel="ser1", timeout_s=20.0,
                   params={"kind": "sftp_get", "action": "sftp_get",
                           "local": "l", "remote": "r"})
    assert action_args(step)["timeout_s"] == 20.0
    step.params["args"] = {"timeout_s": 45.0}
    assert action_args(step)["timeout_s"] == 45.0
    step.params = {"kind": "sftp_get", "action": "sftp_get"}
    step.timeout_s = 0.0
    assert action_args(step)["timeout_s"] == 30.0


# ------------------------------------------------------ normalization
def test_legacy_wait_pre_step_merges_into_one_row():
    wait = _step("Earphone (wait)", timeout_s=10,
                 params={"fct_console": True, "kind": "wait",
                         "expect_pass_re": "tone?"})
    main = _step("Earphone", timeout_s=5,
                 params={"fct_console": True, "kind": "send",
                         "expect_pass_re": "heard", "send": "y"})
    out = normalize_fct_steps([wait, main])
    assert [s.name for s in out] == ["Earphone"]
    assert out[0].params["wait_enabled"] is True
    assert out[0].params["wait_pattern"] == "tone?"
    assert out[0].params["wait_timeout"] == 10.0
    assert [s.to_dict() for s in normalize_fct_steps(out)] == \
        [s.to_dict() for s in out]


def test_legacy_confirm_marker_becomes_explicit_dialog_step():
    step = _step("Earphone", timeout_s=5,
                 params={"fct_console": True, "confirm_enabled": True,
                         "confirm_message": "Did you hear it?", "send": "y"})
    out = normalize_fct_steps([step])
    assert [s.name for s in out] == ["Earphone", "Confirm: Earphone"]
    dlg = out[1]
    assert (dlg.category, dlg.type) == (CATEGORY_MESSAGE, "yesno_console")
    assert dlg.params["console_dialog"] is True
    assert dlg.params["message"] == "Did you hear it?"
    assert [s.to_dict() for s in normalize_fct_steps(out)] == \
        [s.to_dict() for s in out]


def test_normalize_fct_cases_collapses_legacy_rows_without_data_loss():
    wait = _step("Earphone (wait)", timeout_s=10,
                 params={"fct_console": True, "kind": "wait",
                         "expect_pass_re": "tone?"})
    main = _step("Earphone", timeout_s=5,
                 params={"fct_console": True, "kind": "send",
                         "send": "y", "expect_pass_re": "heard"})
    cases = [
        {"name": "Earphone (wait)", "kind": "CapturefromConsole",
         "op_params": {"fct_step": wait.to_dict()}},
        {"name": "Earphone", "kind": "CapturefromConsole",
         "op_params": {"fct_step": main.to_dict()}},
        {"name": "Manual dialog", "kind": "MessageOK", "op_params": None},
    ]
    out = normalize_fct_cases(cases)
    assert [c["name"] for c in out] == ["Earphone", "Manual dialog"]
    marker = out[0]["op_params"]["fct_step"]
    assert marker["params"]["wait_pattern"] == "tone?"
    assert marker["params"]["wait_enabled"] is True
    assert marker["params"]["send"] == "y"
    assert normalize_fct_cases(out) == out


def test_strip_legacy_name_suffix():
    for raw, want in [
        ("Console login: 'done' (expected)", "Console login"),
        ("fat.py: HDMI visual: 'visual command completed' (expected)",
         "fat.py: HDMI visual"),
        ("Console login (wait): 'done' (expected)", "Console login (wait)"),
        ("fat.py: MQS earphone tone", "fat.py: MQS earphone tone"),
    ]:
        assert strip_legacy_name_suffix(raw) == want, raw
        assert strip_legacy_name_suffix(
            strip_legacy_name_suffix(raw)) == want


def test_legacy_name_suffix_stripped_on_case_normalization():
    step = FctStep(name="fat.py: MQS earphone tone: 'done' (expected)",
                   category=CATEGORY_CONSOLE, type="serial", channel="ser1",
                   timeout_s=5,
                   params={"fct_console": True, "kind": "send", "send": "y"})
    cases = [
        {"name": "fat.py: MQS earphone tone: 'done' (expected)",
         "kind": "CapturefromConsole",
         "op_params": {"fct_step": step.to_dict()}},
        {"name": "Power on DUT: 'done' (expected)", "kind": "MessageGoStop",
         "op_params": None},
    ]
    out = normalize_fct_cases(cases)
    assert [c["name"] for c in out] == [
        "fat.py: MQS earphone tone", "Power on DUT"]
    assert normalize_fct_cases(out) == out


def test_sequence_from_dict_keeps_the_explicit_category_and_type():
    document = {"name": "s", "steps": [
        {"name": "Earphone (wait)", "category": CATEGORY_CONSOLE,
         "type": "serial", "channel": "ser1", "timeout_s": 10,
         "params": {"fct_console": True, "kind": "wait",
                    "expect_pass_re": "tone?"}},
        {"name": "Earphone", "category": CATEGORY_CONSOLE, "type": "serial",
         "channel": "ser1", "timeout_s": 5,
         "params": {"fct_console": True, "confirm_enabled": True,
                    "confirm_message": "Did you hear it?", "send": "y"}},
    ]}
    seq = FctSequence.from_dict(document)
    assert [s.name for s in seq.steps] == ["Earphone", "Confirm: Earphone"]
    saved = seq.to_dict()
    assert [(d["category"], d["type"]) for d in saved["steps"]] == [
        (CATEGORY_CONSOLE, "serial"), (CATEGORY_MESSAGE, "yesno_console")]
    again = FctSequence.from_dict(saved)
    assert again.to_dict() == saved


# -------------------------------------------------------- ExternalGui.flash
def test_external_gui_flash_slots():
    gui = build_fct_sequence("g", flash_mode="gui")
    flash = [s for s in gui.steps if s.category == CATEGORY_EXTERNAL_GUI]
    assert [s.params["slot"] for s in flash] == ["fat", "oobe"]
    cli = build_fct_sequence("c", flash_mode="cli", channel="ser1",
                             cli_command="blhost x", cli_done_keyword="ok")
    flash = [s for s in cli.steps if s.category == CATEGORY_CONSOLE
             and s.type == "cli"]
    assert [s.params["slot"] for s in flash] == ["fat", "oobe"]


def test_external_gui_flash_validate():
    bad_slot = FctStep(name="f", category=CATEGORY_EXTERNAL_GUI,
                       type="flash", params={"slot": "x"})
    assert "params.slot" in " ".join(bad_slot.validate({"f"}))
    ok = FctStep(name="f", category=CATEGORY_EXTERNAL_GUI, type="flash",
                 params={"slot": "fat"})
    assert ok.validate({"f"}) == []
