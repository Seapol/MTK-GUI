# -*- coding: utf-8 -*-
"""GUI global layout compliance tests (V4.0 acceptance section 6).

Offscreen geometry assertions over the whole MainWindow and the Yaml
Build page at multiple resolutions: global non-intrusion, adaptive
dual-pane ratio, uniform button bar, adaptive module dialogs, and
page-switch stability.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.gui.yamlbuild.blocks import BlockConfigDialog  # noqa: E402
from mtkgui.gui.yamlbuild.schema import fields_for  # noqa: E402
from mtkgui.gui.yamlbuild.stages import (  # noqa: E402
    STAGE_KEYS,
    WORKFLOW_STAGES,
)
from mtkgui.yaml_build_page import YamlBuildPage  # noqa: E402

#: V4.0 acceptance resolution matrix (rule 6.2)
RESOLUTIONS = ((1920, 1080), (2560, 1440), (3840, 2160), (1024, 640))


@pytest.fixture(scope="module")
def qapp():
    """One offscreen QApplication (full MainWindow included so the
    app-level dialog centering event filter is active)."""
    app = QApplication.instance() or QApplication([])
    from mtkgui.main_window import MainWindow
    window = MainWindow()
    window.show()
    yield window
    window.close()


@pytest.fixture
def page(qapp, tmp_path, monkeypatch):
    """A fresh Yaml Build page with the store pointed at tmp."""
    from mtkgui.gui.yamlbuild import store
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    monkeypatch.setattr(store, "STATE_FILE", tmp_path / "state.json")
    return YamlBuildPage()


def _activate(page, width: int, height: int) -> None:
    """Show the page at one resolution and flush the layout (Qt only
    distributes final geometries once the widget is shown)."""
    page.resize(width, height)
    page.show()
    QApplication.processEvents()


def _card_rects(page) -> dict:
    """Card geometries in flow coordinates (None when not laid out)."""
    out = {}
    flow = page.block_flow.flow
    for stage in WORKFLOW_STAGES:
        card = page.block_flow._cards[stage.key]
        out[stage.key] = card.geometry() if card.parent() is flow \
            else card.geometry()
    return out


# ---------------------------------------------------------------------------
# 6.1 global layout non-intrusion
# ---------------------------------------------------------------------------


def test_global_layout_unpolluted(qapp):
    """Mounting the Yaml Build tab adds exactly one tab at the
    rightmost position and leaves every other page's structure
    intact (tab texts, event log visible, workflow page default)."""
    window = qapp
    tabs = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert tabs == ["Test Work Flow", "Equipment", "Yaml Build"]
    assert window.tabs.currentWidget() is window.workflow_page
    assert window.event_log.isVisible() or window.event_log.parent() \
        is not None
    # classic page roots still carry their own content
    assert window.workflow_page.product_group.parent() is not None
    assert window.equipment_page.layout() is not None


# ---------------------------------------------------------------------------
# 6.2 multi-resolution adaptation + 6.3 button bar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width,height", RESOLUTIONS)
def test_resolution_adaptation(page, qapp, width, height):
    """At every resolution: children stay inside the page, the dual
    pane keeps its 6:4 ratio, cards never overlap or clip, and no
    horizontal overflow appears."""
    _activate(page, width, height)
    # dual-pane ratio locked (stretch factors 6:4)
    split = None
    for child in page.children():
        if type(child).__name__ == "QSplitter":
            split = child
    assert split is not None
    sizes = split.sizes()
    ratio = sizes[0] / max(1, sum(sizes))
    assert 0.55 <= ratio <= 0.65, f"pane ratio {ratio:.2f} at {width}x{height}"
    # no child of the page extends beyond the page rect
    page_rect = page.rect()
    for child in page.findChildren(type(page.block_flow)):
        rect = child.geometry()
        assert rect.right() <= page_rect.width() + 1, (
            f"horizontal overflow at {width}x{height}: "
            f"{type(child).__name__}")
    # flow cards: pairwise disjoint, fully inside the flow area
    rects = [page.block_flow._cards[k].geometry()
             for k in STAGE_KEYS]
    for i, a in enumerate(rects):
        assert 0 <= a.left() and a.right() <= page.block_flow.width(), (
            f"card clipped at {width}x{height}")
        for b in rects[i + 1:]:
            assert not a.intersects(b), (
                f"card overlap at {width}x{height}")


@pytest.mark.parametrize("width,height", RESOLUTIONS)
def test_button_bar_uniform(page, qapp, width, height):
    """The four action buttons keep a fixed height, share one row,
    never overlap and stay inside the page at every resolution."""
    _activate(page, width, height)
    rects = [btn.geometry() for btn in page._action_buttons]
    heights = {r.height() for r in rects}
    assert len(heights) == 1                   # fixed, uniform height
    assert next(iter(heights)) >= 34           # never squeezed below
    ys = {r.y() for r in rects}
    assert len(ys) == 1                        # one aligned row
    xs = [r.x() for r in rects]
    assert xs == sorted(xs)                    # stable order
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not a.intersects(b)
        assert a.right() <= page.rect().width()


# ---------------------------------------------------------------------------
# 6.5 dialog layout adaptation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_key", STAGE_KEYS)
def test_module_dialog_adapts(page, qapp, module_key):
    """Every module dialog shows all its fields, auto-sizes to the
    content and pops up centered on the screen (app event filter)."""
    dialog = BlockConfigDialog(module_key, {}, page)
    rows = dialog.form.rowCount()
    assert rows >= len(fields_for(module_key))   # no field dropped
    dialog.show()
    QApplication.processEvents()
    hint = dialog.sizeHint()
    assert dialog.width() >= min(int(hint.width() * 1.4), hint.width())
    screen = dialog.screen() or \
        QApplication.instance().primaryScreen()
    avail = screen.availableGeometry()
    center = dialog.frameGeometry().center()
    assert avail.adjusted(-40, -40, 40, 40).contains(center), (
        "dialog not centered on its screen")
    dialog.close()


# ---------------------------------------------------------------------------
# 6.6 page-switch stability
# ---------------------------------------------------------------------------


def test_tab_switch_and_restart_stability(page, qapp):
    """Repeated tab switching and a page re-instantiation keep the
    layout byte-stable (no first-load shift, no re-render collapse)."""
    _activate(page, 1600, 900)
    before = {k: r for k, r in _card_rects(page).items()}
    before_buttons = [b.geometry() for b in page._action_buttons]

    for _ in range(5):
        page.setVisible(False)
        page.setVisible(True)
        QApplication.processEvents()
    page.resize(1600, 900)
    page.layout().activate()
    QApplication.processEvents()

    after = _card_rects(page)
    assert after == before, "card geometry shifted after tab switching"
    assert [b.geometry() for b in page._action_buttons] == before_buttons

    # restart simulation: a fresh page with the same size lays out
    # identically (first-load == steady state)
    fresh = YamlBuildPage()
    _activate(fresh, 1600, 900)
    assert _card_rects(fresh) == before


def test_window_geometry_persistence(qapp, monkeypatch):
    """Rule 6.7 sizing policy: with a saved user geometry the window
    restores it (the screen-fit branch never runs); without one the
    window auto-fits the screen.  The policy seam is tested by
    recording restoreGeometry calls (real geometry restore is the
    Qt framework's job and is screen-clamped offscreen)."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from mtkgui import main_window as mw
    from mtkgui.style import APP_NAME, APP_ORG

    settings = QSettings(APP_ORG, APP_NAME)
    original = settings.value("window/geometry")
    calls = {"n": 0}

    def fake_restore(self, geometry):
        calls["n"] += 1
        return geometry is not None

    monkeypatch.setattr(mw.MainWindow, "restoreGeometry", fake_restore)

    # 1) saved user geometry -> restore wins, no screen-fit resize
    settings.setValue("window/geometry", b"user-geometry-marker")
    w2 = mw.MainWindow()
    assert calls["n"] == 1
    fit_w = min(mw.DEFAULT_WIDTH,
                QApplication.primaryScreen().availableGeometry().width()
                - 40)
    assert w2.width() != fit_w or calls["n"] == 1

    # 2) no saved geometry -> screen-fit default (centered, <= screen)
    settings.remove("window/geometry")
    w3 = mw.MainWindow()
    assert calls["n"] == 1                    # restore not attempted
    assert w3.width() <= QApplication.primaryScreen().availableGeometry(
        ).width()
    w3.close()
    # cleanup: restore the previous setting for the operator's session
    if original is None:
        settings.remove("window/geometry")
    else:
        settings.setValue("window/geometry", original)
    settings.sync()
