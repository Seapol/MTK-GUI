# -*- coding: utf-8 -*-
"""v2-3a: the seven-step Yaml Build wizard shell.

The page hosts the seven steps of ``mtkgui/gui/yamlbuild/steps_v2.py``:
a horizontal step bar across the top, a stacked body and one footer row
``[Cancel] [Save Draft] [Back] [Next: NN >]``.  The shell only hosts the
panels — it never redesigns their internals; a placeholder step shows one
sentence and nothing else.

Routing, greying and the project tree / draft hook come from
``steps_v2`` (Qt-free, tested separately).  This widget is the thin Qt
skin over that state.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild import steps_v2 as sv


class YamlBuildWizard(QWidget):
    """Seven-step shell: step bar + stacked body + footer."""

    #: the operator pressed [Cancel] (the wizard stops; no file is deleted)
    cancelled = Signal()
    #: a launcher step asked to open its external builder
    build_ict_requested = Signal()
    build_fct_requested = Signal()

    def __init__(self, model: YamlBuildModel | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model or YamlBuildModel()
        self.current: str = "design_input"
        self.visited: set[str] = {"design_input"}
        self.tree_created: bool = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ------------------------------------------------ step bar
        self._bar_buttons: dict[str, QPushButton] = {}
        bar = QHBoxLayout()
        bar.setSpacing(4)
        for step in sv.YAML_STEPS:
            btn = QPushButton(sv.step_label(step.key))
            btn.setCheckable(False)
            btn.setFlat(True)
            btn.clicked.connect(
                lambda _=False, k=step.key: self._on_bar_clicked(k))
            self._bar_buttons[step.key] = btn
            bar.addWidget(btn)
        bar.addStretch(1)
        root.addLayout(bar)

        # ------------------------------------------------ body
        self.body = QStackedWidget()
        self._bodies: dict[str, QWidget] = {}
        self._panels: dict[str, QWidget] = {}
        for step in sv.YAML_STEPS:
            self.body.addWidget(self._build_body(step.key))
        root.addWidget(self.body, 1)

        # ------------------------------------------------ footer
        footer = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_save_draft = QPushButton("Save Draft")
        self.btn_save_draft.clicked.connect(self._on_save_draft)
        self.btn_back = QPushButton("Back")
        self.btn_back.clicked.connect(self._on_back)
        self.btn_next = QPushButton("Next: 02 >")
        self.btn_next.clicked.connect(self._on_next)
        footer.addWidget(self.btn_cancel)
        footer.addWidget(self.btn_save_draft)
        footer.addStretch(1)
        footer.addWidget(self.btn_back)
        footer.addWidget(self.btn_next)
        root.addLayout(footer)

        self._refresh()

    # ------------------------------------------------------------- body
    def _build_body(self, key: str) -> QWidget:
        """One body widget per step; placeholders stay one sentence."""
        step = sv.STEP_BY_KEY[key]
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        if step.key in sv.PLACEHOLDER_STEPS:
            label = QLabel(sv.PLACEHOLDER_TEXT)
            label.setWordWrap(True)
            label.setProperty("tone", "muted")
            lay.addWidget(label)
            self._bodies[key] = body
            return body
        if step.kind == "launcher":
            btn = QPushButton(f"Open {step.title}")
            if key == "build_ict":
                btn.clicked.connect(self.build_ict_requested.emit)
            else:
                btn.clicked.connect(self.build_fct_requested.emit)
            lay.addWidget(btn)
            lay.addStretch(1)
            self._bodies[key] = body
            return body
        # panel: re-parent the existing widget unchanged
        panel = self._make_panel(key)
        lay.addWidget(panel)
        self._panels[key] = panel
        self._bodies[key] = body
        return body

    def _make_panel(self, key: str) -> QWidget:
        """Instantiate the real panel for a ``panel`` step."""
        if key == "design_input":
            from mtkgui.gui.yamlbuild.design_input_panel import \
                DesignInputPanel
            panel = DesignInputPanel()
            # v2-3e: node 01 reaches the model - load the persisted
            # design_input params, then write back on every change.
            panel.set_values(self.model.get_params("design_input") or {})
            panel.content_changed.connect(
                lambda: self.model.set_params("design_input",
                                              panel.values()))
            return panel
        if key == "parse_ict":
            from mtkgui.gui.yamlbuild.parse_nets_v2_panel import \
                ParseNetsV2Panel
            panel = ParseNetsV2Panel()
            # v2-4: Route B re-imports the ICT Excel recorded on node 01
            # (LOAD ONLY there); Route A is driven by an explicit parse.
            design = self.model.get_params("design_input") or {}
            if str(design.get("ict_route") or "") == "excel":
                excel = str(design.get("ict_excel_file") or "").strip()
                if excel:
                    panel.load_route_b(excel)
            return panel
        if key == "firmware":
            from mtkgui.gui.yamlbuild.firmware_panel import \
                FirmwareConfigPanel
            panel = FirmwareConfigPanel()
            # v2-5: node 03 reaches the model - load the persisted
            # firmware config, then write back on every change.
            panel.set_values(self.model.get_firmware_config())
            panel.content_changed.connect(
                lambda: self.model.set_firmware_config(panel.values()))
            return panel
        if key == "equipment":
            from mtkgui.gui.yamlbuild.instruments_panel import \
                InstrumentsPanel
            return InstrumentsPanel()
        label = QLabel(sv.PLACEHOLDER_TEXT)
        return label

    # ------------------------------------------------------------- state
    def ict_on(self) -> bool:
        design = self.model.get_params("design_input") or {}
        return str(design.get("ict_block_enabled", "true")).lower() \
            not in ("false", "0", "no")

    def fct_on(self) -> bool:
        design = self.model.get_params("design_input") or {}
        return str(design.get("fct_block_enabled", "true")).lower() \
            not in ("false", "0", "no")

    def validate_current(self) -> tuple[bool, str]:
        """Delegate to node 01's panel (v2-3b); the default never blocks."""
        panel = self._panels.get(self.current)
        validator = getattr(panel, "validate", None)
        if callable(validator):
            return validator()
        return True, ""

    # --------------------------------------------------------- navigation
    def _on_bar_clicked(self, key: str) -> None:
        if key in self.visited and sv.is_step_enabled(
                key, self.ict_on(), self.fct_on()):
            self.current = key
            self._refresh()

    def _on_back(self) -> None:
        prev = sv.prev_key(self.current, self.ict_on(), self.fct_on())
        if prev is not None:
            self.current = prev
            self._refresh()

    def _on_next(self) -> None:
        # v2-4: node 02 blocks [Next >] on a Route B consistency-gate
        # mismatch (and node 01 on its own validation) - delegate to the
        # current panel's validate(), default never blocks.
        ok, _msg = self.validate_current()
        if not ok:
            return
        if self.current == "design_input":
            design = self.model.get_params("design_input") or {}
            core = str(design.get("product_id") or "").strip()
            if core:
                sv.ensure_project_tree(core)
                self.tree_created = True
        else:
            sv.save_draft(self.model)
        nxt = sv.next_key(self.current, self.ict_on(), self.fct_on())
        if nxt is not None:
            self.visited.add(nxt)
            self.current = nxt
            self._refresh()

    def _on_save_draft(self) -> None:
        sv.save_draft(self.model)

    def _on_cancel(self) -> None:
        """Stop the wizard.  Nothing on disk is deleted — whatever an
        earlier [Next >] / [Save Draft] already created stays."""
        self.current = "design_input"
        self.visited = {"design_input"}
        self.tree_created = False
        self.cancelled.emit()
        self._refresh()

    def _refresh(self) -> None:
        """Repaint the bar, the body and the footer for the current state."""
        ict_on, fct_on = self.ict_on(), self.fct_on()
        for key, btn in self._bar_buttons.items():
            step = sv.STEP_BY_KEY[key]
            enabled = sv.is_step_enabled(key, ict_on, fct_on)
            btn.setEnabled(enabled)
            if key == self.current:
                btn.setProperty("current", True)
            elif key in self.visited:
                btn.setProperty("current", False)
                btn.setProperty("visited", True)
            else:
                btn.setProperty("current", False)
                btn.setProperty("visited", False)
            btn.setText((sv.step_label(key) + "  ✓")
                        if key in self.visited and key != self.current
                        else sv.step_label(key))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.body.setCurrentIndex(sv.STEP_KEYS.index(self.current))
        self.btn_back.setVisible(self.current != "design_input")
        self.btn_next.setText(sv.next_label(self.current, ict_on, fct_on))
        # v2-4: any panel may gate [Next >] (node 01 validates its
        # fields, node 02 the Route B consistency gate).
        nxt = sv.next_key(self.current, ict_on, fct_on)
        ok, msg = self.validate_current()
        self.btn_next.setEnabled(ok and nxt is not None)
        self.btn_next.setToolTip(msg if not ok else "")

    # --------------------------------------------------------- test hook
    def goto(self, key: str) -> None:
        """Programmatic navigation (tests): visit *key* directly."""
        self.current = key
        self.visited.add(key)
        self._refresh()
