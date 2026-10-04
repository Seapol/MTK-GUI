# -*- coding: utf-8 -*-
"""P2-11 login & audit-trail page (pure incremental).

Route key ``audit``:

  * login box       — username/password -> AccessControl.login,
                      current session + role shown (operator sees a
                      restricted-role badge; admin full)
  * guarded demo    — a "修改配置" button that calls
                      access.require(session, "edit_config") so the
                      operator denial is visible and audited
  * audit board     — ledger table (time/user/action/target/before/
                      after/detail) with action/user/text filters
  * export          — CSV / JSON one-click export of the ledger

Headless-safe via the usual ``interactive`` flag.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from mtkgui.engine.auth_audit import AccessControl, AuditLog, Role

from .theme import StyleSpec


class AuditPage(QWidget):
    """Permission & audit trail (route ``audit``)."""

    #: emitted on every successful login with the role value
    logged_in = Signal(str)

    def __init__(self, access: AccessControl, audit: AuditLog,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.access = access
        self.audit = audit
        self.session = None                 # Session | None
        self.interactive = True

        root = QVBoxLayout(self)

        # login bar ----------------------------------------------------
        bar = QHBoxLayout()
        self.user_edit = QLineEdit(self)
        self.user_edit.setPlaceholderText("账号")
        self.pwd_edit = QLineEdit(self)
        self.pwd_edit.setPlaceholderText("密码")
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_btn = QPushButton("登录", self)
        self.login_btn.clicked.connect(self.on_login)
        self.session_label = QLabel("未登录", self)
        for w in (self.user_edit, self.pwd_edit, self.login_btn,
                  self.session_label):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        # guard demo ----------------------------------------------------
        bar2 = QHBoxLayout()
        self.guard_btn = QPushButton("修改配置(受权限管控)", self)
        self.guard_btn.clicked.connect(self.on_edit_config)
        self.filter_action = QComboBox(self)
        self.filter_action.addItem("全部动作")
        for a in ("login", "edit_config", "edit_case", "import",
                  "export", "upload", "report_delete", "audit_export"):
            self.filter_action.addItem(a)
        self.filter_user = QLineEdit(self)
        self.filter_user.setPlaceholderText("按操作员筛选")
        self.filter_text = QLineEdit(self)
        self.filter_text.setPlaceholderText("内容搜索…")
        self.query_btn = QPushButton("查询", self)
        self.query_btn.clicked.connect(self.refresh)
        self.csv_btn = QPushButton("导出 CSV", self)
        self.csv_btn.clicked.connect(lambda: self.on_export("csv"))
        self.json_btn = QPushButton("导出 JSON", self)
        self.json_btn.clicked.connect(lambda: self.on_export("json"))
        for w in (self.guard_btn, self.filter_action,
                  self.filter_user, self.filter_text, self.query_btn,
                  self.csv_btn, self.json_btn):
            bar2.addWidget(w)
        root.addLayout(bar2)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["时间", "操作员", "动作", "对象", "变更前", "变更后",
             "备注"])
        root.addWidget(self.table, 1)

        self.refresh()

    # ------------------------------------------------------------ login
    def on_login(self) -> None:
        session = self.access.login(self.user_edit.text().strip(),
                                    self.pwd_edit.text())
        if session is None:
            if self.interactive:
                QMessageBox.warning(self, "登录失败",
                                    "账号或密码错误（已留痕）")
            self.session_label.setText("未登录")
            self.session = None
        else:
            self.session = session
            badge = "管理员(全权限)" if session.role is Role.ADMIN \
                else "操作员(受限权限)"
            self.session_label.setText(
                f"{session.username} | {badge}")
            self.logged_in.emit(session.role.value)
        self.refresh()

    # ------------------------------------------------------------ guard
    def on_edit_config(self) -> None:
        """Permission-guarded operation (operator gets denied)."""
        try:
            self.access.require(self.session, "edit_config",
                                "project.yaml")
        except PermissionError:
            self.session_label.setText(
                (self.session.username if self.session else "未登录")
                + " | 无权限（已留痕）")
            self.refresh()
            return                  # denial audited, nothing changed
        # admin path reaches here — record the change
        self.audit.log(self.session.username, "edit_config",
                       "project.yaml", before={"retry": 2},
                       after={"retry": 3}, detail="GUI 提交")
        self.refresh()

    # ------------------------------------------------------------- view
    def _rows(self) -> list[dict]:
        action = None
        if self.filter_action.currentIndex() > 0:
            action = self.filter_action.currentText()
        return self.audit.query(
            action=action,
            user=self.filter_user.text().strip() or None,
            text=self.filter_text.text().strip() or None)

    def refresh(self) -> None:
        rows = self._rows()
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            vals = [e["ts"], e["user"], e["action"], e["target"],
                    e["before"], e["after"], e["detail"]]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))

    # ----------------------------------------------------------- export
    def on_export(self, fmt: str):
        name = f"audit_{fmt}.{fmt if fmt == 'json' else 'csv'}"
        path = self.audit.path.parent / name
        path = self.audit.export(path, fmt=fmt)
        if self.interactive:
            QMessageBox.information(self, "审计导出", str(path))
        return path
