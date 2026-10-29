# -*- coding: utf-8 -*-
"""P3-9 RBAC permission board (pure incremental).

Route key ``rbac``: five-role x action matrix table, page-plane
minimum-role table, account creation with role combo (escalation
guard enforced by the hub).  Read-mostly visualization + runtime
tuning; headless-safe via interactive.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from mtkgui.engine.rbac_hub import Role5, RbacHub

from .dialog_sizing import wrap_page
from .theme import StyleSpec


class RbacPage(QWidget):
    """Five-role RBAC middle-platform board (route ``rbac``)."""

    def __init__(self, hub: RbacHub,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.hub = hub
        self.interactive = True

        root = QVBoxLayout(self)
        tabs = QTabWidget(self)
        root.addWidget(tabs)

        # ---- tab 1: function-plane matrix (roles x actions) ----
        self.matrix = QTableWidget(len(Role5), 2, self)
        self.matrix.setHorizontalHeaderLabels(["Role", "Granted actions"])
        self.matrix.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        tabs.addTab(self.matrix, "Function permission matrix")

        # ---- tab 2: page-plane minimum role ----
        self.pages = QTableWidget(0, 2, self)
        self.pages.setHorizontalHeaderLabels(["Page route", "Minimum role"])
        self.pages.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        tabs.addTab(self.pages, "Page permissions")

        # ---- tab 3: account admin ----
        acct = QWidget(self)
        form = QHBoxLayout(acct)
        self.user_edit = QLineEdit(acct)
        self.user_edit.setPlaceholderText("Username")
        self.pwd_edit = QLineEdit(acct)
        self.pwd_edit.setPlaceholderText("Password")
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.role_combo = QComboBox(acct)
        self.role_combo.addItems([r.value for r in Role5])
        self.add_btn = QPushButton("Create account", acct)
        self.add_btn.clicked.connect(self.on_add)
        for w in (self.user_edit, self.pwd_edit, self.role_combo,
                  self.add_btn):
            form.addWidget(w)
        form.addStretch(1)
        tabs.addTab(acct, "Account management")

        self.stats_label = QLabel("", self)
        root.addWidget(self.stats_label)
        # M34: scroll-protect the page on very small windows
        wrap_page(self)
        self.refresh()

    # ------------------------------------------------------------ view
    def refresh(self) -> int:
        snap = self.hub.matrix_snapshot()
        roles = sorted(snap)
        self.matrix.setRowCount(len(roles))
        for r, role in enumerate(roles):
            self.matrix.setItem(r, 0, QTableWidgetItem(role))
            self.matrix.setItem(
                r, 1, QTableWidgetItem(", ".join(snap[role])))
        pages = self.hub.pages_snapshot()
        level_of = {0: "VIEWER", 1: "OPERATOR", 2: "ENGINEER",
                    3: "MANAGER", 4: "ADMIN"}
        self.pages.setRowCount(len(pages))
        for r, (route, lvl) in enumerate(pages.items()):
            self.pages.setItem(r, 0, QTableWidgetItem(route))
            self.pages.setItem(
                r, 1, QTableWidgetItem(level_of.get(lvl, str(lvl))))
        self.stats_label.setText(
            f"Five-role RBAC | roles {len(roles)} | pages {len(pages)}")
        return len(roles)

    # ----------------------------------------------------------- ops
    def on_add(self):
        user = self.user_edit.text().strip()
        pwd = self.pwd_edit.text()
        if not user or not pwd:
            if self.interactive:
                QMessageBox.warning(self, "Create account",
                                    "Enter a username and password")
            return None
        role = Role5(self.role_combo.currentText())
        try:
            # actor is ADMIN (the rbac page itself is ADMIN-only)
            self.hub.add_account(Role5.ADMIN, user, pwd, role)
        except PermissionError as exc:
            if self.interactive:
                QMessageBox.warning(self, "Escalation blocked", str(exc))
            return None
        self.refresh()
        if self.interactive:
            QMessageBox.information(self, "Create account", "Done")
        return (user, role.value)
