# -*- coding: utf-8 -*-
"""P2-9 report export & preview page (pure incremental).

Route key ``export`` — drives :mod:`report_export` against the shared
P2-5 :class:`MetricsEngine` (read-only):

  * preview           — QTextBrowser rendering of the live HTML report
  * zoom in/out/reset — preview scaling
  * find box          — quick text search in the preview
  * export HTML / PDF — one-click deliverable files (QFileDialog when
                        interactive, deterministic paths headless)

Headless-safe via the usual ``interactive`` flag.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QTextCursor
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFileDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTextBrowser,
                               QHBoxLayout, QVBoxLayout, QWidget)

from mtkgui.engine.metrics import (MetricsEngine,  # noqa: F401
                                   compute_cpk_all, compute_cycle_time,
                                   compute_yield, filter_records)

from .report_export import build_html_report, export_pdf
from .theme import StyleSpec


class ExportPage(QWidget):
    """Commercial report export (route ``export``)."""

    #: emitted after each successful export with the file path
    report_exported = Signal(str)

    def __init__(self, engine: MetricsEngine | None = None,
                 spec: StyleSpec = StyleSpec(), parent=None,
                 out_dir: str | None = None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.engine = engine or MetricsEngine()
        self.interactive = True
        self.out_dir = Path(out_dir or "reports_export")
        self.meta = {}                      # part_number / version / ...
        self.cpk_case = ""                  # CpK trend config (optional)
        self.cpk_lsl = 0.0
        self.cpk_usl = 0.0
        self._html = ""

        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.find_box = QLineEdit(self)
        self.find_box.setPlaceholderText("查找内容…")
        self.find_box.returnPressed.connect(self.find_next)
        self.zoom_label = QLabel("100%", self)
        zoom_out = QPushButton("缩小", self)
        zoom_in = QPushButton("放大", self)
        zoom_reset = QPushButton("复位缩放", self)
        zoom_out.clicked.connect(lambda: self.zoom(-1))
        zoom_in.clicked.connect(lambda: self.zoom(1))
        zoom_reset.clicked.connect(lambda: self.zoom(0))
        for w in (self.find_box, zoom_out, zoom_in, zoom_reset,
                  self.zoom_label):
            bar.addWidget(w)
        root.addLayout(bar)

        self.preview = QTextBrowser(self)
        root.addWidget(self.preview, 1)

        bar2 = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新预览", self)
        self.refresh_btn.clicked.connect(self.refresh)
        self.html_btn = QPushButton("导出 HTML", self)
        self.html_btn.clicked.connect(self.export_html)
        self.pdf_btn = QPushButton("导出 PDF", self)
        self.pdf_btn.clicked.connect(self.export_pdf_file)
        self.batch_btn = QPushButton("批次汇总导出", self)
        self.batch_btn.clicked.connect(self.export_batch_summary)
        for w in (self.refresh_btn, self.html_btn, self.pdf_btn,
                  self.batch_btn):
            bar2.addWidget(w)
        bar2.addStretch(1)
        root.addLayout(bar2)

        self._zoom = 0
        self.refresh()

    # ----------------------------------------------------------- build
    def _batch_summaries(self) -> dict:
        batches = sorted({r.batch for r in self.engine.records
                          if r.batch})
        return {b: self.engine.batch_summary(b) for b in batches}

    def _meta(self, batch: str | None = None) -> dict:
        meta = dict(self.meta)
        meta.setdefault("version", "v2.0.0")
        meta.setdefault("revision", "1.0")
        if batch:
            meta["batch"] = batch
        meta["generated_at"] = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
        return meta

    def _build(self, records, batch=None, with_batch_table=False):
        cpk = compute_cpk_all(
            records, {self.cpk_case: (self.cpk_lsl, self.cpk_usl)},
            {}) if self.cpk_case else {}
        summaries = self._batch_summaries() if with_batch_table else {}
        return build_html_report(
            records=records,
            yield_report=compute_yield(records), 
            cycle_report=compute_cycle_time(records),
            cpk_reports=cpk, batch_summaries=summaries,
            meta=self._meta(batch))

    # ----------------------------------------------------------- view
    def refresh(self) -> None:
        self._html = self._build(self.engine.records,
                                 with_batch_table=True)
        self.preview.setHtml(self._html)

    def zoom(self, direction: int) -> None:
        if direction > 0:
            self.preview.zoomIn(1)
            self._zoom += 1
        elif direction < 0:
            self.preview.zoomOut(1)
            self._zoom -= 1
        else:
            self.preview.zoomOut(10) if self._zoom > 0 else \
                self.preview.zoomIn(10)
            self._zoom = 0
        self.zoom_label.setText(f"{100 + self._zoom * 10}%")

    def find_next(self) -> None:
        """Quick find: highlight the next occurrence (wraps)."""
        text = self.find_box.text()
        if not text:
            return
        if not self.preview.find(text):
            self.preview.moveCursor(QTextCursor.MoveOperation.Start)
            self.preview.find(text)

    # ---------------------------------------------------------- export
    def _target(self, suffix: str, name: str) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self.out_dir / name

    def _pick(self, path: Path, filt: str) -> Path | None:
        if not self.interactive:
            return path
        chosen, _ = QFileDialog.getSaveFileName(self, "导出报告",
                                                str(path), filt)
        return Path(chosen) if chosen else None

    def export_html(self) -> Path | None:
        path = self._pick(self._target(
            ".html", f"report_{datetime.now():%Y%m%d_%H%M%S}.html"),
            "HTML (*.html)")
        if path is None:
            return None
        path.write_text(self._html, encoding="utf-8")
        self.report_exported.emit(str(path))
        return path

    def export_pdf_file(self) -> Path | None:
        path = self._pick(self._target(
            ".pdf", f"report_{datetime.now():%Y%m%d_%H%M%S}.pdf"),
            "PDF (*.pdf)")
        if path is None:
            return None
        export_pdf(self._html, path)
        self.report_exported.emit(str(path))
        return path

    def export_batch_summary(self) -> list[Path] | None:
        """Batch export: one HTML per batch + the merged summary."""
        base = datetime.now().strftime("%Y%m%d_%H%M%S")
        written: list[Path] = []
        batches = sorted({r.batch for r in self.engine.records
                          if r.batch})
        for batch in batches:
            recs = filter_records(self.engine.records, batch=batch)
            html = self._build(recs, batch=batch, with_batch_table=True)
            p = self._target(".html", f"report_{batch}_{base}.html")
            p.write_text(html, encoding="utf-8")
            written.append(p)
        merged = self._build(self.engine.records,
                             with_batch_table=True)
        p = self._target(".html", f"report_SUMMARY_{base}.html")
        p.write_text(merged, encoding="utf-8")
        written.append(p)
        self.report_exported.emit(str(written[-1]))
        if self.interactive:
            QMessageBox.information(
                self, "批量导出", f"已导出 {len(written)} 份报告")
        return written
