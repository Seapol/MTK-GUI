#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the ICT demo project YAML for 96624 (NXP S32N79) - v1.0.1.

ICT-only demo (no FCT), Virtual mode (no physical instruments):

  * parse ``NET-96624_A.net`` (block-02 core) into Power / Clock / GPIO;
  * auto-allocate the Channel Allocation resources (block 05) to FULL
    capacity - the pool is filled then the excess nets are left alone:
      - Power: DAQM908A sense channels (R-GND + voltage, same
        channel) for up to 80 nets, and the 12 U2355A AI power-rail
        channels for the FIRST 12 power nets (the DAQ AI up-sequence);
      - Clock: the 3 SE clock channels (DAQM907A TOT 0-100 kHz +
        U2355A CTR0/CTR1) filled in LOW-SPEED-first order (the
        32.768 kHz RTC crystal nets win the totalizer);
      - GPIO: the 24 U2355A DIO channels (Control IO);
  * clock measurement targets 32.768 kHz (low-speed), every clock row
    gets Expected=32768.0 Hz with +/-50 ppm limits;
  * ICT-only: fct_build disabled and the Overall Flow FCT stage off;
  * the Test Work Flow DAQ AI rails = the 12 U2355A AI channels.

The YAML is written into the project folder as
``A-96624_ICT_Demo_v1.0.1.yaml`` (part ``A-96624`` from the board path,
mirroring the FCT demo ``<Part>_<Type>_Demo_v<ver>.yaml`` naming), then
verified two ways:
  1. reload through ``project_config.load_config`` (the GUI loader);
  2. run the FULL flow headless in Virtual mode via the real
     ``TestRunner.run_demo`` and check every step PASSes.

Usage:
    python scripts/build_96624_ict_demo_yaml.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from mtkgui.gui.yamlbuild.channel_allocation import (  # noqa: E402
    CLOCK_BANDS,
    CLOCK_CHANNELS,
    DAQM908A_SENSE_CHANNELS,
    UNSET,
    U2355A_AI_CHANNELS,
    GPIO_DIO_CHANNELS,
    AllocatedRow,
    ChannelAllocationData,
    rows_from_testable,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel  # noqa: E402
from mtkgui.ict.netparse import parse_testable_nets  # noqa: E402

CORE = "96624"
PART = "A-96624"
BATCH = "EVT (Proto-1)"
VERSION = "1.0.1"
OUT_DIR = ROOT / "projects" / CORE
OUT_NAME = f"{PART}_ICT_Demo_v{VERSION}.yaml"

#: the clock measurement targets 32.768 kHz (low-speed RTC clock)
CLOCK_HZ = 32768.0
CLOCK_TOL_PPM = 50.0
_CLOCK_LO = f"{CLOCK_HZ * (1 - CLOCK_TOL_PPM * 1e-6):.1f}"
_CLOCK_HI = f"{CLOCK_HZ * (1 + CLOCK_TOL_PPM * 1e-6):.1f}"
_CLOCK_EXP = f"{CLOCK_HZ:.1f}"

#: low-speed clock preference: the 32.768 kHz slow crystal oscillator
#: (SXOSC) first, then crystal pins (XTAL/EXTAL); power-rail pins of a
#: clock chip (SI5332_CLK_VDD*/VIO) are NOT real clock signals
def _clock_rank(net: str) -> int:
    n = (net or "").upper()
    if ("VDD" in n or "VIO" in n or "VCC" in n or "VDDA" in n
            or n.startswith("SI5332")):
        return 2            # clock-chip power rails -> not a real clock
    if "SXOSC" in n:
        return 0            # slow crystal oscillator (32.768 kHz)
    if "XTAL" in n or "EXTAL" in n:
        return 1            # crystal pins (lower speed than comm clocks)
    return 2

MAX_GPIO_ROWS = 24          # U2355A DIO pool (Control IO)


def best_test_point(members):
    """TP probe pin when present, else the first pin (auto rule)."""
    members = [m for m in (members or []) if m]
    if not members:
        return UNSET
    probe = next((m for m in members
                  if m.upper().startswith("TP")), None)
    return probe or members[0]


def board_part(net_text: str, core: str) -> str:
    """Part number from the NET header board path (LAY-96624_A.brd)."""
    m = re.search(r"(?:LAY|BRD)-(\w+)_([A-Za-z0-9]+)\.brd", net_text)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return f"PROTO-{core}"


def build_testable(result) -> dict:
    """The single testable-net data source (name -> category/members)."""
    testable = {}
    for cat, records in (("Power", result.power),
                         ("Clock", result.clock),
                         ("GPIO", result.gpio)):
        for rec in records:
            testable[rec.name] = {"category": cat,
                                  "members": list(rec.members)}
    return testable


def build_allocation(testable: dict) -> ChannelAllocationData:
    """Fill every resource pool to capacity; excess nets left alone."""
    alloc = ChannelAllocationData()
    # power: sense channels (R-GND == voltage == same channel) +
    # the 12 U2355A AI power-rail channels
    sense = iter(DAQM908A_SENSE_CHANNELS)
    rails = iter(U2355A_AI_CHANNELS)
    power = rows_from_testable(testable, "power")
    for row in power:
        row.test_point = best_test_point(
            testable.get(row.net, {}).get("members"))
        try:
            channel = next(sense)
            row.impedance = channel
            row.voltage = channel
            row.power_rails = next(rails)
        except StopIteration:
            pass                        # sense / AI pool exhausted
    alloc.power = power

    # clock: LOW-SPEED first so the 32.768 kHz RTC wins the totalizer
    # (stable sort: the crystal/RTC markers first, parse order kept)
    clocks = sorted(rows_from_testable(testable, "clock"),
                    key=lambda r: _clock_rank(r.net))
    clk_iter = iter(CLOCK_CHANNELS)
    for row in clocks:
        row.test_point = best_test_point(
            testable.get(row.net, {}).get("members"))
        try:
            row.se_clock_hz = next(clk_iter)
            row.band = CLOCK_BANDS.get(row.se_clock_hz, UNSET)
        except StopIteration:
            pass                        # 3 clock channels = full
    alloc.clock = clocks

    # gpio: 24 U2355A DIO channels
    gpio = rows_from_testable(testable, "gpio")[:MAX_GPIO_ROWS]
    dio = iter(GPIO_DIO_CHANNELS)
    for row in gpio:
        row.test_point = best_test_point(
            testable.get(row.net, {}).get("members"))
        try:
            row.dio_channel = next(dio)
        except StopIteration:
            pass
    alloc.gpio = gpio
    return alloc


def rail_nets(alloc: dict) -> list[str]:
    """The DAQ AI power-rails (ordered by U2355A AI channel number)."""
    derived = []
    for row in (alloc or {}).get("power") or []:
        channel = str(row.get("power_rails") or "")
        net = str(row.get("net") or "").strip()
        if not net or "U2355A AI" not in channel:
            continue
        digits = "".join(c for c in channel if c.isdigit())
        derived.append((int(digits) if digits else 999, net))
    derived.sort(key=lambda item: item[0])
    return [net for _ch, net in derived]


def clock_nets(alloc: dict) -> list[str]:
    """The clock nets holding an SE clock channel (3 max)."""
    return [str(row.get("net") or "").strip()
            for row in (alloc or {}).get("clock") or []
            if str(row.get("se_clock_hz") or "").strip() not in ("", UNSET)]


def build_model(net_path: Path, spf_path) -> YamlBuildModel:
    net_text = net_path.read_text(encoding="utf-8", errors="replace")
    result = parse_testable_nets(net_text)
    testable = build_testable(result)

    alloc = build_allocation(testable)
    model = YamlBuildModel()
    model.enable_all()
    model.set_plan_version(VERSION)

    part = board_part(net_text, CORE)
    spf_name = spf_path.name if spf_path else ""
    model.set_params("design_input", {
        "product_id": CORE, "part_number": part,
        "sw_version": "1.0.0", "hw_version": "1.0.0",
        "batch": BATCH,
        "spf_file": spf_name, "net_file": net_path.name,
    })
    model.set_params("parse_ict", {"netlist_file": net_path.name})
    # Virtual mode: the physical VISA addresses are ignored at run time
    # (the simulated rack drives the measurements); kept as placeholders
    model.set_params("instruments", {
        "psu_visa": "TCPIP0::192.168.1.20::inst0",
        "daq_visa": "GPIB0::9::INSTR",
        "dmm_visa": "",
        "channel_alloc": "",
        "self_test": "true",
    })
    model.imported["net"] = {"file": net_path.name, "raw": net_text}
    model.imported["testable_nets"] = testable
    model.set_channel_allocation(alloc.to_dict())

    # rails / clocks / gpios module params (legacy no-UI mirrors)
    rails = rail_nets(alloc.to_dict())
    clocks = clock_nets(alloc.to_dict())
    gpio_nets = [r.net for r in alloc.gpio]
    model.set_params("rails", {
        "sequence": "\n".join(f"{net}:{0.1 * i:.1f}"
                              for i, net in enumerate(rails)),
        "sample_rate_hz": "200",
        "pre_trigger_s": "-0.5",
        "post_trigger_s": "6.0",
    })
    model.set_params("clocks", {
        # low-speed 32.768 kHz clock measurement (user direction)
        "clocks": "\n".join(f"{net}:{int(CLOCK_HZ)}:2"
                            for net in clocks) or "CLK1:32768:2",
    })
    model.set_params("gpios", {
        "groups": "\n".join(
            f"{net}:{best_test_point(testable[net]['members'])}:in:none"
            for net in gpio_nets),
    })
    # ICT-only plan: the FCT build stays disabled
    model.set_enabled("fct_build", False)
    return model


def build_sequence(model: YamlBuildModel) -> list[tuple]:
    """The ICT test rows (R-GND -> voltage -> clock) with the
    correct limits: auto tolerance for power voltage / R-GND, and
    an explicit 32.768 kHz (+/-50 ppm) for the clock rows."""
    from mtkgui.gui.yamlbuild.ict_sequence import (
        auto_fill_limits,
        generate_sequence,
    )
    rows = auto_fill_limits(generate_sequence(model.allocated_testable()))
    out = []
    for step in rows:
        kind, name, unit, _exp, _lo, _hi = step
        if "Clock Hz" in name:
            out.append((kind, name, unit, _CLOCK_EXP, _CLOCK_LO, _CLOCK_HI))
        else:
            out.append(step)
    return out


def make_window():
    from PySide6.QtWidgets import QApplication
    from mtkgui.main_window import MainWindow
    from mtkgui.permissions import ROLE_SUPERVISOR
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("build_96624_ict_demo")
    return MainWindow(role=ROLE_SUPERVISOR, mode="Virtual")


def apply_to_window(window, model) -> None:
    """Push the headless-built model into the real pages (the same
    state the GUI holds after the user walks through the blocks, using
    the SAME path as 'Load current yaml')."""
    page = window.workflow_page
    page_model = window.yaml_build_page.model
    page_model.apply_state(model.to_dict())

    page.core_edit.setText(CORE)
    page.part_edit.setText(PART)
    page.batch_edit.setText(BATCH)
    window._on_yaml_apply_committed = lambda: None   # no save dialogs

    # power-rails capture (12) must exist BEFORE the sequence builder
    # inserts the DAQ AI row
    from mtkgui.gui.yamlbuild.ict_sequence import (
        daq_ai_rail_count,
        standard_ict_sequence,
    )
    window._sync_rails_to_workflow()
    # the canonical sequence (standard operations + tests + the derived
    # DAQ AI rail capture): the YAML carries the SAME sequence the
    # Build ICT dialog emits, so the demo plan stays complete
    window._fill_ict_sequence(standard_ict_sequence(
        build_sequence(page_model),
        daq_ai_rail_count(page_model.channel_allocation)))
    # ICT-only: no FCT cases + disable the Overall Flow FCT stage
    page.load_fct_cases([])
    page._overall_en[1] = False
    window.yaml_build_page.refresh_all()


def run_virtual_demo(window) -> str:
    """Run the full flow headless in Virtual mode and return the
    Overall Result plus a per-step FAIL summary."""
    page = window.workflow_page
    runner = page._runner
    runner.run_demo()
    verdict = runner.verdict() or "—"
    failures = []
    for kind, rows, steps in (("ict", page.ict_enables, page.ict_steps),):
        for r, enabled in enumerate(rows):
            if not enabled:
                continue
            text = runner._results.get((kind, r), "")
            if text in ("FAIL", "Error"):
                failures.append(f"{kind}#{r} {text}: {steps[r][1]}")
    return verdict, failures


def main() -> int:
    folder = OUT_DIR
    net_path = sorted(folder.glob("*.net")) or sorted(folder.glob("*.net.txt"))
    spf_path = sorted(folder.glob("*.pdf"))
    net = net_path[0] if net_path else None
    spf = spf_path[0] if spf_path else None
    if net is None:
        print(f"[FAIL] no NET file under {folder}")
        return 1

    from mtkgui import project_config

    model = build_model(net, spf)
    errors = model.validate_all()
    if errors:
        print("[FAIL] model invalid:")
        for e in errors[:10]:
            print("   -", e)
        return 1

    window = make_window()
    apply_to_window(window, model)

    config = project_config.build_config(
        window.workflow_page, window.equipment_page,
        window.yaml_build_page.model.to_dict())
    out_path = OUT_DIR / OUT_NAME
    project_config.save_config(config, out_path)

    # verify 1: reload through the real project loader
    back = project_config.load_config(out_path)
    probe = make_window()
    project_config.apply_config(
        back, probe.workflow_page, probe.equipment_page,
        probe.yaml_build_page.model)
    probe.workflow_page.set_mode("Virtual")
    cases = back.get("test_workflow", {}).get("ict_test_cases", [])
    rails = back.get("test_workflow", {}).get(
        "power_rails_up_sequence", {}).get("rails", [])
    fct_cases = back.get("test_workflow", {}).get("fct_test_cases", [])
    print(f"[OK] wrote {out_path}")
    print(f"     ict cases: {len(cases)}, fct cases: {len(fct_cases)}, "
          f"rails: {len(rails)}")
    print(f"     power channels: "
          f"{len(probe.yaml_build_page.model.channel_allocation.get('power') or [])}, "
          f"clock channels: "
          f"{len(probe.yaml_build_page.model.channel_allocation.get('clock') or [])}, "
          f"gpio channels: "
          f"{len(probe.yaml_build_page.model.channel_allocation.get('gpio') or [])}")

    # verify 2: run the full flow headless in Virtual mode
    verdict, failures = run_virtual_demo(probe)
    n_pass = sum(1 for c in cases if c.get("enable", True))
    print(f"[RUN] Overall Result: {verdict}")
    if failures:
        print(f"[RUN] failures ({len(failures)}):")
        for line in failures[:20]:
            print("   -", line)
        return 1
    print(f"[RUN] all {n_pass} enabled ICT steps PASS (virtual)")
    return 0


if __name__ == "__main__":
    sys.exit(main())