# -*- coding: utf-8 -*-
"""MTK GUI entry point.

Run with: python main.py
"""

import sys
from pathlib import Path

# M81: the DUT report renderer runs in THIS same executable as a child
# process (--render-pdf) and must not pay the QtWebEngine import, so the
# dispatch sits before the preload below.
if "--render-pdf" in sys.argv:
    from mtkgui.render_proc import main as _render_main

    raise SystemExit(_render_main())

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


def _set_supervisor_password(accounts):
    """Prompt (twice, no echo) and write work/accounts/supervisor.json."""
    import getpass
    print(f"Station account file: {accounts.supervisor_path()}")
    try:
        first = getpass.getpass("New supervisor password: ")
        second = getpass.getpass("Repeat it: ")
    except (KeyboardInterrupt, EOFError):
        print("cancelled")
        raise SystemExit(1)
    if first != second:
        print("the two entries differ - nothing written")
        raise SystemExit(1)
    try:
        path = accounts.set_password(first)
    except ValueError as exc:
        print(f"refused: {exc}")
        raise SystemExit(1)
    print(f"written: {path}")


def main():
    import faulthandler

    # M97: station setup - set / show the supervisor hash without opening a
    # window.  This runs before QApplication so a headless deploy works.
    from mtkgui import accounts
    if "--set-supervisor-password" in sys.argv:
        _set_supervisor_password(accounts)
        return 0
    if "--supervisor-password-status" in sys.argv:
        print("configured" if accounts.is_configured()
              else "not configured")
        return 0

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from mtkgui import __app_name__
    from mtkgui.main_window import MainWindow
    from mtkgui.permissions import LoginDialog
    from mtkgui.style import apply_theme, saved_theme

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
    # M94: palette + stylesheet, so unstyled surfaces follow the theme too
    apply_theme(app, saved_theme())
    icon_path = _app_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    _timing.mark("QApplication ready")

    # startup login: Supervisor (password) or Operator; must pick one.
    # Returns (role, mode, fixture_type); Virtual mode is supervisor-
    # only, fixture type is ATE (default) / Manual per login.
    # The login prompt is WAIT (human time) - never confused with
    # program time in the performance log.
    _timing.begin("login", category="wait", wait=True)
    result = LoginDialog.login(None, allow_cancel=False)
    if result is None:
        _timing.end("login", note="cancelled - exiting")
        sys.exit(0)
    role, mode, fixture = result
    _timing.end("login",
                note=f"operator signed in ({role}, {mode}, {fixture})")

    from mtkgui.gui.startup_progress import StartupProgress
    progress = StartupProgress()
    progress.show()
    _timing.set_progress_handler(progress.handle_stage)
    try:
        window = MainWindow(role, mode, fixture)
        _timing.mark("MainWindow constructed")
    finally:
        # the progress window ALWAYS goes away, even if construction
        # raised (M14 F4)
        _timing.set_progress_handler(None)
        progress.close()
        progress.deleteLater()
    window.show()
    _timing.mark("window shown")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
