"""M93: every checked checkbox must show a check mark, not a colour
swatch.  The indicator is a filled accent square plus a 15x15 PNG mark
that the stylesheet references from the per-user temp folder."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from mtkgui import style  # noqa: E402


@pytest.mark.parametrize("theme", sorted(style.GUI_THEMES))
def test_every_theme_references_an_existing_tick(theme):
    qss = style.build_qss(theme)
    marker = 'image: url("'
    occurrences = qss.count(marker)
    assert occurrences == 2, f"{theme}: expected the checkbox and the item-view rule"
    for chunk in qss.split(marker)[1:]:
        path = Path(chunk.split('"')[0])
        assert path.exists(), f"{theme}: missing tick image {path}"
        assert path.stat().st_size > 150, f"{theme}: tick image looks empty"


def test_mark_colour_follows_accent_text():
    light = style.build_qss("Light")
    dark = style.build_qss("Dark")
    assert "check_white.png" in light
    assert "check_dark.png" in dark


def test_checked_indicator_is_not_a_flat_square(qapp):
    """Pixel regression: inside the accent square the check mark must
    contribute its own pixels.  A flat swatch gives exactly 0."""
    from PySide6.QtWidgets import QCheckBox

    theme = style.GUI_THEMES["Light"]
    accent = tuple(int(theme["accent"][i:i + 2], 16) for i in (1, 3, 5))
    mark = tuple(int(theme["accent_text"][i:i + 2], 16) for i in (1, 3, 5))

    def near(px, rgb, tol=25):
        return all(abs(c - t) <= tol
                   for c, t in zip((px.red(), px.green(), px.blue()), rgb))

    box = QCheckBox("Stop if failure")
    box.setStyleSheet(style.build_qss("Light"))
    box.setChecked(True)
    box.resize(160, 26)
    box.show()
    qapp.processEvents()
    image = box.grab().toImage()

    accent_px = [(x, y) for y in range(image.height())
                 for x in range(image.width())
                 if near(image.pixelColor(x, y), accent)]
    assert len(accent_px) > 40, "accent fill missing"

    xs = [p[0] for p in accent_px]
    ys = [p[1] for p in accent_px]
    # inset by 4px so the rounded corners' background pixels do not count
    mark_px = sum(
        1
        for y in range(min(ys) + 4, max(ys) - 3)
        for x in range(min(xs) + 4, max(xs) - 3)
        if near(image.pixelColor(x, y), mark)
    )
    assert mark_px >= 6, f"no check mark drawn inside the indicator ({mark_px})"
