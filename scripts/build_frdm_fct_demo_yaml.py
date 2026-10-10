#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build FRDM-IMX93_FCT_Demo_v1.0.0.yaml (FCT-only, Linux DUT).

Headless equivalent of the GUI "Build FCT Test Work Flow" (Yaml Build
block 07) -> Apply and Save path:

  * product: FRDM-IMX93 / Core 94611 / Batch "Demo FCT";
  * ICT disabled (FCT only - the board is already powered, no rack
    instruments, no ATE fixture, no flashing);
  * DUT OS/Firmware = linux (FRDM-IMX93, Yocto, u-blox/NXP Wi-Fi+BT);
  * Console (serial 115200): tolerant login -> kernel -> load RF drivers
    -> prepare A2DP sink -> run fat.py unattended -> bring up the Wi-Fi
    station (DUT joins the factory router AP) -> SFTP-get fat.log ->
    DUT->Host ping;
  * Wi-Fi: Scan/RSSI read on the DUT console (station mode) + iPerf3
    (Host is the server, DUT the client, same LAN through the router);
  * Bluetooth: RSSI discovery + Pair/Connect + L2CAP ping + A2DP tone
    (Host source -> DUT sink, GUI confirm);
  * setup power_mode = none (the board is already powered on the bench).

The YAML is written under yaml_plan/examples/imx93frdm/ and verified by
loading it back through project_config (the same loader the GUI uses).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

DUT_PORT = "/dev/cu.usbmodem53930099631"
DUT_SSH_HOST = "192.168.10.129"      # DUT mlan0 on the factory router LAN
HOST_LAN_IP = "192.168.10.141"       # Host PC (iperf3 server, ping target)
ROUTER_SSID = "TP-LINK_F68E_AP"
DUT_BT_NAME = "FRDM-IMX93-DUT"
OUT_DIR = ROOT / "yaml_plan" / "examples" / "imx93frdm"
OUT_NAME = "FRDM-IMX93_FCT_Demo_v1.0.0.yaml"
# headless SFTP landing file (the run script archives it per serial no.)
SFTP_LANDING = str(OUT_DIR / "_run_work" / "fat.log")


def console_row(name, *, kind="send", transport="serial",
                wait=False, send_on=True, capture=False,
                send="", wait_pat="", wait_regex=False,
                cap_pat="", cap_regex=False, cap_expected=True,
                end_line="", case_sensitive=True,
                cap_timeout=6.0, wait_timeout=10.0, send_timeout=4.0,
                retries=0, action="", local="", remote=""):
    """Build one v2 ConsoleCommand dict (explicit stage flags)."""
    row = {
        "kind": kind, "name": name, "transport": transport,
        "wait_enabled": wait, "send_enabled": send_on,
        "capture_enabled": capture,
        "send": send,
        "expect_pass": wait_pat, "expect_pass_is_regex": wait_regex,
        # the Capture pattern travels in expect_fail (model v2 field name)
        "expect_fail": cap_pat, "expect_fail_is_regex": cap_regex,
        "case_sensitive": case_sensitive,
        "capture_is_expected": cap_expected,
        "capture_end_line": end_line, "capture_forbid": "",
        "timeout": float(cap_timeout),
        "wait_timeout": float(wait_timeout),
        "send_timeout": float(send_timeout),
        "retries": int(retries),
        "action": action, "local": local, "remote": remote,
    }
    return row


FCT_TEST_CONFIG = {
    "dut_type": "linux",
    "console": {
        "enabled": True,
        "port": DUT_PORT,
        "baudrate": 115200,
        "newline": "lf",
        "inter_cmd_delay_ms": 120,
        "ssh_host": DUT_SSH_HOST,
        "ssh_username": "root",
        "test_commands": [
            # 1) Login - tolerant of an already-open root shell
            console_row(
                "Console login",
                wait=True, send_on=True,
                wait_pat=r"(imx93frdm login:|root@imx93frdm|#)",
                wait_regex=True, wait_timeout=10,
                send="root", send_timeout=4),
            # 2) Kernel check
            console_row(
                "Kernel check",
                send_on=True, capture=True,
                send="uname -a",
                cap_pat="Linux imx93frdm", cap_timeout=10),
            # 3) Load Wi-Fi/BT RF drivers (BSP script, editable command)
            console_row(
                "Load RF drivers",
                send_on=True, capture=True,
                send="/root/load_rf_drivers.sh",
                cap_pat="RF drivers loaded OK", cap_timeout=30,
                retries=1),
            # 4) Prepare the Linux A2DP sink (pipewire + NoInputNoOutput
            #    agent + discoverable + trust host)
            console_row(
                "Prepare BT audio sink",
                send_on=True, capture=True,
                send="/root/start_bt_audio.sh",
                cap_pat="BT_AUDIO_READY", cap_timeout=40),
            # 5) Run fat.py fully unattended (prompts answered 'y');
            #    pass/fail of fat itself is irrelevant - just capture the
            #    completion marker and always pull the log.
            console_row(
                "Run fat.py board test",
                send_on=True, capture=True,
                send="/root/run_fat_headless.sh",
                cap_pat=r"FATTEN=\d+", cap_regex=True,
                cap_timeout=180.0, send_timeout=4.0),
            # 6) Bring Wi-Fi up as a STATION joined to the factory router
            #    (Host and DUT then share one LAN for ping/iperf/SFTP)
            console_row(
                "Wi-Fi connect to router",
                send_on=True, capture=True,
                send="/root/connect_wifi.sh",
                cap_pat="WIFI_CONNECTED_OK", cap_timeout=45.0,
                retries=1),
            # 7) SFTP-get fat.log back to the Host over SSH
            console_row(
                "Retrieve fat.log (SFTP)",
                kind="sftp_get", transport="ssh",
                send_on=False, action="sftp_get",
                remote="/root/fat.log", local=SFTP_LANDING,
                send_timeout=20.0),
            # 8) DUT -> Host ping over the shared LAN (>=1 reply = PASS)
            console_row(
                "Wi-Fi ping DUT to Host",
                send_on=True, capture=True,
                send=f"ping -I mlan0 -c 20 {HOST_LAN_IP}",
                cap_pat=r"[1-9][0-9]* received", cap_regex=True,
                end_line="packet loss", cap_timeout=40.0),
        ],
    },
    "wifi": {
        "enabled": True,
        "interface": "mlan0",
        "driver_load_cmd": "",          # loaded explicitly in console list
        # 1) Scan / RSSI - station mode, read on the DUT console
        "scan_enabled": True,
        "scan_ssid": ROUTER_SSID,
        "scan_via": "dut_console",
        "rssi_min": -70,
        "scan_timeout": 15,
        # 2) Connect & Ping is expressed as a console command above
        #    (DUT joins the router; the Host never associates to the DUT)
        "ping_enabled": False,
        "ping_ssid": ROUTER_SSID,
        "ping_count": 20,
        "ping_timeout": 15,
        # 3) iPerf3: Host server / DUT client (bench-calibrated floor;
        #    both ends are wireless on this bench -> ~2-5 Mbps)
        "iperf_enabled": True,
        "iperf_tool": "iperf3",
        "iperf_min_mbps": 1.0,
        "iperf_server_ip": HOST_LAN_IP,
        "iperf_duration": 10,
        "iperf_timeout": 45,
    },
    "bluetooth": {
        "enabled": True,
        # 1) RSSI discovery (host inquiry) - always a real inquiry
        "rssi_enabled": True,
        "expected_name": DUT_BT_NAME,
        # Fixed BD address: pair/tone connect straight to it if an inquiry
        # happens to miss the DUT (classic discovery is probabilistic).
        "expected_addr": "B8:F4:4F:59:51:A0",
        "scan_retries": 3,
        "rssi_min": -75,
        "rssi_timeout": 25,
        # 2) Pair & connect + L2CAP data-path proof
        "pair_enabled": True,
        "pair_timeout": 40,
        "l2ping_count": 10,
        # 3) A2DP tone, Host source -> DUT sink (GUI confirm)
        "tone_enabled": True,
        "audio_confirm": True,
        "tone_timeout": 50,
    },
    "setup": {
        "power_mode": "none",           # board already powered on bench
        "use_fixture": False,
        "manual_on_message": "",
        "manual_off_message": "",
    },
}


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from mtkgui import project_config
    from mtkgui.engine.fct_test_config import FctTestConfig, build_fct_steps
    from mtkgui.gui.yamlbuild.fct_build import (
        STEP_MESSAGE_CHECK, FctSequence, to_project_fct_cases, FctStep)
    from mtkgui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("build_frdm_fct_demo")
    window = MainWindow()
    window._on_yaml_apply_committed = lambda: None    # no save dialogs

    page = window.workflow_page
    # product identity
    page.part_edit.setText("FRDM-IMX93")
    page.core_edit.setText("94611")
    page.batch_edit.setText("Demo FCT")

    # ICT disabled -> FCT only
    page.ict_steps = []
    page.ict_enables = []
    page.ict_waits = []
    page.ict_timeouts = []
    page.ict.setRowCount(0)

    cfg = FctTestConfig.from_dict(FCT_TEST_CONFIG)
    errors = cfg.validate()
    if errors:
        print("[FAIL] config invalid:")
        for e in errors:
            print("   -", e)
        return 1
    steps = build_fct_steps(cfg)
    steps.append(FctStep(name="FCT done.", step_type=STEP_MESSAGE_CHECK,
                         expect_pass=["done"], timeout_s=0.0))
    seq = FctSequence(name="FRDM-IMX93 FCT Demo", steps=steps)
    cases = to_project_fct_cases(seq)
    for case, step in zip(cases, steps):
        case.setdefault("op_params", {})["fct_step"] = step.to_dict()
    page.load_fct_cases(cases)

    model = window.yaml_build_page.model
    model.set_enabled("fct_build", True)
    model.set_params("fct_build", {
        "fct_test_config_yaml": yaml.safe_dump(
            cfg.to_yaml_node(), sort_keys=False, allow_unicode=True),
    })

    config = project_config.build_config(
        page, window.equipment_page, model.to_dict())
    config["console"] = [{
        "kind": "serial",
        "params": {"port": DUT_PORT, "baudrate": 115200,
                   "bytesize_key": "8", "parity_key": "None",
                   "stopbits_key": "1", "flow_control": False},
    }]
    config["fct_test_config"] = cfg.to_dict()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "_run_work").mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / OUT_NAME
    project_config.save_config(config, out_path)

    # verify: load it back through the real project loader
    back = project_config.load_config(out_path)
    fct_cases = back.get("test_workflow", {}).get("fct_test_cases", [])
    restored = FctTestConfig.from_dict(back.get("fct_test_config", {}))
    rest_err = restored.validate()
    print(f"[OK] wrote {out_path}")
    print(f"     fct cases: {len(fct_cases)}, ict cases: "
          f"{len(back.get('test_workflow', {}).get('ict_test_cases', []))}")
    print(f"     restored fct_test_config validate: "
          f"{'OK' if not rest_err else rest_err}")
    for c in fct_cases:
        print(f"     - {c.get('kind', '?'):<16} {c.get('name', '?')}")
    return 0 if not rest_err else 1


if __name__ == "__main__":
    sys.exit(main())
