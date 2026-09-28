# -*- coding: utf-8 -*-
"""MTK GUI entry point.

Run with: python main.py
"""

import sys

from PySide6.QtWidgets import QApplication

from mtkgui import __app_name__
from mtkgui.main_window import MainWindow
from mtkgui.permissions import LoginDialog
from mtkgui.style import QSS


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName(__app_name__)
    app.setOrganizationName("Manufacturing Test Kit")
    app.setStyleSheet(QSS)

    # startup login: Supervisor (password) or Operator; must pick one.
    # Returns (role, mode); Virtual mode is supervisor-only.
    result = LoginDialog.login(None, allow_cancel=False)
    if result is None:
        sys.exit(0)
    role, mode = result

    window = MainWindow(role, mode)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
