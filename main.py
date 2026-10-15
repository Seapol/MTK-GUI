# -*- coding: utf-8 -*-
"""MTK GUI entry point.

Run with: python main.py
"""

import sys

import mtkgui.startup_timing as _timing

_timing.mark("entry (pyinstaller bootloader done)")


def main():
    import faulthandler

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
