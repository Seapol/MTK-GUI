# -*- coding: utf-8 -*-
"""P2-1 unified GUI style spec (pure incremental).

Single source of truth for palette / font / spacing across all P2 pages.
New pages must consume ``StyleSpec`` + ``build_stylesheet`` instead of
hardcoding colors, per the P2-1 acceptance criteria (统一UI样式规范).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont


@dataclass(frozen=True)
class StyleSpec:
    """Frozen style constants — changing values here restyles the whole app."""

    # palette
    BG_DARK: str = "#1e2229"
    BG_PANEL: str = "#262b34"
    BG_NAV: str = "#2c323d"
    TEXT_MAIN: str = "#e6e9ef"
    TEXT_DIM: str = "#9aa3b2"
    ACCENT: str = "#3f8cff"
    ACCENT_HOVER: str = "#5da2ff"
    OK: str = "#3fb96f"
    WARN: str = "#e5b13a"
    ERROR: str = "#e5566d"
    BORDER: str = "#3a4150"

    # log levels (fixed order drives the filter combo)
    LOG_LEVELS: tuple = ("DEBUG", "INFO", "WARN", "ERROR")

    # fonts
    FONT_FAMILY: str = "Menlo"
    FONT_SIZE: int = 12

    # spacing / sizing
    TOPNAV_H: int = 40
    SIDEBAR_W: int = 168
    STATUS_H: int = 28
    LOGPANEL_H: int = 180
    MIN_W: int = 1024
    MIN_H: int = 640

    def font(self) -> QFont:
        f = QFont(self.FONT_FAMILY, self.FONT_SIZE)
        f.setStyleHint(QFont.StyleHint.Monospace)
        return f

    def qcolor(self, name: str) -> QColor:
        return QColor(getattr(self, name))


def build_stylesheet(spec: StyleSpec = StyleSpec()) -> str:
    """Global QSS applying the unified palette to every widget class."""
    return f"""
    QWidget {{
        background: {spec.BG_DARK};
        color: {spec.TEXT_MAIN};
        font-family: "{spec.FONT_FAMILY}";
        font-size: {spec.FONT_SIZE}px;
    }}
    #TopNav, #SideDock, #StatusBar {{
        background: {spec.BG_NAV};
        border: none;
    }}
    #SideDock QPushButton {{
        text-align: left;
        padding: 8px 12px;
        border: none;
        border-left: 3px solid transparent;
        background: transparent;
        color: {spec.TEXT_DIM};
    }}
    #SideDock QPushButton:hover {{ color: {spec.TEXT_MAIN}; }}
    #SideDock QPushButton:checked {{
        background: {spec.BG_PANEL};
        border-left: 3px solid {spec.ACCENT};
        color: {spec.TEXT_MAIN};
    }}
    #CentralArea {{ background: {spec.BG_PANEL}; }}
    QPushButton {{
        background: {spec.BG_PANEL};
        border: 1px solid {spec.BORDER};
        border-radius: 4px;
        padding: 5px 14px;
    }}
    QPushButton:hover {{ border-color: {spec.ACCENT}; }}
    QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {{
        background: {spec.BG_DARK};
        border: 1px solid {spec.BORDER};
        border-radius: 4px;
        padding: 3px 6px;
    }}
    QStatusBar {{ background: {spec.BG_NAV}; }}
    QLabel#StatusBarChip {{ background: transparent; color: {spec.TEXT_DIM}; }}
    """
