# -*- coding: utf-8 -*-
"""Virtual mode fault-injection configuration.

Virtual mode (supervisor only, chosen at login) simulates the DUT,
instruments and peripherals, so no real hardware is needed.  Two random
faults can be injected into every executed test case:

* ``test_fail_ratio``       - the measurement randomly exceeds its
  limits or an unexpected message is returned -> result FAIL.
* ``equipment_error_ratio`` - a random instrument / peripheral / serial
  fault occurs -> result Error.

Both are percentages (0-100) persisted in config/virtual_fault.json.
Virtual fault injection is only available while the GUI runs in
Virtual mode.
"""

import json
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
)

DEFAULT_FAULT_CONFIG = {"test_fail_ratio": 0.0, "equipment_error_ratio": 0.0}


def candidate_paths():
    yield Path(__file__).resolve().parent / "config" / "virtual_fault.json"
    yield Path.cwd() / "config" / "virtual_fault.json"
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        yield Path(sys.executable).resolve().parent / "config" / "virtual_fault.json"


def load_fault_config():
    """Return the stored fault-injection ratios (defaults if missing)."""
    for path in candidate_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            cfg = dict(DEFAULT_FAULT_CONFIG)
            for key in cfg:
                try:
                    cfg[key] = round(min(100.0, max(
                        0.0, float(data.get(key, 0.0)))), 2)
                except (TypeError, ValueError):
                    pass
            return cfg
    return dict(DEFAULT_FAULT_CONFIG)


def save_fault_config(cfg):
    """Persist the fault-injection ratios to config/virtual_fault.json."""
    payload = {key: round(min(100.0, max(0.0, float(cfg.get(key, 0.0)))), 2)
               for key in DEFAULT_FAULT_CONFIG}
    path = next(candidate_paths())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


class VirtualFaultDialog(QDialog):
    """Configure the random faults injected while running in Virtual mode."""

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Virtual Fault Injection")
        form = QFormLayout(self)

        note = QLabel(
            "Random faults injected into every executed test case while "
            "the GUI runs in Virtual mode (supervisor only).")
        note.setObjectName("muted")
        form.addRow(note)

        self.fail_spin = QDoubleSpinBox()
        self.fail_spin.setRange(0.0, 100.0)
        self.fail_spin.setDecimals(2)  # 0.01 % precision
        self.fail_spin.setSingleStep(0.1)
        self.fail_spin.setSuffix(" %")
        self.fail_spin.setValue(float(cfg.get("test_fail_ratio", 0.0)))
        self.fail_spin.setToolTip(
            "Chance per test case of a random out-of-limit measurement "
            "or unexpected reply -> FAIL")
        form.addRow("Virtual Test Fail Ratio:", self.fail_spin)

        self.err_spin = QDoubleSpinBox()
        self.err_spin.setRange(0.0, 100.0)
        self.err_spin.setDecimals(2)  # 0.01 % precision
        self.err_spin.setSingleStep(0.1)
        self.err_spin.setSuffix(" %")
        self.err_spin.setValue(float(cfg.get("equipment_error_ratio", 0.0)))
        self.err_spin.setToolTip(
            "Chance per test case of a random instrument / peripheral / "
            "serial fault -> Error")
        form.addRow("Virtual Equipment Error:", self.err_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def get_config(self):
        return {
            "test_fail_ratio": self.fail_spin.value(),
            "equipment_error_ratio": self.err_spin.value(),
        }

    @staticmethod
    def edit(cfg, parent=None):
        """Modal editor; return the new config dict or None on cancel."""
        dlg = VirtualFaultDialog(cfg, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.get_config()
        return None
