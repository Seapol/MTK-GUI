# -*- coding: utf-8 -*-
"""P2-8 SharePoint upload control & monitor page (pure incremental).

Route key ``upload`` — visualizes the :class:`SharePointUploader`
closed loop (zero upload logic here, the page only drives it):

  * config status line   (site / dir / retry / policy, hot-updated)
  * precheck button      (connectivity + permission + writable probe)
  * upload button        (outbox sweep with filter/dedup/retry/fallback)
  * ledger table         (name / status / url / sha256 / ts book)
  * audit tail           (last [UPLOAD] lines, traceability)

The page is headless-safe: ``interactive=False`` suppresses dialogs.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from mtkgui.engine.uploader import SharePointUploader

from .theme import StyleSpec


class UploadPage(QWidget):
    """Cloud archive monitor (route ``upload``)."""

    #: emitted after each outbox sweep with (uploaded, failed) counts
    upload_done = Signal(int, int)

    def __init__(self, manager: SharePointUploader,
                 spec: StyleSpec = StyleSpec(), parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.manager = manager
        self.interactive = True  # False -> headless-safe (no dialogs)

        root = QVBoxLayout(self)

        # status + action bar ----------------------------------------------
        self.status_label = QLabel("", self)
        root.addWidget(self.status_label)
        bar = self._build_bar()
        root.addLayout(bar)

        # ledger table -------------------------------------------------------
        self.ledger_table = QTableWidget(0, 5, self)
        self.ledger_table.setHorizontalHeaderLabels(
            ["File", "State", "Cloud URL", "SHA-256", "Uploaded at"])
        root.addWidget(self.ledger_table, 1)

        # audit tail ----------------------------------------------------------
        self.audit_view = QPlainTextEdit(self)
        self.audit_view.setReadOnly(True)
        root.addWidget(self.audit_view, 1)

        self.refresh()

    # ---------------------------------------------------------------- UI
    def _build_bar(self):
        from PySide6.QtWidgets import QHBoxLayout
        bar = QHBoxLayout()
        self.precheck_btn = QPushButton("Connectivity precheck", self)
        self.precheck_btn.clicked.connect(self.on_precheck)
        self.upload_btn = QPushButton("Upload pending queue", self)
        self.upload_btn.clicked.connect(self.on_upload)
        self.refresh_btn = QPushButton("Refresh ledger", self)
        self.refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self.precheck_btn)
        bar.addWidget(self.upload_btn)
        bar.addWidget(self.refresh_btn)
        bar.addStretch(1)
        return bar

    # ------------------------------------------------------------ slots
    def on_precheck(self) -> None:
        """Run the precheck chain and surface the verdict."""
        problems = self.manager.precheck()
        ok = not problems
        self.status_label.setText(
            "Precheck passed: cloud reachable, directory writable" if ok
            else "Precheck failed: " + "; ".join(problems))
        if self.interactive:
            QMessageBox.information(
                self, "Precheck result", self.status_label.text())

    def on_upload(self) -> None:
        """Sweep the outbox through the full gate chain."""
        results = self.manager.upload_pending()
        ok = sum(1 for r in results
                 if r.status in ("UPLOADED", "DEDUPED"))
        bad = len(results) - ok
        self.refresh()                      # ledger first...
        self.status_label.setText(          # ...then the sweep verdict
            f"Upload complete: {ok} succeeded, {bad} failed "
            f"(failed files stay in the local outbox)")
        self.upload_done.emit(ok, bad)
        if bad and self.interactive:
            QMessageBox.warning(
                self, "Upload alert",
                f"{bad} file(s) failed to upload; kept locally as "
                "fallback, see the ledger")

    def apply_config(self, cfg: dict) -> None:
        """Config hot-update hook (P2-2 config_applied signal)."""
        self.manager.apply_config(cfg)
        self.refresh()

    def refresh(self) -> None:
        """Reload status line, ledger book and audit tail."""
        cfg = self.manager.config
        self.status_label.setText(
            f"Cloud archive: {'enabled' if cfg.enabled else 'disabled'} | "
            f"site {cfg.site_url or '-'} | dir "
            f"/{cfg.project_dir or '-'}"
            f" | retries {cfg.retry_count} | policy "
            f"{cfg.overwrite_policy}")
        rows = self.manager.records()
        self.ledger_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            vals = [row["name"], row["status"], row["url"],
                    row["sha256"][:16], row["ts"]]
            for c, v in enumerate(vals):
                self.ledger_table.setItem(
                    r, c, QTableWidgetItem(str(v)))
        self.audit_view.setPlainText("\n".join(
            f"[{t}] {a}: {d}" for t, a, d in
            self.manager.audit[-200:]))
