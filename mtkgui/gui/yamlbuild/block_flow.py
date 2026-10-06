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
    DISPLAY_CARD_MODULES,
    WORKFLOW_DISPLAY_STAGES,
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


#: standard tooltips of the twelve workflow modules (rule 6.2: every
#: module describes its purpose AND its responsibility boundary;
#: disabled blocks KEEP their tooltip)
MODULE_TOOLTIPS = {
    "design_input":
        "导入原理图与网表，构建只读全局DesignModel数据源；"
        "不含仪器配置与测试步骤生成",
    "instruments":
        "机架ATE仪器全局配置（Keysight PSU/DAQ/DMM、VISA地址、"
        "通道分配、仪器自检）；全流程唯一仪器配置入口，"
        "后续模块只读引用",
    "parse_ict":
        "从DesignModel提取ICT网络信息生成ICTNetModel；不生成测试序列",
    "ict_workflow":
        "合并的ICT测试工作流节点（原04/05/06）：双击打开Test Work Flow"
        "页编辑ICT Test Cases（阻抗/电压/Power rails、时钟、GPIO测试"
        "步骤）；复用block03已配置仪器资源",
    "rails":
        "生成ICT阻抗/电压测量与DUT上下电序列；复用block03仪器资源，"
        "不重复配置仪器",
    "clocks": "构建时钟ICT测试步骤，复用block03已配置仪器资源",
    "gpios": "构建GPIO ICT测试步骤，复用block03已配置仪器资源",
    "programmer":
        "JLink/烧录调试器固件与调试资源配置，与机架ATE仪器分离；"
        "不生成测试步骤",
    "peripherals":
        "DUT板载外设（WiFi/BT/SD/USB）参数配置；不生成测试步骤",
    "fct_parse": "从DesignModel解析FCT接口定义生成FCTInterfaceModel；"
                 "不生成测试序列",
    "fct_build":
        "生成FCT功能测试与固件烧录步骤；复用全部已定义资源模型，"
        "不重新配置仪器",
    "validate_sequence":
        "跨节点全局校验：资源冲突、参数范围、依赖违规；"
        "校验失败则禁用block12导出；不修改流程数据",
    "preview_export":
        "预览完整测试工作流并导出完整YAML至工程配置目录，"
        "工作流终点",
}

#: context-menu tooltips (rule 6.3, fixed wording)
TT_ENABLE_SINGLE = "单独开启/关闭当前模块流程能力"
TT_DISABLE_SINGLE = "单独开启/关闭当前模块流程能力"
TT_ENABLE_ALL = "一键启用全部流程模块，所有模块参与YAML生成与校验"
TT_DISABLE_ALL = "一键禁用全部流程模块，所有模块暂不参与流程编译"

#: original project status color (main_window LED "connected" green);
#: used for the Enabled badge - NOT the theme link/text color
STATUS_ENABLED_COLOR = "#22c55e"


class BlockCard(QFrame):
    """One workflow block: click opens the config dialog, right click
    opens the Enable / Disable menu."""

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
        self._enabled = False
        # module tooltip (rule 6.2): present in enabled AND disabled
        # state alike - disabling never hides the description
        self.setToolTip(MODULE_TOOLTIPS.get(stage.key, stage.title))
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(280)
        self.setMinimumHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.title_label = QLabel(
            f"{index + 1:02d} · {stage.title}")
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
                "font-weight: bold; color: #ffffff;")
            self.state_label.setStyleSheet(
                f"font-weight: bold; color: {STATUS_ENABLED_COLOR};")
        else:
            self.setStyleSheet(
                "BlockCard { background: rgba(128,128,128,0.15); "
                "border: 1px dashed #9ca3af; border-radius: 8px; }"
                "QLabel { color: #9ca3af; }")
            self.title_label.setStyleSheet(
                "font-weight: bold; color: #9ca3af;")

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
    """Left pane: the ten fixed blocks chained in workflow order."""

    configure_requested = Signal(str)
    enable_requested = Signal(str, bool)
    enable_all_requested = Signal()
    disable_all_requested = Signal()

    def __init__(self, parent=None) -> None:
        """Create the flow widget with all fixed blocks."""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        # never let the flow area shrink below one card width (rule
        # 6.2: no card clipping at any resolution)
        self.setMinimumWidth(300)
        self._cards: dict[str, BlockCard] = {}
        # display card -> underlying YAML modules (the merged ICT
        # workflow card represents rails + clocks + gpios)
        self._card_modules: dict[str, tuple[str, ...]] = {}
        self._module_states: dict[str, bool] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.flow = FlowLayout(self)
        layout.addWidget(self.flow)
        previous = None
        for index, stage in enumerate(WORKFLOW_DISPLAY_STAGES):
            card = BlockCard(stage, index)
            card.configure_requested.connect(self.configure_requested)
            card.enable_requested.connect(self._on_enable_request)
            card.enable_all_requested.connect(self.enable_all_requested)
            card.disable_all_requested.connect(
                self.disable_all_requested)
            self._cards[stage.key] = card
            self._card_modules[stage.key] = DISPLAY_CARD_MODULES.get(
                stage.key, (stage.key,))
            self.flow.add_widget(card)
            if previous is not None:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                arrow.setFixedWidth(24)
                self.flow.add_widget(arrow)
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
        self._module_states[module_key] = enabled
        for display_key, modules in self._card_modules.items():
            if module_key in modules:
                self._cards[display_key].set_enabled(any(
                    self._module_states.get(m, False)
                    for m in modules))
                return

    def open_dialog(self, module_key: str, params: dict,
                    parent: QWidget,
                    log_sink=None, progress_sink=None,
                    net_source: tuple[str, str] | None = None,
                    panel_state: dict | None = None):
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

        Returns:
            ``(values, dialog)`` where ``values`` is the validated
            parameter dict (None when cancelled) and ``dialog`` is the
            closed BlockConfigDialog (None when cancelled).
        """
        dialog = BlockConfigDialog(module_key, params, parent,
                                   net_source=net_source,
                                   panel_state=panel_state)
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
