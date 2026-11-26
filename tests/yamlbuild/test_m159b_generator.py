# -*- coding: utf-8 -*-
"""M159b: annotation -> FctStep generator (Plan A and Plan B)."""
from __future__ import annotations

import pytest

from mtkgui.gui.yamlbuild.fct_authoring import (
    MULTISELECT_SAME_WAIT,
    annotations_to_step,
    classify_target,
    resolve_multiselect,
    split_by_tx,
)
from mtkgui.gui.yamlbuild.fct_build import FctSequence
from mtkgui.gui.yamlbuild.fct_capture import (
    ANNOTATION_COMMAND,
    ANNOTATION_EXPECT_FAIL,
    ANNOTATION_EXPECT_PASS,
    CaptureAnnotation,
)


def _ann(text, kind, channel="dut"):
    return CaptureAnnotation(text=text, kind=kind, channel=channel)


def test_linux_shape_tx_plus_green_red_rx():
    annotations = [
        _ann("uname -r", ANNOTATION_COMMAND),
        _ann("Linux 6.6", ANNOTATION_EXPECT_PASS),
        _ann("panic", ANNOTATION_EXPECT_FAIL),
        _ann("reboot", ANNOTATION_COMMAND),
    ]
    step = annotations_to_step(annotations, "dut")
    assert step.command == "uname -r\nreboot"
    assert step.expect_pass == ["Linux 6.6"]
    assert step.expect_fail == ["panic"]
    assert step.channel == "dut"
    assert step.params["fct_console"] is True
    assert step.params["send_enabled"] is True
    assert step.params["capture_enabled"] is True


def test_bare_metal_listen_has_no_command():
    step = annotations_to_step(
        [_ann("BT_READY", ANNOTATION_EXPECT_PASS)], "ser1")
    assert step.command == ""
    assert step.params["send_enabled"] is False
    assert step.expect_pass == ["BT_READY"]
    assert step.channel == "ser1"


def test_split_by_tx_segments_rx_to_preceding_tx():
    annotations = [
        _ann("boot ok", ANNOTATION_EXPECT_PASS),
        _ann("uname -a", ANNOTATION_COMMAND),
        _ann("Linux", ANNOTATION_EXPECT_PASS),
        _ann("panic", ANNOTATION_EXPECT_FAIL),
        _ann("hciconfig", ANNOTATION_COMMAND),
        _ann("HCI", ANNOTATION_EXPECT_PASS),
    ]
    segments = split_by_tx(annotations)
    assert [[a.text for a in seg] for seg in segments] == [
        ["boot ok"],
        ["uname -a", "Linux", "panic"],
        ["hciconfig", "HCI"],
    ]
    steps = [annotations_to_step(seg, "dut") for seg in segments]
    assert [s.command for s in steps] == ["", "uname -a", "hciconfig"]
    assert steps[1].expect_pass == ["Linux"]
    assert steps[1].expect_fail == ["panic"]
    assert steps[2].expect_pass == ["HCI"]


def test_same_wait_vs_sequential_step_counts():
    words = ["OK", "READY", "DONE"]
    same = resolve_multiselect(words, MULTISELECT_SAME_WAIT)
    assert len(same) == 1
    assert same[0].expect_pass == words
    sequential = resolve_multiselect(words)          # default: sequential
    assert len(sequential) == 3
    assert [s.expect_pass for s in sequential] == [["OK"], ["READY"],
                                                  ["DONE"]]
    with pytest.raises(ValueError):
        resolve_multiselect(words, "sometimes")


def test_sequence_routed_word_lands_in_keyword_fail_not_a_step():
    word = "timeout"
    target, kind = classify_target(word)
    assert (target, kind) == ("sequence", "keyword_fail")
    sequence = FctSequence(name="FCT Sequence")
    assert getattr(sequence, kind) is sequence.keyword_fail
    sequence.keyword_fail.append(word)
    assert word in sequence.keyword_fail
    assert sequence.steps == []
    # an ordinary keyword stays on the step side
    assert classify_target("BT_READY") == ("step", "expect_pass")
    assert classify_target("ok") == ("sequence", "keyword_pass")
