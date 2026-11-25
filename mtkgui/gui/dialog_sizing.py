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
from PySide6.QtWidgets import (QApplication, QFrame, QScrollArea,
                               QVBoxLayout, QWidget)

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
    target_w = int(width)
    target_h = int(height)
    if screen is not None:
        avail = screen.availableGeometry()
        # M124: a 1180 px dialog on a 1366 px laptop left no room for the
        # desktop and pushed content off the edge - keep it inside the
        # screen and let the operator maximize when more space is needed.
        # leave the window frame reachable on both sides; 92% is the
        # same ceiling the app-wide DialogCenterer uses
        max_w = max(420, min(int(avail.width() * 0.92),
                             avail.width() - 70))
        target_w = min(target_w, max_w)
        max_h = max(_MIN_DIALOG_H, int(avail.height()) - bottom_margin)
        target_h = min(target_h, max_h)
    dlg.resize(target_w, target_h)
    cap_form_inputs(dlg)
    return dlg


#: M124: the widest a single-line form field may grow.  A wide dialog
#: used to stretch a 4-character field to the full row (the "too wide"
#: input the operator kept reporting) - a cap keeps the field near its
#: content while the window can still be resized freely.
_INPUT_CAPS = (
    ("QLineEdit", 420, 320),
    ("QComboBox", 360, 260),
    ("QSpinBox", 200, 180),
    ("QDoubleSpinBox", 200, 180),
    ("QPlainTextEdit", 560, 480),
    ("QTextEdit", 560, 480),
)


def cap_form_inputs(root: QWidget) -> int:
    """Stop a form input from stretching across a wide dialog.

    Walks every input of ``root`` (dialog, panel or page body) and
    lowers only the ones whose ``maximumWidth`` is still unbounded;
    widgets with their own bounded width (a 120 px numeric entry, a
    channel row capped at 280 px) are left exactly as designed.  Inputs
    living inside an item view (cell editors of a table) are skipped -
    those must follow the cell, not the form.  Returns the count capped.
    """
    from PySide6.QtWidgets import QAbstractItemView
    capped = 0
    for type_name, cap, floor in _INPUT_CAPS:
        for widget in root.findChildren(QWidget):
            if type(widget).__name__ != type_name:
                continue
            if widget.minimumWidth() == widget.maximumWidth():
                # the caller deliberately fixed this width (a 120 px
                # numeric entry, a 480 px path field + Browse...)
                continue
            # the cap follows the field's own content hint as well: a
            # 99 px combo must not become 360 px just because the tier
            # cap allows it (still "2.5x the hint" oversized)
            limit = max(floor, min(cap, widget.sizeHint().width() * 2 + 50))
            if widget.maximumWidth() <= limit:
                continue
            ancestor = widget.parentWidget()
            while ancestor is not None:
                if isinstance(ancestor, QAbstractItemView):
                    break
                ancestor = ancestor.parentWidget()
            else:
                widget.setMaximumWidth(limit)
                capped += 1
    return capped


# --------------------------------------------------------------- M34 scroll
#: dynamic property set on the CONTENT widget of every scroll guard - tests
#: and callers use it to prove the content really sits inside a QScrollArea.
_SCROLLED_PROP = "_m34_scrolled"


def _is_scrolled(widget: QWidget | None) -> bool:
    """True when ``widget`` is already protected by a scroll area.

    Either the ``_m34_scrolled`` marker is set on the widget itself (it is
    the CONTENT of a :func:`wrap_scrollable` wrapper), or one of its
    ancestors is a :class:`QScrollArea` (e.g. the Wi-Fi / BT tab bodies
    wrapped by M31 / M32).
    """
    if widget is None:
        return False
    if bool(widget.property(_SCROLLED_PROP)):
        return True
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            return True
        parent = parent.parentWidget()
    return False


def _mark_scrolled(content: QWidget) -> None:
    content.setProperty(_SCROLLED_PROP, True)


def wrap_scrollable(content: QWidget, min_w: int = 0,
                    min_h: int = 0) -> QWidget:
    """Put ``content`` into a scroll area and return the wrapper.

    ``widgetResizable=True`` + ``NoFrame`` - the M31 / M32 template.  Idempotent
    via the ``_m34_scrolled`` marker: a repeated call returns the existing
    wrapper (never a second QScrollArea).  When the content is already the
    widget of a QScrollArea the existing scroll area is returned and merely
    marked.
    """
    if content is None:
        return content
    existing = getattr(content, "_m34_scroll_wrapper", None)
    if existing is not None:
        return existing
    # QScrollArea.setWidget() reparents the content to the scroll area's
    # VIEWPORT, not to the scroll area itself - resolve both layouts so
    # an already-scrolled body is never wrapped a second time (a stray
    # second QScrollArea re-parents the body and its tables, and once
    # the orphan wrapper is collected Qt deletes the whole content).
    parent = content.parentWidget()
    candidate = parent
    if parent is not None and not isinstance(parent, QScrollArea):
        candidate = parent.parentWidget()
    if isinstance(candidate, QScrollArea) and candidate.widget() is content:
        _mark_scrolled(content)
        content._m34_scroll_wrapper = candidate
        return candidate
    cap_form_inputs(content)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    # M124: a long path / wide table must stay reachable - the bar shows
    # up only when the content really is wider than the viewport.
    scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(content)
    if min_w > 0 or min_h > 0:
        scroll.setMinimumSize(max(0, int(min_w)), max(0, int(min_h)))
    _mark_scrolled(content)
    content._m34_scroll_wrapper = scroll
    return scroll


def apply_scroll_to_dialog(dlg: QWidget, content: QWidget,
                           min_w: int = 0, min_h: int = 0) -> QWidget:
    """Scroll-protect ``dlg``'s body ``content`` while keeping its button
    row OUTSIDE the scroll area (always visible at the bottom).

    ``content`` must be the widget that holds every input field / table of
    the dialog; the caller keeps the OK / Cancel (or Close) button row in
    the dialog's own layout.  Idempotent via :func:`wrap_scrollable`.
    """
    if dlg is None or content is None:
        return dlg
    if _is_scrolled(content):
        return dlg
    lay = dlg.layout()
    index = -1
    if lay is not None:
        index = lay.indexOf(content)
        if index >= 0:
            lay.takeAt(index)
    scroll = wrap_scrollable(content, min_w, min_h)
    if lay is None:
        lay = QVBoxLayout(dlg)
    if index >= 0:
        lay.insertWidget(index, scroll, 1)
    else:
        lay.addWidget(scroll, 1)
    return dlg


def wrap_page(page: QWidget, min_w: int = 0, min_h: int = 0) -> QWidget:
    """Scroll-protect a standalone QWidget page (not a dialog).

    Moves the page's existing top-level layout items into one content
    widget inside a QScrollArea and installs that scroll area as the page
    layout - the page then scrolls instead of squeezing / clipping its
    children on a small window.  Idempotent via ``_m34_page_scrolled``.
    """
    if page is None or bool(page.property("_m34_page_scrolled")):
        return page
    old = page.layout()
    if old is None:
        return page
    margins = old.contentsMargins()
    spacing = old.spacing()
    body = QWidget()
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(margins)
    if spacing >= 0:
        body_lay.setSpacing(spacing)
    while old.count():
        item = old.takeAt(0)
        if item is None:
            continue
        if item.widget() is not None:
            body_lay.addWidget(item.widget())
        elif item.layout() is not None:
            body_lay.addLayout(item.layout())
        else:
            body_lay.addItem(item)
    # detach the (now empty) old layout so the page can take a new one
    QWidget().setLayout(old)
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    outer.addWidget(wrap_scrollable(body, min_w, min_h))
    page.setProperty("_m34_page_scrolled", True)
    return page


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
