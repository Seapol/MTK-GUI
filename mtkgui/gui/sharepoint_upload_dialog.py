# -*- coding: utf-8 -*-
"""Report > SharePoint Upload dialog (user direction 2026-10-14).

Pure-incremental GUI on top of the P2-8 :class:`SharePointUploader`
engine (precheck / retry / dedup / outbox / ledger stay in the engine):

  * SharePoint site link + TEST CONNECTION probe (connectivity +
    permission + directory writable, honest result either way)
  * local folder picker used as the upload source
  * upload mode:  1. Real-time sync  - mirror the local folder into
    the SharePoint folder (hash dedup, failures stay queued)
                   2. Packaged upload - zip the folder with a timestamp
    and upload once per period (day / week / bi-weekly / month /
    quarter / half-year / year)
  * config persisted to config/sharepoint_upload.json (hot reload on
    the next open); a 30 s timer drives the selected mode while the
    dialog is open

Virtual mode uses the FakeSharePoint transport (demo), Real mode talks
HTTP to the configured site - mirroring the station-wide virtual/
real split.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from mtkgui.engine.uploader import (
    MODE_PACKAGED,
    MODE_SYNC,
    PERIODS,
    FakeSharePoint,
    HttpSharePoint,
    SharePointUploader,
)

#: persisted config (virtual_fault.json pattern: module config dir
#: first, then the working directory)
CONFIG_NAME = "sharepoint_upload.json"


def candidate_config_paths():
    here = Path(__file__).resolve().parents[1] / "config" / CONFIG_NAME
    yield here
    yield Path.cwd() / "config" / CONFIG_NAME


def load_upload_config() -> dict:
    """The stored ``sharepoint`` section (empty dict when missing)."""
    for path in candidate_config_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(
                data.get("sharepoint"), dict):
            return data["sharepoint"]
    return {}


def save_upload_config(section: dict) -> Path:
    """Persist the ``sharepoint`` section (module config dir)."""
    path = next(candidate_config_paths())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sharepoint": section},
                               ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


#: period key -> the label shown in the combo (order follows PERIODS)
PERIOD_LABELS = {
    "daily": "Daily",
    "weekly": "Weekly",
    "biweekly": "Bi-weekly",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "semiannual": "Semi-annual (half year)",
    "yearly": "Yearly",
}


class SharePointUploadDialog(QDialog):
    """Configure / test / drive the SharePoint upload (Report menu)."""

    #: (message) one line for the main-window Event Log
    action_logged = Signal(str)
    #: the sharepoint config section was saved
    config_saved = Signal(dict)

    #: auto-drive interval while the dialog is open
    TICK_MS = 30_000

    def __init__(self, parent=None, *, virtual: bool = False,
                 config_path=None, uploader: SharePointUploader | None = None,
                 state_dir=None):
        super().__init__(parent)
        self.setWindowTitle("SharePoint Upload")
        self.setModal(True)
        self.virtual = bool(virtual)
        self._config_path = (Path(config_path) if config_path else None)
        self._state_dir = (Path(state_dir) if state_dir else None)
        self._uploader = uploader
        self.resize(640, 520)

        root = QVBoxLayout(self)

        # ---------------------------------------------- connection box
        conn = QGroupBox("SharePoint Connection")
        form = QFormLayout(conn)
        self.site_edit = QLineEdit()
        self.site_edit.setPlaceholderText(
            "https://corp.sharepoint.com/sites/ict-reports")
        form.addRow("Site link:", self.site_edit)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("bearer token (optional)")
        form.addRow("Token:", self.token_edit)
        test_row = QHBoxLayout()
        self.btn_test = QPushButton("Test Connection")
        self.btn_test.clicked.connect(self.test_connection)
        test_row.addWidget(self.btn_test)
        self.conn_status = QLabel("")
        self.conn_status.setWordWrap(True)
        test_row.addWidget(self.conn_status, 1)
        form.addRow(test_row)
        root.addWidget(conn)

        # ------------------------------------------------- source folder
        src = QGroupBox("Local Folder")
        sform = QFormLayout(src)
        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(
            "folder to sync / pack (e.g. the report output folder)")
        folder_row.addWidget(self.folder_edit, 1)
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.clicked.connect(self._browse)
        folder_row.addWidget(self.btn_browse)
        sform.addRow(folder_row)
        root.addWidget(src)

        # ------------------------------------------------------- mode box
        mode = QGroupBox("Upload Mode")
        mform = QFormLayout(mode)
        self.rb_sync = QRadioButton(
            "Real-time sync - mirror the local folder into SharePoint "
            "(new / changed files only)")
        self.rb_packaged = QRadioButton(
            "Packaged upload - zip the folder with a timestamp and "
            "upload once per period")
        mform.addRow(self.rb_sync)
        mform.addRow(self.rb_packaged)
        self.period_combo = QComboBox()
        for key in PERIODS:
            self.period_combo.addItem(PERIOD_LABELS.get(key, key), key)
        mform.addRow("Period:", self.period_combo)
        self.rb_sync.toggled.connect(self._sync_mode_widgets)
        self.rb_packaged.toggled.connect(self._sync_mode_widgets)
        root.addWidget(mode)

        # ------------------------------------------------------ actions
        actions = QHBoxLayout()
        self.btn_save = QPushButton("Save Config")
        self.btn_save.clicked.connect(self.save_config)
        actions.addWidget(self.btn_save)
        self.btn_sync = QPushButton("Sync Now")
        self.btn_sync.clicked.connect(self.sync_now)
        actions.addWidget(self.btn_sync)
        self.btn_pack = QPushButton("Pack & Upload Now")
        self.btn_pack.clicked.connect(self.pack_now)
        actions.addWidget(self.btn_pack)
        actions.addStretch(1)
        root.addLayout(actions)

        # ------------------------------------------------- status / audit
        if self.virtual:
            root.addWidget(QLabel(
                "Virtual mode: the FakeSharePoint transport simulates "
                "the cloud (results marked virtual)."))
        self.audit_view = QPlainTextEdit()
        self.audit_view.setReadOnly(True)
        self.audit_view.setPlaceholderText("upload audit trail…")
        root.addWidget(self.audit_view, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # ----------------------------------------------------- timer
        self._timer = self._make_timer()

        # saved config -> fields (defaults: sync mode). An explicitly
        # injected config_path (tests / embedders) wins over the module
        # config so a local sharepoint_upload.json can never leak into
        # an isolated dialog; the real GUI passes config_path=None and
        # keeps restoring the persisted upload mode.
        if self._config_path is not None:
            try:
                data = json.loads(
                    self._config_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            saved = (data or {}).get("sharepoint", {}) \
                if isinstance(data, dict) else {}
        else:
            saved = load_upload_config()
        self._apply_section(saved)

    # ---------------------------------------------------------- plumbing
    def _make_timer(self):
        from PySide6.QtCore import QTimer
        timer = QTimer(self)
        timer.setInterval(self.TICK_MS)
        timer.timeout.connect(self._auto_tick)
        timer.start()
        return timer

    def _sync_mode_widgets(self):
        packaged = self.rb_packaged.isChecked()
        self.period_combo.setEnabled(packaged)
        self.btn_sync.setEnabled(not packaged)
        self.btn_pack.setEnabled(packaged)

    def _apply_section(self, section: dict) -> None:
        self.site_edit.setText(str(section.get("site_url") or ""))
        self.token_edit.setText(str(section.get("token") or ""))
        self.folder_edit.setText(str(section.get("local_folder") or ""))
        mode = str(section.get("upload_mode") or MODE_SYNC)
        idx = self.period_combo.findData(
            str(section.get("pack_period") or "weekly"))
        self.period_combo.setCurrentIndex(max(0, idx))
        if mode == MODE_PACKAGED:
            self.rb_packaged.setChecked(True)
        else:
            self.rb_sync.setChecked(True)
        self._sync_mode_widgets()

    def current_section(self) -> dict:
        """The ``sharepoint`` section built from the current fields."""
        return {
            "enabled": True,
            "site_url": self.site_edit.text().strip(),
            "token": self.token_edit.text().strip(),
            "local_folder": self.folder_edit.text().strip(),
            "upload_mode": (MODE_PACKAGED if self.rb_packaged.isChecked()
                            else MODE_SYNC),
            "pack_period": self.period_combo.currentData() or "weekly",
        }

    def _browse(self):
        start = self.folder_edit.text().strip() or str(Path.cwd())
        chosen = QFileDialog.getExistingDirectory(
            self, "Select the local upload folder", start)
        if chosen:
            self.folder_edit.setText(chosen)

    def _build_uploader(self) -> SharePointUploader:
        """A fresh uploader wired to the CURRENT fields (engine keeps
        ledger / dedup state per dialog session).  Ledger + archive
        zips live in a DEDICATED state dir - never inside the user's
        source folder (they would be re-synced / re-packed)."""
        from mtkgui.engine.uploader import UploadConfig
        section = self.current_section()
        folder = section["local_folder"]
        state = (self._state_dir or
                 Path(__file__).resolve().parents[1] / "config"
                 / "sharepoint_state")
        outbox = Path(folder) if folder else state / "sharepoint_outbox"
        cfg = UploadConfig.from_config({"sharepoint": section})
        if self._uploader is not None:
            uploader = self._uploader
        else:
            transport = (FakeSharePoint() if self.virtual else
                         HttpSharePoint(section["site_url"],
                                        token=section["token"],
                                        timeout=8.0))
            uploader = SharePointUploader(
                outbox, state_dir=state, transport=transport)
        uploader.apply_config(cfg)
        return uploader

    def _log(self, message: str) -> None:
        stamp = self._uploader.now() if self._uploader else None
        line = (f"[{stamp:%Y-%m-%d %H:%M:%S}] {message}" if stamp
                else message)
        self.audit_view.appendPlainText(line)
        self.action_logged.emit(message)

    # --------------------------------------------------------- actions
    def test_connection(self) -> list[str]:
        """Connectivity + permission + writable probe (honest result)."""
        self.conn_status.setText("testing…")
        problems = self._build_uploader().precheck()
        if problems:
            self.conn_status.setStyleSheet("color:#d35400;")
            self.conn_status.setText("FAIL: " + "; ".join(problems))
            self._log(f"sharepoint test connection: FAIL "
                      f"({'; '.join(problems)})")
        else:
            tag = " (virtual)" if self.virtual else ""
            self.conn_status.setStyleSheet("color:#1d7a3c;")
            self.conn_status.setText(
                f"OK{tag}: reachable, folder writable")
            self._log(f"sharepoint test connection: OK{tag}")
        return problems

    def sync_now(self) -> list:
        folder = self.folder_edit.text().strip()
        if not folder:
            self._warn("Select a local folder first.")
            return []
        results = self._build_uploader().sync_folder(folder)
        up = sum(1 for r in results if r.status == "UPLOADED")
        bad = sum(1 for r in results if r.status in ("FAILED",))
        self._log(f"sharepoint sync: {len(results)} files, "
                  f"{up} uploaded, {bad} failed (kept in outbox)")
        return results

    def pack_now(self) -> tuple:
        folder = self.folder_edit.text().strip()
        if not folder:
            self._warn("Select a local folder first.")
            return None, None
        result, zpath = self._build_uploader().pack_and_upload(folder)
        if result is None:
            self._log(f"sharepoint pack: {folder} is empty - "
                      "nothing to upload")
        else:
            self._log(f"sharepoint pack: {zpath.name} -> "
                      f"{result.status}")
        return result, zpath

    def save_config(self) -> Path:
        section = self.current_section()
        path = (save_upload_config(section) if self._config_path is None
                else _save_to(section, self._config_path))
        self._log(f"sharepoint config saved: {path}")
        self.config_saved.emit(section)
        return path

    # ------------------------------------------------------ auto drive
    def _auto_tick(self):
        """The 30 s driver: sync sweep or due-pack while open."""
        if not self.folder_edit.text().strip():
            return
        if self.rb_sync.isChecked():
            self.sync_now()
        elif self._build_uploader().pack_due():
            self.pack_now()

    def _warn(self, message: str):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "SharePoint Upload", message)
        self._log(f"sharepoint upload: {message.lower()}")

    # ------------------------------------------------------ test hooks
    def showEvent(self, event):
        super().showEvent(event)
        if not self.audit_view.toPlainText():
            self.audit_view.setPlainText(
                f"uploader ready (mode="
                f"{'packaged' if self.rb_packaged.isChecked() else 'sync'}"
                f", virtual={self.virtual})")


def _save_to(section: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sharepoint": section},
                               ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path
