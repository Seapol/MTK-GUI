# -*- coding: utf-8 -*-
"""Account roles and operator permissions.

Two accounts share one GUI:

* **Supervisor** - full access: every menu, every editor, YAML saving.
* **Operator**   - runs tests and may connect / disconnect instruments,
  but every other right is granted per key by the supervisor
  (Settings > Operator Permissions, persisted in config/permissions.json).

The supervisor password lives only in this source file (SUPERVISOR_PASSWORD
below); it never appears in the UI, the manual or any other document.
"""

import json
import sys
from pathlib import Path

from . import __version__

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

ROLE_SUPERVISOR = "Supervisor"
ROLE_OPERATOR = "Operator"
ROLES = (ROLE_SUPERVISOR, ROLE_OPERATOR)

# Default supervisor password (source-only by design; do not document it).
SUPERVISOR_PASSWORD = "nxp"

# permission key -> UI label shown in the supervisor dialog.  Defaults are
# what a fresh operator account gets; "connect / disconnect instruments"
# is always allowed and therefore intentionally not a key here.
PERMISSION_LABELS = {
    "save_yaml": "Save YAML (Apply and Save / Save as)",
    "edit_ict": "Edit ICT test cases (double-click rows)",
    "edit_fct": "Edit FCT test cases (double-click rows)",
    "edit_product_info": "Edit Product Information",
    "edit_run_control": "Edit Long Run / Interval",
    "edit_serial_params": "Configure serial / SSH channel parameters",
    "manage_channels": "Add / Remove console channels",
    "equipment_config": "Open Equipment page configuration windows",
    "sn_format_check": "Serial Number Format Check (Settings)",
}
DEFAULT_PERMISSIONS = {key: False for key in PERMISSION_LABELS}


def candidate_paths():
    """Locations searched for permissions.json, in priority order."""
    pkg_root = Path(__file__).resolve().parent.parent
    yield pkg_root / "config" / "permissions.json"
    yield Path.cwd() / "config" / "permissions.json"
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        yield Path(sys.executable).resolve().parent / "config" / "permissions.json"


def load_permissions():
    """Return the stored operator permission dict (defaults if missing)."""
    for path in candidate_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            perm = dict(DEFAULT_PERMISSIONS)
            for key in perm:
                if key in data:
                    perm[key] = bool(data[key])
            return perm
    return dict(DEFAULT_PERMISSIONS)


def save_permissions(perm):
    """Persist the operator permission dict to config/permissions.json."""
    payload = {key: bool(perm.get(key, False)) for key in PERMISSION_LABELS}
    path = next(candidate_paths())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


class LoginDialog(QDialog):
    """Startup / switch-account dialog.

    Pick Supervisor or Operator; the supervisor must enter the account
    password.  After accept, :attr:`role` holds the chosen role."""

    def __init__(self, parent=None, allow_cancel=True):
        super().__init__(parent)
        self.setWindowTitle("MTK GUI - Login")
        self.role = None

        form = QFormLayout(self)

        # welcome header: line 1 greeting, line 2 version number
        welcome = QLabel(
            '<span style="font-size:17px;font-weight:600;">'
            'Welcome to MTK All-in-One GUI</span><br>'
            f'<span style="font-size:12px;">'
            f'Version {__version__}</span>')
        form.addRow(welcome)

        self.role_combo = QComboBox()
        self.role_combo.addItems(ROLES)
        form.addRow("Account:", self.role_combo)

        # Real mode (default) needs the physical DUT / instruments /
        # peripherals; Virtual mode simulates them (supervisor only).
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(("Real", "Virtual"))
        form.addRow("Mode:", self.mode_combo)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Supervisor password")
        form.addRow("Password:", self.password_edit)

        hint = QLabel("Operator: no password needed.\n"
                      "Supervisor: enter the account password.")
        hint.setObjectName("muted")
        form.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        if not allow_cancel:
            buttons.button(
                QDialogButtonBox.StandardButton.Cancel).setVisible(False)
        form.addRow(buttons)

        self._sync_password()
        self.role_combo.currentTextChanged.connect(
            lambda _t: self._sync_password())

    def _sync_password(self):
        supervisor = (self.role_combo.currentText() == ROLE_SUPERVISOR)
        self.password_edit.setEnabled(supervisor)
        # Virtual mode is supervisor-only: operators always run Real mode
        self.mode_combo.setEnabled(supervisor)
        if not supervisor and self.mode_combo.currentText() != "Real":
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(0)
            self.mode_combo.blockSignals(False)
        if supervisor:
            self.password_edit.setFocus()

    def _on_accept(self):
        role = self.role_combo.currentText()
        if role == ROLE_SUPERVISOR:
            if self.password_edit.text() != SUPERVISOR_PASSWORD:
                QMessageBox.warning(self, "Login Failed",
                                    "Wrong supervisor password.")
                self.password_edit.selectAll()
                self.password_edit.setFocus()
                return
        self.role = role
        self.mode = self.mode_combo.currentText()
        self.accept()

    @staticmethod
    def login(parent=None, allow_cancel=True):
        """Show the dialog modally; return (role, mode) or None on cancel."""
        dlg = LoginDialog(parent, allow_cancel=allow_cancel)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.role, dlg.mode
        return None


class PermissionsDialog(QDialog):
    """Supervisor-only editor for the operator permission set."""

    def __init__(self, perm, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Operator Permissions")
        layout = QVBoxLayout(self)

        note = QLabel(
            "Uncheck a right to take it away from Operator accounts.\n"
            "Connecting / disconnecting instruments is always allowed.")
        note.setObjectName("muted")
        layout.addWidget(note)

        self._checks = {}
        for key, label in PERMISSION_LABELS.items():
            check = QCheckBox(label)
            check.setChecked(bool(perm.get(key, False)))
            self._checks[key] = check
            layout.addWidget(check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_permissions(self):
        return {key: check.isChecked()
                for key, check in self._checks.items()}

    @staticmethod
    def edit(perm, parent=None):
        """Return the new permission dict, or None if cancelled."""
        dlg = PermissionsDialog(perm, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.result_permissions()
        return None
