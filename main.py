# -*- coding: utf-8 -*-
"""MTK GUI entry point.

Run with: python main.py
"""

import sys
from pathlib import Path

import mtkgui.startup_timing as _timing

# QtWebEngine MUST be loaded before QApplication is created (M13):
# the SharePoint sign-in window builds QWebEngineProfile /
# QWebEnginePage / QWebEngineView at runtime, and PySide6 6.10.3
# segfaults (SIGSEGV) when the WebEngine modules are first imported
# after the Cocoa platform plug-in is live.  The dialog keeps its own
# lazy import, so this unconditional pre-QApplication load is the fix;
# it must stay outside any try/except that could silently skip it.
import PySide6.QtWebEngineWidgets  # noqa: F401

_timing.mark("QtWebEngine loaded")


def _app_icon_path():
    """Application icon (brand mark) inside the bundled ``resources``.

    A frozen PyInstaller build unpacks ``resources`` next to the entry
    script under ``sys._MEIPASS`` (``_internal`` for onedir), so the
    bundle root is used there instead of the source tree.
    """
    bundle_root = getattr(sys, "_MEIPASS", None)
    root = (Path(bundle_root) if bundle_root
            else Path(__file__).resolve().parent)
    return root / "resources" / "app_icon.png"


def main():
    import faulthandler

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from mtkgui import __app_name__
    from mtkgui.main_window import MainWindow
    from mtkgui.permissions import LoginDialog
    from mtkgui.style import QSS

    _timing.mark("imports done")
    # native crash reports lack Python frames; faulthandler prints the
    # exact Python stack to stderr on SIGSEGV (macOS exit-crash forensics)
    if sys.stderr is not None:  # windowed PyInstaller builds have no stderr
        faulthandler.enable()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)
    app.setOrganizationName("Manufacturing Test Kit")
    app.setStyleSheet(QSS)
    icon_path = _app_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    _timing.mark("QApplication ready")

    # startup login: Supervisor (password) or Operator; must pick one.
    # Returns (role, mode, fixture_type); Virtual mode is supervisor-
    # only, fixture type is ATE (default) / Manual per login.
    result = LoginDialog.login(None, allow_cancel=False)
    if result is None:
        sys.exit(0)
    role, mode, fixture = result
    _timing.mark(f"login done (role={role}, mode={mode}, fixture={fixture})")

    window = MainWindow(role, mode, fixture)
    _timing.mark("MainWindow constructed")
    window.show()
    _timing.mark("window shown")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
