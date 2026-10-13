#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build FRDM-IMX93_FCT_Demo_v1.0.2.yaml (FCT-only, Linux DUT, v1.0.2).

v1.0.2 changes over v1.0.1 (console sequence TIMING DISCIPLINE — the
sequence now runs strictly synchronously with the DUT console):

  * WAIT means "the previous step finished": every Send row first
    waits for a FRESH shell prompt (root@imx93frdm).  The runner's
    wait stage only matches bytes received AFTER the previous send,
    so a prompt that appeared earlier in the session can never let a
    row run ahead of the still-running previous command.
  * 'Console wake' first row: sends one newline to establish the
    fresh window and elicit a brand-new prompt (login prompt and
    shell prompt both re-print) — stale bytes from before the run
    are discarded by the send-time buffer reset.
  * fat.py interactive rows wait for the EXACT fat.py question
    before the operator dialog / answer send (no premature y).
  * Echo-safe capture anchors: an anchor must never be a substring
    of the command line itself (the DUT echoes the command before
    running it).  'ls -l' + line-anchored regex for the fat.py
    assets row; quote-split echo markers (echo HDMI_"MONITOR_OK",
    echo SSHD_"STARTED") so only the real output can match.
  * fat.py summary row is capture-only and looks back through the
    WHOLE session transcript (console start -> 'Overall result:'),
    parse_summary expands the Summary table into per-item rows.
  * Reverse validation: a silent DUT can never PASS — wait/capture
    time out to FAIL ('no console output (DUT unresponsive?)').
  * login wait widened to 60 s (true cold boot) with 1 retry.
  * HOST CLI rows (new 'host' kind): the iperf3 server on the test
    PC is now managed BY THE PLAN — a host row starts 'iperf3 -s'
    right before the RF section (macOS/Windows command variants) and
    a post-RF teardown section shuts the DUT down ('shutdown now')
    and then stops the host iperf3 server.  post_rf_commands run
    AFTER the Wi-Fi/BT sections so the DUT stays up while any RF
    sub-test can still run.

v1.0.1 changes over v1.0.0 (single yaml plan for EVERY DUT):

  * REAL interactive fat.py (not the headless yes-piped wrapper): the
    console steps use the new Wait -> MessageYesNo -> Send pipeline -
    every fat.py operator question (setup confirm, MQS earphone tone,
    HDMI visibility, RGB LED colors) pops a GUI confirm dialog and the
    operator's Yes sends the answer line.  No auto-yes anywhere.
  * wait->send->capture ENVIRONMENT PREFLIGHT rows before anything runs
    (kernel, fat.py assets, ALSA card, HDMI monitor connected).
  * sshd is STARTED BY THE PLAN via a console SendTo row with a capture
    check (SSHD_STARTED) - no manual sshd bring-up per board.
  * fat.py's own verdict line ('Overall result: PASS') is captured as
    the fat step's pass criterion, with a drift-tolerant 420 s window
    (same yaml for fast and slow boards).
  * DUT mlan0 IP evidence row (the harness resolves the SFTP host from
    the live IP - no hard-coded per-board address in the flow).

Headless equivalent of the GUI "Build FCT Test Work Flow" (Yaml Build
block 07) -> Apply and Save path:

  * product: FRDM-IMX93 / Core 94611 / Batch "Demo FCT";
  * ICT disabled (FCT only - the board is already powered, no rack
    instruments, no ATE fixture, no flashing);
  * DUT OS/Firmware = linux (FRDM-IMX93, Yocto, u-blox/NXP Wi-Fi+BT);
  * Console (serial 115200): tolerant login -> preflight -> load RF
    drivers -> prepare A2DP sink -> run interactive fat.py (operator
    confirms each physical check) -> fat verdict -> start sshd -> bring
    up the Wi-Fi station -> DUT IP evidence -> SFTP-get fat_result.json
    -> DUT->Host ping;
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
OUT_NAME = "FRDM-IMX93_FCT_Demo_v1.0.2.yaml"
# headless SFTP landing file (the run script archives it per serial no.)
SFTP_LANDING = str(OUT_DIR / "_run_work" / "fat_result.json")


#: the DUT shell prompt (regex) - a FRESH occurrence of it after the
#: previous send is the "previous command finished" barrier
SHELL_PROMPT = r"root@imx93frdm"


def console_row(name, *, kind="send", transport="serial",
                wait=False, send_on=True, capture=False,
                send="", wait_pat="", wait_regex=False,
                cap_pat="", cap_regex=False, cap_expected=True,
                end_line="", case_sensitive=True,
                cap_timeout=6.0, wait_timeout=10.0, send_timeout=4.0,
                retries=0, action="", local="", remote="",
                confirm=False, confirm_msg="", parse_summary=False):
    """Build one v2.1 ConsoleCommand dict (explicit stage flags).

    confirm=True inserts an operator MessageYesNo stage between Wait
    and Send (interactive DUT prompts): the GUI pops the dialog, the
    operator's Yes sends the answer line, No fails the unit."""
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
        "confirm_enabled": bool(confirm),
        "confirm_message": str(confirm_msg or ""),
        "timeout": float(cap_timeout),
        "wait_timeout": float(wait_timeout),
        "send_timeout": float(send_timeout),
        "retries": int(retries),
        "action": action, "local": local, "remote": remote,
        "parse_summary": bool(parse_summary),
    }
    return row


def host_row(name, *, host_cmd, host_cmd_windows="", timeout=15.0,
             retries=0):
    """Build one 'host' ConsoleCommand dict: the command runs ON THE
    HOST PC (macOS default / Windows override), PASS = exit code 0."""
    return {
        "kind": "host", "name": name, "transport": "serial",
        "wait_enabled": False, "send_enabled": False,
        "capture_enabled": False,
        "send": "",
        "expect_pass": "", "expect_pass_is_regex": False,
        "expect_fail": "", "expect_fail_is_regex": False,
        "case_sensitive": True,
        "capture_is_expected": False,
        "capture_end_line": "", "capture_forbid": "",
        "confirm_enabled": False, "confirm_message": "",
        "timeout": float(timeout),
        "wait_timeout": 10.0, "send_timeout": 4.0,
        "retries": int(retries),
        "action": "", "local": "", "remote": "",
        "parse_summary": False,
        "host_cmd": host_cmd,
        "host_cmd_windows": host_cmd_windows,
    }


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
            # 0) Console wake: one newline establishes the FRESH window
            #    (the send-time buffer reset discards everything that
            #    arrived before the run) and elicits a brand-new prompt
            #    - getty re-prints 'login:', bash re-prints the prompt.
            console_row(
                "Console wake",
                send="\n", wait_timeout=5, send_timeout=4),
            # 1) Login - tolerant of an already-open root shell; the
            #    fresh-window wait only matches a prompt printed AFTER
            #    the wake newline (true cold boot gets 60 s + 1 retry)
            console_row(
                "Console login",
                wait=True, send_on=True,
                wait_pat=r"(imx93frdm login:|root@imx93frdm)",
                wait_regex=True, wait_timeout=60, retries=1,
                send="root", send_timeout=4),
            # ---- environment preflight (wait -> send -> capture) ----
            # every Send row waits for a FRESH shell prompt first: the
            # previous command's completion barrier
            # 2) Kernel up
            console_row(
                "Preflight: kernel",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="uname -a",
                cap_pat="Linux imx93frdm", cap_timeout=10),
            # 3) fat.py assets present ('-rw' line-anchored regex: the
            #    echoed command line contains 'fat.py' but never a
            #    leading '-rw' - only the real ls output can match)
            console_row(
                "Preflight: fat.py assets",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="ls -l /root/frdm_imx93_board_test/fat.py",
                cap_pat=r"-rw.*fat\.py", cap_regex=True, cap_timeout=10),
            # 4) ALSA sound card present (MQS playback needs it)
            console_row(
                "Preflight: ALSA card",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="aplay -l",
                cap_pat="card 0", cap_timeout=10),
            # 5) HDMI monitor electrically connected (grep -x rejects
            #    'disconnected'); catches a powered-off monitor early.
            #    Quote-split marker: the echoed command contains
            #    HDMI_"MONITOR_OK", only the real echo OUTPUT prints
            #    the literal HDMI_MONITOR_OK
            console_row(
                "Preflight: HDMI monitor",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="cat /sys/class/drm/card0-HDMI-A-1/status "
                     "| grep -x connected && echo HDMI_\"MONITOR_OK\"",
                cap_pat="HDMI_MONITOR_OK", cap_timeout=10),
            # 6) Load Wi-Fi/BT RF drivers + prepare the A2DP sink
            #    (pipewire + NoInputNoOutput agent + discoverable +
            #    trust host - merged from the former start_bt_audio.sh;
            #    the pipewire/wireplumber/agent sleeps total ~12 s, so
            #    the capture window is 60 s)
            console_row(
                "Load RF drivers",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="/root/load_rf_drivers.sh",
                cap_pat="RF drivers loaded OK", cap_timeout=60,
                retries=1),
            # ---- interactive fat.py (Wait -> MessageYesNo -> Send) ----
            # 8) Launch the REAL fat.py in the console foreground
            console_row(
                "Start fat.py (interactive)",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True,
                wait_timeout=30,
                send="cd /root/frdm_imx93_board_test && "
                     "python3 fat.py --json /root/fat_result.json",
                cap_pat="FRDM-i.MX93 DUT", cap_timeout=20),
            # 9) fat.py setup confirm (earphone / HDMI / RGB visible)
            console_row(
                "fat.py: setup confirm",
                wait=True, send_on=True, capture=True,
                wait_pat="Confirm DUT setup is complete and start FAT",
                wait_timeout=60,
                confirm=True,
                confirm_msg="fat.py setup check: earphone plugged in, "
                            "HDMI monitor on, RGB LED visible - setup "
                            "complete?",
                send="y", cap_pat="Running as root", cap_timeout=30),
            # 10) MQS earphone tone (aplay plays ~2 s, then asks)
            console_row(
                "fat.py: MQS earphone tone",
                wait=True, send_on=True, capture=True,
                wait_pat=r"Did you hear the \d+ Hz tone from the "
                         r"3\.5 mm earphone\?",
                wait_regex=True, wait_timeout=300,
                confirm=True,
                confirm_msg="MQS audio: listen to the 3.5 mm earphone - "
                            "did you hear the 1000 Hz tone?",
                send="y", cap_pat="operator confirmed tone heard",
                cap_timeout=30),
            # 11) HDMI visual output (connector check is automatic)
            console_row(
                "fat.py: HDMI visual",
                wait=True, send_on=True, capture=True,
                wait_pat="Is HDMI output visible on the monitor",
                wait_timeout=300,
                confirm=True,
                confirm_msg="HDMI: look at the monitor - is the DUT "
                            "output visible?",
                send="y", cap_pat="Operator confirmed HDMI output",
                cap_timeout=30),
            # 12) RGB LED start gate (any key starts the color cycle)
            console_row(
                "fat.py: RGB LED start",
                wait=True, send_on=True, capture=True,
                wait_pat="Press any key to start the RGB LED test",
                wait_timeout=300,
                confirm=True,
                confirm_msg="RGB LED: get ready to watch the on-board "
                            "LED - press Yes to start the color cycle",
                send="",                       # one newline = "any key"
                cap_pat="[RGB LED] Display RED", cap_timeout=20),
            # 13) RGB LED color confirmation (7 x 1 s cycle first)
            console_row(
                "fat.py: RGB LED colors",
                wait=True, send_on=True, capture=True,
                wait_pat="Did the RGB LED display RED/GREEN/BLUE/"
                         "YELLOW/CYAN/MAGENTA/WHITE correctly",
                wait_timeout=300,
                confirm=True,
                confirm_msg="RGB LED: did all 7 colors (RED/GREEN/BLUE/"
                            "YELLOW/CYAN/MAGENTA/WHITE) look correct?",
                send="y", cap_pat="Operator confirmed all RGB LED colors",
                cap_timeout=30),
            # 14) fat.py Summary - CAPTURE-ONLY row: no send, so the
            #     runner judges it against the WHOLE session transcript
            #     (console start -> 'Overall result:'), which includes
            #     everything printed while earlier rows were reading.
            #     parse_summary expands the table into per-item rows
            #     (one report row per fat.py test line); a Summary that
            #     never arrives (DUT died mid-run) times out to FAIL.
            console_row(
                "fat.py summary",
                send_on=False, capture=True,
                cap_pat="Overall result:", cap_timeout=420,
                parse_summary=True),
            # 15) Ensure an SSH server is reachable for the SFTP row.
            #     The board's sshd runs as a SYSTEMD SOCKET-ACTIVATED
            #     unit (sshd.socket holds :22 via init; no persistent
            #     sshd daemon), so 'pidof sshd' is always empty - probe
            #     the LISTENER instead (works for daemon AND socket
            #     activation).  /usr/sbin/sshd is still attempted for
            #     images without the socket unit.  Quote-split marker:
            #     the echoed command never contains the literal
            #     SSHD_STARTED - only the real echo OUTPUT does
            console_row(
                "Start sshd",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="mkdir -p /var/run/sshd; /usr/sbin/sshd "
                     "2>/dev/null; netstat -tln 2>/dev/null "
                     "| grep -q ':22 ' && echo SSHD_\"STARTED\"",
                cap_pat="SSHD_STARTED", cap_timeout=10),
            # 16) Bring Wi-Fi up as a STATION joined to the factory
            #     router (Host and DUT then share one LAN)
            console_row(
                "Wi-Fi connect to router",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="/root/connect_wifi.sh",
                cap_pat="WIFI_CONNECTED_OK", cap_timeout=45.0,
                retries=1),
            # 17) DUT Wi-Fi IP evidence (the harness resolves the SFTP
            #     host from the live mlan0 address - no per-board IP)
            console_row(
                "DUT Wi-Fi IP check",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="ip -4 addr show mlan0",
                cap_pat="inet", cap_timeout=10),
            # 18) SFTP-get fat_result.json back to the Host over SSH
            console_row(
                "Retrieve fat_result.json (SFTP)",
                kind="sftp_get", transport="ssh",
                send_on=False, action="sftp_get",
                remote="/root/fat_result.json", local=SFTP_LANDING,
                send_timeout=20.0),
            # 19) DUT -> Host ping over the shared LAN (>=1 reply = PASS)
            console_row(
                "Wi-Fi ping DUT to Host",
                wait=True, send_on=True, capture=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send=f"ping -I mlan0 -c 20 {HOST_LAN_IP}",
                cap_pat=r"[1-9][0-9]* received", cap_regex=True,
                end_line="packet loss", cap_timeout=40.0),
            # 20) HOST CLI: start the iperf3 server on the TEST PC right
            #     before the RF section (the DUT-client iPerf3 sub-test
            #     connects back to it).  macOS: daemon mode; Windows:
            #     'start /B' returns immediately.  A missing iperf3
            #     binary fails the row (rc != 0) BEFORE the throughput
            #     test would time out.
            host_row(
                "Start iperf3 server (Host CLI)",
                host_cmd="iperf3 -s -D",
                host_cmd_windows="start /B iperf3 -s"),
        ],
        # Post-RF teardown: AFTER the Wi-Fi/BT sections (the DUT must
        # stay up while any RF sub-test can still run)
        "post_rf_commands": [
            # T1) power the DUT off — the run ends with the board down.
            #     Send-only (no capture): the console goes silent as the
            #     board powers off; the wait proves the DUT was alive.
            console_row(
                "Shutdown DUT",
                wait=True, send_on=True,
                wait_pat=SHELL_PROMPT, wait_regex=True, wait_timeout=30,
                send="shutdown now", send_timeout=4),
            # T2) HOST CLI: stop the iperf3 server (rc forced to 0 on
            #     Windows even when nothing matched; '|| true' on macOS)
            host_row(
                "Stop iperf3 server (Host CLI)",
                host_cmd="pkill -x iperf3 || true",
                host_cmd_windows="taskkill /IM iperf3.exe /F & ver > nul"),
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
