# -*- coding: utf-8 -*-
"""P2-1 GUI shell framework (pure incremental).

Standardized main-window skeleton: global layout zones (top nav / side
function dock / central routed content / bottom status bar / log panel),
global routing with page cache, unified style spec, startup init with
exception fallback and safe close.  Business features mount later via
``MainWindow.register_page`` — this package owns NO business logic.
"""
from .shell import MainWindow
from .status_bar import StatusBarWidget
from .theme import StyleSpec, build_stylesheet
from .log_panel import LogPanelWidget

__all__ = [
    "MainWindow", "StatusBarWidget", "StyleSpec", "build_stylesheet",
    "LogPanelWidget",
]
