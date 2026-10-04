# -*- coding: utf-8 -*-
"""P3-11 open API administration board (pure incremental).

Route key ``api``: API key issuance (secret shown once), quick
request tester (method/path), MES order intake box with result
readout.  Headless-safe via interactive.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from mtkgui.engine.api_server import ApiServer, MesAdapter

from .theme import StyleSpec


class ApiPage(QWidget):
    """Open API & MES adapter board (route ``api``)."""

    def __init__(self, server: ApiServer, mes: MesAdapter | None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.server = server
        self.mes = mes
        self.interactive = True
        self._secrets: list[tuple[str, str]] = []

        root = QVBoxLayout(self)

        bar1 = QHBoxLayout()
        self.kid_edit = QLineEdit(self)
        self.kid_edit.setPlaceholderText("KeyID")
        self.scope_combo = QComboBox(self)
        self.scope_combo.addItems(["read", "write", "admin"])
        self.issue_btn = QPushButton("发放密钥", self)
        self.issue_btn.clicked.connect(self.on_issue)
        self.last_secret = QLabel("", self)
        for w in (self.kid_edit, self.scope_combo, self.issue_btn,
                  self.last_secret):
            bar1.addWidget(w)
        bar1.addStretch(1)
        root.addLayout(bar1)

        bar2 = QHBoxLayout()
        self.method_combo = QComboBox(self)
        self.method_combo.addItems(["GET", "POST"])
        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText("/api/v1/status")
        self.send_btn = QPushButton("发送请求", self)
        self.send_btn.clicked.connect(self.on_send)
        self.code_label = QLabel("", self)
        for w in (self.method_combo, self.path_edit, self.send_btn,
                  self.code_label):
            bar2.addWidget(w)
        bar2.addStretch(1)
        root.addLayout(bar2)

        bar3 = QHBoxLayout()
        self.order_edit = QLineEdit(self)
        self.order_edit.setPlaceholderText("MES工单: WO-1,MT6897,3")
        self.order_btn = QPushButton("接收工单", self)
        self.order_btn.clicked.connect(self.on_order)
        self.mes_label = QLabel("", self)
        for w in (self.order_edit, self.order_btn, self.mes_label):
            bar3.addWidget(w)
        bar3.addStretch(1)
        root.addLayout(bar3)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["KeyID", "密钥(仅显一次)"])
        root.addWidget(self.table, 2)

    # ------------------------------------------------------------ view
    def refresh(self) -> int:
        self.table.setRowCount(len(self._secrets))
        for r, (kid, secret) in enumerate(self._secrets):
            self.table.setItem(r, 0, QTableWidgetItem(kid))
            self.table.setItem(r, 1, QTableWidgetItem(secret))
        return len(self._secrets)

    # ----------------------------------------------------------- ops
    def on_issue(self):
        kid = self.kid_edit.text().strip()
        if not kid:
            return None
        scope = self.scope_combo.currentText()
        secret = self.server.issue_key(
            kid, scopes=(scope,) if scope != "admin"
            else ("read", "write", "admin"))
        self._secrets.append((kid, secret))
        self.last_secret.setText(f"新密钥: {secret[:12]}...")
        self.refresh()
        return (kid, secret)

    def on_send(self):
        path = self.path_edit.text().strip() or "/api/v1/status"
        method = self.method_combo.currentText()
        key = self._secrets[-1][1] if self._secrets else ""
        code, body = self.server.request(key, method, path)
        self.code_label.setText(f"HTTP {code} | ok={body.get('ok')}")
        return (code, body)

    def on_order(self):
        if self.mes is None:
            if self.interactive:
                QMessageBox.information(self, "MES", "适配器未绑定")
            return None
        parts = [p.strip() for p in
                 self.order_edit.text().split(",")]
        if len(parts) != 3:
            if self.interactive:
                QMessageBox.warning(self, "MES工单",
                                    "格式: WO-1,MT6897,3")
            return None
        try:
            qty = int(parts[2])
        except ValueError:
            return None
        result = self.mes.receive_order(
            {"order_id": parts[0], "part_no": parts[1],
             "quantity": qty})
        self.mes_label.setText(
            f"工单 {parts[0]}: {'接受' if result.get('accepted') else '拒绝'}"
            f" ({result.get('units', 0)} 单元)")
        return result
