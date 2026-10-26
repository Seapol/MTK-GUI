"""Dialog geometry helpers.

2026-10-26 (user report): big config dialogs - the FCT / ICT
sequence builders, the SharePoint dialogs - could grow taller than
the screen, pushing the Ok / Cancel row below the taskbar where it
was unreachable, and they carried no minimize / maximize buttons.

Every config dialog now routes its ``resize()`` through
:func:`fit_dialog`:

* the height is clamped to the screen's available area (taskbar
  excluded) so the bottom button row always stays visible;
* ``WindowMinimizeButtonHint`` / ``WindowMaximizeButtonHint`` /
  ``WindowResizeableHint`` are added, so the dialog supports
  minimize, maximize and free resizing;
* the ``_dlg_enlarged`` property is set, which makes the main-window
  :class:`~mtkgui.main_window.DialogCenterer` center the dialog but
  NEVER inflate it again (the centerer used to grow dialogs to 92 %
  of the screen height, which hid the button row).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

#: spare screen height (px) left below the dialog for the taskbar and
#: window edges - the button row must sit above it.
_BOTTOM_MARGIN = 80
#: smallest sensible dialog height when the screen is very small.
_MIN_DIALOG_H = 300


def fit_dialog(dlg: QWidget, width: int, height: int,
               bottom_margin: int = _BOTTOM_MARGIN) -> QWidget:
    """Resize a config dialog with sane, screen-bounded geometry.

    Keeps the given ``width``; clamps ``height`` to the primary /
    owning screen's available height minus ``bottom_margin`` so the
    bottom button row never falls behind the taskbar.  Enables
    minimize / maximize / free resize and marks the dialog
    ``_dlg_enlarged`` (the DialogCenterer only centers it afterwards).
    """
    dlg.setProperty("_dlg_enlarged", True)
    enable_dialog_controls(dlg)
    screen = dlg.screen() if dlg.screen() is not None \
        else QApplication.primaryScreen()
    target_h = int(height)
    if screen is not None:
        avail = screen.availableGeometry()
        max_h = max(_MIN_DIALOG_H, int(avail.height()) - bottom_margin)
        target_h = min(int(height), max_h)
    dlg.resize(int(width), target_h)
    return dlg


def enable_dialog_controls(dlg: QWidget,
                           min_height: int = _MIN_DIALOG_H) -> QWidget:
    """Give a dialog minimize / maximize / free-resize support WITHOUT
    touching its default size.

    Used by the dialogs that let the layout / sizeHint decide their
    size (they are still grown by the main-window DialogCenterer,
    capped at 85 % of the screen height - see main_window.py).  Marks
    nothing, so those dialogs keep their centerer-driven sizing.
    """
    dlg.setWindowFlags(
        dlg.windowFlags()
        | Qt.WindowType.WindowMinimizeButtonHint
        | Qt.WindowType.WindowMaximizeButtonHint)
    dlg.setMinimumHeight(max(dlg.minimumHeight(), min_height))
    dlg.setSizeGripEnabled(True)
    return dlg
