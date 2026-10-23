# -*- coding: utf-8 -*-
"""Workflow block flow widget (left pane of the Yaml Build page).

Renders the five fixed stages as chained blocks in ONE horizontal row
(user direction 2026-10-13): the cards share the row width evenly and
shrink their fonts to stay compact - the Channel Allocation tables
embedded below stay visible without scrolling.

Interactions (V4.0 rules 5.2-1 / 5.2-2):

* single click  -> opens the block's dedicated config dialog (the
                   "Auto-Channel Allocation" card runs the automatic
                   allocation instead),
* right click   -> Enable / Disable context menu (nav cards have
                   none); a disabled block renders grayed with an
                   explicit Disabled badge, keeps its parameters and
                   is skipped by the flow.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog
from mtkgui.gui.yamlbuild.schema import module_title
from mtkgui.gui.yamlbuild.stages import (
    DISPLAY_CARD_MODULES,
    NAV_CARD_KEYS,
    WORKFLOW_DISPLAY_STAGES,
    Stage,
)


#: standard tooltips of the workflow modules (rule 6.2: every module
#: describes its purpose AND its responsibility boundary; disabled
#: blocks KEEP their tooltip).  GUI language = English (user rule);
#: Chinese is reserved for message-box prompts only.
MODULE_TOOLTIPS = {
    "design_input":
        "Import the schematic and netlist and build the read-only "
        "global DesignModel data source; no instrument config, no "
        "test step generation",
    "instruments":
        "Rack-ATE instrument global configuration (Keysight "
        "PSU/DAQ/DMM, VISA addresses, channel allocation, self "
        "test); configured on the Equipment page - referenced "
        "read-only here",
    "parse_ict":
        "Extract the ICT net information from the DesignModel into "
        "the ICTNetModel; no test sequence generation",
    "channel_alloc":
        "Auto-Channel Allocation: click to auto-assign the Power / "
        "Clock tables top-down (best test point + sequential "
        "instrument channels; Impedance and Voltage share the SAME "
        "DAQM908A channel, Power rails come from the U2355A AI pool). "
        "Rows beyond the pool capacity stay unset (no test); GPIO DIO "
        "channels are NOT auto-assigned. Results appear in the "
        "embedded tables below",
    "ict_workflow":
        "Merged ICT test work flow node: opens the Test Work Flow "
        "page to edit the ICT Test Cases (impedance / voltage / "
        "power rails, clock, GPIO test steps); reuses the "
        "Equipment-page instrument resources",
    "rails":
        "Generate the ICT impedance / voltage measurement and DUT "
        "power up/down sequence; reuses the configured instruments, "
        "no reconfiguration",
    "clocks": "Build the clock ICT test steps, reusing the configured "
              "instruments",
    "gpios": "Build the GPIO ICT test steps, reusing the configured "
             "instruments",
    "fct_build":
        "Generate the FCT functional test and firmware flash steps; "
        "reuses all defined resource models, no instrument "
        "reconfiguration",
}

#: context-menu tooltips (rule 6.3, fixed wording)
TT_ENABLE_SINGLE = "Enable / disable this module flow participation"
TT_DISABLE_SINGLE = "Enable / disable this module flow participation"
TT_ENABLE_ALL = ("Enable every flow module - all join the YAML "
                 "generation and validation")
TT_DISABLE_ALL = ("Disable every flow module - none joins the flow "
                  "compilation")

#: original project status color (main_window LED "connected" green);
#: used for the Enabled badge - NOT the theme link/text color
STATUS_ENABLED_COLOR = "#22c55e"

#: card marks (user direction): a configured module (OK saved) shows
#: a star at the top-right; the mark persists with the project
MARK_NONE = ""
MARK_STAR = "star"
MARK_CHECK = "check"
_MARK_GLYPH = {MARK_STAR: "★", MARK_CHECK: "✓"}
_MARK_COLOR = {MARK_STAR: "#f59e0b", MARK_CHECK: "#22c55e"}

#: compact single-row card fonts (user direction 2026-10-13)
_TITLE_CSS = "font-weight: bold; font-size: 11px;"
_STATE_CSS = "font-weight: bold; font-size: 10px;"

#: M10-FIX4 F4: minimum TOTAL flow width that keeps all five cards
#: readable in the real splitter - every title stays on at most TWO
#: wrapped lines (measured with the app font: 137 px card labels).
#: Without it the QSplitter compressed the left pane to ~490 px, the
#: cards landed ~80 px wide and titles 04 / 05 clipped.
MIN_FLOW_WIDTH = 880


class BlockCard(QFrame):
    """One workflow block: click opens the config dialog, right click
    opens the Enable / Disable menu.  Navigation-only cards (nav) have
    no enable / disable semantics - they always render enabled and
    their click is routed by the page (e.g. the "Auto-Channel
    Allocation" card runs the automatic allocation)."""

    configure_requested = Signal(str)
    enable_requested = Signal(str, bool)
    enable_all_requested = Signal()
    disable_all_requested = Signal()

    def __init__(self, stage: Stage, index: int, parent=None) -> None:
        """Create the block card.

        Args:
            stage: The workflow stage this block represents.
            index: Zero-based position in the fixed sequence (rendered
                   as the uniform sequence badge).
        """
        super().__init__(parent)
        self.stage = stage
        self._nav = stage.key in NAV_CARD_KEYS
        self._enabled = False
        # module tooltip (rule 6.2): present in enabled AND disabled
        # state alike - disabling never hides the description
        self.setToolTip(MODULE_TOOLTIPS.get(stage.key, stage.title))
        self.setFrameShape(QFrame.Shape.StyledPanel)
        # compact single-row card (user direction 2026-10-13): the
        # five cards share ONE row - width comes from the row layout
        # (evenly divided).  M10-FIX2 F6: the old 96 px minimum made
        # titles wrap twice / clip in a narrow window; 120 px keeps
        # every title on 1-2 clean lines.
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if not self._nav:
            self.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._context_menu)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(1)
        self.title_label = QLabel(
            f"{index + 1:02d} · {stage.title}")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(_TITLE_CSS)
        # top-right mark: ★ = edited (OK saved)
        self.mark_label = QLabel("")
        self.mark_label.setStyleSheet("font-weight: bold;")
        header = QHBoxLayout()
        header.addWidget(self.title_label, 1)
        header.addWidget(self.mark_label)
        self.state_label = QLabel(
            "Auto assign" if self._nav else "Disabled")
        self.state_label.setObjectName("muted")
        self.state_label.setStyleSheet(_STATE_CSS)
        lay.addLayout(header)
        lay.addWidget(self.state_label)
        if self._nav:
            # nav cards have no module state - always render enabled
            self._enabled = True
        self._apply_state_style()

    def resizeEvent(self, event) -> None:
        """Keep the locked card height tall enough for the wrapped
        title: a word-wrapped QLabel under-reports its required height
        after a width change and the Fixed vertical policy keeps the
        stale value - the title text would clip at the card top
        (visible when the window is not maximized)."""
        metrics = self.title_label.fontMetrics()
        available = max(24, self.title_label.width())
        line_h = max(1, metrics.height())
        wrapped = metrics.boundingRect(
            0, 0, available, 0,
            Qt.TextFlag.TextWordWrap, self.title_label.text())
        lines = max(1, (wrapped.height() + line_h - 1) // line_h)
        self.setMinimumHeight(max(46, lines * line_h + 26))
        super().resizeEvent(event)

    # ----------------------------------------------------------- state
    def set_mark(self, mark: str) -> None:
        """Set the top-right mark: MARK_STAR (edited) / MARK_CHECK
        (validated) / MARK_NONE.  Nav cards (Auto-Channel Allocation)
        carry the star too once their action ran (user direction).

        Args:
            mark: One of the MARK_* constants.
        """
        self.mark_label.setText(_MARK_GLYPH.get(mark, ""))
        if mark in _MARK_GLYPH:
            self.mark_label.setStyleSheet(
                f"font-weight: bold; color: {_MARK_COLOR[mark]};")
            self.mark_label.setToolTip(
                "Edited (OK saved)" if mark == MARK_STAR else
                "Configured (OK saved)")
        else:
            self.mark_label.setStyleSheet("font-weight: bold;")
            self.mark_label.setToolTip("")

    def set_enabled(self, enabled: bool) -> None:
        """Refresh the visual state (grays out disabled blocks).

        Args:
            enabled: New module state.
        """
        if self._nav:
            return      # nav cards have no module state - stay enabled
        self._enabled = enabled
        self.state_label.setText("Enabled" if enabled else "Disabled")
        self._apply_state_style()

    def _apply_state_style(self) -> None:
        """Disabled blocks render grayed with an explicit badge
        (rule 3.2: gray-only, NO strikethrough; visual distinction
        must be obvious).  Colors use semi-transparent overlays so
        both light and dark GUI themes stay readable.

        Theme-variable isolation (M0): the ENABLED card binds its own
        text colors inside the card QSS scope - main title white,
        Enabled status in the original status green - so the labels
        can never inherit the global theme's text/link colors (the
        light-theme blue leak).  Background and border stay exactly as
        originally designed."""
        if self._enabled:
            self.setStyleSheet(
                "BlockCard { background: rgba(47,111,179,0.18); "
                "border: 1px solid #2f6fb3; border-radius: 8px; }"
                "BlockCard QLabel { color: #ffffff; }")
            self.title_label.setStyleSheet(
                f"{_TITLE_CSS} color: #ffffff;")
            self.state_label.setStyleSheet(
                f"font-weight: bold; font-size: 10px; "
                f"color: {STATUS_ENABLED_COLOR};")
        else:
            self.setStyleSheet(
                "BlockCard { background: rgba(128,128,128,0.15); "
                "border: 1px dashed #9ca3af; border-radius: 8px; }"
                "QLabel { color: #9ca3af; }")
            self.title_label.setStyleSheet(
                f"{_TITLE_CSS} color: #9ca3af;")
            self.state_label.setStyleSheet(
                f"{_STATE_CSS} color: #9ca3af;")

    # ------------------------------------------------------- interactions
    def mousePressEvent(self, event) -> None:
        """Single left click -> open the dedicated config dialog (the
        page owns the dialog lifecycle via the signal)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.configure_requested.emit(self.stage.key)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """Double click on the merged ICT workflow card jumps to the
        Test Work Flow page (same navigation as the single click)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.configure_requested.emit(self.stage.key)
        super().mouseDoubleClickEvent(event)

    def _build_menu(self) -> QMenu:
        """Build the right-click menu (single + batch operations,
        rule 3.2: Enable / Disable / Enable All / Disable All with
        the fixed standard tooltips).

        Returns:
            The unexecuted :class:`QMenu`.
        """
        menu = QMenu(self)
        act_enable = menu.addAction("Enable")
        act_enable.setToolTip(TT_ENABLE_SINGLE)
        act_enable.setEnabled(not self._enabled)
        act_disable = menu.addAction("Disable")
        act_disable.setToolTip(TT_DISABLE_SINGLE)
        act_disable.setEnabled(self._enabled)
        menu.addSeparator()
        act_enable_all = menu.addAction("Enable All")
        act_enable_all.setToolTip(TT_ENABLE_ALL)
        act_disable_all = menu.addAction("Disable All")
        act_disable_all.setToolTip(TT_DISABLE_ALL)
        menu._actions_map = {
            "enable": act_enable, "disable": act_disable,
            "enable_all": act_enable_all, "disable_all": act_disable_all,
        }
        return menu

    def _context_menu(self, pos: QPoint) -> None:
        """Right click -> open the Enable / Disable menu."""
        menu = self._build_menu()
        actions = menu._actions_map
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is actions["enable"]:
            self.enable_requested.emit(self.stage.key, True)
        elif chosen is actions["disable"]:
            self.enable_requested.emit(self.stage.key, False)
        elif chosen is actions["enable_all"]:
            self.enable_all_requested.emit()
        elif chosen is actions["disable_all"]:
            self.disable_all_requested.emit()


class BlockFlowWidget(QWidget):
    """Left pane: the five fixed blocks chained in workflow order."""

    configure_requested = Signal(str)
    enable_requested = Signal(str, bool)
    enable_all_requested = Signal()
    disable_all_requested = Signal()

    def __init__(self, parent=None) -> None:
        """Create the flow widget with all fixed blocks."""
        super().__init__(parent)
        # M10-FIX4 F4: the splitter may never compress the row below a
        # width where the card titles stop being readable
        self.setMinimumWidth(MIN_FLOW_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        self._cards: dict[str, BlockCard] = {}
        # display card -> underlying YAML modules (the merged ICT
        # workflow card represents rails + clocks + gpios)
        self._card_modules: dict[str, tuple[str, ...]] = {}
        self._module_states: dict[str, bool] = {}
        # ONE horizontal row (user direction 2026-10-13): the five
        # cards share the row width evenly (QHBoxLayout), so all steps
        # stay visible without any vertical scrolling
        self.flow = QHBoxLayout(self)
        self.flow.setContentsMargins(2, 2, 2, 2)
        self.flow.setSpacing(4)
        previous = None
        for index, stage in enumerate(WORKFLOW_DISPLAY_STAGES):
            if previous is not None:
                # the arrow sits BETWEEN two cards: add it BEFORE the
                # current card (adding it after left card 01 -> 02
                # without an arrow and a stray arrow after card 05)
                arrow = QLabel("\u2192")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setFixedWidth(12)
                self.flow.addWidget(arrow, 0)
            card = BlockCard(stage, index)
            card.configure_requested.connect(self.configure_requested)
            card.enable_requested.connect(self._on_enable_request)
            card.enable_all_requested.connect(self.enable_all_requested)
            card.disable_all_requested.connect(
                self.disable_all_requested)
            self._cards[stage.key] = card
            self._card_modules[stage.key] = DISPLAY_CARD_MODULES.get(
                stage.key, (stage.key,))
            self.flow.addWidget(card, 1)
            previous = stage
        # sequence is fixed: the flow order equals
        # WORKFLOW_DISPLAY_STAGES and no user interaction can reorder
        # the cards

    def _on_enable_request(self, module_key: str, enabled: bool) -> None:
        """Enable / Disable request from a card: the merged ICT
        workflow card applies the state to ALL of its underlying
        modules (rails / clocks / gpios)."""
        for module in self._card_modules.get(module_key,
                                             (module_key,)):
            self.enable_requested.emit(module, enabled)

    def set_state(self, module_key: str, enabled: bool) -> None:
        """Mirror one module's enable state on its card (the merged
        ICT workflow card shows Enabled when ANY of its underlying
        modules - rails / clocks / gpios - is enabled).

        Args:
            module_key: Stage key.
            enabled:    New state.
        """
        if module_key in NAV_CARD_KEYS:
            return      # nav cards have no module state
        self._module_states[module_key] = enabled
        for display_key, modules in self._card_modules.items():
            if module_key in modules:
                self._cards[display_key].set_enabled(any(
                    self._module_states.get(m, False)
                    for m in modules))
                return

    def set_module_mark(self, module_key: str, mark: str) -> None:
        """Set the mark of one module's card (the merged ICT workflow
        card carries the mark of its rails / clocks / gpios modules;
        the Auto-Channel Allocation nav card carries its own).

        Args:
            module_key: Stage key of the underlying module.
            mark:       One of the MARK_* constants.
        """
        display = next(
            (d for d, mods in self._card_modules.items()
             if module_key in mods), module_key)
        card = self._cards.get(display)
        if card is not None:
            card.set_mark(mark)

    def open_dialog(self, module_key: str, params: dict,
                    parent: QWidget,
                    log_sink=None, progress_sink=None,
                    net_source: tuple[str, str] | None = None,
                    panel_state: dict | None = None,
                    yaml_model=None):
        """Open the dedicated config dialog for one module.

        Args:
            module_key:       Stage key.
            params:           Current parameters.
            parent:           Parent widget for the dialog.
            log_sink:         Optional callable (level, message) wired
                              to the dialog BEFORE exec so embedded
                              panels log live (T6).
            progress_sink:    Optional callable (percent, label) wired
                              before exec (T6 global progress).
            net_source:       Block 02 (raw netlist text, file name)
                              from the Design Input import (T8).
            panel_state:      Block 02 restore data (rules / power
                              tree / overrides / spf_nets) - item 24.
            yaml_model:       Block 02 ICT Test Plan sync target (M5).

        Returns:
            ``(values, dialog)`` where ``values`` is the validated
            parameter dict (None when cancelled) and ``dialog`` is the
            closed BlockConfigDialog (None when cancelled).
        """
        dialog = BlockConfigDialog(module_key, params, parent,
                                   net_source=net_source,
                                   panel_state=panel_state,
                                   yaml_model=yaml_model)
        if log_sink is not None:
            dialog.task_log.connect(log_sink)
        if progress_sink is not None:
            dialog.task_progress.connect(progress_sink)
        if dialog.exec() == BlockConfigDialog.DialogCode.Accepted:
            return dialog.values(), dialog
        return None, None

    @staticmethod
    def module_title(module_key: str) -> str:
        """Title lookup helper (kept for the page layer).

        Args:
            module_key: Stage key.

        Returns:
            The module's UI title.
        """
        return module_title(module_key)
