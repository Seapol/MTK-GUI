# -*- coding: utf-8 -*-
"""M83 C10: the instrument checklist shows the full device name."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QCheckBox, QDialog  # noqa: E402

from mtkgui.gui.steps_editor import edit_op_step_dialog  # noqa: E402

EQUIPMENT = {
    "daq973a": {"fields": {"Address": "GPIB0::9::INSTR"},
                "params": {"Scan speed (ch/s)": "450"}},
    "u2355a": {"fields": {"Address": "USB0::U2355A::INSTR"},
               "params": {"Sample rate (kSa/s)": "20"}},
    "psu": {"fields": {"Address": "TCPIP0::x",
                       "Model": "Keysight N5747A DC Power Supply"},
            "params": {"Voltage set (V)": "5.0"}},
    "jlink": {"fields": {"Address": "JLinkExe"}},
}


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _open(monkeypatch, name="Init Instruments", equipment=EQUIPMENT):
    seen: list = []

    def fake_exec(dlg):
        seen.append(dlg)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    edit_op_step_dialog(None, name,
                        {"type": "instruments",
                         "instruments": ["daq973a", "psu"]},
                        True, 100, 5000, equipment=equipment)
    assert seen, "the operation dialog never opened"
    return seen[0]


def _checkboxes(dlg) -> list:
    return [cb.text() for cb in dlg.findChildren(QCheckBox)]


def test_m83_instrument_checklist_shows_model_not_abbr(qapp, monkeypatch):
    dlg = _open(monkeypatch)
    texts = _checkboxes(dlg)
    assert any("Keysight DAQ973A" in text for text in texts)
    assert any("Keysight U2355A" in text for text in texts)
    assert any("Keysight N5747A" in text for text in texts)
    assert any("Segger J-Link" in text for text in texts)
    assert not set(texts) & {"DAQM", "DAQ", "PSU", "JLINK"}


def test_m83_slot_modules_are_not_selectable_instruments(qapp, monkeypatch):
    dlg = _open(monkeypatch)
    texts = _checkboxes(dlg)
    assert len(texts) == 4                     # one per Equipment key
    # the slot modules are owned by the DAQ973A mainframe - they are
    # never their own selectable instrument
    assert not any(text.strip().lower() in ("m908a_1", "m908a_2", "m907a")
                   for text in texts)
