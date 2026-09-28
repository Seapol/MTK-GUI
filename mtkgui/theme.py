# -*- coding: utf-8 -*-
"""Console color themes.

The console defaults to a black background (dark theme). When the user
picks a background color, the theme is chosen from its relative
luminance so the text always has enough contrast.
"""

DEFAULT_BACKGROUND = "#000000"

THEMES = {
    "dark": {
        "rx": "#33d17a",
        "tx": "#55a3ff",
        "sys": "#f5c211",
        "err": "#ff7b63",
        "timestamp": "#7a828a",
        "tag": "#9aa4b2",
        "base": "#e6e6e6",
        "border": "#3a3f46",
    },
    "light": {
        "rx": "#1a7a3c",
        "tx": "#1f5fbf",
        "sys": "#cc6600",
        "err": "#c0504d",
        "timestamp": "#888888",
        "tag": "#888888",
        "base": "#222222",
        "border": "#c5ccd6",
    },
}


def is_dark(color):
    """Return True if a QColor / hex string is a dark background."""
    name = color if isinstance(color, str) else color.name()
    name = name.lstrip("#")
    if len(name) == 3:
        name = "".join(c * 2 for c in name)
    r, g, b = (int(name[i:i + 2], 16) for i in (0, 2, 4))
    # sRGB relative luminance.
    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return luminance < 0.5


def theme_for(color):
    return "dark" if is_dark(color) else "light"


def text_on_light(color, max_luma=0.30):
    """Return a variant of `color` that stays readable as text on a
    white / light background: colors that are too bright (yellow, light
    teal, sky blue, ...) are darkened just enough for comfortable
    reading. Used for colored labels, e.g. the rail checkboxes."""
    name = color if isinstance(color, str) else color.name()
    name = name.lstrip("#")
    if len(name) == 3:
        name = "".join(c * 2 for c in name)
    r, g, b = (int(name[i:i + 2], 16) for i in (0, 2, 4))

    def lum(r, g, b):
        def lin(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else \
                ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    while lum(r, g, b) > max_luma and (r, g, b) != (0, 0, 0):
        r, g, b = int(r * 0.88), int(g * 0.88), int(b * 0.88)
    return f"#{r:02x}{g:02x}{b:02x}"


def text_on_dark(color, min_luma=0.55):
    """Return a variant of `color` that stays readable as text on a
    dark background: colors that are too dark are lightened just
    enough for comfortable reading."""
    name = color if isinstance(color, str) else color.name()
    name = name.lstrip("#")
    if len(name) == 3:
        name = "".join(c * 2 for c in name)
    r, g, b = (int(name[i:i + 2], 16) for i in (0, 2, 4))

    def lum(r, g, b):
        def lin(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else \
                ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    while lum(r, g, b) < min_luma and (r, g, b) != (255, 255, 255):
        r, g, b = (min(255, int(v * 1.15) + 6) for v in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"
