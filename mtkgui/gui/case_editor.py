# -*- coding: utf-8 -*-
"""P2-3 AI-case GUI visual editor & human-final-review page (pure incr).

Route key ``cases``.  Left pane: case list grouped by 电源/时钟/信号
网络 (priority + test-dimension badges).  Right pane: single-case
form (thresholds / timing / enable / retry / skip / instrument /
notes), power-tree priority editing, topology view, dimension
toggles, version lock and an AI-gen / manual-edit traceability panel.

Underlying casegen (P1-16) is reused untouched via
:mod:`mtkgui.gui.case_store`; the engine never reads this page.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from .case_store import (AUDIT_KEY, DIMENSIONS, DIM_CN, LockedCaseError,
                         CaseStore, categorize)
from .theme import StyleSpec

CATEGORIES = ("电源网络", "时钟网络", "信号网络", "操作流程")
INSTRUMENT_CHOICES = ("DAQM", "DAQ", "DMM", "SCOPE", "—")


class CaseEditorPage(QWidget):
    """Visual ICT case editor & final-review page (route ``cases``)."""

    #: emitted after a successful save (hot-effect hook for P2-4+)
    cases_applied = Signal(dict)

    def __init__(self, yaml_path: str, store: CaseStore | None = None,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.yaml_path = yaml_path
        self.store = store or CaseStore()
        self._cfg = self.store.load(yaml_path)
        self._current: dict | None = None
        self.interactive = True  # False -> headless-safe (no modal dialogs)

        root = QVBoxLayout(self)

        # dimension toggles + actions bar -------------------------------
        bar = QHBoxLayout()
        self.dim_boxes: dict[str, QCheckBox] = {}
        for dim in DIMENSIONS:
            box = QCheckBox(f"{DIM_CN[dim]}测试", self)
            box.toggled.connect(lambda on, d=dim:
                                self.on_dimension_toggle(d, on))
            self.dim_boxes[dim] = box
            bar.addWidget(box)
        bar.addStretch(1)
        self.path_label = QLabel(yaml_path, self)
        self.save_btn = QPushButton("保存修改 (快照+审计)", self)
        self.lock_btn = QPushButton("锁定用例", self)
        bar.addWidget(self.path_label)
        bar.addWidget(self.lock_btn)
        bar.addWidget(self.save_btn)
        root.addLayout(bar)

        # splitter: case tree | detail form ------------------------------
        split = QSplitter(Qt.Orientation.Horizontal, self)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["用例", "优先级", "维度", "状态"])
        self.tree.currentItemChanged.connect(self.on_select)
        split.addWidget(self.tree)
        split.addWidget(self._build_detail_form())
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

        # traceability panel ---------------------------------------------
        self.trace = QPlainTextEdit(self)
        self.trace.setReadOnly(True)
        self.trace.setFixedHeight(110)
        root.addWidget(self.trace)

        self.refresh_tree()
        self._refresh_dim_boxes()
        self._refresh_trace()

    # detail form -------------------------------------------------------
    def _build_detail_form(self) -> QWidget:
        host = QWidget(self)
        lay = QVBoxLayout(host)
        form = QGridLayout()
        self.f_name = QLineEdit(host)
        self.f_name.setReadOnly(True)
        self.f_kind = QLineEdit(host)
        self.f_kind.setReadOnly(True)
        self.f_enable = QCheckBox("测试使能", host)
        self.f_wait = QLineEdit(host)
        self.f_timeout = QLineEdit(host)
        self.f_retry = QLineEdit(host)
        self.f_skip = QLineEdit(host)
        self.f_skip.setPlaceholderText("skip_if 条件表达式")
        self.f_unit = QLineEdit(host)
        self.f_unit.setReadOnly(True)
        self.f_lo = QLineEdit(host)
        self.f_hi = QLineEdit(host)
        self.f_prio = QLineEdit(host)
        self.f_domain = QLineEdit(host)
        self.f_instrument = QComboBox(host)
        self.f_instrument.addItems(list(INSTRUMENT_CHOICES))
        self.f_notes = QPlainTextEdit(host)
        self.f_notes.setFixedHeight(48)
        rows = [("用例名称", self.f_name), ("类型", self.f_kind),
                ("测试使能", self.f_enable), ("等待ms", self.f_wait),
                ("超时ms", self.f_timeout), ("重试次数", self.f_retry),
                ("跳过条件", self.f_skip), ("单位", self.f_unit),
                ("阈值下限", self.f_lo), ("阈值上限", self.f_hi),
                ("优先级(电源树层级)", self.f_prio),
                ("所属电源域", self.f_domain),
                ("仪器分配", self.f_instrument)]
        for row, (label, w) in enumerate(rows):
            form.addWidget(QLabel(label, host), row, 0)
            form.addWidget(w, row, 1)
        lay.addLayout(form)
        topo = QGroupBox("上下游拓扑", host)
        topo_lay = QHBoxLayout(topo)
        self.f_upstream = QLabel("—", topo)
        self.f_downstream = QLabel("—", topo)
        topo_lay.addWidget(QLabel("上游:", topo))
        topo_lay.addWidget(self.f_upstream)
        topo_lay.addWidget(QLabel("下游:", topo))
        topo_lay.addWidget(self.f_downstream)
        topo_lay.addStretch(1)
        lay.addWidget(topo)
        lay.addWidget(QLabel("备注", host))
        lay.addWidget(self.f_notes)
        lay.addStretch(1)
        return host

    # tree ----------------------------------------------------------------
    def refresh_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for cat in CATEGORIES:
            groups[cat] = QTreeWidgetItem([cat, "", "", ""])
            self.tree.addTopLevelItem(groups[cat])
        for case in self._cfg.get("ict_test_cases") or []:
            cat = categorize(case)
            locked = self.store.is_locked(self._cfg,
                                          str(case.get("name")))
            dim = str(case.get("test_dim") or "op")
            item = QTreeWidgetItem(
                [str(case.get("name")),
                 "" if case.get("priority", "") == "" else
                 str(case.get("priority")),
                 DIM_CN.get(dim, dim),
                 "🔒已锁定" if locked else
                 ("启用" if case.get("enable") else "停用")])
            item.setData(0, Qt.ItemDataRole.UserRole, case)
            groups[cat].addChild(item)
        for cat, node in groups.items():
            node.setExpanded(True)
            if node.childCount() == 0:
                idx = self.tree.indexOfTopLevelItem(node)
                self.tree.takeTopLevelItem(idx)
        self.tree.blockSignals(False)

    def _select_case(self, name: str) -> bool:
        """Re-select a case by name after tree rebuilds (stability)."""
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.text(0) == name:
                    self.tree.setCurrentItem(child)
                    return True
        return False

    def on_select(self, cur, _prev=None) -> None:
        if cur is None or cur.parent() is None:
            self._current = None
            return
        self._current = cur.data(0, Qt.ItemDataRole.UserRole)
        self._load_case(self._current)

    # form <-> case dict --------------------------------------------------
    def _load_case(self, case: dict) -> None:
        locked = self.store.is_locked(self._cfg, str(case.get("name")))
        self.f_name.setText(str(case.get("name") or ""))
        self.f_kind.setText(str(case.get("kind") or ""))
        self.f_enable.setChecked(bool(case.get("enable")))
        self.f_wait.setText(str(case.get("wait_ms", "")))
        self.f_timeout.setText(str(case.get("timeout_ms", "")))
        self.f_retry.setText(str(case.get("retry", 0)))
        self.f_skip.setText(str(case.get("skip_if", "") or ""))
        self.f_unit.setText(str(case.get("unit") or ""))
        self.f_lo.setText(str(case.get("threshold_min", "")))
        self.f_hi.setText(str(case.get("threshold_max", "")))
        self.f_prio.setText("" if case.get("priority", "") == "" else
                            str(case.get("priority")))
        self.f_domain.setText(str(case.get("power_domain") or "—"))
        idx = self.f_instrument.findText(
            str(case.get("instrument") or "—"))
        self.f_instrument.setCurrentIndex(idx if idx >= 0 else 0)
        self.f_notes.setPlainText(str(case.get("notes") or ""))
        self.f_upstream.setText(str(case.get("upstream") or "—"))
        self.f_downstream.setText(str(case.get("downstream") or "—"))
        for w in (self.f_enable, self.f_wait, self.f_timeout, self.f_retry,
                  self.f_skip, self.f_lo, self.f_hi, self.f_prio,
                  self.f_domain, self.f_instrument, self.f_notes):
            w.setEnabled(not locked)
        self.lock_btn.setText("解锁用例" if locked else "锁定用例")

    def _collect_updates(self) -> dict:
        return {"enable": self.f_enable.isChecked(),
                "wait_ms": self.f_wait.text(),
                "timeout_ms": self.f_timeout.text(),
                "retry": self.f_retry.text(),
                "skip_if": self.f_skip.text(),
                "threshold_min": self.f_lo.text(),
                "threshold_max": self.f_hi.text(),
                "priority": self.f_prio.text(),
                "power_domain": self.f_domain.text(),
                "instrument": self.f_instrument.currentText(),
                "notes": self.f_notes.toPlainText()}

    # dimension toggles ------------------------------------------------------
    def _refresh_dim_boxes(self) -> None:
        for dim, box in self.dim_boxes.items():
            cases = [c for c in self._cfg.get("ict_test_cases") or []
                     if str(c.get("test_dim")) == dim]
            on = bool(cases) and all(c.get("enable") for c in cases)
            box.blockSignals(True)
            box.setChecked(on)
            box.blockSignals(False)

    def on_dimension_toggle(self, dim: str, on: bool) -> None:
        changes = self.store.set_dimension_enabled(self._cfg, dim, on)
        self.store.save(self._cfg, self.yaml_path)
        self.refresh_tree()
        self._refresh_dim_boxes()
        self._refresh_trace()
        self.cases_applied.emit(self._cfg)
        self._info(f"{DIM_CN[dim]}测试已{'开启' if on else '关闭'} "
                   f"({len(changes)} 条用例更新)")

    # actions ---------------------------------------------------------------
    def on_save(self) -> tuple[dict, list] | None:
        """Collect the form and persist the single-case edit."""
        if self._current is None:
            self._info("未选中用例")
            return None
        name = str(self._current.get("name"))
        try:
            new_cfg, changes = self.store.edit_and_save(
                self._cfg, name, self._collect_updates(), self.yaml_path)
        except LockedCaseError:
            if self.interactive:
                QMessageBox.warning(self, "锁定", "用例已版本锁定，禁止修改")
            self._info(f"保存被拦截: {name} 已锁定")
            return None
        except ValueError as exc:
            if self.interactive:
                QMessageBox.warning(self, "非法参数", str(exc))
            self._info(f"保存被拦截: {exc}")
            return None
        self._cfg = new_cfg
        self.refresh_tree()
        self._refresh_trace()
        self.cases_applied.emit(new_cfg)
        self._info(f"已保存 {len(changes)} 项修改 ({name})")
        return new_cfg, changes

    def on_lock_toggle(self) -> None:
        if self._current is None:
            self._info("未选中用例")
            return
        name = str(self._current.get("name"))
        locked = not self.store.is_locked(self._cfg, name)
        self.store.set_locked(self._cfg, name, locked)
        self.store.save(self._cfg, self.yaml_path)
        self.store._audit("lock" if locked else "unlock", name)
        self.refresh_tree()
        self._select_case(name)  # keep context after tree rebuild
        self._refresh_trace()
        self._info(f"{name} 已{'锁定' if locked else '解锁'}")
        self.cases_applied.emit(self._cfg)

    # reload (e.g. after external Excel sync in P2-4) --------------------
    def reload(self) -> None:
        self._cfg = self.store.load(self.yaml_path)
        self.refresh_tree()
        self._refresh_dim_boxes()
        self._refresh_trace()

    # helpers ---------------------------------------------------------------
    def _refresh_trace(self) -> None:
        audit = self._cfg.get(AUDIT_KEY) or {}
        self.trace.setPlainText("")
        ai = (f"AI生成: 版本 {audit.get('ai_version', '—')} "
              f"时间 {audit.get('gen_time', '—')} "
              f"来源 {(audit.get('sources') or ['—'])}")
        self.trace.appendPlainText(ai)
        for entry in reversed(list(audit.get("history") or [])[-30:]):
            changed = "; ".join(
                f"{c.get('name')}.{c.get('field')}: "
                f"{c.get('old')!r}->{c.get('new')!r}"
                for c in (entry.get("changed") or [])) or "—"
            self.trace.appendPlainText(
                f"[{entry.get('time')}] {entry.get('source')} / "
                f"{entry.get('actor')}: {changed}")
        locks = list((audit.get("locks") or {}).keys())
        self.trace.appendPlainText(f"版本锁定: {locks or '无'}")

    def _info(self, text: str) -> None:
        self.trace.appendPlainText(f">> {text}")
