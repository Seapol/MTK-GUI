# -*- coding: utf-8 -*-
"""fct_capture — M159 log-driven FCT step authoring: capture buffer.

The operator selects console text in "Annotate" mode and tags it as a
command (TX), an expected-pass keyword (green RX) or an expected-fail
keyword (red RX).  ``Generate step`` turns the annotations of ONE
console into a draft :class:`~mtkgui.gui.yamlbuild.fct_build.FctStep`
and appends it here.

The buffer is application-level (one instance owned by the main
window, shared by the Test Work Flow console and node 06) and is PURE
data: nothing here writes the project YAML.  Only node 07 "Apply and
Save" publishes the sequence that imports these steps.

No Qt, no channel I/O (same red line as :mod:`fct_build`).
"""
from __future__ import annotations

from dataclasses import dataclass

#: annotation kinds: one TX command, one positive / negative keyword
ANNOTATION_COMMAND = "command"
ANNOTATION_EXPECT_PASS = "expect_pass"
ANNOTATION_EXPECT_FAIL = "expect_fail"
ANNOTATION_KINDS = (ANNOTATION_COMMAND, ANNOTATION_EXPECT_PASS,
                    ANNOTATION_EXPECT_FAIL)


@dataclass
class CaptureAnnotation:
    """One tagged console selection (text + how it should be used)."""

    text: str
    kind: str
    channel: str = ""


class CaptureBuffer:
    """Pending FCT steps produced from console annotations."""

    def __init__(self) -> None:
        self._steps: list = []
        self._annotations: list = []

    def add_step(self, step, annotations=None) -> None:
        """Append one draft step plus the annotations that produced it."""
        self._steps.append(step)
        self._annotations.append(list(annotations or []))

    def steps(self) -> list:
        """The pending steps, in capture order (shallow copy)."""
        return list(self._steps)

    def annotations(self) -> list:
        """Every annotation that produced a pending step (flat copy)."""
        return [item for group in self._annotations for item in group]

    def clear(self) -> None:
        """Drop every pending step (node 06 import did consume them)."""
        self._steps.clear()
        self._annotations.clear()

    def is_empty(self) -> bool:
        """True while no step has been captured."""
        return not self._steps

    def __len__(self) -> int:
        return len(self._steps)
