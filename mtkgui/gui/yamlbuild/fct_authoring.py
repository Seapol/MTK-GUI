# -*- coding: utf-8 -*-
"""fct_authoring — M159 annotations -> FCT steps (pure logic, no Qt).

Plan A turns ONE console's annotations into a single step (a TX
selection is the command, green RX keywords are expected-pass, red RX
keywords are expected-fail; no TX means a bare-metal listen step).

Plan B records a whole console session: :func:`split_by_tx` cuts the
annotation stream at every TX so each command owns the RX that follows
it, and :func:`annotations_to_step` drafts one step per segment.

The module is pure data: no channel I/O, no YAML writes, no Qt (same
red line as :mod:`fct_build`).
"""
from __future__ import annotations

from .fct_build import (
    DEFAULT_KEYWORD_FAIL,
    DEFAULT_KEYWORD_PASS,
    STEP_MESSAGE_CHECK,
    FctStep,
)
from .fct_capture import (
    ANNOTATION_COMMAND,
    ANNOTATION_EXPECT_FAIL,
    ANNOTATION_EXPECT_PASS,
)

#: multiselect modes: one step waiting for every word, or one per word
MULTISELECT_SAME_WAIT = "same_wait"
MULTISELECT_SEQUENTIAL = "sequential"
MULTISELECT_MODES = (MULTISELECT_SAME_WAIT, MULTISELECT_SEQUENTIAL)

#: routing targets of a selected word
TARGET_STEP = "step"
TARGET_SEQUENCE = "sequence"


def _clean_words(annotations, kind):
    """The stripped, non-empty texts of one annotation kind, in order."""
    return [str(a.text).strip() for a in annotations
            if getattr(a, "kind", "") == kind and str(a.text).strip()]


def annotations_to_step(annotations, channel: str, timeout_s: float = 30.0,
                        name: str = "") -> FctStep:
    """Draft ONE FctStep from one console's annotations.

    TX -> ``command`` (newline-joined), green RX -> ``expect_pass``,
    red RX -> ``expect_fail``.  No TX annotation means a bare-metal
    listen step (``command == ""``, the executor's
    ``console_send_and_expect`` with an empty payload).
    """
    command = "\n".join(_clean_words(annotations, ANNOTATION_COMMAND))
    pass_words = _clean_words(annotations, ANNOTATION_EXPECT_PASS)
    fail_words = _clean_words(annotations, ANNOTATION_EXPECT_FAIL)
    step_name = name or (f"Console {channel} capture" if command
                         else f"Console {channel} listen")
    return FctStep(
        name=step_name,
        step_type=STEP_MESSAGE_CHECK,
        channel=channel,
        command=command,
        expect_pass=pass_words,
        expect_fail=fail_words,
        timeout_s=float(timeout_s),
        params={"fct_console": True, "kind": "send",
                "send_enabled": bool(command), "send": command,
                "capture_enabled": bool(pass_words or fail_words),
                "capture_timeout": float(timeout_s), "wait_enabled": False},
    )


def split_by_tx(annotations) -> list:
    """Plan B: cut the annotation stream at every TX.

    Each TX starts a new segment; RX keywords attach to the most recent
    segment (RX that precedes the first TX forms a listen-only segment).
    Returns a list of annotation lists, in capture order.
    """
    segments: list = []
    current: list = []
    for annotation in annotations:
        if getattr(annotation, "kind", "") == ANNOTATION_COMMAND:
            current = [annotation]
            segments.append(current)
        else:
            if not segments:
                current = []
                segments.append(current)
            current.append(annotation)
    return segments


def resolve_multiselect(words, mode: str = MULTISELECT_SEQUENTIAL) -> list:
    """Resolve a multi-word RX selection into FctStep drafts.

    ``same_wait`` -> ONE step whose ``expect_pass`` holds every word;
    ``sequential`` -> one step per word, in selection order.
    """
    if mode not in MULTISELECT_MODES:
        raise ValueError(f"unknown multiselect mode {mode!r} - expected "
                         f"one of {MULTISELECT_MODES}")
    cleaned = [str(word).strip() for word in (words or [])
               if str(word).strip()]
    if not cleaned:
        return []
    if mode == MULTISELECT_SAME_WAIT:
        return [FctStep(name=f"Expect: {', '.join(cleaned)}",
                        step_type=STEP_MESSAGE_CHECK,
                        expect_pass=list(cleaned))]
    return [FctStep(name=f"Expect: {word}",
                    step_type=STEP_MESSAGE_CHECK, expect_pass=[word])
            for word in cleaned]


def classify_target(word: str) -> tuple:
    """Route one selected word: ``("step", "expect_pass")`` or the
    sequence-level ``("sequence", "keyword_pass" | "keyword_fail")``.

    The default keyword tables decide: a negative default routes to
    ``keyword_fail`` (negative wins), a positive default to
    ``keyword_pass``, anything else stays a step-level positive keyword.
    """
    text = str(word or "").strip().lower()
    if text and text in [k.lower() for k in DEFAULT_KEYWORD_FAIL]:
        return TARGET_SEQUENCE, "keyword_fail"
    if text and text in [k.lower() for k in DEFAULT_KEYWORD_PASS]:
        return TARGET_SEQUENCE, "keyword_pass"
    return TARGET_STEP, ANNOTATION_EXPECT_PASS
