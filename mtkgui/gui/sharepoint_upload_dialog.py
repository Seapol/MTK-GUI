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
from datetime import datetime
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

from mtkgui.engine.sharepoint_site import (
    SharePointSession,
    host_of,
    parse_sharepoint_link,
    session_cookies,
)
from mtkgui.engine.uploader import (
    MODE_PACKAGED,
    MODE_SYNC,
    PERIODS,
    FakeSharePoint,
    HttpSharePoint,
    SharePointRestTransport,
    SharePointUploader,
    TransportError,
)

#: persisted config (virtual_fault.json pattern: module config dir
#: first, then the working directory)
CONFIG_NAME = "sharepoint_upload.json"

#: signed-in session file inside the SharePoint state dir
SESSION_NAME = "session.json"

#: Chrome user agent - some tenants reject the stock Qt WebEngine UA
CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
             "AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/124.0.0.0 Safari/537.36")


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


class SharePointSignInDialog(QDialog):
    """Embedded login window (QtWebEngine) for the real NXP site.

    The operator signs in with their own corporate account (MFA
    included) in a normal browser window; MTK GUI only captures the
    resulting FedAuth / rtFa session cookies - the password never
    reaches the application.  The web profile (cookie store) persists
    under ``sharepoint_state/webprofile`` so the tenant session
    survives a dialog close.

    ``view_factory`` lets tests inject a stub view (no QtWebEngine
    process needed); :meth:`add_cookie` is the single success-detection
    entry point for both the live cookie store and the tests.
    """

    def __init__(self, parent=None, *, site_url: str = "", profile_dir=None,
                 view_factory=None):
        super().__init__(parent)
        self.setWindowTitle("SharePoint Sign-in")
        self.setModal(True)
        self.resize(900, 680)
        self.site_url = str(site_url or "")
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.host = host_of(self.site_url)
        self.signed_in = False
        self.session_cookies: list[dict] = []

        root = QVBoxLayout(self)
        self.url_label = QLineEdit()
        self.url_label.setReadOnly(True)
        self.url_label.setPlaceholderText("sign-in page…")
        root.addWidget(self.url_label)
        self.view = (view_factory() if view_factory is not None
                     else self._make_view())
        root.addWidget(self.view, 1)
        self.status = QLabel("Sign in with your NXP account (MFA included)."
                             " MTK GUI stores no password.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------- web view
    def _make_view(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView
        profile = QWebEngineProfile("mtkgui-sharepoint", self)
        if self.profile_dir is not None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            profile.setPersistentStoragePath(str(self.profile_dir))
            profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy
                .ForcePersistentCookies)
        profile.setHttpUserAgent(CHROME_UA)
        page = QWebEnginePage(profile, self)
        view = QWebEngineView(self)
        view.setPage(page)
        store = profile.cookieStore()
        store.cookieAdded.connect(self._on_qt_cookie)
        store.loadAllCookies()
        view.urlChanged.connect(
            lambda url: self.url_label.setText(url.toString()))
        view.load(QUrl(self.site_url))
        return view

    def _on_qt_cookie(self, cookie):
        """Qt cookie store -> the plain dict :meth:`add_cookie` wants."""
        def text(data) -> str:
            return bytes(data).decode("utf-8", "ignore")

        self.add_cookie({"name": text(cookie.name().data()),
                         "value": text(cookie.value().data()),
                         "domain": cookie.domain(),
                         "path": cookie.path() or "/",
                         "secure": cookie.isSecure()})

    # ------------------------------------------------- signed-in state
    def add_cookie(self, cookie: dict) -> bool:
        """Keep a session cookie for the site host; the first FedAuth /
        rtFa cookie marks the sign-in as complete."""
        kept = session_cookies([cookie], self.host)
        if not kept:
            return False
        current = kept[0]
        self.session_cookies = [
            c for c in self.session_cookies
            if (c.get("name"), c.get("path")) !=
            (current.get("name"), current.get("path"))]
        self.session_cookies.append(current)
        if not self.signed_in:
            self.signed_in = True
            self.status.setStyleSheet("color:#1d7a3c;")
            self.status.setText("Signed in — close this window")
        return True


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
                 state_dir=None, session: SharePointSession | None = None):
        super().__init__(parent)
        self.setWindowTitle("SharePoint Upload")
        self.setModal(True)
        self.virtual = bool(virtual)
        self._config_path = (Path(config_path) if config_path else None)
        self._state_dir = (Path(state_dir) if state_dir else None)
        self._state_root = (self._state_dir or
                            Path(__file__).resolve().parents[1] / "config"
                            / "sharepoint_state")
        self._uploader = uploader
        # signed-in session: injected (tests / embedders) or restored
        # from the persisted session.json; virtual mode never signs in
        self._session = session if session is not None else (
            None if self.virtual else
            SharePointSession.load(self._state_root / SESSION_NAME))
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
        self.token_edit.setPlaceholderText("bearer token (optional, legacy)")
        form.addRow("Token:", self.token_edit)
        sign_row = QHBoxLayout()
        self.btn_signin = QPushButton("Connect & Sign in…")
        self.btn_signin.clicked.connect(self.connect_and_sign_in)
        self.btn_signin.setEnabled(not self.virtual)
        sign_row.addWidget(self.btn_signin)
        self.signin_status = QLabel(
            "virtual mode: no sign-in needed" if self.virtual
            else "not signed in")
        self.signin_status.setWordWrap(True)
        sign_row.addWidget(self.signin_status, 1)
        form.addRow(sign_row)
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
        self._apply_session()

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

    def _apply_session(self) -> None:
        """Show the persisted session (if any) as the sign-in status."""
        if self.virtual or not (self._session and self._session.cookies):
            return
        self.signin_status.setStyleSheet("color:#1d7a3c;")
        self.signin_status.setText(
            f"Signed in as {self._session.user or 'signed-in user'} — "
            "SharePoint test-data upload ready")

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
        state = self._state_root
        outbox = Path(folder) if folder else state / "sharepoint_outbox"
        cfg = UploadConfig.from_config({"sharepoint": section})
        if self._uploader is not None:
            uploader = self._uploader
        else:
            uploader = SharePointUploader(
                outbox, state_dir=state, transport=self._transport())
        uploader.apply_config(cfg)
        return uploader

    def _transport(self):
        """Fake (virtual) / signed-in REST (real) / legacy token."""
        if self.virtual:
            return FakeSharePoint()
        rest = self._rest_transport()
        if rest is not None:
            return rest
        section = self.current_section()
        return HttpSharePoint(section["site_url"], token=section["token"],
                              timeout=8.0)

    def _rest_transport(self) -> SharePointRestTransport | None:
        """The REST transport for the signed-in session (None when the
        operator has not signed in - legacy token mode stays)."""
        if self.virtual or not (self._session and self._session.cookies):
            return None
        link = self.site_edit.text().strip() or self._session.link
        site, folder = self._session.site, self._session.folder_path
        if link:
            try:
                parsed = parse_sharepoint_link(link)
                site = site or parsed.site
                folder = parsed.folder_path or folder
            except ValueError:
                pass
        if not site:
            return None
        return SharePointRestTransport(site, self._session.jar(),
                                       folder_path=folder, timeout=8.0)

    # --------------------------------------------------------- sign-in
    def connect_and_sign_in(self):
        """Open the embedded login window and capture the tenant
        session (FedAuth / rtFa cookies).  No password is stored."""
        if self.virtual:
            return None
        link = self.site_edit.text().strip()
        if not link:
            self._warn("Enter the SharePoint site link first.")
            return None
        try:
            parsed = parse_sharepoint_link(link)
        except ValueError as exc:
            self._warn(f"Invalid SharePoint link: {exc}")
            return None
        dlg = SharePointSignInDialog(
            self, site_url=parsed.site,
            profile_dir=self._state_root / "webprofile")
        dlg.exec()
        if not (dlg.signed_in and dlg.session_cookies):
            self._log("sharepoint sign-in: cancelled / not completed")
            return None
        return self.adopt_sign_in(parsed, dlg.session_cookies)

    def adopt_sign_in(self, parsed, cookies: list[dict]):
        """Persist the captured session, resolve the user name over REST
        and run Test Connection once."""
        site = parsed.site
        user = ""
        try:
            user = SharePointRestTransport(
                site, SharePointSession(site=site,
                                        cookies=list(cookies)).jar(),
                folder_path=parsed.folder_path,
                timeout=8.0).current_user().strip()
        except (TransportError, ConnectionError):
            user = ""
        session = SharePointSession(
            site=site, folder_path=parsed.folder_path,
            user=user or "signed-in user",
            link=self.site_edit.text().strip(),
            signed_in_at=datetime.now().isoformat(timespec="seconds"),
            cookies=list(cookies))
        session.save(self._state_root / SESSION_NAME)
        self._session = session
        self.signin_status.setStyleSheet("color:#1d7a3c;")
        self.signin_status.setText(
            f"Signed in as {session.user} — SharePoint test-data upload "
            "ready")
        self._log(f"sharepoint sign-in: {session.user} ({site})")
        self.test_connection()
        return session

    def _log(self, message: str) -> None:
        stamp = self._uploader.now() if self._uploader else None
        line = (f"[{stamp:%Y-%m-%d %H:%M:%S}] {message}" if stamp
                else message)
        self.audit_view.appendPlainText(line)
        self.action_logged.emit(message)

    # --------------------------------------------------------- actions
    def test_connection(self) -> list[str]:
        """Connectivity + permission + writable probe (honest result).

        Real mode needs a signed-in session: without one the honest
        answer is "not signed in", never a silent legacy fallback."""
        self.conn_status.setText("testing…")
        if not self.virtual and not (self._session and self._session.cookies):
            problems = ["not signed in — click Connect & Sign in… first"]
        else:
            try:
                problems = self._build_uploader().precheck()
            except TransportError as exc:
                problems = [str(exc)]
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
