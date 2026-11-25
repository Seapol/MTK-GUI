# -*- coding: utf-8 -*-
"""M83/M124: shared editor layout kit (C0).

The three dialogs reported by the user shared one layout defect: a long
``QLabel`` without word wrap inflates the dialog past its own maximum
width, the scroll area then grows a horizontal scrollbar and the
sentence is clipped.  Every editor touched by this milestone routes its
width / hints / scroll behaviour through this module:

    apply_fixed_width(dlg, width)   - width FLOOR, window stays resizable
    hint(text, parent_width)        - wrapped, muted helper sentence
    disable_horizontal_scroll(area) - horizontal bar on demand, never clipped
    cap_editor_width(editor, kind)  - a form field stops at a readable width
    path_label(label, prefix, path) - base name on screen, full path on hover
    finish(dlg)                     - height follows content

Width tiers (M124: a floor, not a lock): simple value editors 420,
editors with paths / notes 560, table / host-command editors 760
pixels.
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
    """M124: give the dialog a sensible MINIMUM width, never a lock.

    The M83 version called ``setFixedWidth`` - minimum == maximum - so
    the operator could neither maximise the dialog nor widen it to read
    a long path, and the usual answer was "the window is too wide / the
    right side is cut".  A floor plus free resizing is what the editors
    actually need: the layout stays readable, maximize / minimize work
    and a wider screen can be used.
    """
    if dlg is None:
        return
    from mtkgui.gui.dialog_sizing import enable_dialog_controls
    enable_dialog_controls(dlg)
    dlg.setMinimumWidth(int(width))
    setter = getattr(dlg, "setSizeGripEnabled", None)
    if callable(setter):
        setter(True)


#: M124: readable caps per editor kind - a form field grows with the
#: dialog in a plain QFormLayout, so a 1180 px dialog ended up with
#: 1100 px-wide single-line inputs and drop-downs.
EDITOR_CAPS: dict[str, tuple[int, int]] = {
    "line": (360, 640),
    "combo": (220, 420),
    "text": (360, 760),
}


def cap_editor_width(editor, kind: str = "line") -> None:
    """Bound one form editor's width to a readable range."""
    if editor is None:
        return
    lo, hi = EDITOR_CAPS.get(kind, EDITOR_CAPS["line"])
    editor.setMinimumWidth(int(lo))
    editor.setMaximumWidth(int(hi))


def hint(text: str, parent_width: int, muted: bool = True) -> QLabel:
    """A word-wrapped helper sentence that can never widen the dialog."""
    label = QLabel(str(text))
    label.setWordWrap(True)
    label.setMaximumWidth(max(80, int(parent_width) - 2 * HINT_MARGIN))
    if muted:
        label.setProperty("tone", "muted")
    return label


def disable_horizontal_scroll(scroll_area) -> None:
    """M124: keep the horizontal scrollbar AVAILABLE (as needed).

    The M83 version forced ``ScrollBarAlwaysOff``: when the content was
    wider than the viewport (a long path, a wide table) the right side
    simply disappeared with no way to reach it.  The bar now appears
    only when it is needed, and never forces a phantom bar otherwise.
    """
    if scroll_area is None:
        return
    scroll_area.setWidgetResizable(True)
    scroll_area.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded)


def path_label(label, prefix: str, path: str, width: int = 0) -> None:
    """M124: show a file path on one line without widening the dialog.

    A plain ``QLabel`` sized itself to the whole path, which stretched
    the dialog past the screen edge after an import.  The label now
    elides in the middle, keeps the full path in the tooltip, wraps as
    a last resort and is bounded in width.
    """
    import os
    if label is None:
        return
    text = os.path.basename(str(path or "")) or str(path or "")
    full = f"{prefix} {path}" if prefix else str(path or "")
    label.setText(f"{prefix} {text}" if prefix else text)
    label.setToolTip(full)
    label.setWordWrap(True)
    if width:
        label.setMaximumWidth(int(width))


def finish(dlg) -> None:
    """Height follows the content; the width stays at its floor or wider."""
    if dlg is None:
        return
    dlg.setSizePolicy(QSizePolicy.Policy.Preferred,
                      QSizePolicy.Policy.Minimum)
    dlg.adjustSize()
