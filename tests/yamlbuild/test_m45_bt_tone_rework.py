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

import yaml  # noqa: E402

from mtkgui.engine.fct_test_config import (  # noqa: E402
    BluetoothCfg,
    FctTestConfig,
    STEP_EXTERNAL_TOOL,
    STEP_TYPE_BT_TONE,
    build_fct_steps,
    console_command_for_label,
)
from mtkgui.engine.wav_util import trim_wav, wav_duration_s  # noqa: E402
from mtkgui.gui.yamlbuild.FCTTestConfigWidget import (  # noqa: E402
    BT_PROBE_CMD,
    DEFAULT_TONE_WAV,
    FCTTestConfigPanel,
    _BtDriverProbeWorker,
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


def test_tone_slider_reads_the_total_length_from_the_wav_header(tmp_path):
    """M50: the per-test dialog builds its slider from the wav header -
    an unreadable file leaves the length at the fallback, no crash."""
    src = _make_wav(tmp_path / "custom.wav", 2.0)
    assert wav_duration_s(str(src)) == pytest.approx(2.0, abs=0.01)
    slider = _ToneRangeSlider(wav_duration_s(str(src)) or 6.0)
    slider.set_values(0.0, 2.0)
    assert slider.total() == pytest.approx(2.0)
    assert (slider.start_s(), slider.end_s()) == (0.0, 2.0)
    # missing file -> header unknown -> the 6 s fallback stays
    assert wav_duration_s(str(tmp_path / "nope.wav")) is None
    slider = _ToneRangeSlider(wav_duration_s(str(tmp_path / "nope.wav"))
                              or 6.0)
    assert slider.total() == pytest.approx(6.0)


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
    """M50: a legacy tone config imports into one BT_Tone step row and
    re-emits the new schema WITHOUT the retired keys."""
    yaml_text = """
fct_test_config:
  dut_type: linux
  bluetooth:
    enabled: true
    tone_enabled: true
    audio_confirm: true
    tone_timeout: 30
    tone_duration_s: 5
"""
    panel = FCTTestConfigPanel()
    panel.set_values({"fct_test_config_yaml": yaml_text})
    out = panel.values()["fct_steps_yaml"]
    assert "audio_confirm" not in out
    assert "tone_timeout" not in out
    steps = ((yaml.safe_load(out) or {}).get("fct") or {}).get("steps") or []
    assert [s["type"] for s in steps] == [STEP_TYPE_BT_TONE]
    # the retired tone_duration_s maps to the End segment
    assert float(steps[0]["end_s"]) == 5.0


def test_tone_row_summary_falls_back_to_the_bundled_default_tone(qapp):
    """The default tone row names the bundled wav in its summary."""
    panel = FCTTestConfigPanel()
    cmd = console_command_for_label(STEP_TYPE_BT_TONE)
    assert panel._rf_summary(cmd) == "tone_1khz_6s.wav, 0.0-6.0s"
    assert DEFAULT_TONE_WAV.endswith("tone_1khz_6s.wav")


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


def test_probe_worker_reports_fail_when_the_console_is_unavailable(qapp):
    """M50: the read-only probe worker never crashes - an unusable
    console (or missing pyserial) becomes an explicit FAIL."""
    worker = _BtDriverProbeWorker("/dev/does-not-exist", 115200)
    seen = {}
    worker.result.connect(lambda state, msg: seen.update(
        {"state": state, "msg": msg}))
    worker.run()
    assert seen["state"] == "FAIL"
    assert "probe failed" in seen["msg"] or "did not answer" in seen["msg"]
