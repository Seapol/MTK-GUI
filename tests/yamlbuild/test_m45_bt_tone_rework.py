# -*- coding: utf-8 -*-
"""m45: BT Tone editor rework.

The Tone module publishes ``wav`` + ``tone_start_s`` / ``tone_end_s``
with NO Timeout and NO automatic operator confirm.  The GUI edits the
segment with a dual-node slider (Start <= End), reads the total length
from the wav header, previews the segment locally (QtMultimedia) with a
live level meter, and probes the DUT BT driver read-only (three states).
Legacy ``audio_confirm`` / ``tone_timeout`` / ``tone_duration_s`` are
tolerated but never re-emitted.
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    BluetoothCfg,
    FctTestConfig,
    STEP_EXTERNAL_TOOL,
    build_fct_steps,
)
from mtkgui.engine.wav_util import trim_wav, wav_duration_s  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    BT_PROBE_CMD,
    DEFAULT_TONE_WAV,
    FCTTestConfigPanel,
    _ToneRangeSlider,
    classify_bt_driver_probe,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_wav(path: Path, seconds: float, rate: int = 8000) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x10\x00" * int(rate * seconds))
    return path


# ------------------------------------------------------------- wav helpers
def test_wav_duration_reads_the_header(tmp_path):
    src = _make_wav(tmp_path / "tone.wav", 2.0)
    assert wav_duration_s(str(src)) == pytest.approx(2.0, abs=0.01)
    assert wav_duration_s(str(tmp_path / "missing.wav")) is None
    assert wav_duration_s("") is None


def test_trim_wav_cuts_the_requested_segment(tmp_path):
    src = _make_wav(tmp_path / "tone.wav", 1.0)
    out = trim_wav(str(src), 0.25, 0.75)
    assert out and Path(out).exists()
    assert wav_duration_s(out) == pytest.approx(0.5, abs=0.01)
    Path(out).unlink()
    assert trim_wav(str(src), 0.5, 0.5) is None


# --------------------------------------------------------------- editor UI
def test_tone_editor_parses_total_and_resets_the_range(qapp, tmp_path):
    """A new wav -> total label + slider span = the WHOLE file."""
    panel = FCTTestConfigPanel()
    src = _make_wav(tmp_path / "custom.wav", 2.0)
    panel.bt_tone_file.setText(str(src))
    panel._refresh_tone_range()
    assert "custom.wav" in panel.bt_tone_total.text()
    assert "2.0 s" in panel.bt_tone_total.text()
    assert panel.bt_tone_range.total() == pytest.approx(2.0)
    assert (panel.bt_tone_range.start_s(),
            panel.bt_tone_range.end_s()) == (0.0, 2.0)
    assert "Start 0.0 s" in panel.bt_tone_segment.text()

    # an unreadable file -> explicit "length unknown", no crash
    panel.bt_tone_file.setText(str(tmp_path / "nope.wav"))
    panel._refresh_tone_range()
    assert "length unknown" in panel.bt_tone_total.text()


def test_tone_slider_enforces_start_le_end(qapp):
    slider = _ToneRangeSlider(6.0)
    slider.set_values(1.0, 4.0)
    assert (slider.start_s(), slider.end_s()) == (1.0, 4.0)
    # a reversed pair clamps the End onto the Start
    slider.set_values(4.0, 1.0)
    assert slider.end_s() == 4.0
    # an over-long End is clamped into the file length
    slider.set_values(2.0, 99.0)
    assert slider.end_s() == 6.0
    # a new file resets the segment to the whole file
    slider.set_total(3.0)
    assert (slider.start_s(), slider.end_s()) == (0.0, 3.0)


def test_tone_range_change_updates_the_segment_label(qapp):
    panel = FCTTestConfigPanel()
    panel._on_tone_range_changed(1.5, 4.5)
    assert "Start 1.5 s" in panel.bt_tone_segment.text()
    assert "End 4.5 s" in panel.bt_tone_segment.text()
    assert "3.0 s played" in panel.bt_tone_segment.text()


def test_preview_toggle_plays_the_segment_then_resets_the_meter(
        qapp, tmp_path, monkeypatch):
    """Preview is a toggle: play() gets the segment bounds, the second
    click stop()s it and the level meter returns to 0."""
    panel = FCTTestConfigPanel()
    src = _make_wav(tmp_path / "tone.wav", 2.0)
    panel.bt_tone_file.setText(str(src))
    panel._refresh_tone_range()
    panel.bt_tone_range.set_values(0.5, 1.5)

    calls: list = []
    state = {"playing": False}

    monkeypatch.setattr(panel._tone_preview, "is_playing",
                        lambda: state["playing"])
    monkeypatch.setattr(
        panel._tone_preview, "play",
        lambda path, start, end: calls.append(("play", path, start, end)))
    monkeypatch.setattr(panel._tone_preview, "stop",
                        lambda: (calls.append(("stop",)),
                                 panel.bt_tone_level.setValue(0),
                                 state.__setitem__("playing", False)))

    panel._on_bt_tone_preview()
    assert calls == [("play", str(src), 0.5, 1.5)]

    state["playing"] = True
    panel.bt_tone_level.setValue(80)
    panel._on_bt_tone_preview()
    assert calls[-1] == ("stop",)
    assert panel.bt_tone_level.value() == 0

    # a missing file never calls play()
    calls.clear()
    panel.bt_tone_file.setText(str(tmp_path / "gone.wav"))
    panel._on_bt_tone_preview()
    assert calls == []
    assert "WAV not found" in panel.bt_tone_preview_status.text()


def test_preview_uses_the_bundled_default_tone(qapp):
    panel = FCTTestConfigPanel()
    assert panel.bt_tone_file.text() == DEFAULT_TONE_WAV
    assert panel.bt_tone_preview_btn.text() == "Preview (local)"
    assert panel.bt_tone_level.value() == 0


# ------------------------------------------------------------ step params
def test_tone_step_publishes_wav_and_range_without_timeout():
    cfg = FctTestConfig(
        dut_type="linux",
        bluetooth=BluetoothCfg(
            tone_enabled=True,
            test_tone="resources/tones/tone_2khz_6s.wav",
            tone_start_s=2.0, tone_end_s=5.0))
    steps = [s for s in build_fct_steps(cfg, channel_key="ser1")
             if "Tone" in s.name]
    assert len(steps) == 1
    step = steps[0]
    assert step.step_type == STEP_EXTERNAL_TOOL
    assert step.timeout_s == 0.0
    rf = step.params["fct_rf"]
    assert rf["mode"] == "a2dp_sink"
    assert rf["wav"] == "resources/tones/tone_2khz_6s.wav"
    assert (rf["tone_start_s"], rf["tone_end_s"]) == (2.0, 5.0)
    # no automatic confirm anywhere in the params or step names
    assert "audio_confirm" not in step.params
    assert "audio_confirm" not in rf
    assert not any("Confirm" in s.name for s in steps)


def test_tone_validate_rejects_a_reversed_range():
    cfg = FctTestConfig(
        dut_type="linux",
        bluetooth=BluetoothCfg(tone_enabled=True,
                               tone_start_s=5.0, tone_end_s=2.0))
    errors = cfg.validate()
    assert any("Start must be <= End" in e for e in errors)


# --------------------------------------------------------- legacy YAML
def test_legacy_audio_confirm_and_tone_duration_are_tolerated():
    node = {"dut_type": "linux",
            "bluetooth": {"enabled": True, "tone_enabled": True,
                          "audio_confirm": True, "tone_timeout": 30,
                          "tone_duration_s": 5}}
    cfg = FctTestConfig.from_dict(node)
    assert cfg.bluetooth.tone_end_s == 5.0          # mapped, not dropped
    out = cfg.to_dict()["bluetooth"]
    assert "audio_confirm" not in out
    assert "tone_timeout" not in out
    assert "tone_duration_s" not in out
    assert (out["tone_start_s"], out["tone_end_s"]) == (0.0, 5.0)


def test_legacy_yaml_roundtrips_through_the_panel_without_new_keys(qapp):
    yaml_text = """
fct_test_config:
  dut_type: linux
  bluetooth:
    enabled: true
    tone_enabled: true
    audio_confirm: true
    tone_timeout: 30
"""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": yaml_text})
    out = panel.values()["fct_test_config_yaml"]
    assert "audio_confirm" not in out
    assert "tone_timeout" not in out


# ------------------------------------------------- DUT BT driver probe
def test_classify_bt_driver_probe_three_states():
    # the command echo carries the done marker once, the shell output the
    # second time -> >= 2 proves the DUT shell answered
    echo = "echo __BT_PING__; ...; echo __BT_DONE__\n"
    assert classify_bt_driver_probe(
        echo + "__BT_PING__\nhci0: Type: Primary Bus: UART\n"
        "__BT_DONE__\n")[0] == "OK"
    state, msg = classify_bt_driver_probe(
        echo + "__BT_PING__\n__BT_DONE__\n")
    assert state == "needs-load" and "Console_serial" in msg
    state, msg = classify_bt_driver_probe("")
    assert state == "FAIL" and "did not answer" in msg


def test_probe_command_has_markers_and_bt_checks():
    assert "__BT_PING__" in BT_PROBE_CMD
    assert "__BT_DONE__" in BT_PROBE_CMD
    assert "hci" in BT_PROBE_CMD


def test_probe_requires_a_console_port(qapp):
    panel = FCTTestConfigPanel()
    panel.console_port.setCurrentText("")
    panel._on_bt_dut_probe()
    assert "Set the Console Port first" in panel.bt_dut_probe_status.text()
    assert not hasattr(panel, "_bt_probe_worker")


def test_probe_result_colors_the_three_states(qapp):
    panel = FCTTestConfigPanel()
    for state, color in (("OK", "#059669"),
                         ("needs-load", "#b45309"),
                         ("FAIL", "#b91c1c")):
        panel._on_bt_probe_result(state, "detail")
        assert panel.bt_dut_probe_status.text().startswith(state)
        assert color in panel.bt_dut_probe_status.styleSheet()
