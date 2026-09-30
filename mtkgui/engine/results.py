# -*- coding: utf-8 -*-
"""Step result model for the test flow engine.

Defines the cross-module result contract from docs/interface_spec.md §3:
`StepStatus` (rendered verdicts) and `StepResult` (one executed step).
The engine is the only producer of StepResult objects; the UI layer only
reads them (via TestRunner signals or the page's RunnerEnv bridge).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StepStatus(str, Enum):
    """Verdict of one executed test step.

    RUNNING: step is in progress (console wait / dialog open).
    PASS:    step judged good (op steps render as "Done" in the tables).
    FAIL:    step judged out of limit / unexpected reply.
    ERROR:   instrument or equipment fault (not a DUT verdict).
    IGNORED: rendered as "Ignore" (gray) in the UI; excluded from the
             overall result rollup.
    """

    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    IGNORED = "IGNORED"


@dataclass
class StepResult:
    """Outcome of a single executed test step.

    status:     final verdict of the step.
    measured:   measured value / matched text as shown in the Measured
                column (None for op steps and rail captures).
    duration_s: wall time of the step execution in seconds.
    message:    sub-action log line, e.g. "Fixture Clamp Down: Done".
    """

    status: StepStatus
    measured: float | str | None = None
    duration_s: float = 0.0
    message: str = ""
