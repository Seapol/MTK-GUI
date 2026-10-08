# -*- coding: utf-8 -*-
"""fct_build (P3-B3 PREPARATION) tests: the data model, YAML round
trips, the skeleton generator and the compatibility with the EXISTING
project YAML fct_test_cases loader.

RED LINE mirrors the module's: these tests cover STRUCTURE only — no
execution engine, no channel I/O, no message judging.
"""
from __future__ import annotations

import pytest
import yaml

from mtkgui.gui.yamlbuild.fct_build import (
    DEFAULT_KEYWORD_FAIL,
    DEFAULT_KEYWORD_PASS,
    FLASH_CLI,
    FLASH_GUI,
    FctSequence,
    FctStep,
    STEP_CLI_RUN,
    STEP_GUI_CONFIRM,
    STEP_MESSAGE_CHECK,
    STEP_TYPES,
    build_fct_sequence,
    from_project_fct_cases,
    to_project_fct_cases,
)

EXAMPLES = (
    "yaml_plan/examples/fct_sequence_gui_flash.yaml",
    "yaml_plan/examples/fct_sequence_cli_flash.yaml",
)


# ------------------------------------------------------------- data model
def test_step_validation_rules():
    """Spec §5.2: unknown type / empty name / bad timeout / retries /
    on_fail / CLI without command / unknown dependency -> errors."""
    ok = FctStep(name="s1", step_type=STEP_MESSAGE_CHECK)
    assert ok.validate({"s1"}) == []
    bad = FctStep(name="", step_type="NOPE", timeout_s=-1, retries=-2,
                  on_fail="whatever", depends=["ghost"])
    errors = " ".join(bad.validate({"s1"}))
    for fragment in ("name must not be empty", "unknown step_type",
                     "timeout_s", "retries", "on_fail", "unknown dependency"):
        assert fragment in errors, fragment
    no_cmd = FctStep(name="c", step_type=STEP_CLI_RUN)
    assert "requires a command" in " ".join(no_cmd.validate({"c"}))


def test_sequence_validation_duplicates_and_defaults():
    seq = FctSequence(name="dup", steps=[
        FctStep(name="a", step_type=STEP_MESSAGE_CHECK),
        FctStep(name="a", step_type=STEP_MESSAGE_CHECK),
    ])
    assert "duplicate step names" in " ".join(seq.validate())
    # defaults carry the configurable keyword tables
    seq2 = FctSequence(name="x", steps=[
        FctStep(name="a", step_type=STEP_MESSAGE_CHECK)])
    assert seq2.keyword_pass == list(DEFAULT_KEYWORD_PASS)
    assert seq2.keyword_fail == list(DEFAULT_KEYWORD_FAIL)


# ------------------------------------------------------------- YAML round trip
@pytest.mark.parametrize("seq", [
    build_fct_sequence("gui-path", flash_mode=FLASH_GUI),
    build_fct_sequence("cli-path", flash_mode=FLASH_CLI, channel="ser1",
                       cli_command="blhost flash-image fat.bin",
                       cli_done_keyword="success",
                       body_steps=[FctStep(
                           name="iperf", step_type=STEP_CLI_RUN,
                           channel="ser1", command="iperf3 -c x",
                           expect_pass=["Mbits/sec"], retries=1)]),
])
def test_yaml_round_trip_identity(seq):
    """to_yaml -> from_yaml reproduces the sequence field-by-field."""
    back = FctSequence.from_yaml(seq.to_yaml())
    assert back.validate() == []
    assert back.to_dict() == seq.to_dict()


def test_from_yaml_missing_section_reports_invalid():
    """A document without `fct_sequence` degrades to an invalid
    sequence (empty name) - validation reports it, no exception."""
    seq = FctSequence.from_yaml("something: else")
    assert seq.name == ""
    assert seq.validate()  # non-empty error list


# ------------------------------------------------------------- generation
def test_skeleton_spine_order_and_modes():
    """Spec §5.4: flash -> body -> OOBE -> teardown, both paths map to
    the declared step types."""
    gui = build_fct_sequence("g", flash_mode=FLASH_GUI)
    types = [s.step_type for s in gui.steps]
    assert types[0] == STEP_GUI_CONFIRM          # FAT via operator dialog
    assert gui.steps[0].params["slot"] == "fat"
    assert gui.steps[0].timeout_s == 0.0         # wait for the operator
    assert types[-4:] == [STEP_GUI_CONFIRM] * 4  # teardown tail
    assert gui.steps[2].params["slot"] == "oobe"

    cli = build_fct_sequence("c", flash_mode=FLASH_CLI, channel="ser1",
                             cli_command="blhost -p COM5 x",
                             cli_done_keyword="success")
    fat = cli.steps[0]
    assert fat.step_type == STEP_CLI_RUN
    assert fat.command == "blhost -p COM5 x"
    assert "success" in fat.expect_pass          # done marker positive
    assert fat.expect_fail == list(DEFAULT_KEYWORD_FAIL)


def test_generation_is_pure_structure():
    """RED LINE: the generator only produces data — the module exposes
    no execute/run/judge callables."""
    import mtkgui.gui.yamlbuild.fct_build as fb
    for forbidden in ("execute", "run", "judge", "connect", "verdict"):
        assert not any(name.startswith(forbidden)
                       for name in dir(fb) if callable(getattr(fb, name))
                       and not name.startswith("_")) or forbidden in (
            "run",) is False
    # positive check: no public callable carries these stems
    public = [n for n in dir(fb) if not n.startswith("_")
              and callable(getattr(fb, n))]
    assert all(not any(stem in n.lower()
                       for stem in ("execute", "connect", "judge"))
               for n in public)


# ------------------------------------------------- loader compatibility
def test_to_project_fct_cases_shape_matches_existing_loader():
    """The converted cases carry the EXISTING project YAML
    fct_test_cases shape: `kind` values are engine FCT methods / op
    (spec §5.6) so `project_config.apply_config` consumes them with
    zero changes."""
    from mtkgui.engine.steps import FCT_METHODS

    seq = build_fct_sequence("compat", flash_mode=FLASH_CLI,
                             channel="ser1",
                             cli_command="blhost -p COM5 x",
                             cli_done_keyword="success")
    cases = to_project_fct_cases(seq)
    for case in cases:
        assert case["kind"] in FCT_METHODS or case["kind"] == "op"
        assert case["name"] and case["enable"] is True
        assert int(case["timeout_ms"]) >= 1000
    # kind mapping: GUI_CONFIRM -> MessageGoStop, CLI_RUN -> SendtoCLI,
    # channel-less MESSAGE_CHECK -> MessageOK
    kinds = [c["kind"] for c in cases]
    assert kinds[0] == "SendtoCLI"               # CLI flash path
    assert "MessageGoStop" in kinds              # teardown ops
    assert any(c["name"].startswith("All Tests") for c in cases)


def test_gui_path_maps_to_messagegostop():
    seq = build_fct_sequence("g", flash_mode=FLASH_GUI)
    kinds = [c["kind"] for c in to_project_fct_cases(seq)]
    assert kinds[0] == "MessageGoStop"           # human confirm flash
    # every GUI_CONFIRM maps to MessageGoStop (the default MESSAGE_CHECK
    # body row maps to MessageOK)
    assert kinds.count("MessageGoStop") == \
        sum(1 for s in seq.steps if s.step_type == STEP_GUI_CONFIRM)


def test_external_tool_family_mapping():
    seq = FctSequence(name="rf", steps=[
        FctStep(name="wifi", step_type="EXTERNAL_TOOL",
                params={"tool_family": "wifi"}),
        FctStep(name="bt", step_type="EXTERNAL_TOOL",
                params={"tool_family": "bluetooth"}),
    ])
    kinds = [c["kind"] for c in to_project_fct_cases(seq)]
    assert kinds == ["WIFI", "Bluetooth"]


def test_round_trip_through_legacy_shape_is_lossless_enough():
    """from_project_fct_cases restores a sequence from the published
    cases and the legacy wait_ms granularity is preserved in params."""
    seq = build_fct_sequence("rt", flash_mode=FLASH_GUI)
    cases = to_project_fct_cases(seq)
    back = from_project_fct_cases(cases, name="rt")
    assert [s.name for s in back.steps] == [s.name for s in seq.steps]
    assert all(s.params.get("legacy") for s in back.steps)
    assert back.steps[0].params["legacy_wait_ms"] == 100


# ------------------------------------------------------------- examples
@pytest.mark.parametrize("path", EXAMPLES)
def test_example_documents_load_and_validate(path):
    """The two shipped examples parse, validate cleanly and carry the
    declared flash path."""
    seq = FctSequence.from_yaml(open(path, encoding="utf-8").read())
    assert seq.validate() == [], path
    assert seq.flash_mode in (FLASH_GUI, FLASH_CLI)
    assert seq.steps, path
    # every step type is one of the four vocabulary entries
    assert all(s.step_type in STEP_TYPES for s in seq.steps)
    # publishable: the converted cases are valid legacy loader input
    cases = to_project_fct_cases(seq)
    assert cases and all(c.get("kind") for c in cases)


def test_examples_have_no_credentials():
    """D4 red line: no plaintext credentials anywhere in the examples."""
    for path in EXAMPLES:
        text = open(path, encoding="utf-8").read()
        doc = yaml.safe_load(text)
        flat = str(doc).lower()
        for forbidden in ("password", "secret", "token", "credential:"):
            assert forbidden not in flat, (path, forbidden)
