# -*- coding: utf-8 -*-
"""B1 final menu-baseline tests: fixed top-level menu order and the
Tools > Set All instruments batch operations (smoke over a scripted
gateway, no hardware)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def window():
    """One offscreen MainWindow."""
    app = QApplication.instance() or QApplication([])
    from mtkgui.main_window import MainWindow
    window = MainWindow()
    window.show()
    yield window
    window.close()


def _wait_batch(window, timeout_s: float = 5.0) -> None:
    """Pump the event loop until the batch worker has delivered."""
    app = QApplication.instance()
    deadline = __import__("time").monotonic() + timeout_s
    while __import__("time").monotonic() < deadline:
        app.processEvents()
        if window._tools_thread is not None \
                and not window._tools_thread.isRunning() \
                and window._tools_thread.isFinished():
            break
    app.processEvents()


def test_fixed_menu_order(window):
    """Final standard order: File, View, Settings, Tools, Report,
    Help (rightmost) - stable across tab switches."""
    from PySide6.QtWidgets import QApplication
    assert [a.text() for a in window.menuBar().actions()] == \
        ["File", "View", "Settings", "Tools", "Report", "Help"]
    window.tabs.setCurrentWidget(window.yaml_build_page)
    QApplication.processEvents()
    assert [a.text() for a in window.menuBar().actions()] == \
        ["File", "View", "Settings", "Tools", "Report", "Help"]


def test_tools_submenu_structure(window):
    """Set All instruments carries the four batch actions, each with
    a non-empty tooltip."""
    tools = [a for a in window.menuBar().actions()
             if a.text() == "Tools"][0]
    set_all = tools.menu().actions()[0]
    assert set_all.text() == "Set All instruments"
    names = [a.text() for a in set_all.menu().actions()]
    assert names == ["Connect all", "Disconnect all", "Reset all",
                     "Test all connections"]
    assert all(a.toolTip().strip() for a in set_all.menu().actions())


def test_tools_batch_requires_configuration(window, monkeypatch):
    """With no instrument configured the batch warns with Equipment
    guidance and never touches the gateway."""
    shown = []
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.warning",
        lambda *a, **k: shown.append(a))
    monkeypatch.setattr(window, "_configured_instruments",
                        lambda: [])
    window._tools_batch("Connect all")
    assert len(shown) == 1
    assert "Equipment" in shown[0][2]
    assert window._tools_thread is None


def _scripted_gateway(monkeypatch, fail: bool = False):
    """Inject a scripted RealGateway into the engine module."""
    class _FakeOutcome:
        def __init__(self):
            self.verdict = "Error" if fail else "Done"
            self.lines = ["DAQM init OK: FAKE-IDN"] if not fail else \
                ["DAQM init failed: connection refused"]

    class _FakeGateway:
        calls = []

        def __init__(self, equipment=None, config=None):
            self.equipment = equipment
            type(self).calls.append(("create", dict(equipment or {})))

        def execute_op(self, name, params):
            type(self).calls.append(("op", name, dict(params or {})))
            return _FakeOutcome()

        def close(self):
            type(self).calls.append(("close",))

    import mtkgui.engine.instruments as inst
    monkeypatch.setattr(inst, "RealGateway", _FakeGateway)
    return _FakeGateway


def test_tools_connect_all_smoke(window, monkeypatch):
    """Connect all opens the gateway with the YAML equipment config,
    reports OK lines into the Event Log and caches the session."""
    fake = _scripted_gateway(monkeypatch, fail=False)
    window.equipment_page.configs = {
        "DAQM": {"fields": {"Address": "TCPIP0::1.2.3.4::inst0::INSTR"}},
        "PSU": {"fields": {"Address": "USB0::123::INSTR"}},
    }
    window._tools_gateway = None
    window._tools_batch("Connect all")
    _wait_batch(window)
    assert window._tools_gateway is not None
    calls = [c[0] for c in fake.calls]
    assert "create" in calls and "op" in calls
    op = [c for c in fake.calls if c[0] == "op"][0]
    assert op[1] == "Init Instruments"
    assert op[2]["instruments"] == ["DAQM", "PSU"]
    log = window.event_log.toPlainText()
    assert "[Tools] Connect all" in log
    # cached session is reused by the next batch (no new gateway)
    create_count = len([c for c in fake.calls if c[0] == "create"])
    window._tools_batch("Disconnect all")
    _wait_batch(window)
    assert len([c for c in fake.calls if c[0] == "create"]) \
        == create_count


def test_tools_failure_popup_with_guidance(window, monkeypatch):
    """Failures pop up with the precise reason and the Equipment-page
    guidance, and are logged for traceability."""
    fake = _scripted_gateway(monkeypatch, fail=True)
    shown = []
    monkeypatch.setattr(
        "mtkgui.main_window.QMessageBox.warning",
        lambda *a, **k: shown.append(a))
    window.equipment_page.configs = {
        "DAQM": {"fields": {"Address": "TCPIP0::1.2.3.4::inst0::INSTR"}},
    }
    window._tools_gateway = None
    window._tools_batch("Connect all")
    _wait_batch(window)
    assert len(shown) == 1
    text = shown[0][2]
    assert "Equipment" in text
    assert "connection refused" in text
    log = window.event_log.toPlainText()
    assert "[Tools] Connect all: DAQM init failed" in log
