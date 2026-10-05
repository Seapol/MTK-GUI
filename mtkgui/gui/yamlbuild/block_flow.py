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


#: standard tooltips of the ten workflow modules (rule 6.2: every
#: module describes its purpose; disabled blocks KEEP their tooltip)
MODULE_TOOLTIPS = {
    "design_input":
        "录入产品ID、料号、软硬件版本与批次，导入原理图与网表，"
        "作为全流程数据源头",
    "power_dut":
        "配置DUT上下电时序、电压电流阈值与保护策略，供电源模块执行",
    "parse_ict":
        "解析网表提取网络与测试点位，筛选有效ICT测试点",
    "rails":
        "生成电源轨上电时序、阻抗与电压测试及波形采样参数",
    "clocks": "配置时钟频率、稳定时长与漂移检测参数",
    "gpios": "配置GPIO分组、模式上下拉与电平阈值校验",
    "programmer": "配置烧录调试器协议、速度、超时与重试策略",
    "peripherals":
        "配置Wi-Fi/蓝牙/串口/I2C/SPI/ADC等外设初始化与阈值",
    "fct_parse": "解析产品功能接口与测试规范，定义FCT校验项",
    "fct_build": "编排FCT功能测试流程、用例关联与良率判定",
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.flow = FlowLayout(self)
        layout.addWidget(self.flow)
        previous = None
        for index, stage in enumerate(WORKFLOW_STAGES):
            card = BlockCard(stage, index)
            card.configure_requested.connect(self.configure_requested)
            card.enable_requested.connect(self.enable_requested)
            card.enable_all_requested.connect(self.enable_all_requested)
            card.disable_all_requested.connect(
                self.disable_all_requested)
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
                    parent: QWidget):
        """Open the dedicated config dialog for one module.

        Args:
            module_key: Stage key.
            params:     Current parameters.
            parent:     Parent widget for the dialog.

        Returns:
            ``(values, import_result)`` where ``values`` is the
            validated parameter dict (None when cancelled) and
            ``import_result`` carries the Design Input import parse
            results (None for other modules).
        """
        dialog = BlockConfigDialog(module_key, params, parent)
        if dialog.exec() == BlockConfigDialog.DialogCode.Accepted:
            return dialog.values(), getattr(dialog, "import_result", None)
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
