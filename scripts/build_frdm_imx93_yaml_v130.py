#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the FRDM-IMX93 FCT-only project YAML v1.3.0 (P3-B5 real test).

Headless pipeline — the SAME project-config format the Yaml Build page
writes.  v1.3.0 upgrade of build_frdm_imx93_yaml.py:

  * fat.py's 24 judgement tests split into 24 individual console serial
    rows (``--only-tests <id>``), each captured on its own
    [PASS]/[FAIL]/[SKIP] marker, plus serial pull of the accumulated
    /root/fat.log into {{dut_report}};
  * full production spine: Power On (MessageGoStop) -> FAT flash
    (disabled) -> FCT body -> OOBE flash (disabled) -> Power Off
    (MessageOK);
  * Wi-Fi iperf threshold 100 Mbps (measured ~247 Mbps) with the engine's
    built-in one-retry gate; Wi-Fi/Bluetooth network 192.168.71.x.

FCT-only: ICT stays disabled.  Console is one serial channel; production
runs on the Windows deployment box (COM4).

NOTE every test_commands row carries explicit wait/send/capture flags:
``ConsoleCommand._from_dict_v2`` only reads the m30+ fields (capture_expected,
rf_subtest, parse_summary, confirm_*, local/remote) on the non-legacy branch,
so the flags are REQUIRED for those fields to survive parsing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

DUT_PORT = "COM4"                       # Windows deployment serial port
AP_SSID = "ChinaNet-4zEc-5G"
AP_PASSWORD = "dgu3vcgs"
AP_IP = "192.168.71.1"                  # gateway (B8 Wi-Fi ping)
HOST_IP = "192.168.71.8"                # host PC (iperf3 server)
DUT_BT_NAME = "FRDM-IMX93-DUT"
IPERF_MIN_MBPS = 100.0                  # measured ~247 Mbps; keep margin
RSSI_MIN = -70


def _send(name, cmd, *, expect=None, timeout=6.0, retries=0):
    """A send-only console row (expect = capture_expected when set)."""
    row = {"kind": "send", "name": name, "channel": "ser1",
           "wait_enabled": False, "send_enabled": True,
           "capture_enabled": bool(expect),
           "send": cmd, "timeout": timeout, "retries": retries}
    if expect:
        row["capture_expected"] = expect
    return row


MQS_NO_CONFIRM = "--mqs-no-user-confirm"

# The 24 fat.py judgement tests (root…leds), one per console serial row via
# ``--only-tests <id>`` and each captured individually.  INFO-only
# (script_info/python_version/kernel_modules), WARN (dmesg), disabled
# (ethernet_loopback) and plan-excluded (rgb_led) tests are intentionally
# omitted.  pdm_capture is known to SKIP on this BSP; ethernet is known to
# FAIL (fat.py internal — left as-is, reported truthfully).
#
# The engine's m30 Capture drains the FULL per-step timeout (no early exit),
# so timeouts are kept tight-but-safe: fast tests 10 s, slow tests 20–35 s.
# mqs_playback uses --mqs-no-user-confirm so fat.py's blocking input() prompt
# cannot hang the sequence (the operator audio veto is therefore disabled —
# fat.py auto-passes when aplay succeeds).
FAT_TESTS = [
    ("root", "Root privilege", 10.0, "[PASS]", ""),
    ("basic_system", "Board/SoC detection", 10.0, "[PASS]", ""),
    ("memory", "Memory", 10.0, "[PASS]", ""),
    ("memtester", "memtester DDR", 20.0, "[PASS]", ""),
    ("storage", "Storage (MMC/SD)", 20.0, "[PASS]", ""),
    ("network", "Network interfaces", 10.0, "[PASS]", ""),
    ("ethernet", "Ethernet ports", 10.0, "[PASS]", ""),
    ("ethernet_throughput", "Ethernet throughput", 35.0, "[PASS]", ""),
    ("usb", "USB sysfs", 10.0, "[PASS]", ""),
    ("usb_port", "USB U-disk presence", 10.0, "[PASS]", ""),
    ("usb_speed", "USB U-disk speed", 20.0, "[PASS]", ""),
    ("audio_devices", "ALSA devices", 10.0, "[PASS]", ""),
    ("mqs_playback", "MQS playback", 30.0, "[PASS]", MQS_NO_CONFIRM),
    ("pdm_capture", "PDM capture", 10.0, "[SKIP]", ""),
    ("hdmi_connector", "HDMI connector", 10.0, "[PASS]", ""),
    ("hdmi_visual", "HDMI visual", 10.0, "[PASS]", ""),
    ("wifi", "Wi-Fi", 25.0, "[PASS]", ""),
    ("bluetooth", "Bluetooth", 30.0, "[PASS]", ""),
    ("i2c", "I2C bus", 10.0, "[PASS]", ""),
    ("gpio", "GPIO chips", 10.0, "[PASS]", ""),
    ("can", "CAN", 10.0, "[PASS]", ""),
    ("uart", "UART", 10.0, "[PASS]", ""),
    ("thermal", "Thermal", 10.0, "[PASS]", ""),
    ("leds", "LEDs", 10.0, "[PASS]", ""),
]


def _fat_test(test_id, label, timeout, expect, extra_flags):
    """One fat.py judgement test as its own console serial capture row.

    Each test runs ``--only-tests <id>`` so the engine captures that row's
    own [PASS]/[FAIL]/[SKIP] marker instead of one monolithic Summary parse.
    Output is tee'd into /root/fat.log (cleared in "Prepare asset dir") for
    the B15 serial pull.
    """
    flags = f" {extra_flags}" if extra_flags else ""
    cmd = (f"cd /root/fct_assets/frdm_imx93_board_test && "
           f"python3 -u fat.py --only-tests {test_id} --no-progress{flags} "
           f"2>&1 | tee -a /root/fat.log")
    row = {"kind": "send", "name": f"FAT: {label}", "channel": "ser1",
           "wait_enabled": False, "send_enabled": True,
           "capture_enabled": True, "send": cmd,
           "capture_expected": expect, "capture_unexpected": "[FAIL]",
           "timeout": timeout}
    return row


FCT_TEST_CONFIG = {
    "dut_type": "linux",
    "console": {
        "port": DUT_PORT,
        "baudrate": 115200,
        "serial_deploy": True,
        "serial_deploy_files": [
            {"local": "assets_FRDM-IMX93/drivers/load_rf_drivers.sh",
             "remote": "/root/fct_assets/drivers/load_rf_drivers.sh"},
            {"local": "assets_FRDM-IMX93/frdm_imx93_board_test.zip",
             "remote": "/root/fct_assets/frdm_imx93_board_test.zip",
             "unzip": "/root/fct_assets"},
        ],
        "test_commands": [
            # B1 Linux login (autoboot countdown -> login: -> root).
            # Names deliberately avoid "login" so the serial deploy is
            # NOT auto-inserted here; it is placed after "Prepare asset
            # dir" instead (see main()).
            {"kind": "wait", "name": "Boot wait for prompt",
             "channel": "ser1", "wait_enabled": True, "send_enabled": False,
             "capture_enabled": False, "expect_pass": "imx93frdm login:",
             "wait_timeout": 60.0},
            {"kind": "send", "name": "Acquire root shell",
             "channel": "ser1", "wait_enabled": False, "send_enabled": True,
             "capture_enabled": True, "send": "root",
             "capture_expected": "root@imx93frdm", "timeout": 10.0},
            # B2 kernel check
            _send("Kernel check", "uname -a", expect="Linux imx93frdm",
                  timeout=5.0),
            # B3 prepare asset dir (clean state before deploy + fat.log)
            _send("Prepare asset dir",
                  "rm -rf /root/fct_assets && mkdir -p /root/fct_assets "
                  "&& rm -f /root/fat.log",
                  timeout=10.0),
            # B5 load RF drivers
            _send("Load RF drivers",
                  "sh /root/fct_assets/drivers/load_rf_drivers.sh",
                  expect="RF drivers loaded OK", timeout=40.0),
            # B6 Wi-Fi connect
            _send("Wi-Fi connect",
                  "WIFI_SSID='{{ssid}}' "
                  "WIFI_PASSWORD='{{password}}' sh /root/connect_wifi.sh",
                  expect="WIFI_CONNECTED_OK", timeout=45.0),
            # B7/B8/B9 Wi-Fi reference rows (expand in place)
            {"kind": "wifi_test", "name": "Wi-Fi scan (RSSI)",
             "channel": "ser1", "rf_subtest": "scan",
             "wait_enabled": False, "send_enabled": False,
             "capture_enabled": False},
            {"kind": "wifi_test", "name": "Wi-Fi ping gateway",
             "channel": "ser1", "rf_subtest": "ping",
             "wait_enabled": False, "send_enabled": False,
             "capture_enabled": False},
            {"kind": "wifi_test", "name": "Wi-Fi iperf",
             "channel": "ser1", "rf_subtest": "iperf",
             "wait_enabled": False, "send_enabled": False,
             "capture_enabled": False},
            # B10 BT discoverable
            _send("BT discoverable", "hciconfig hci0 piscan",
                  expect="PSCAN", timeout=5.0),
            # B11 BT host RSSI reference row
            {"kind": "bt_test", "name": "BT host RSSI",
             "channel": "ser1", "rf_subtest": "rssi",
             "wait_enabled": False, "send_enabled": False,
             "capture_enabled": False},
            # B12 BT L2CAP ping (host adapter address)
            _send("BT L2CAP ping", "l2ping -c 10 {{host_bt_addr}}",
                  expect="10 received", timeout=30.0),
            # B14 fat.py — 24 judgement tests, one serial row each, each
            # captured on its own [PASS]/[FAIL]/[SKIP] marker (mqs_playback
            # keeps its inline confirm; pdm_capture expects [SKIP]).
            *[_fat_test(*t) for t in FAT_TESTS],
            # B15 pull fat.log -> {{dut_report}} (m107a token)
            {"kind": "serial_pull", "name": "Pull FAT log",
             "channel": "ser1", "wait_enabled": False,
             "send_enabled": False, "capture_enabled": False,
             "remote": "/root/fat.log", "local": "{{dut_report}}",
             "timeout": 600.0},
            # B16 cleanup
            _send("Cleanup assets", "rm -rf /root/fct_assets",
                  timeout=10.0),
        ],
    },
    "wifi": {
        "interface": "mlan0",
        "scan_enabled": True,
        "ap_ssid": AP_SSID,
        "ap_password": AP_PASSWORD,
        "ap_ip": AP_IP,
        "host_ip": HOST_IP,
        "rssi_min": RSSI_MIN,
        "scan_via": "dut_console",
        "ping_enabled": True,
        "ping_count": 20,
        "ping_timeout": 30.0,
        "iperf_enabled": True,
        "iperf_tool": "iperf3",
        "iperf_min_mbps": IPERF_MIN_MBPS,
        "iperf_server_ip": HOST_IP,
        "iperf_duration": 10,
        "iperf_timeout": 30.0,
    },
    "bluetooth": {
        "rssi_enabled": True,
        "expected_name": DUT_BT_NAME,
        "scan_retries": 3,
        "rssi_min": RSSI_MIN,
        "pair_enabled": False,
        "l2ping_count": 10,
        "tone_enabled": False,          # deferred: BSP lacks pipewire-alsa
    },
    "setup": {
        "power_mode": "none",           # power handled by explicit spine rows
        "use_fixture": False,
    },
}


def _dialog(name: str, style: str) -> "object":
    from mtkgui.gui.yamlbuild.fct_build import FctStep, STEP_GUI_CONFIRM
    return FctStep(name=name, step_type=STEP_GUI_CONFIRM, timeout_s=0.0,
                   params={"style": style})


def _host_cli(name: str, command: str) -> "object":
    from mtkgui.gui.yamlbuild.fct_build import FctStep, STEP_CLI_RUN
    return FctStep(name=name, step_type=STEP_CLI_RUN, command=command,
                   timeout_s=120.0)


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from mtkgui import project_config
    from mtkgui.engine.fct_test_config import FctTestConfig
    from mtkgui.engine.fct_test_config import build_fct_steps
    from mtkgui.engine.fct_test_config import _serial_deploy_step
    from mtkgui.gui.yamlbuild.fct_build import (
        FctSequence, to_project_fct_cases,
    )
    from mtkgui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("build_frdm_imx93_v130")
    window = MainWindow()
    window._on_yaml_apply_committed = lambda: None   # no save dialogs

    # FCT test-plan version (the v1.3.0 upgrade)
    window.yaml_build_page.model.set_plan_version("1.3.1")

    # product info
    page = window.workflow_page
    page.core_edit.setText("i.MX93")
    page.part_edit.setText("FRDM-IMX93")
    page.batch_edit.setText("EVT (Proto-1)")

    # ICT disabled: FCT only
    page.ict_steps = []
    page.ict_enables = []
    page.ict_waits = []
    page.ict_timeouts = []
    page.ict.setRowCount(0)

    # FCT body from fct_test_config
    cfg = FctTestConfig.from_dict(FCT_TEST_CONFIG)
    errors = cfg.validate()
    if errors:
        print("[FAIL] config invalid:")
        for e in errors:
            print("  -", e)
        return 1
    body = build_fct_steps(cfg)

    # Serial asset deploy goes right after "Prepare asset dir" (B3), not
    # after login — the deploy targets /root/fct_assets which B3 creates.
    deploy = _serial_deploy_step(cfg.console, "ser1")
    for i, step in enumerate(body):
        if step.name == "Prepare asset dir":
            body.insert(i + 1, deploy)
            break

    # production spine: Power On -> FAT (disabled) -> body -> OOBE
    # (disabled) -> Power Off
    steps = [
        _dialog("Power On DUT", "gostop"),
        _dialog("Enter USB download mode (FAT)", "gostop"),
        _host_cli("Burn FAT firmware", "uuu.exe -b <fat_image.sd>"),
        *body,
        _dialog("Enter USB download mode (OOBE)", "gostop"),
        _host_cli("Burn OOBE firmware", "uuu.exe -b <oobe_image.sd>"),
        _dialog("Power Off DUT", "ok"),
    ]
    seq = FctSequence(name="FRDM-IMX93 FCT", steps=steps)
    cases = to_project_fct_cases(seq)

    # A / C firmware segments are DISABLED (FCT-only DUT, no firmware burn)
    disabled = {
        "Enter USB download mode (FAT)", "Burn FAT firmware",
        "Enter USB download mode (OOBE)", "Burn OOBE firmware",
    }
    for case in cases:
        if case["name"] in disabled:
            case["enable"] = False
    page.load_fct_cases(cases)

    # fct_test_config travels in the yaml_build_state (block 07 params)
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

    config.setdefault("test_workflow", {})["overall_flow"] = [
        {"stage": "ICT", "enable": False},
        {"stage": "FCT", "enable": True},
    ]

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
        flag = "" if c.get("enable", True) else "  (disabled)"
        print(f"     - {c['kind']:<20} {c['name']}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
