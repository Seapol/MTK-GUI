# -*- coding: utf-8 -*-
"""P2-2 visual YAML config page (pure incremental).

Schema-driven form over the registered sections, real-time per-field
validation, one-click formatted save with auto-snapshot, hot-apply
signal (no engine restart), snapshot rollback + diff view and an
in-page modification record.  Zero changes to the underlying YAML
parsing base (``mtkgui.project_config`` stays untouched).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .config_spec import (SECTIONS, ValidationIssue, set_path, get_path,
                          validate_value)
from .config_store import ConfigStore
from .theme import StyleSpec

ERR_BG = "#4a2430"


class ConfigPage(QWidget):
    """Visual all-parameter YAML editor page (route key: ``config``)."""

    #: emitted after a successful save — the hot-effect hook (P2-8+ may
    #: subscribe; the engine never polls this page)
    config_applied = Signal(dict)

    def __init__(self, yaml_path: str, store: ConfigStore | None = None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.yaml_path = yaml_path
        self.store = store or ConfigStore()

        self._cfg = self.store.load(yaml_path)
        self._editors: dict[str, QWidget] = {}
        self._errors: dict[str, QLabel] = {}
        self.interactive = True  # False -> headless-safe (no modal dialogs)

        root = QVBoxLayout(self)
        # top action bar ------------------------------------------------
        bar = QHBoxLayout()
        self.path_label = QLabel(yaml_path, self)
        self.save_btn = QPushButton("Save (格式化+快照)", self)
        self.rollback_combo = QComboBox(self)
        self.rollback_btn = QPushButton("回滚", self)
        self.diff_btn = QPushButton("差异对比", self)
        self.validate_btn = QPushButton("全量校验", self)
        for w in (self.path_label, self.validate_btn, self.diff_btn,
                  self.rollback_combo, self.rollback_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.save_btn)
        root.addLayout(bar)

        # validation summary ---------------------------------------------
        self.summary = QLabel("", self)
        root.addWidget(self.summary)

        # scrollable form sections ----------------------------------------
        form_host = QWidget(self)
        form_lay = QVBoxLayout(form_host)
        for section, fields in SECTIONS.items():
            group = QGroupBox(section, form_host)
            grid = QGridLayout(group)
            for row, fs in enumerate(fields):
                grid.addWidget(QLabel(fs.label, group), row, 0)
                editor = self._make_editor(fs, group)
                self._editors[fs.path] = editor
                grid.addWidget(editor, row, 1)
                err = QLabel("", group)
                err.setStyleSheet(f"color: {spec.ERROR};")
                grid.addWidget(err, row, 2)
                self._errors[fs.path] = err
                # real-time validation on every keystroke / toggle
                fs_ref = fs
                if isinstance(editor, QCheckBox):
                    editor.toggled.connect(
                        lambda _t, s=fs_ref: self._validate_field(s))
                elif hasattr(editor, "textChanged"):
                    editor.textChanged.connect(  # type: ignore[attr-defined]
                        lambda _t, s=fs_ref: self._validate_field(s))
                elif isinstance(editor, QComboBox):
                    editor.currentTextChanged.connect(
                        lambda _t, s=fs_ref: self._validate_field(s))
            form_lay.addWidget(group)
        form_lay.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_host)
        root.addWidget(scroll, 1)

        # modification record ----------------------------------------------
        self.record = QPlainTextEdit(self)
        self.record.setReadOnly(True)
        self.record.setFixedHeight(96)
        root.addWidget(self.record)

        # buttons ------------------------------------------------------------
        self.save_btn.clicked.connect(self.on_save)
        self.rollback_btn.clicked.connect(self.on_rollback)
        self.diff_btn.clicked.connect(self.on_diff)
        self.validate_btn.clicked.connect(self.on_validate_all)
        self._refresh_snapshots()

    # editor factory ----------------------------------------------------
    def _make_editor(self, fs, parent) -> QWidget:
        from .config_spec import get_path
        val = get_path(self._cfg, fs.path)
        if fs.ftype == "bool":
            box = QCheckBox(parent)
            box.setChecked(bool(val))
            return box
        if fs.ftype == "choice":
            combo = QComboBox(parent)
            combo.addItems(list(fs.choices))
            if val is not None:
                combo.setCurrentText(str(val))
            return combo
        edit = QLineEdit(parent)
        if fs.ftype == "list_str":
            edit.setPlaceholderText("一行一项")
        if fs.secret:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        if val is not None and fs.ftype != "list_str":
            edit.setText("" if isinstance(val, (list, dict)) else str(val))
        elif val is not None and fs.ftype == "list_str":
            edit.setText("\n".join(map(str, val)) if isinstance(val, list)
                         else str(val))
        return edit

    # form <-> dict -------------------------------------------------------
    def _collect_updates(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for section, fields in SECTIONS.items():
            for fs in fields:
                w = self._editors[fs.path]
                if fs.ftype == "bool":
                    out[fs.path] = w.isChecked()
                elif fs.ftype == "choice":
                    out[fs.path] = w.currentText()
                else:
                    out[fs.path] = w.text()
        return out

    # validation --------------------------------------------------------
    def _editor_value(self, fs):
        w = self._editors[fs.path]
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QComboBox):
            return w.currentText()
        return w.text()

    def _validate_field(self, fs) -> ValidationIssue | None:
        issue = validate_value(fs, self._editor_value(fs))
        err_label = self._errors[fs.path]
        editor = self._editors[fs.path]
        if issue:
            err_label.setText(issue.reason)
            if isinstance(editor, QLineEdit):
                editor.setStyleSheet(f"background: {ERR_BG};")
        else:
            err_label.setText("")
            if isinstance(editor, QLineEdit):
                editor.setStyleSheet("")
        return issue

    def validate_form(self) -> list[ValidationIssue]:
        from .config_spec import SECTIONS as S
        issues = []
        for fields in S.values():
            for fs in fields:
                it = self._validate_field(fs)
                if it:
                    issues.append(it)
        return issues

    def on_validate_all(self) -> list[ValidationIssue]:
        issues = self.validate_form()
        if issues:
            self.summary.setText(
                f"校验未通过 {len(issues)} 项:\n" +
                "\n".join(str(i) for i in issues))
        else:
            self.summary.setText("校验通过 ✔")
        return issues

    # actions -------------------------------------------------------------
    def on_save(self) -> tuple[dict, list] | None:
        issues = self.validate_form()
        if issues:
            if self.interactive:
                QMessageBox.warning(self, "校验失败",
                                    "存在非法参数，保存被拦截:\n" +
                                    "\n".join(str(i) for i in issues))
            self.summary.setText("校验失败，保存被拦截")
            return None
        new_cfg, changes = self.store.apply_and_save(
            self._cfg, self._collect_updates(), self.yaml_path,
            snapshot_note="pre-save")
        self._cfg = new_cfg
        for ch in changes:
            self.record.appendPlainText(f"{ch}")
        self.config_applied.emit(new_cfg)   # 热生效（无需重启引擎）
        self.summary.setText(f"已保存 {len(changes)} 项修改，已热生效 ✔")
        return new_cfg, changes

    def on_rollback(self) -> None:
        snap_id = self.rollback_combo.currentData()
        if not snap_id:
            if self.interactive:
                QMessageBox.information(self, "回滚", "无可用快照")
            return
        restored, changes = self.store.rollback(self._cfg, snap_id)
        self.store.save(restored, self.yaml_path)  # 一键回滚：同步落盘
        self._cfg = restored
        self.record.appendPlainText(f"rollback -> {snap_id} "
                                    f"({len(changes)} diffs)")
        self.config_applied.emit(restored)
        self.summary.setText(f"已回滚至 {snap_id}（差异 {len(changes)} 项）")

    def on_diff(self) -> None:
        changes = self.store.diff(self._cfg,
                                  self._materialize(self._collect_updates()))
        text = "\n".join(str(c) for c in changes) or "(no differences)"
        QMessageBox.information(self, "差异对比", text)

    def _materialize(self, updates: dict) -> dict:
        from .config_spec import set_path
        import copy
        out = copy.deepcopy(self._cfg)
        for path, val in updates.items():
            set_path(out, path, val)
        return out

    def _refresh_snapshots(self) -> None:
        self.rollback_combo.clear()
        for info in self.store.list_snapshots():
            self.rollback_combo.addItem(f"{info.time} {info.note}",
                                        userData=info.snap_id)
