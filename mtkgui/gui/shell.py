# -*- coding: utf-8 -*-
"""P2-1 GUI main-window shell framework (pure incremental).

Standardized, extensible application skeleton:

  +--------------------------------------------------------------+
  | TopNav (app title + baseline chip + clock)                   |
  +--------+-----------------------------------------------------+
  | Side   |  CentralArea (QStackedWidget — routed pages, cached)|
  | Dock   |  ...                                                |
  +--------+-----------------------------------------------------+
  | LogPanel (live scroll / level / keyword filter)              |
  +--------------------------------------------------------------+
  | StatusBar (engine state / devices / progress / ver / uptime) |

Zero imports from ``mtkgui.engine`` — the shell never touches P1 core
code; later P2 stages mount business pages purely via ``register_page``.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from mtkgui.engine.metrics import MetricsEngine
from mtkgui.engine.uploader import SharePointUploader

from .case_editor import CaseEditorPage
from .case_io_page import CaseIOPage
from .log_panel import LogPanelWidget
from .report_page import ReportPage
from .upload_page import UploadPage
from .export_page import ExportPage
from .cluster_page import ClusterPage
from .audit_page import AuditPage
from mtkgui.engine.cluster_scheduler import ClusterScheduler
from mtkgui.engine.auth_audit import AccessControl, AuditLog
from .config_page import ConfigPage
from .status_bar import StatusBarWidget
from .theme import StyleSpec, build_stylesheet

APP_TITLE = "MTK-GUI TestFlow"


class PlaceholderPage(QWidget):
    """Minimal default page for framework-only routes (no business logic)."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(f"[ {title} ]\n\n(module mounts here in later P2 stages)",
                       self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label)


class MainWindow(QMainWindow):
    """Global shell: layout zones + routing + status/log infrastructure."""

    def __init__(self, baseline_version: str = "V1.0-P2",
                 spec: Optional[StyleSpec] = None, parent=None) -> None:
        super().__init__(parent)
        self._spec = spec or StyleSpec()
        self._routes: dict[str, tuple[Callable[[], QWidget], str]] = {}
        self._pages: dict[str, QWidget] = {}
        self._close_confirmed = False

        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 800)
        self.setMinimumSize(self._spec.MIN_W, self._spec.MIN_H)
        self.setFont(self._spec.font())
        self.setStyleSheet(build_stylesheet(self._spec))

        self.status = StatusBarWidget(baseline_version, self._spec, self)
        self.log_panel = LogPanelWidget(self._spec, self)

        central = QWidget(self)
        central.setObjectName("CentralArea")
        self.stack = QStackedWidget(central)
        self.side_dock = QWidget(central)
        self.side_dock.setObjectName("SideDock")
        self.side_dock.setFixedWidth(self._spec.SIDEBAR_W)
        self.side_lay = QVBoxLayout(self.side_dock)
        self.side_lay.setContentsMargins(0, 8, 0, 8)
        self.side_lay.setSpacing(2)

        # top nav ------------------------------------------------------
        self.top_nav = QWidget(self)
        self.top_nav.setObjectName("TopNav")
        self.top_nav.setFixedHeight(self._spec.TOPNAV_H)
        nav_lay = QHBoxLayout(self.top_nav)
        nav_lay.setContentsMargins(12, 4, 12, 4)
        title = QLabel(APP_TITLE, self.top_nav)
        self.nav_baseline = QLabel(baseline_version, self.top_nav)
        nav_lay.addWidget(title)
        nav_lay.addStretch(1)
        nav_lay.addWidget(self.nav_baseline)

        # central column: nav + stack + status; log panel below split ----
        body_col = QWidget(central)
        col = QVBoxLayout(body_col)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(self.top_nav)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(0)
        main_row.addWidget(self.side_dock)
        main_row.addWidget(self.stack, 1)
        row_host = QWidget(central)
        row_host.setLayout(main_row)
        col.addWidget(row_host, 1)
        col.addWidget(self.log_panel)

        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(body_col, 1)
        self.setCentralWidget(central)
        self.setWindowButtonFlagsSafe()

        # status bar zone (bottom strip) --------------------------------
        sb_host = QWidget(self)
        sb_lay = QVBoxLayout(sb_host)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)
        sep = QFrame(self)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {self._spec.BORDER};")
        sb_lay.addWidget(sep)
        sb_lay.addWidget(self.status)
        self.statusBar().hide()  # native bar unused; we render our own strip
        shell.addWidget(sb_host)

        # uptime ticker --------------------------------------------------
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self.status.tick)
        self._ticker.start()

        self.log_panel.append("INFO", "GUI shell initialized "
                                      "(P2-1 framework baseline)")

    # window close safety -----------------------------------------------
    def setWindowButtonFlagsSafe(self) -> None:
        flags = self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint
        self.setWindowFlags(flags)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Safe-exit gate: confirm once, stop tickers, flush log marker."""
        if not self._close_confirmed:
            box = QMessageBox(self)
            box.setWindowTitle("Exit")
            box.setText("Confirm exit? Running tasks will be stopped.")
            box.setStandardButtons(QMessageBox.StandardButton.Yes
                                   | QMessageBox.StandardButton.No)
            ok = box.exec() == QMessageBox.StandardButton.Yes
            self.log_panel.append("INFO", "exit confirmed" if ok
                                  else "exit cancelled")
            if not ok:
                event.ignore()
                return
        self._close_confirmed = True
        self._ticker.stop()
        self.log_panel.append("INFO", "GUI shell shutdown (resources flushed)")
        event.accept()

    # routing ------------------------------------------------------------
    def register_page(self, key: str, factory: Callable[[], QWidget],
                      title: str) -> None:
        """Mount a page under a route key (later P2 stages hook here)."""
        if not key or key in self._routes:
            raise ValueError(f"illegal/duplicate route key: {key!r}")
        self._routes[key] = (factory, title)
        btn = QPushButton(title, self.side_dock)
        btn.setCheckable(True)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Fixed)
        btn.clicked.connect(lambda _c=False, k=key: self.navigate(k))
        self.side_lay.addWidget(btn)
        self._nav_buttons = getattr(self, "_nav_buttons", {})
        self._nav_buttons[key] = btn

    def navigate(self, key: str) -> None:
        """Route to a page, lazily constructing + caching it."""
        if key not in self._routes:
            self.log_panel.append("WARN", f"route not found: {key}")
            return
        if key not in self._pages:
            factory, _title = self._routes[key]
            try:
                page = factory()
            except Exception as exc:  # startup/runtime fallback per P2-1 spec
                self.log_panel.append("ERROR",
                                      f"page build failed for {key}: {exc}")
                page = PlaceholderPage(f"{key} (unavailable)", self.stack)
            self._pages[key] = page
            self.stack.addWidget(page)
        self.stack.setCurrentWidget(self._pages[key])
        for k, btn in getattr(self, "_nav_buttons", {}).items():
            btn.setChecked(k == key)
        self.log_panel.append("DEBUG", f"navigated -> {key}")

    @property
    def route_keys(self) -> list[str]:
        return list(self._routes)

    @property
    def cached_pages(self) -> list[str]:
        return list(self._pages)

    # default skeleton routes ---------------------------------------------
    @staticmethod
    def _default_config_yaml() -> str:
        import glob
        cands = sorted(glob.glob("config/PROJECT_*.yaml"))
        return cands[0] if cands else "config/project.yaml"

    @staticmethod
    def _default_outbox_dir() -> str:
        """Local upload outbox (fallback layer, never auto-deleted)."""
        import os
        return os.environ.get("MTKGUI_OUTBOX_DIR", "outbox")

    @staticmethod
    def _default_export_dir() -> str:
        """Deliverable report export directory."""
        import os
        return os.environ.get("MTKGUI_EXPORT_DIR", "reports_export")

    @staticmethod
    def _default_audit_path() -> str:
        import os
        return os.environ.get("MTKGUI_AUDIT_LOG", "audit/audit.jsonl")

    @staticmethod
    def _default_accounts_path() -> str:
        import os
        return os.environ.get("MTKGUI_ACCOUNTS", "audit/accounts.json")

    def mount_default_routes(self) -> None:
        """Framework routes; the config page is the P2-2 increment and
        the AI-case editor page is the P2-3 increment."""
        self.register_page("home", lambda: PlaceholderPage("Home"), "Home")
        self.register_page("workflow", lambda: PlaceholderPage("Workflow"),
                           "Test Workflow")
        self.register_page("cases",
                           lambda: CaseEditorPage(
                               self._default_config_yaml()),
                           "AI Case Editor")
        self.register_page("case_io",
                           lambda: CaseIOPage(self._default_config_yaml()),
                           "Review Excel")
        # P2-6: live dashboard over a shared MetricsEngine (P2-5 base)
        self.metrics_engine = MetricsEngine()
        self.register_page("reports",
                           lambda: ReportPage(self.metrics_engine),
                           "Reports")
        # P2-8: cloud archive monitor over a shared uploader
        self.upload_manager = SharePointUploader(
            self._default_outbox_dir())
        self.register_page("upload",
                           lambda: UploadPage(self.upload_manager),
                           "Upload")
        # P2-9: commercial report export over the shared engine
        self.register_page("export",
                           lambda: ExportPage(self.metrics_engine,
                                              out_dir=self
                                              ._default_export_dir()),
                           "Export")
        # P2-10: multi-device cluster board over a shared scheduler
        self.cluster_scheduler = ClusterScheduler()
        self.register_page("cluster",
                           lambda: ClusterPage(self.cluster_scheduler),
                           "Cluster")
        # P2-11: RBAC + operation audit over shared stores
        self.audit_log = AuditLog(self._default_audit_path())
        self.access = AccessControl(self._default_accounts_path(),
                                    audit=self.audit_log)
        self.access.ensure_default_accounts()
        self.register_page("audit",
                           lambda: AuditPage(self.access,
                                             self.audit_log),
                           "Audit")
        self.register_page("config",
                           lambda: ConfigPage(self._default_config_yaml()),
                           "Config")
        self.navigate("home")

    # console-style helpers for future engine bridges ----------------------
    def set_engine_state(self, state: str) -> None:
        self.status.set_engine_state(state)
        self.log_panel.append("INFO", f"engine state -> {state}")

    def set_devices_online(self, count: int) -> None:
        self.status.set_devices_online(count)

    def set_progress(self, done: int, total: int) -> None:
        self.status.set_progress(done, total)

    def log(self, level: str, message: str) -> None:
        self.log_panel.append(level, message)
