# -*- coding: utf-8 -*-
"""M83: shared editor layout kit (C0).

The three dialogs reported by the user shared one layout defect: a long
``QLabel`` without word wrap inflates the dialog past its own maximum
width, the scroll area then grows a horizontal scrollbar and the
sentence is clipped.  Every editor touched by this milestone routes its
width / hints / scroll behaviour through this module:

    apply_fixed_width(dlg, width)   - width locked, horizontal resize off
    hint(text, parent_width)        - wrapped, muted helper sentence
    disable_horizontal_scroll(area) - no phantom horizontal scrollbar
    finish(dlg)                     - height follows content

Width tiers: simple value editors 420, editors with paths / notes 560,
table / host-command editors 760 pixels.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy

WIDTH_SIMPLE = 420
WIDTH_FORM = 560
WIDTH_WIDE = 760

#: inner side margin used to size wrapped hint labels inside a dialog
HINT_MARGIN = 16


def apply_fixed_width(dlg, width: int = WIDTH_SIMPLE) -> None:
    """Lock one dialog's width; vertical resizing stays free.

    ``setFixedWidth`` makes minimum == maximum, so neither the operator
    nor a layout pass can widen the dialog past its designed width (the
    clipping root cause)."""
    if dlg is None:
        return
    dlg.setFixedWidth(int(width))
    setter = getattr(dlg, "setSizeGripEnabled", None)
    if callable(setter):
        setter(False)


def hint(text: str, parent_width: int, muted: bool = True) -> QLabel:
    """A word-wrapped helper sentence that can never widen the dialog."""
    label = QLabel(str(text))
    label.setWordWrap(True)
    label.setMaximumWidth(max(80, int(parent_width) - 2 * HINT_MARGIN))
    if muted:
        label.setProperty("tone", "muted")
    return label


def disable_horizontal_scroll(scroll_area) -> None:
    """Forbid a horizontal scrollbar inside a vertical scroll area."""
    if scroll_area is None:
        return
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


def finish(dlg) -> None:
    """Height follows the content while the locked width stays fixed."""
    if dlg is None:
        return
    dlg.setSizePolicy(QSizePolicy.Policy.Preferred,
                      QSizePolicy.Policy.Minimum)
    dlg.adjustSize()
