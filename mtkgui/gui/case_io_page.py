# -*- coding: utf-8 -*-
"""P2-4 GUI YAML<->Excel review import/export page (pure incremental).

Route key ``case_io``.  One-click export of the full-field review
workbook (17 columns via P1-16 ``export_review_excel``) and one-click
import of the engineer-edited workbook (P1-16 ``sync_review_excel``:
import -> diff -> apply -> audit history).  The diff report (added /
removed / parameter changes / instrument re-assignment / priority
moves) is shown in a modal dialog when interactive, otherwise rendered
into the in-page log.  Import auto-snapshots the YAML, blocks on dirty
workbooks (ValueError from the importer) and keeps a [XLS] audit trail.

Zero changes to the casegen engine modules.
"""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from mtkgui.engine.casegen.excel_io import export_review_excel
from mtkgui.engine.casegen.sync import sync_review_excel

from .case_store import CaseStore
from .theme import StyleSpec

DEFAULT_EXPORT_DIR = "yaml_plan/review"


class CaseIOPage(QWidget):
    """Review-Excel import/export page (route ``case_io``)."""

    #: emitted after a successful import (YAML updated + snapshot taken)
    cases_applied = Signal(dict)

    def __init__(self, yaml_path: str, store: CaseStore | None = None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.yaml_path = yaml_path
        self.store = store or CaseStore()
        self.interactive = True  # False -> headless-safe (no modal dialogs)
        self.last_report: dict | None = None

        root = QVBoxLayout(self)

        # export row -------------------------------------------------------
        bar = QHBoxLayout()
        self.export_edit = QLineEdit(self)
        self.export_edit.setPlaceholderText("导出路径（留空自动命名）")
        self.export_btn = QPushButton("一键导出复审 Excel (17列)", self)
        bar.addWidget(QLabel("导出:", self))
        bar.addWidget(self.export_edit, 1)
        bar.addWidget(self.export_btn)
        root.addLayout(bar)

        # import row ---------------------------------------------------------
        bar2 = QHBoxLayout()
        self.import_edit = QLineEdit(self)
        self.import_edit.setPlaceholderText("人工修订后的 Excel 路径")
        self.import_btn = QPushButton("一键导入修订 Excel", self)
        bar2.addWidget(QLabel("导入:", self))
        bar2.addWidget(self.import_edit, 1)
        bar2.addWidget(self.import_btn)
        root.addLayout(bar2)

        # summary + traceability log -------------------------------------
        self.summary = QLabel("", self)
        root.addWidget(self.summary)
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        self.export_btn.clicked.connect(self.on_export)
        self.import_btn.clicked.connect(self.on_import)

    # ------------------------------------------------------------- export
    def on_export(self, *_args) -> str | None:
        """Export the current YAML cases to a full-field review Excel."""
        cfg = self.store.load(self.yaml_path)
        cases = cfg.get("ict_test_cases") or []
        if not cases:
            self._info("导出被拦截: 当前工程无 ict_test_cases 用例")
            return None
        path = self.export_edit.text().strip()
        if not path:
            os.makedirs(DEFAULT_EXPORT_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = os.path.join(DEFAULT_EXPORT_DIR, f"ICT_REVIEW_{ts}.xlsx")
        try:
            count = export_review_excel(cfg, path)
        except Exception as exc:  # unreadable YAML / no write permission
            self._info(f"导出被拦截: {exc}")
            return None
        self._audit("export", f"{count} case(s) -> {path}")
        self.summary.setText(f"导出完成 ✔ {count} 条用例 (17列) -> {path}")
        self._info(f"导出 {count} 条用例 -> {path}")
        return path

    # ------------------------------------------------------------- import
    def on_import(self, *_args) -> dict | None:
        """Import the edited workbook: snapshot -> diff -> apply -> save."""
        path = self.import_edit.text().strip()
        if not path:
            self._info("导入被拦截: 请填写修订 Excel 路径")
            return None
        if not os.path.exists(path):
            self._info(f"导入被拦截: 文件不存在 {path}")
            return None
        cfg = self.store.load(self.yaml_path)
        # pre-flight: block the whole import when a version-locked case
        # would be touched (P2-3 lock contract; zero core change)
        try:
            from mtkgui.engine.casegen.excel_io import import_review_excel
            from mtkgui.engine.casegen.sync import diff_rows
            pre = diff_rows(cfg.get("ict_test_cases") or [],
                            import_review_excel(path).rows)
        except ValueError as exc:
            self._info(f"导入被拦截 (脏数据/空表): {exc}")
            self._warn("导入失败", f"异常数据已拦截，YAML 未被修改:\n{exc}")
            return None
        except Exception as exc:  # corrupt workbook / wrong format
            self._info(f"导入被拦截 (文件损坏): {exc}")
            self._warn("导入失败", f"文件无法解析，YAML 未被修改:\n{exc}")
            return None
        locked_hits = sorted(
            {str(ch["name"]) for ch in pre["changed"]
             if self.store.is_locked(cfg, str(ch["name"]))}
            | {str(row.get("name")) for row in pre["removed"]
               if self.store.is_locked(cfg, str(row.get("name")))})
        if locked_hits:
            msg = ("以下用例已版本锁定，导入被整体拦截:\n"
                   + "\n".join(locked_hits))
            self._info(f"导入被拦截 (锁定冲突): {locked_hits}")
            self._warn("锁定冲突", msg)
            return None
        try:
            # P1-16 pipeline: import -> diff -> apply -> audit history
            report = sync_review_excel(cfg, path, source="gui-import",
                                       actor="operator")
        except Exception as exc:  # defensive: pre-flight already filtered
            self._info(f"导入被拦截: {exc}")
            return None

        # auto version snapshot of the NEW state + formatted YAML write
        self.store.save_snapshot(cfg, note=f"post-import {os.path.basename(path)}")
        self.store.save(cfg, self.yaml_path)
        self.last_report = report
        self.summary.setText(self._summarize(report))
        self._info("导入比对明细:\n" + self._render_diff(report))
        self._audit("import",
                    f"{os.path.basename(path)} +{len(report['added'])} "
                    f"-{len(report['removed'])} "
                    f"~{len(report['changed'])} changed, "
                    f"ignored_cols={report['ignored_columns']}")
        if self.interactive:
            QMessageBox.information(self, "导入完成", self._summarize(report))
        self.cases_applied.emit(cfg)
        return report

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _summarize(report: dict) -> str:
        return (f"导入完成 ✔ 新增 {len(report['added'])} | "
                f"删除 {len(report['removed'])} | "
                f"参数修改 {len(report['changed'])} | "
                f"忽略列 {len(report['ignored_columns'])}")

    @staticmethod
    def _render_diff(report: dict) -> str:
        lines: list[str] = []
        for row in report["added"]:
            lines.append(f"  [新增] {row.get('name')}")
        for row in report["removed"]:
            lines.append(f"  [删除] {row.get('name')}")
        for ch in report["changed"]:
            tag = ""
            if ch["field"] == "instrument":
                tag = "仪器重分配"
            elif ch["field"] == "priority":
                tag = "优先级变动"
            lines.append(f"  [参数修改{('·' + tag) if tag else ''}] "
                         f"{ch['name']}.{ch['field']}: "
                         f"{ch['old']!r} -> {ch['new']!r}")
        if report["ignored_columns"]:
            lines.append(f"  [脏列忽略] {report['ignored_columns']}")
        return "\n".join(lines) or "  (无差异)"

    def _info(self, text: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {text}")

    def _audit(self, action: str, detail: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[XLS] {stamp} {action}: {detail}")
        self._info(f"操作留痕 [{action}] source=gui-{action} "
                   f"actor=operator: {detail}")

    def _warn(self, title: str, text: str) -> None:
        if self.interactive:
            QMessageBox.warning(self, title, text)
