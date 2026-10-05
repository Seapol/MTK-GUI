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

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
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

MODE_REAL = "Real"
MODE_VIRTUAL = "Virtual"

FIXTURE_ATE = "ATE"
FIXTURE_MANUAL = "Manual"
FIXTURE_TYPES = (FIXTURE_ATE, FIXTURE_MANUAL)

# Fixed wording of the Manual-fixture notice (spec item 5): shown once
# after a Manual login and whenever a blocked fixture / IO entry is used.
MANUAL_FIXTURE_NOTICE = (
    "当前为Manual Fixture模式，无IO资源自动控制权限，"
    "所有夹具动作、硬件操作需由用户手动自行操作")

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
    "toggle_stages": "Enable / disable ICT / FCT stages (Overall Flow EN)",
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


class SlideSwitch(QAbstractButton):
    """Generic left/right slide toggle (one control, two options).

    Left = unchecked option (default docking), right = checked
    option.  Single selection is inherent: a checkable button is
    either on one side or the other, never both / neither.

    Args:
        left_label:  Text of the left (unchecked) half.
        right_label: Text of the right (checked) half.
        off_color:   Track color while the left half is active.
        on_color:    Track color while the right half is active.
    """

    def __init__(self, left_label: str, right_label: str,
                 off_color: str, on_color: str, parent=None):
        super().__init__(parent)
        self._left_label = left_label
        self._right_label = right_label
        self._off_color = QColor(off_color)
        self._on_color = QColor(on_color)
        self.setCheckable(True)
        self.setChecked(False)          # left docking by default
        self.setFixedSize(132, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        on = self.isChecked()
        bg = (self._on_color if (on and enabled)
              else self._off_color if enabled else QColor("#d1d5db"))
        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor("#9ca3af"), 1))
        p.setBrush(bg)
        p.drawRoundedRect(track, 14, 14)
        # half labels
        p.setPen(QColor("#ffffff") if enabled else QColor("#6b7280"))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(QRectF(0, 0, self.width() / 2, self.height()),
                   Qt.AlignmentFlag.AlignCenter, self._left_label)
        p.drawText(QRectF(self.width() / 2, 0, self.width() / 2,
                          self.height()),
                   Qt.AlignmentFlag.AlignCenter, self._right_label)
        # sliding knob
        knob_r = self.height() - 8
        x = (self.width() - knob_r - 4) if on else 4
        p.setPen(QPen(QColor("rgba(0,0,0,0.25)"), 1))
        p.setBrush(QColor("#ffffff" if enabled else "#f3f4f6"))
        p.drawEllipse(QRectF(x, 4, knob_r, knob_r))
        p.end()


class ModeSwitch(SlideSwitch):
    """Run-mode slide switch (spec item 2).

    Left = Real (physical hardware, default), right = Virtual
    (simulated, supervisor-only).  Disabled (grayed) until unlocked
    by the login permission logic."""

    def __init__(self, parent=None):
        super().__init__(MODE_REAL, MODE_VIRTUAL,
                         "#1d7a3c", "#7c3aed", parent)


class FixtureSwitch(SlideSwitch):
    """Fixture-type slide switch (M0 sub-task, spec item 4).

    Left = ATE (production fixture auto test, default baseline),
    right = Manual (bench manual debug).  Same look & interaction as
    :class:`ModeSwitch`; single selection, mutually exclusive.  The
    choice is per-login only and is NOT persisted (a restart returns
    to the ATE baseline)."""

    def __init__(self, parent=None):
        super().__init__(FIXTURE_ATE, FIXTURE_MANUAL,
                         "#2563eb", "#b45309", parent)

    # ------------------------------------------------------------- compat
    def fixture_type(self) -> str:
        """Currently selected fixture type (ATE or Manual)."""
        return FIXTURE_MANUAL if self.isChecked() else FIXTURE_ATE

    def set_fixture_type(self, fixture: str) -> None:
        """Programmatic selection (used by tests and state restore)."""
        self.setChecked(fixture == FIXTURE_MANUAL)


# the former two-button selector is now the slide switch itself
FixtureSelector = FixtureSwitch


class LoginDialog(QDialog):
    """Startup / switch-account dialog (spec items 1-4).

    Fixed vertical order: Account -> Password -> Mode switch ->
    Fixture selector -> Login button.

    The Mode switch starts disabled (grayed, forced Real) and unlocks
    ONLY after a successful supervisor login validation (Supervisor
    account + correct password typed); ordinary accounts stay locked
    on Real mode forever.

    After accept: :attr:`role`, :attr:`mode` (Real / Virtual) and
    :attr:`fixture_type` (ATE / Manual, default ATE) hold the result."""

    def __init__(self, parent=None, allow_cancel=True):
        super().__init__(parent)
        self.setWindowTitle("MTK GUI - Login")
        self.role = None
        self.mode = MODE_REAL
        # balanced dialog sizing: hard minimum floor + default startup
        # dimension (kept together with the slider layout change)
        self.setMinimumSize(430, 400)
        self.resize(480, 470)

        form = QFormLayout(self)

        # welcome header: line 1 greeting, line 2 version number
        welcome = QLabel(
            '<span style="font-size:17px;font-weight:600;">'
            'Welcome to MTK All-in-One GUI</span><br>'
            f'<span style="font-size:12px;">'
            f'Version {__version__}</span>')
        form.addRow(welcome)

        # 1 ------------------------------------------------------- account
        self.role_combo = QComboBox()
        self.role_combo.addItems(ROLES)
        form.addRow("Account:", self.role_combo)

        # 2 ------------------------------------------------------ password
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Supervisor password")
        form.addRow("Password:", self.password_edit)

        # 3 ---------------------------------------------------- mode switch
        # Left = Real (default), right = Virtual.  Disabled + grayed
        # until the supervisor password validates (spec items 2-3).
        self.mode_switch = ModeSwitch()
        self.mode_switch.setEnabled(False)
        form.addRow("Mode:", self.mode_switch)

        # 4 ------------------------------------------------- fixture choice
        self.fixture_selector = FixtureSelector()
        form.addRow("Fixture:", self.fixture_selector)

        hint = QLabel("Operator: no password needed.\n"
                      "Supervisor: enter the account password.\n"
                      "Mode switch unlocks for supervisor only.")
        hint.setObjectName("muted")
        form.addRow(hint)

        # 5 --------------------------------------------------- login button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText("Login")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        if not allow_cancel:
            buttons.button(
                QDialogButtonBox.StandardButton.Cancel).setVisible(False)
        form.addRow(buttons)

        # permission rule: the switch unlocks only when a supervisor
        # account AND the correct password are present (live check)
        self.role_combo.currentTextChanged.connect(
            lambda _t: self._sync_mode_lock())
        self.password_edit.textChanged.connect(
            lambda _t: self._sync_mode_lock())
        self._sync_mode_lock()

    # ------------------------------------------------------------ helpers
    def _supervisor_unlocked(self) -> bool:
        """True when the supervisor credential pair validates."""
        return (self.role_combo.currentText() == ROLE_SUPERVISOR
                and self.password_edit.text() == SUPERVISOR_PASSWORD)

    def _sync_mode_lock(self):
        """Gray out + force Real until the supervisor login validates."""
        unlocked = self._supervisor_unlocked()
        self.mode_switch.setEnabled(unlocked)
        if not unlocked:
            # ordinary accounts are locked on the Real baseline forever
            self.mode_switch.blockSignals(True)
            self.mode_switch.setChecked(False)
            self.mode_switch.blockSignals(False)
        if unlocked:
            self.password_edit.setFocus()

    # ------------------------------------------------------------- accept
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
        # the switch can only be Virtual if the supervisor unlocked it;
        # keep the defensive fallback for non-supervisor logins
        self.mode = (MODE_VIRTUAL if self.mode_switch.isChecked()
                     else MODE_REAL)
        self.fixture_type = self.fixture_selector.fixture_type()
        self.accept()

    @staticmethod
    def login(parent=None, allow_cancel=True):
        """Show the dialog modally.

        Returns (role, mode, fixture_type) or None on cancel."""
        dlg = LoginDialog(parent, allow_cancel=allow_cancel)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.role, dlg.mode, dlg.fixture_type
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
