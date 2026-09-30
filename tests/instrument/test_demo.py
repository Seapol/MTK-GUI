# -*- coding: utf-8 -*-
"""Unit tests for the headless demo script (src/instrument/demo.py).

Covers the station-YAML parsing, TP->channel mapping, ICT judging
logic, the simulated executors and the full end-to-end simulated run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# make the repo root AND src/instrument importable
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_INSTRUMENT = _REPO_ROOT / "src" / "instrument"
for _p in (_REPO_ROOT, str(_SRC_INSTRUMENT)):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import demo  # noqa: E402
from mtkgui.drivers.base import Status  # noqa: E402


# -- station YAML parsing ---------------------------------------------------

STATION_YAML = """\
project:
  software: mtk-gui v2.0.0
product:
  part_number: TEST-BOARD
  core_id: '99999'
  batch: Dev
test_workflow:
  ict_test_cases:
  - name: Init Instruments
    kind: op
    enable: true
    threshold_min: '-'
  - name: 'Impedance Shorts: VDD_3V3 (TP_P01)'
    enable: true
    unit: ohm
    threshold_min: '1.5'
  - name: 'Impedance Shorts: VDD_1V8 (TP_P41)'
    enable: false
    threshold_min: '1.5'
  - name: 'Power Voltages: VDD_3V3 (TP_P02)'
    enable: true
    unit: V
    threshold_min: '3.267'
    threshold_max: '3.333'
  - name: 'Power Voltages: Broken (TP_P03)'
    enable: true
    threshold_min: '-'      # placeholder -> skipped
    threshold_max: '-'
  - name: 'Clock Hz: RTC (TP_C01)'
    enable: true
    threshold_min: '32766.4'
    threshold_max: '32769.6'
"""


@pytest.fixture
def station_config(tmp_path: Path) -> dict:
    """Write the mini station YAML and return the parsed demo config."""
    path = tmp_path / "station.yaml"
    path.write_text(STATION_YAML, encoding="utf-8")
    return demo.load_station_config(str(path))


def test_load_station_config_parses_points(station_config: dict) -> None:
    """Impedance / voltage / clock cases map to the right methods."""
    points = station_config["ict_points"]
    methods = [p["method"] for p in points]
    assert methods == ["resistance", "dcv", "freq"]
    assert points[0] == {"name": "TP_P01", "method": "resistance",
                         "channel": "101", "min_ohm": 1.5}
    assert points[1]["min_v"] == pytest.approx(3.267)
    assert points[1]["max_v"] == pytest.approx(3.333)
    assert points[2]["min_hz"] == pytest.approx(32766.4)


def test_load_station_config_skips_disabled_and_placeholders(
        station_config: dict) -> None:
    """enable=false cases and '-' thresholds are excluded."""
    names = [p["name"] for p in station_config["ict_points"]]
    assert "TP_P41" not in names          # enable: false
    assert "TP_P03" not in names          # '-' placeholder thresholds
    assert "Init Instruments" not in names


def test_load_station_config_keeps_fct_defaults(station_config: dict) -> None:
    """WiFi / Bluetooth sections fall back to the embedded defaults."""
    assert station_config["wifi"]["ssid"] == "MYDUT-AP"
    assert station_config["bluetooth"]["bt_type"] == "ble"


def test_load_station_config_product_info(station_config: dict) -> None:
    """Product block is carried through for the banner print."""
    assert station_config["station"]["product"]["part_number"] == "TEST-BOARD"


# -- TP -> channel mapping ---------------------------------------------------

@pytest.mark.parametrize("tp,channel", [
    ("TP_P01", "101"),
    ("TP_P40", "140"),
    ("TP_P41", "201"),
    ("TP_P80", "240"),
])
def test_tp_to_channel_mapping(tp: str, channel: str) -> None:
    """Slot1 covers TP_P01-40 (CH101-140), slot2 TP_P41-80 (CH201-240)."""
    assert demo._tp_to_channel(tp) == channel


def test_num_placeholder() -> None:
    """'-' / garbage thresholds parse to None instead of raising."""
    assert demo._num("1.5") == 1.5
    assert demo._num("-") is None
    assert demo._num("—") is None
    assert demo._num(None) is None


# -- simulated SCPI generation -----------------------------------------------

def test_build_sim_scpi_covers_all_points(station_config: dict) -> None:
    """Every derived point has a scripted reply for its exact command."""
    script = demo.build_sim_scpi(station_config["ict_points"])
    assert "MEAS:RES? AUTO,DEF,(@101)" in script
    assert "MEAS:VOLT:DC? AUTO,DEF,(@102)" in script
    assert "MEAS:FREQ? DEF,DEF,(@1201)" in script


# -- ICT judging -------------------------------------------------------------

def test_run_ict_pass(station_config: dict) -> None:
    """All simulated readings sit inside their limits -> overall OK."""
    overall, results = demo.run_ict(station_config)
    assert overall is Status.OK
    assert len(results) == 3


def test_run_ict_fail_on_open_input(station_config: dict) -> None:
    """An overload reading (9.9e37, open probe) fails the sequence."""
    points = station_config["ict_points"]
    script = demo.build_sim_scpi(points)
    script["MEAS:RES? AUTO,DEF,(@101)"] = "+9.90000000E+37"
    config = dict(station_config)
    config["ict_points"] = points

    import demo as demo_mod
    original = demo_mod.build_sim_scpi
    demo_mod.build_sim_scpi = lambda pts: script
    try:
        overall, results = demo_mod.run_ict(config)
    finally:
        demo_mod.build_sim_scpi = original
    assert overall is Status.FAIL
    assert results[0].value == pytest.approx(9.9e37)


# -- executors / helpers -------------------------------------------------------

def test_build_wifi_executor_scripted() -> None:
    """Scripted executor answers netsh / ping / iperf probes."""
    executor = demo.build_wifi_executor(real=False)
    outcome = executor.run(["netsh", "wlan", "show", "networks"], 5.0)
    assert "MYDUT-AP" in outcome.stdout
    outcome = executor.run(["ping", "-n", "4", "192.168.4.1"], 5.0)
    assert "Reply from" in outcome.stdout
    outcome = executor.run(["iperf3", "-c", "x"], 5.0)
    assert "bits_per_second" in outcome.stdout


def test_build_wifi_executor_real(monkeypatch) -> None:
    """--real selects the subprocess executor."""
    from mtkgui.drivers.rf_common import SubprocessExecutor
    executor = demo.build_wifi_executor(real=True)
    assert isinstance(executor, SubprocessExecutor)


def test_demo_bt_executor_content_match() -> None:
    """BT executor routes probes by PowerShell payload substring."""
    executor = demo.DemoBTExecutor()
    outcome = executor.run(["powershell", "-c", "AdvertisementWatcher"], 5.0)
    assert "AABBCCDDEEFF" in outcome.stdout
    outcome = executor.run(["powershell", "-c", "FAILURES="], 5.0)
    assert "ATTEMPTS=20" in outcome.stdout
    outcome = executor.run(["powershell", "-c", "unknown probe"], 5.0)
    assert outcome.stdout == ""


def test_verdict_text() -> None:
    """Spec Status renders as station PASS/FAIL wording."""
    assert demo.verdict_text(Status.OK) == "PASS"
    assert demo.verdict_text(Status.FAIL) == "FAIL"


# -- end-to-end simulated run ---------------------------------------------------

def test_main_end_to_end_with_station_yaml(station_config: dict,
                                           tmp_path: Path,
                                           capsys) -> None:
    """Full simulated run with the mini station YAML -> exit 0."""
    # rewrite the YAML so main() re-parses it (fixture only parsed it)
    path = tmp_path / "station.yaml"
    path.write_text(STATION_YAML, encoding="utf-8")
    sys.argv = ["demo.py", "--config", str(path)]
    try:
        exit_code = demo.main()
    finally:
        sys.argv = ["demo.py"]
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "OVERALL VERDICT: PASS" in output
    assert "TEST-BOARD" in output
