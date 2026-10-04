# -*- coding: utf-8 -*-
"""P3-1 global resident project selector (pure incremental GUI top).

A compact combo placed in the shell top-nav.  Selecting a project:
  TenantRegistry.switch (context refresh + path redirect + cache
  clear) -> shell.apply_tenant (shared stores rebound to the tenant,
  cached pages purged so every existing page rebuilds inside the new
  tenant) -> logged + audited.  Selecting the first entry
  "P2单项目模式" deactivates the tenant layer (legacy mode).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QWidget

from mtkgui.engine.project_context import TenantError, TenantRegistry

from .theme import StyleSpec

LEGACY = "P2 单项目模式"


class ProjectSwitcher(QWidget):
    """Top-nav tenant space selector."""

    #: emitted after a successful switch with the active project id
    #: (empty string = legacy P2 single-project mode)
    tenant_switched = Signal(str)

    def __init__(self, registry: TenantRegistry, shell=None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.registry = registry
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(4)
        self.combo = QComboBox(self)
        self.combo.addItem(LEGACY)
        self.combo.currentTextChanged.connect(self.on_switch)
        lay.addWidget(self.combo)
        # NOTE: no strong back-reference to the shell is kept — the
        # active shell is resolved via self.window() at switch time,
        # so the widget tree owns this widget one-way (GC-safe).

    # ------------------------------------------------------------ items
    def add_project(self, project_id: str) -> None:
        """Register + expose a tenant (idempotent combo insert)."""
        try:
            self.registry.register(project_id)
        except TenantError:
            pass                       # already registered -> load only
        else:
            self.combo.addItem(project_id)

    def load_project(self, project_id: str) -> None:
        """Expose an existing on-disk tenant without registering."""
        self.registry.load(project_id)
        if self.combo.findText(project_id) < 0:
            self.combo.addItem(project_id)

    def project_ids(self) -> list[str]:
        return [self.combo.itemText(i)
                for i in range(1, self.combo.count())]

    # ----------------------------------------------------------- switch
    def on_switch(self, text: str) -> None:
        if text == LEGACY:
            self.registry.deactivate()
            pid = ""
        else:
            self.registry.switch(text)
            pid = text
        shell = self.window()
        if pid and hasattr(shell, "apply_tenant"):
            shell.apply_tenant(self.registry.get(pid))
        elif hasattr(shell, "apply_tenant"):
            shell.apply_tenant(None)
        self.tenant_switched.emit(pid)
