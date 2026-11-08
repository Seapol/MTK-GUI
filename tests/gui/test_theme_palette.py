"""M94: a theme must set a palette as well as a stylesheet, otherwise the
surfaces the stylesheet does not name stay light and the theme's light
text disappears into them."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402

from mtkgui import style  # noqa: E402


@pytest.mark.parametrize("theme", sorted(style.GUI_THEMES))
def test_palette_matches_the_tokens(theme):
    t = style.GUI_THEMES[theme]
    p = style.theme_palette(theme)
    pairs = (
        (QPalette.ColorRole.Window, "page"),
        (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "card"),
        (QPalette.ColorRole.AlternateBase, "alt"),
        (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.Highlight, "accent"),
        (QPalette.ColorRole.HighlightedText, "accent_text"),
        (QPalette.ColorRole.PlaceholderText, "placeholder"),
    )
    for role, key in pairs:
        assert p.color(role).name().lower() == QColor(t[key]).name().lower()


def _light_share(widget):
    image = widget.grab().toImage()
    light = total = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            px = image.pixelColor(x, y)
            lum = 0.2126 * px.red() + 0.7152 * px.green() + 0.0722 * px.blue()
            light += lum > 200
            total += 1
    return light / total


@pytest.mark.parametrize("theme", sorted(style.GUI_THEMES))
def test_dialog_body_matches_the_page_luminance(qapp, theme):
    """The reported bug: a light scroll panel inside a dark dialog.
    Dark = page luminance < 128 (today only Dark; Ocean, Forest, Light
    and High Contrast are light themes and must stay light)."""
    from mtkgui.main_window import FctWatchdogDialog

    style.apply_theme(qapp, theme)
    dialog = FctWatchdogDialog(8.0)
    dialog.resize(560, 700)
    dialog.show()
    qapp.processEvents()
    share = _light_share(dialog)
    dialog.close()
    if style.is_dark(style.GUI_THEMES[theme]["page"]):
        assert share < 0.15, f"{theme}: {share:.1%} of the dialog is a light panel"
    else:
        assert share > 0.55, f"{theme}: light theme went dark ({share:.1%})"
