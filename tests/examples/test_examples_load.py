"""Shared examples stay loadable and stay honest.

Both example plans are shipped as reference material: a reader opens them in
the GUI, and the numbers quoted in their READMEs must match the file. These
tests fail when an example drifts (a row re-enabled, a limit-less row losing
its reason, a bucket count changing) so the docs cannot quietly go stale.
"""
from pathlib import Path

import pytest

from mtkgui import project_config

REPO = Path(__file__).resolve().parents[2]
ICT = REPO / "examples" / "ict_96624" / "A-96624_ICT_Demo_v1.0.1.yaml"
FCT = (REPO / "examples" / "fct_frdm_imx93"
       / "FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev_1.3.1.yaml")

LIMITLESS = ("Power Voltage - VBAT_SENSE",
             "Power Voltage - VCC_OSC_AUXCLKIN",
             "Power Voltage - VDD2_LP5X")


@pytest.fixture(scope="module")
def ict_cfg():
    return project_config.load_config(ICT)


@pytest.fixture(scope="module")
def fct_cfg():
    return project_config.load_config(FCT)


def test_ict_example_exists():
    assert ICT.is_file(), "the ICT example plan is missing"


def test_ict_row_count_and_disabled_reasons(ict_cfg):
    cases = ict_cfg["test_workflow"]["ict_test_cases"]
    tests = [c for c in cases if c.get("kind") == "test"]
    # 34 rows = 27 test rows + 7 standard operations
    assert len(cases) == 34
    assert len(tests) == 27
    disabled = [c for c in tests if not c.get("enable", True)]
    assert len(disabled) == 3
    assert {c["name"] for c in disabled} == set(LIMITLESS)
    for case in disabled:
        # a disabled row must say why - never a silent skip
        assert "No limit sourced" in str(case.get("comment") or "")


def test_ict_example_declares_the_psu_setpoints(ict_cfg):
    params = ((ict_cfg.get("equipment") or {}).get("psu") or {}).get(
        "params") or {}
    assert float(params["Voltage set (V)"]) == pytest.approx(12.0)
    assert float(params["Current limit (A)"]) == pytest.approx(3.0)


def test_ict_example_carries_twelve_rails(ict_cfg):
    rails = ict_cfg["test_workflow"]["power_rails_up_sequence"]["rails"]
    assert len(rails) == 12
    # the three limit-less rails carry nominal 0.0 - the rails chart draws
    # them flat until a limit is authored, which is visible on purpose
    named = [r for r in rails if float(r.get("nominal_v") or 0.0) > 0.0]
    assert len(named) == 9


def test_fct_example_exists():
    assert FCT.is_file(), "the FCT example plan is missing"


def test_fct_row_count_and_closed_rows(fct_cfg):
    wf = fct_cfg["test_workflow"]
    rows = wf["fct_test_cases"]
    assert len(rows) == 45
    closed = {c["name"]: c for c in rows if not c.get("enable", True)}
    for name in ("Wi-Fi iPerf Throughput (iperf3)", "BT L2CAP ping",
                 "Pull FAT log"):
        assert name in closed, f"{name} must stay in the plan, disabled"
    stages = [s.get("stage") for s in wf["overall_flow"]]
    assert stages == ["ICT", "FCT"]


def test_fct_example_declares_the_rssi_budget(fct_cfg):
    rows = fct_cfg["test_workflow"]["fct_test_cases"]
    rssi = [c for c in rows
            if c["name"] == "Bluetooth RSSI" and c.get("enable", True)]
    assert rssi, "the Bluetooth RSSI row must stay enabled"
    for case in rssi:
        assert int(case["timeout_ms"]) >= 35000
