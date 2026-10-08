#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build one project YAML per project folder under ``projects/``.

Every folder is named by its Core ID and carries the raw design
inputs (SPF + NET).  The script runs the SAME headless pipeline the
GUI uses:

  1. parse the NET file (parse_testable_nets - the block-02 core),
  2. auto-allocate the Channel Allocation resources (block 05 rules),
  3. fill the Yaml Build model (design input / rails / clocks / gpios),
  4. apply the model into a real (offscreen) MainWindow and save via
     project_config.build_config - the SAME project-config format the
     GUI's File > Save as Yaml writes (product / equipment / console /
     test_workflow / yaml_build_state), so File > Load Yaml restores
     everything (root-cause fix: the publish() plan format is the
     archive shape and does NOT carry the workflow/equipment pages).

Usage:
    python scripts/build_project_yaml.py [projects_dir]

The YAML is written INTO each project folder
(<part>_<core>_<batch>_rev<ver>.yaml, the GUI suggested name) and
verified by loading it back through project_config.load_config.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from mtkgui.gui.yamlbuild.channel_allocation import (
    CLOCK_BANDS,
    CLOCK_CHANNELS,
    DAQM908A_SENSE_CHANNELS,
    UNSET,
    U2355A_AI_CHANNELS,
    ChannelAllocationData,
    rows_from_testable,
)
from mtkgui.gui.yamlbuild.model import YamlBuildModel
from mtkgui.gui.yamlbuild.parse_nets import parse_testable_nets

MAX_GPIO_ROWS = 16          # DAQM907A DIO pool
MAX_RAMP_RAILS = 10         # rails in the power-up sequence


def best_test_point(members):
    """Auto rule: a TP probe pin when present, else the first pin."""
    members = [m for m in (members or []) if m]
    if not members:
        return UNSET
    probe = next((m for m in members
                  if m.upper().startswith("TP")), None)
    return probe or members[0]


def board_part(net_text: str, core: str) -> str:
    """Part number from the NET header board path (LAY-29420_H.brd);
    fallback PROTO-<core>."""
    m = re.search(r"(?:LAY|BRD)-(\w+)_([A-Za-z0-9]+)\.brd", net_text)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return f"PROTO-{core}"


def find_inputs(folder: Path):
    """The NET (+ optional SPF) files of one project folder."""
    net = sorted(folder.glob("*.net")) or \
        sorted(folder.glob("*.net.txt"))
    spf = sorted(folder.glob("*.pdf"))
    return (net[0] if net else None, spf[0] if spf else None)


def build_model(core: str, net_path: Path, spf_path):
    net_text = net_path.read_text(encoding="utf-8", errors="replace")
    result = parse_testable_nets(net_text)

    # testable_nets: the T8 single data source (like the GUI)
    testable = {}
    for cat, records in (("Power", result.power),
                         ("Clock", result.clock),
                         ("GPIO", result.gpio)):
        for rec in records:
            testable[rec.name] = {"category": cat,
                                  "members": list(rec.members)}

    # ---- channel allocation (auto rules, block 05) -----------------
    alloc = ChannelAllocationData()
    for kind in ("power", "clock", "gpio"):
        rows = rows_from_testable(testable, kind)
        sense = iter(DAQM908A_SENSE_CHANNELS)
        rails = iter(U2355A_AI_CHANNELS)
        clocks = iter(CLOCK_CHANNELS)
        for row in rows:
            row.test_point = best_test_point(
                testable.get(row.net, {}).get("members"))
            if kind == "power":
                try:
                    channel = next(sense)
                    row.impedance = channel
                    row.voltage = channel       # same channel both
                    row.power_rails = next(rails)
                except StopIteration:
                    pass                        # pool exhausted
            elif kind == "clock":
                try:
                    row.se_clock_hz = next(clocks)
                    row.band = CLOCK_BANDS.get(row.se_clock_hz, UNSET)
                except StopIteration:
                    pass
        setattr(alloc, kind, rows)
    model = YamlBuildModel()
    model.enable_all()

    # ---- design input / parse_ict ----------------------------------
    part = board_part(net_text, core)
    spf_name = spf_path.name if spf_path else ""
    model.set_params("design_input", {
        "product_id": core, "part_number": part,
        "sw_version": "1.0.0", "hw_version": "1.0.0",
        "batch": "EVT (Proto-1)",
        "spf_file": spf_name, "net_file": net_path.name,
    })
    model.set_params("parse_ict", {"netlist_file": net_path.name})
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

    # ---- rails / clocks / gpios from the parse result ---------------
    power_nets = [r.name for r in result.power]
    clock_nets = [r.name for r in result.clock]
    gpio_nets = [r.name for r in result.gpio][:MAX_GPIO_ROWS]
    model.set_params("rails", {
        "sequence": "\n".join(
            f"{net}:{0.1 * i:.1f}"
            for i, net in enumerate(power_nets[:MAX_RAMP_RAILS])),
        "sample_rate_hz": "200",
        "pre_trigger_s": "-0.5",
        "post_trigger_s": "6.0",
    })
    model.set_params("clocks", {
        "clocks": "\n".join(f"{net}:1000000:2"
                            for net in clock_nets)
        or "CLK1:1000000:2",
    })
    model.set_params("gpios", {
        "groups": "\n".join(
            f"{net}:{best_test_point(testable[net]['members'])}:in:none"
            for net in gpio_nets),
    })
    # ICT-only plan: the FCT build stays disabled (like the examples)
    model.set_enabled("fct_build", False)
    return model


def _tests_from_testable(testable: dict) -> list[tuple]:
    """The automatic ICT sequence (IctWorkFlowSequenceDialog._generate
    logic, called unbound so no dialog is needed)."""
    from mtkgui.gui.yamlbuild.ict_sequence import (
        METHOD_NET_CATEGORY,
        METHOD_ORDER,
        METHOD_UNITS,
    )
    rows = []
    for method in METHOD_ORDER:
        category = METHOD_NET_CATEGORY[method]
        for net in sorted(n for n, info in (testable or {}).items()
                          if (info or {}).get("category") == category):
            label = {"Static Impedance": f"Static Impedance - {net}",
                     "Power Voltage": f"Power Voltage - {net}",
                     "Clock Hz": f"Clock Hz - {net}"}.get(
                method, f"{method} - {net}")
            rows.append(("test", label, METHOD_UNITS[method],
                         "—", "—", "—"))
    return rows


def make_window():
    """One offscreen MainWindow reused for every project."""
    from PySide6.QtWidgets import QApplication
    from mtkgui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("build_project_yaml")
    return MainWindow()


def apply_to_window(window, model, core: str, part: str) -> None:
    """Push the headless-built model into the real pages (the same
    state the GUI holds after the user walks through the blocks)."""
    page_model = window.yaml_build_page.model
    page_model.apply_state(model.to_dict())
    # product info on the Test Work Flow page (build_config source)
    window.workflow_page.core_edit.setText(core)
    window.workflow_page.part_edit.setText(part)
    window.workflow_page.batch_edit.setText("EVT (Proto-1)")
    # ICT test cases table: standard ops around the generated tests
    window._on_yaml_apply_committed = lambda: None   # no save dialogs
    window._on_ict_sequence_ready(_tests_from_testable(
        model.imported.get("testable_nets") or {}))
    window._sync_rails_to_workflow()
    window.yaml_build_page.refresh_all()


def main(projects_dir: str = "projects") -> int:
    base = Path(projects_dir)
    folders = sorted(p for p in base.iterdir() if p.is_dir())
    if not folders:
        print(f"no project folders under {base}")
        return 1
    from mtkgui import project_config
    window = make_window()
    failures = 0
    for folder in folders:
        core = folder.name
        net, spf = find_inputs(folder)
        if net is None:
            print(f"[SKIP] {core}: no NET file")
            continue
        try:
            model = build_model(core, net, spf)
            errors = model.validate_all()
            if errors:
                print(f"[FAIL] {core}: {errors[:3]}")
                failures += 1
                continue
            part = model.get_params("design_input")["part_number"]
            apply_to_window(window, model, core, part)
            config = project_config.build_config(
                window.workflow_page, window.equipment_page,
                window.yaml_build_page.model.to_dict())
            path = folder / project_config.default_filename(config)
            project_config.save_config(config, path)
            # verify: load back into a FRESH window, zero surprises
            back = project_config.load_config(path)
            probe = make_window()
            project_config.apply_config(
                back, probe.workflow_page, probe.equipment_page,
                probe.yaml_build_page.model)
            probe._sync_rails_to_workflow()
            cases = back.get("test_workflow", {}).get("ict_test_cases", [])
            print(f"[OK] {core}: {path.name} "
                  f"({len(cases)} ict cases, "
                  f"{len(probe.workflow_page.rails)} rails, "
                  f"{len(probe.yaml_build_page.model.channel_allocation.get('power') or [])} power rows)")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"[FAIL] {core}: {exc}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "projects"))
