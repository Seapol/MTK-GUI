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

import base64
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette

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
            "ok": "#1d7a3c", "bad": "#c0392b", "virtual_ok": "#7aa016", "virtual_bad": "#d35400", "run": "#2f6fb3",
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
            "ok": "#4ade80", "bad": "#f87171", "virtual_ok": "#a3d139", "virtual_bad": "#ff7043", "run": "#6cb2f5",
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
            "ok": "#1e7a46", "bad": "#b03a2e", "virtual_ok": "#7aa016", "virtual_bad": "#c9551e", "run": "#1f6fa8",
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
            "ok": "#2e7d54", "bad": "#a84433", "virtual_ok": "#4e7d1e", "virtual_bad": "#bf4d1e", "run": "#2c6ba8",
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
            "ok": "#006400", "bad": "#8f1d1d", "virtual_ok": "#6b7d00", "virtual_bad": "#a03d00", "run": "#003d7a",
            "warn": "#7a4a00", "neutral": "#3c3c3c",
        },
    },
}

#: M67: every theme gets a `placeholder` token derived from `muted` and
#: tuned with the contrast helpers (>= 4.5:1 on that theme's card).  Qt
#: otherwise uses the Fusion palette placeholder color, which does NOT
#: follow the GUI theme ("switching themes does nothing" report).
for _name, _theme in GUI_THEMES.items():
    _muted = _theme["muted"]
    _theme["placeholder"] = (text_on_dark(_muted)
                             if is_dark(_theme["card"])
                             else text_on_light(_muted))

# M94: semantic label tones derived from the contrast-checked verdicts
for _theme in GUI_THEMES.values():
    _theme["text_ok"] = _theme["verdicts"]["ok"]
    _theme["text_bad"] = _theme["verdicts"]["bad"]

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
QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QDateTimeEdit, QDateEdit, QTimeEdit {
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
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QDateTimeEdit:focus, QDateEdit:focus, QTimeEdit:focus {
    border: 1px solid @accent;
}
QPlainTextEdit:disabled, QLineEdit:disabled, QComboBox:disabled,
QSpinBox:disabled, QDoubleSpinBox:disabled,
QDateTimeEdit:disabled, QDateEdit:disabled, QTimeEdit:disabled {
    background-color: @disabled_bg;
    color: @disabled_text;
}
/* M67: placeholder text follows the GUI theme (Fusion's palette color
   does not); Qt 6 exposes the same property on the text editors. */
QLineEdit, QPlainTextEdit, QTextEdit {
    placeholder-text-color: @placeholder;
}
/* M67: read-only rows (Basic Information / Hardware Info) stay readable
   on every theme instead of falling back to palette rendering.  The
   widget property selector is the Qt QSS form that reliably applies
   (there is no :read-only pseudo-state on the edit widgets). */
QLineEdit[readOnly="true"], QPlainTextEdit[readOnly="true"],
QTextEdit[readOnly="true"], QComboBox[readOnly="true"] {
    background-color: @alt;
    color: @text;
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
/* styling ANY QCheckBox property switches Qt to stylesheet rendering;
   without an explicit indicator rule the checkbox degenerates into an
   unreadable solid square (checked and unchecked look identical on
   the dark themes) */
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid @border;
    border-radius: 3px;
    background-color: @card;
}
QCheckBox::indicator:hover {
    border-color: @accent;
}
QCheckBox::indicator:checked {
    background-color: @accent;
    border-color: @accent;
    image: url("@check_icon");
}
/* the checkable item views (multi-select popups etc.) need the same
   explicit indicator rules - otherwise the check mark degenerates
   into an unreadable solid square on the dark themes */
QListView::indicator, QListWidget::indicator, QTreeWidget::indicator,
QTreeView::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid @border;
    border-radius: 3px;
    background-color: @card;
}
QListView::indicator:checked, QListWidget::indicator:checked,
QTreeWidget::indicator:checked, QTreeView::indicator:checked {
    background-color: @accent;
    border-color: @accent;
    image: url("@check_icon");
}
QLabel { background-color: transparent; }
QLabel#muted { color: @muted; }
QLabel#strong { color: @text; font-weight: bold; }
QLabel#accent_label { color: @link; font-weight: bold; }
QLabel#warn { color: @warn; }
/* M94: semantic label tones.  Widgets carry a `tone` property instead of
   an inline colour, so the theme can repaint them on every switch. */
QLabel[tone="muted"] { color: @muted; }
QLabel[tone="warn"] { color: @warn; }
QLabel[tone="error"] { color: @text_bad; }
QLabel[tone="ok"] { color: @text_ok; }
QLabel[tone="error"][emphasis="true"] { font-weight: bold; }
QGraphicsView[tone="bordered"] { border: 1px solid @border; }

/* M67: date / calendar / message-box families were not themed and
   could fall back to the system palette on the dark themes. */
QCalendarWidget QWidget {
    background-color: @card;
    color: @text;
}
QCalendarWidget QToolButton {
    background-color: @alt;
    color: @text;
    border: 1px solid @border;
    border-radius: 4px;
    padding: 3px 8px;
}
QCalendarWidget QToolButton:hover { background-color: @border; }
QCalendarWidget QMenu {
    background-color: @card;
    color: @text;
}
QCalendarWidget QSpinBox {
    background-color: @card;
    color: @text;
}
QCalendarWidget QAbstractItemView:enabled {
    background-color: @card;
    color: @text;
    selection-background-color: @accent;
    selection-color: @accent_text;
}
QMessageBox {
    background-color: @card;
}
QMessageBox QLabel { color: @text; }

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

/* ------------------------------------------------------- list widgets
   Without this rule an unstyled QListWidget falls back to the macOS
   system palette (dark in dark mode) next to theme-styled widgets -
   dark text on a dark background, unreadable. */
QListWidget, QListView {
    background-color: @card;
    alternate-background-color: @alt;
    color: @text;
    border: 1px solid @border;
    border-radius: 5px;
}
QListWidget::item { padding: 4px 8px; }
QListWidget::item:selected { background-color: @sel_bg; color: @sel_text; }
QListWidget::item:hover { background-color: @alt; }

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


# M93: the checked indicator used to be a solid accent square with no
# glyph, so "checked" was conveyed by colour only.  A 15x15 transparent
# check mark is written to the per-user temp folder and referenced from
# the stylesheet, because the frozen bundle does not ship mtkgui/assets
# (MTK_GUI_windows.spec datas only carries the root assets/ template)
# and this module promises "packaging needs no assets".  The mark colour
# follows accent_text, whose >= 4.5:1 contrast on accent is already
# enforced by audit_theme().
_TICK_PNG = {
    "white": (
        "iVBORw0KGgoAAAANSUhEUgAAAA8AAAAPCAYAAAA71pVKAAAACXBIWXMAAA7EAAAOxAGVKw4bAAAA"
        "mUlEQVQokd3QoQoCQRSF4QXBIKxFi1gMigaDL2L0mXweDYLRYBGbYBIsgiAYfILP4A3LsuiuweCB"
        "gWHu+X+4kyT/H4wwR/Mb8OaVWRWwh0uAK9TzhSFqBWAHpwA3aOQL0xgus1a0cIjZvnBXDHCP0gJ1"
        "pNjF2xHtd3tNMoI1tnE/o1vmY7ICuKL/EcwJHnHGpcGMIEVaGfxZnvEWzHrS3aKzAAAAAElFTkSu"
        "QmCC"
    ),
    "dark": (
        "iVBORw0KGgoAAAANSUhEUgAAAA8AAAAPCAYAAAA71pVKAAAACXBIWXMAAA7EAAAOxAGVKw4bAAAB"
        "E0lEQVQokd2QO08CURCFv7krJD4umnVJZCk0EVncWFj76G228z/5YyiMFQnBQnqtDBCDiQUGbYii"
        "USPsvTa6QYKJNBaebubkO5kz8P+lc8WS9otHrlvIAMxMA4pQB7LxrHMBlNVvwKWV0poSakAWofK4"
        "6JwAJLD2gwBwxsG51c2cUaZmIS9QnzdPhzQa7wms/UIk2FbGD44Jw3QSmC8tp4bDKrAO9tx5M1G3"
        "23358hWAqFQL6IGNMg+DMmGY9rxAC6ZirWwBTWvloNdr90evkqRXfmPbWDkFXJAq2AVgB7gZKPZe"
        "O1e345VkdPgeAMAdKt7vd67bkx4p44vPgDMAEzu7z/fNy0ngj/K8QHteoKeC/lQf8ytRNAeVRBgA"
        "AAAASUVORK5CYII="
    ),
}
_TICK_CACHE: dict[str, str] = {}


def _tick_bucket(accent_text: str) -> str:
    """Which check-mark variant sits on this theme's accent fill:
    'white' when accent_text is a light colour, 'dark' otherwise."""
    name = accent_text.lstrip("#")
    r, g, b = (int(name[i:i + 2], 16) for i in (0, 2, 4))
    light_mark = (0.2126 * r + 0.7152 * g + 0.0722 * b) >= 128
    return "white" if light_mark else "dark"


def _tick_icon(accent_text: str) -> str:
    """Filesystem url() for the check-mark PNG; '' when it cannot be
    written (the indicator then falls back to the plain accent fill)."""
    bucket = _tick_bucket(accent_text)
    if bucket in _TICK_CACHE:
        return _TICK_CACHE[bucket]
    try:
        folder = Path(tempfile.gettempdir()) / "mtkgui_qss"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"check_{bucket}.png"
        data = base64.b64decode(_TICK_PNG[bucket])
        if not path.exists() or path.stat().st_size != len(data):
            path.write_bytes(data)
        _TICK_CACHE[bucket] = path.as_posix()
    except OSError:
        _TICK_CACHE[bucket] = ""
    return _TICK_CACHE[bucket]


def build_qss(name="Light"):
    """Full application stylesheet for the theme `name` (tokens are
    substituted into the template via @name placeholders)."""
    t = GUI_THEMES.get(name, GUI_THEMES["Light"])
    t = dict(t, accent_hover=t.get("accent_hover", _hover(t["accent"])))
    t["check_icon"] = _tick_icon(t["accent_text"])
    qss = _TEMPLATE
    # longest token first: "@accent_text" / "@accent_press" must be
    # replaced before "@accent", or their leftovers become invalid
    # colors like "#2f6fb3_text"
    for key in sorted(
            (k for k, v in t.items() if isinstance(v, str)),
            key=len, reverse=True):
        qss = qss.replace("@" + key, t[key])
    return qss


def theme_palette(name="Light") -> QPalette:
    """QPalette for one GUI theme.

    The stylesheet alone leaves every surface it does not name (scroll
    viewports, spin-box popups, tooltips, plain containers, message boxes)
    on Fusion's light palette, while QWidget's colour token still paints
    light text into them.  Setting a palette as well means an unstyled
    widget is themed instead of merely recoloured."""
    t = GUI_THEMES.get(name, GUI_THEMES["Light"])
    p = QPalette()
    roles = (
        (QPalette.ColorRole.Window, "page"),
        (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "card"),
        (QPalette.ColorRole.AlternateBase, "alt"),
        (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.Button, "card"),
        (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.BrightText, "text"),
        (QPalette.ColorRole.Highlight, "accent"),
        (QPalette.ColorRole.HighlightedText, "accent_text"),
        (QPalette.ColorRole.ToolTipBase, "card"),
        (QPalette.ColorRole.ToolTipText, "text"),
        (QPalette.ColorRole.PlaceholderText, "placeholder"),
        (QPalette.ColorRole.Link, "link"),
    )
    for role, key in roles:
        p.setColor(role, QColor(t[key]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role,
                   QColor(t["disabled_text"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,
               QColor(t["disabled_bg"]))
    p.setColor(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight,
               QColor(t["accent"]))
    p.setColor(QPalette.ColorGroup.Inactive,
               QPalette.ColorRole.HighlightedText, QColor(t["accent_text"]))
    return p


def apply_theme(app, name="Light") -> None:
    """Apply palette AND stylesheet.  Call this, never setStyleSheet()
    alone: a stylesheet without a matching palette is exactly what made
    the Dark theme's dialogs unreadable."""
    app.setPalette(theme_palette(name))
    app.setStyleSheet(build_qss(name))


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
        # M67: placeholder + read-only rows + pressed accent button text
        ("placeholder on card", t["placeholder"], t["card"], 4.5),
        ("read-only text on alt", t["text"], t["alt"], 4.5),
        ("accent_text on accent_press", t["accent_text"],
         t["accent_press"], 3.0),
        ("verdict ok on card", t["verdicts"]["ok"], t["card"], 3.0),
        ("verdict bad on card", t["verdicts"]["bad"], t["card"], 3.0),
        ("verdict run on card", t["verdicts"]["run"], t["card"], 3.0),
        ("verdict warn on card", t["verdicts"]["warn"], t["card"], 3.0),
        ("disabled_text on disabled_bg",
         t["disabled_text"], t["disabled_bg"], 3.0),
        # M94: the semantic label tones
        ("text_ok on card", t["text_ok"], t["card"], 4.5),
        ("text_bad on card", t["text_bad"], t["card"], 4.5),
    ]
    return [(n, round(contrast(f, b), 2), req)
            for n, f, b, req in checks if contrast(f, b) < req]


def audit_all():
    """Audit every theme; return {theme: violations} (empty dict = all
    themes pass)."""
    return {name: issues for name in GUI_THEMES
            if (issues := audit_theme(name))}
