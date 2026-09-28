# -*- coding: utf-8 -*-
"""QSS stylesheet generator (packaging needs no assets).

One builder, several selectable GUI themes (View -> GUI Theme). Every
theme stores its palette as tokens; build_qss() turns them into the
complete stylesheet. All text/background pairs are tuned for readability
(contrast >= 4.5:1 for normal text; audit_all() verifies every theme).

Theme tokens:
    page            window / menu bar background
    card            group box / dialog card background
    alt             alternating table rows, tab strip, header, flat buttons
    text / muted    normal / secondary text
    border          widget borders
    accent(+press)  highlight color (buttons, selection, focus)
    accent_text     text color on accent backgrounds
    link            emphasized label text (e.g. project file name)
    warn            warning note text on cards
    sel_bg/text     table / list selection
    scroll(+hover)  scrollbar handle
    disabled_*      disabled input / button colors
    tab_sel_text    selected tab label color
    verdicts        big PASS / FAIL / RUNNING / IGNORE verdict colors
"""

from PySide6.QtCore import QSettings

from .theme import is_dark, text_on_dark, text_on_light

APP_NAME = "Manufacturing Test Kit"
APP_ORG = "MTK GUI"

GUI_THEMES = {
    "Light": {
        "page": "#f3f5f8", "card": "#ffffff", "alt": "#eef2f7",
        "text": "#22303f", "muted": "#5b6b7a", "border": "#d0d7e0",
        "accent": "#2f6fb3", "accent_press": "#265a94",
        "accent_text": "#ffffff", "link": "#2c5fa8", "warn": "#96590f",
        "sel_bg": "#d9e7f6", "sel_text": "#1c2430",
        "danger": "#c0504d", "danger_hover": "#d3615e",
        "scroll": "#c3cddb", "scroll_hover": "#9fb0c4",
        "disabled_bg": "#eef1f5", "disabled_text": "#7a8794",
        "tab_sel_text": "#2c5fa8",
        "verdicts": {
            "ok": "#1d7a3c", "bad": "#c0392b", "run": "#2f6fb3",
            "warn": "#b35c00", "neutral": "#5b6b7a",
        },
    },
    "Dark": {
        "page": "#1e242c", "card": "#262d36", "alt": "#2c333d",
        "text": "#e6eaf0", "muted": "#a3b0bd", "border": "#3a434e",
        "accent": "#4d9deb", "accent_press": "#3b82c4",
        "accent_text": "#0e1a26", "link": "#7db9f0", "warn": "#e8a94c",
        "sel_bg": "#34506e", "sel_text": "#e6eaf0",
        "danger": "#e06c5e", "danger_hover": "#ea7d6e",
        "scroll": "#4a5462", "scroll_hover": "#6b7684",
        "disabled_bg": "#2c333d", "disabled_text": "#8a95a1",
        "tab_sel_text": "#7db9f0",
        "verdicts": {
            "ok": "#4ade80", "bad": "#f87171", "run": "#6cb2f5",
            "warn": "#fbbf24", "neutral": "#a3b0bd",
        },
    },
    "Ocean": {
        "page": "#eaf1f7", "card": "#ffffff", "alt": "#e2ecf4",
        "text": "#173049", "muted": "#4f6a83", "border": "#c3d4e2",
        "accent": "#1f6fa8", "accent_press": "#185a8a",
        "accent_text": "#ffffff", "link": "#1a5d8f", "warn": "#8f5510",
        "sel_bg": "#d3e4f2", "sel_text": "#12283c",
        "danger": "#b54a44", "danger_hover": "#c75c55",
        "scroll": "#b6cadb", "scroll_hover": "#8fa9c0",
        "disabled_bg": "#e7edf2", "disabled_text": "#7a8794",
        "tab_sel_text": "#1a5d8f",
        "verdicts": {
            "ok": "#1e7a46", "bad": "#b03a2e", "run": "#1f6fa8",
            "warn": "#a05a08", "neutral": "#4f6a83",
        },
    },
    "Forest": {
        "page": "#edf4ee", "card": "#ffffff", "alt": "#e4efe6",
        "text": "#1d3527", "muted": "#5a7362", "border": "#c4d8c8",
        "accent": "#2e7d54", "accent_press": "#246544",
        "accent_text": "#ffffff", "link": "#276b49", "warn": "#7d5410",
        "sel_bg": "#d4e9dc", "sel_text": "#17301f",
        "danger": "#b0503f", "danger_hover": "#c26351",
        "scroll": "#b8cdbd", "scroll_hover": "#93ac99",
        "disabled_bg": "#e9f0ea", "disabled_text": "#75806f",
        "tab_sel_text": "#276b49",
        "verdicts": {
            "ok": "#2e7d54", "bad": "#a84433", "run": "#2c6ba8",
            "warn": "#8a5a12", "neutral": "#5a7362",
        },
    },
    "High Contrast": {
        "page": "#ffffff", "card": "#ffffff", "alt": "#e8e8e8",
        "text": "#000000", "muted": "#3c3c3c", "border": "#555555",
        "accent": "#003d7a", "accent_press": "#002b57",
        "accent_text": "#ffffff", "link": "#003d7a", "warn": "#7a4a00",
        "sel_bg": "#b3d4f5", "sel_text": "#000000",
        "danger": "#8f1d1d", "danger_hover": "#a52a2a",
        "scroll": "#999999", "scroll_hover": "#555555",
        "disabled_bg": "#e0e0e0", "disabled_text": "#666666",
        "tab_sel_text": "#003d7a",
        "verdicts": {
            "ok": "#006400", "bad": "#8f1d1d", "run": "#003d7a",
            "warn": "#7a4a00", "neutral": "#3c3c3c",
        },
    },
}

_TEMPLATE = """
QWidget {
    font-size: 15px;
    color: @text;
}

QMainWindow, QDialog {
    background-color: @page;
}

/* ------------------------------------------------------------- cards */
QGroupBox {
    background-color: @card;
    border: 1px solid @border;
    border-radius: 8px;
    margin-top: 26px;
    padding: 10px 10px 8px 10px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 2px 6px;
    color: @link;
    font-size: 15px;
}

/* -------------------------------------------------- menu + menu bar */
QMenuBar {
    background-color: @page;
    color: @text;
    border-bottom: 1px solid @border;
    padding: 2px 4px;
}
QMenuBar::item {
    background: transparent;
    padding: 6px 14px;
    border-radius: 4px;
    color: @text;
}
QMenuBar::item:selected { background-color: @accent; color: @accent_text; }
QMenuBar::item:pressed { background-color: @accent_press; color: @accent_text; }
QMenu {
    background-color: @card;
    color: @text;
    border: 1px solid @border;
    border-radius: 6px;
}
QMenu::item {
    padding: 6px 30px 6px 14px;
    border-radius: 4px;
}
QMenu::item:selected { background-color: @accent; color: @accent_text; }
QMenu::item:disabled { color: @disabled_text; }
QMenu::separator {
    height: 1px;
    background-color: @border;
    margin: 4px 8px;
}

/* ----------------------------------------------------------- buttons */
QPushButton {
    background-color: @accent;
    color: @accent_text;
    border: none;
    border-radius: 5px;
    padding: 7px 16px;
    min-height: 26px;
}
QPushButton:hover { background-color: @accent_hover; }
QPushButton:pressed { background-color: @accent_press; }
QPushButton:focus { border: 1px solid @text; outline: none; }
QPushButton:disabled { background-color: @disabled_bg; color: @disabled_text; }
QPushButton#danger { background-color: @danger; color: @accent_text; }
QPushButton#danger:hover { background-color: @danger_hover; }
QPushButton#flat {
    background-color: @alt;
    color: @text;
}
QPushButton#flat:hover { background-color: @border; }
QPushButton#flat:pressed { background-color: @scroll; }
QPushButton#flat:disabled { background-color: @disabled_bg; color: @disabled_text; }

/* ------------------------------------------------------------ inputs */
QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: @card;
    color: @text;
    border: 1px solid @border;
    border-radius: 5px;
    padding: 5px 8px;
    min-height: 22px;
    selection-background-color: @accent;
    selection-color: @accent_text;
}
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid @accent;
}
QPlainTextEdit:disabled, QLineEdit:disabled, QComboBox:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled {
    background-color: @disabled_bg;
    color: @disabled_text;
}
QComboBox QAbstractItemView {
    background-color: @card;
    color: @text;
    border: 1px solid @border;
    selection-background-color: @sel_bg;
    selection-color: @sel_text;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 3px 8px;
}

/* ----------------------------------------------------------- console */
QPlainTextEdit#console, QTextEdit#console {
    font-family: Consolas, "Courier New", Menlo, monospace;
    font-size: 14px;
}

/* -------------------------------------------------------- status bar */
QStatusBar {
    background-color: @alt;
    color: @text;
    min-height: 26px;
}
QProgressBar {
    background-color: @disabled_bg;
    border: 1px solid @border;
    border-radius: 8px;
    min-height: 16px;
    text-align: center;
    color: @text;
    font-size: 12px;
}
QProgressBar::chunk {
    background-color: @accent;
    border-radius: 7px;
}

QCheckBox { spacing: 8px; color: @text; }
QLabel { background-color: transparent; }
QLabel#muted { color: @muted; }
QLabel#strong { color: @text; font-weight: bold; }
QLabel#accent_label { color: @link; font-weight: bold; }
QLabel#warn { color: @warn; }

QToolTip {
    background-color: @card;
    color: @text;
    border: 1px solid @border;
    border-radius: 4px;
    padding: 6px 9px;
    font-size: 13px;
}

/* -------------------------------------------------------------- tabs */
QTabWidget::pane {
    border: 1px solid @border;
    border-radius: 0 0 6px 6px;
    background-color: @page;
    top: -1px;
}
QTabBar::tab {
    background-color: @alt;
    color: @text;
    padding: 8px 24px;
    border: 1px solid @border;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    font-weight: bold;
}
QTabBar::tab:selected {
    background-color: @card;
    color: @tab_sel_text;
    border-top: 3px solid @accent;
}
QTabBar::tab:hover:!selected { background-color: @border; }

/* ------------------------------------------------------------- table */
QHeaderView::section {
    background-color: @alt;
    color: @text;
    border: 1px solid @border;
    padding: 6px 10px;
    font-weight: bold;
}
QTableWidget {
    background-color: @card;
    alternate-background-color: @alt;
    color: @text;
    border: 1px solid @border;
    border-radius: 5px;
    gridline-color: @border;
    selection-background-color: @sel_bg;
    selection-color: @sel_text;
}
QTableWidget::item { padding: 3px 6px; }
QTableWidget::item:selected { background-color: @sel_bg; color: @sel_text; }

/* --------------------------------------------------------- splitter */
QSplitter::handle { background-color: @border; }
QSplitter::handle:hover { background-color: @accent; }

/* -------------------------------------------------------- scrollbars */
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: @scroll;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: @scroll_hover; }
QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: @scroll;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: @scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0px; width: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def build_qss(name="Light"):
    """Full application stylesheet for the theme `name` (tokens are
    substituted into the template via @name placeholders)."""
    t = GUI_THEMES.get(name, GUI_THEMES["Light"])
    t = dict(t, accent_hover=t.get("accent_hover", _hover(t["accent"])))
    qss = _TEMPLATE
    for key, value in t.items():
        if isinstance(value, str):
            qss = qss.replace("@" + key, value)
    return qss


def _hover(accent):
    """A slightly lighter hover variant of the accent color."""
    name = accent.lstrip("#")
    if len(name) == 3:
        name = "".join(c * 2 for c in name)
    r, g, b = (int(name[i:i + 2], 16) for i in (0, 2, 4))
    lift = lambda v: min(255, int(v + (255 - v) * 0.15))
    return f"#{lift(r):02x}{lift(g):02x}{lift(b):02x}"


def saved_theme():
    """Theme name chosen by the user (Light when never changed)."""
    name = QSettings(APP_ORG, APP_NAME).value("gui_theme", "Light")
    return name if name in GUI_THEMES else "Light"


def gui_theme_color(key):
    """Verdict / status color for the current GUI theme ('ok', 'bad',
    'run', 'warn', 'neutral')."""
    verdicts = GUI_THEMES[saved_theme()]["verdicts"]
    return verdicts.get(key, verdicts["neutral"])


def text_for_card(color):
    """Readable text variant of a brand color on the current theme's
    card background (darkens it on light cards, lightens on dark)."""
    card = GUI_THEMES[saved_theme()]["card"]
    return text_on_dark(color) if is_dark(card) else text_on_light(color)


# backward-compatible default (main.py applies this before any window)
QSS = build_qss("Light")


# ------------------------------------------------------------ contrast
def _lum(hex_color):
    name = hex_color.lstrip("#")
    if len(name) == 3:
        name = "".join(c * 2 for c in name)
    r, g, b = (int(name[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    lin = lambda v: v / 12.92 if v <= 0.03928 \
        else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(fg, bg):
    """WCAG contrast ratio between two hex colors (1.0 - 21.0)."""
    l1, l2 = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def audit_theme(name):
    """Return [(pair, ratio, required)] for every text/background pair
    of the theme that falls below its WCAG threshold (4.5:1 normal
    text, 3.0:1 disabled or decorative)."""
    t = GUI_THEMES[name]
    checks = [
        ("text on page", t["text"], t["page"], 4.5),
        ("text on card", t["text"], t["card"], 4.5),
        ("text on alt", t["text"], t["alt"], 4.5),
        ("muted on card", t["muted"], t["card"], 4.5),
        ("muted on page", t["muted"], t["page"], 4.5),
        ("accent_text on accent", t["accent_text"], t["accent"], 4.5),
        ("accent_text on danger", t["accent_text"], t["danger"], 4.5),
        ("sel_text on sel_bg", t["sel_text"], t["sel_bg"], 4.5),
        ("link on card", t["link"], t["card"], 4.5),
        ("warn on card", t["warn"], t["card"], 4.5),
        ("tab_sel_text on card", t["tab_sel_text"], t["card"], 4.5),
        ("verdict ok on card", t["verdicts"]["ok"], t["card"], 3.0),
        ("verdict bad on card", t["verdicts"]["bad"], t["card"], 3.0),
        ("verdict run on card", t["verdicts"]["run"], t["card"], 3.0),
        ("verdict warn on card", t["verdicts"]["warn"], t["card"], 3.0),
        ("disabled_text on disabled_bg",
         t["disabled_text"], t["disabled_bg"], 3.0),
    ]
    return [(n, round(contrast(f, b), 2), req)
            for n, f, b, req in checks if contrast(f, b) < req]


def audit_all():
    """Audit every theme; return {theme: violations} (empty dict = all
    themes pass)."""
    return {name: issues for name in GUI_THEMES
            if (issues := audit_theme(name))}
