# -*- coding: utf-8 -*-
"""Workflow block flow widget (left pane of the Yaml Build page).

Renders the ten fixed stages as chained blocks on a self-implemented
FlowLayout: wide windows lay the blocks out in multiple flowing rows,
narrow windows fall back to a single vertical column - the switch is
pure geometry, live on resize, no squeezed or overlapping blocks.

Interactions (V4.0 rules 5.2-1 / 5.2-2):

* single click  -> opens the block's dedicated config dialog,
* right click   -> Enable / Disable context menu; a disabled block
                   renders grayed with an explicit Disabled badge,
                   keeps its parameters and is skipped by the flow.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
from mtkgui.gui.yamlbuild.schema import module_title
from mtkgui.gui.yamlbuild.stages import (
    WORKFLOW_STAGES,
    Stage,
)


class FlowLayout(QWidget):
    """Minimal flow layout: wrapping rows of fixed-size children.

    Children are placed left-to-right; when the next child does not
    fit into the current row width a new row is started.  With a
    narrow viewport each row holds exactly one child, which is the
    required single-column fallback.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._items: list[QWidget] = []
        self._spacing = 12

    def add_widget(self, widget: QWidget) -> None:
        """Add one child widget.

        Args:
            widget: Child to manage.
        """
        widget.setParent(self)
        self._items.append(widget)
        self._relayout()

    def resizeEvent(self, event) -> None:
        """Re-place the children on width changes (live adaptive
        layout)."""
        self._relayout()
        super().resizeEvent(event)

    def _relayout(self) -> None:
        """Place the children in wrapping rows."""
        width = max(1, self.width())
        x = y = 0
        row_height = 0
        for item in self._items:
            hint = item.sizeHint()
            w = max(hint.width(), item.minimumWidth())
            h = max(hint.height(), item.minimumHeight())
            if x > 0 and x + w > width:
                x = 0
                y += row_height + self._spacing
                row_height = 0
            item.setGeometry(QRect(x, y, w, h))
            x += w + self._spacing
            row_height = max(row_height, h)
        self.setMinimumHeight(y + row_height + 2)


class BlockCard(QFrame):
    """One workflow block: click opens the config dialog, right click
    opens the Enable / Disable menu."""

    configure_requested = Signal(str)
    enable_requested = Signal(str, bool)

    def __init__(self, stage: Stage, parent=None) -> None:
        """Create the block card.

        Args:
            stage: The workflow stage this block represents.
        """
        super().__init__(parent)
        self.stage = stage
        self._enabled = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(280)
        self.setMinimumHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.title_label = QLabel(f"{stage.title}")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-weight: bold;")
        self.state_label = QLabel("Disabled")
        self.state_label.setObjectName("muted")
        lay.addWidget(self.title_label)
        lay.addWidget(self.state_label)
        self._apply_state_style()

    # ----------------------------------------------------------- state
    def set_enabled(self, enabled: bool) -> None:
        """Refresh the visual state (grays out disabled blocks).

        Args:
            enabled: New module state.
        """
        self._enabled = enabled
        self.state_label.setText("Enabled" if enabled else "Disabled")
        self._apply_state_style()

    def _apply_state_style(self) -> None:
        """Disabled blocks render grayed / faded with an explicit
        badge (rule: visual distinction must be obvious)."""
        if self._enabled:
            self.setStyleSheet(
                "BlockCard { background: #e8f1fb; border: 1px solid "
                "#2f6fb3; border-radius: 8px; }")
            self.title_label.setStyleSheet("font-weight: bold;")
        else:
            self.setStyleSheet(
                "BlockCard { background: #ececec; color: #9ca3af; "
                "border: 1px dashed #b0b0b0; border-radius: 8px; }"
                "QLabel { color: #9ca3af; }")
            self.title_label.setStyleSheet(
                "font-weight: bold; color: #9ca3af; text-decoration: "
                "line-through;")

    # ------------------------------------------------------- interactions
    def mousePressEvent(self, event) -> None:
        """Single left click -> open the dedicated config dialog (the
        page owns the dialog lifecycle via the signal)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.configure_requested.emit(self.stage.key)
        super().mousePressEvent(event)

    def _context_menu(self, pos: QPoint) -> None:
        """Right click -> Enable / Disable menu."""
        menu = QMenu(self)
        act_enable = menu.addAction("Enable")
        act_disable = menu.addAction("Disable")
        act_enable.setEnabled(not self._enabled)
        act_disable.setEnabled(self._enabled)
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_enable:
            self.enable_requested.emit(self.stage.key, True)
        elif chosen is act_disable:
            self.enable_requested.emit(self.stage.key, False)


class BlockFlowWidget(QWidget):
    """Left pane: the ten fixed blocks chained in workflow order."""

    configure_requested = Signal(str)
    enable_requested = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        """Create the flow widget with all fixed blocks."""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._cards: dict[str, BlockCard] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.flow = FlowLayout(self)
        layout.addWidget(self.flow)
        previous = None
        for stage in WORKFLOW_STAGES:
            card = BlockCard(stage)
            card.configure_requested.connect(self.configure_requested)
            card.enable_requested.connect(self.enable_requested)
            self._cards[stage.key] = card
            self.flow.add_widget(card)
            if previous is not None:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setFixedWidth(24)
                self.flow.add_widget(arrow)
            previous = stage
        # sequence is fixed: the flow order equals WORKFLOW_STAGES and
        # no user interaction can reorder the cards

    def set_state(self, module_key: str, enabled: bool) -> None:
        """Mirror one module's enable state on its card.

        Args:
            module_key: Stage key.
            enabled:    New state.
        """
        if module_key in self._cards:
            self._cards[module_key].set_enabled(enabled)

    def open_dialog(self, module_key: str, params: dict,
                    parent: QWidget) -> dict | None:
        """Open the dedicated config dialog for one module.

        Args:
            module_key: Stage key.
            params:     Current parameters.
            parent:     Parent widget for the dialog.

        Returns:
            The validated new parameter dict, or None when cancelled.
        """
        dialog = BlockConfigDialog(module_key, params, parent)
        if dialog.exec() == BlockConfigDialog.DialogCode.Accepted:
            return dialog.values()
        return None

    @staticmethod
    def module_title(module_key: str) -> str:
        """Title lookup helper (kept for the page layer).

        Args:
            module_key: Stage key.

        Returns:
            The module's UI title.
        """
        return module_title(module_key)
