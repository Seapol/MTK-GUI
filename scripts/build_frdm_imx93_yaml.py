#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the FRDM-IMX93 FCT-only project YAML (P3-B5 real test).

Headless pipeline, the SAME project-config format the GUI writes:

  * product: i.MX93 / FRDM-IMX93;
  * console: one serial channel on the DUT UART
    (/dev/cu.usbmodem53930099631 @ 115200);
  * ICT: disabled (empty sequence - FCT only per the directive);
  * FCT: the fct_test_config (Console login + Kernel check + Load RF
    drivers, Wi-Fi rssi_only, Bluetooth rssi_only) -> generated FCT
    test cases (op_params.fct_step markers) -> executed by the B5
    fct_exec branch through the multi-console serial channel.

The YAML is written into projects/FRDM-IMX93/ and verified by loading
it back through project_config.load_config.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

DUT_PORT = "/dev/cu.usbmodem53930099631"
DUT_SSID = "FRDM-IMX93-DUT"
DUT_BT_NAME = "FRDM-IMX93-DUT"

FCT_TEST_CONFIG = {
    "dut_type": "linux",
    "console": {
        "enabled": True,
        "port": DUT_PORT,
        "baudrate": 115200,
        "login_sequence": [
            {"wait_for": "login:", "send": "root"},
            {"wait_for": "Password:", "send": ""},
            {"wait_for": "root@imx93frdm"},
        ],
        "test_commands": [
            {"name": "Kernel check", "send": "uname -a",
             "expect_pass": "Linux imx93frdm", "expect_fail": "",
             "timeout": 5, "retries": 1},
            {"name": "Load RF drivers", "send": "/root/load_rf_drivers.sh",
             "expect_pass": "RF drivers loaded OK",
             "expect_fail": "FAILED", "timeout": 15, "retries": 2},
        ],
    },
    "wifi": {
        "enabled": True,
        "mode": "rssi_only",
        "interface": "mlan0",
        "driver_load_cmd": "/root/load_rf_drivers.sh",
        "ssid": DUT_SSID,
        "rssi_min": -70,
        "gateway": "192.168.10.1",
        "ping_count": 20,
        "loss_max": 5,
        "bandwidth": {
            "enabled": True,
            "tool": "iperf3",
            "server_ip": "192.168.10.141",   # host PC running iperf3 -s
            # bench calibration: BOTH ends are wireless on this bench
            # (host Wi-Fi too) - the airtime is shared, ~1-4 Mbps is
            # the bottleneck; recalibrate for the production form
            # (wireless DUT vs WIRED host, ~17 Mbps)
            "min_mbps": 2,
        },
    },
    "bluetooth": {
        "enabled": True,
        "mode": "rssi_only",
        "expected_name": DUT_BT_NAME,
        "rssi_min": -70,
        "audio_confirm": True,
        "l2ping_count": 10,
    },
}


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from mtkgui import project_config
    from mtkgui.engine.fct_test_config import FctTestConfig
    from mtkgui.engine.fct_test_config import build_fct_steps
    from mtkgui.gui.yamlbuild.fct_build import (
        STEP_MESSAGE_CHECK,
        FctSequence,
        to_project_fct_cases,
    )
    from mtkgui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("build_frdm_imx93")
    window = MainWindow()
    window._on_yaml_apply_committed = lambda: None   # no save dialogs

    # product info
    page = window.workflow_page
    page.core_edit.setText("i.MX93")
    page.part_edit.setText("FRDM-IMX93")
    page.batch_edit.setText("EVT (Proto-1)")

    # ICT disabled: FCT only (directive 5.1)
    page.ict_steps = []
    page.ict_enables = []
    page.ict_waits = []
    page.ict_timeouts = []
    page.ict.setRowCount(0)

    # FCT sequence from fct_test_config
    cfg = FctTestConfig.from_dict(FCT_TEST_CONFIG)
    errors = cfg.validate()
    if errors:
        print("[FAIL] config invalid:", errors)
        return 1
    steps = build_fct_steps(cfg)
    steps.append(FctStep_done := type(steps[0])(
        name="FCT done.", step_type=STEP_MESSAGE_CHECK,
        expect_pass=["done"], timeout_s=0.0))
    seq = FctSequence(name="FRDM-IMX93 FCT", steps=steps)
    cases = to_project_fct_cases(seq)
    for case, step in zip(cases, steps):
        case.setdefault("op_params", {})["fct_step"] = step.to_dict()
    page.load_fct_cases(cases)

    # fct_test_config travels in the yaml_build_state (block 07 params)
    # so Preview & Export shows the full node and a reload restores it
    window.yaml_build_page.model.set_enabled("fct_build", True)
    window.yaml_build_page.model.set_params("fct_build", {
        "fct_test_config_yaml": yaml.safe_dump(
            cfg.to_yaml_node(), sort_keys=False, allow_unicode=True),
    })

    config = project_config.build_config(
        page, window.equipment_page,
        window.yaml_build_page.model.to_dict())
    # console: one serial channel on the DUT UART
    config["console"] = [{
        "kind": "serial",
        "params": {"port": DUT_PORT, "baudrate": 115200,
                   "bytesize_key": "8", "parity_key": "None",
                   "stopbits_key": "1", "flow_control": False},
    }]
    # top-level fct_test_config (readable documentation node)
    config["fct_test_config"] = cfg.to_dict()

    out_dir = Path("projects/FRDM-IMX93")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / project_config.default_filename(config)
    project_config.save_config(config, path)

    # verify: load back into a fresh window
    back = project_config.load_config(path)
    probe = MainWindow()
    project_config.apply_config(back, probe.workflow_page,
                                probe.equipment_page,
                                probe.yaml_build_page.model)
    fct_cases = back.get("test_workflow", {}).get("fct_test_cases", [])
    print(f"[OK] {path}")
    print(f"     fct cases: {len(fct_cases)}, "
          f"console: {back.get('console')}, "
          f"ict cases: "
          f"{len(back.get('test_workflow', {}).get('ict_test_cases', []))}")
    for c in fct_cases:
        print(f"     - {c['kind']:<20} {c['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
