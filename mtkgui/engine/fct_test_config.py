# -*- coding: utf-8 -*-
"""fct_test_config — P3-B5 data model for the FCT test configuration
(Console / Wi-Fi / Bluetooth tabs of Yaml Build block 07).

Pure data + (de)serialization + validation + the mapping to B4
``FctStep`` markers (op_params.fct_step) so the published project YAML
runs through the EXISTING fct_exec executor unchanged.

RED LINES honoured:
  * no Qt, no channel I/O here (execution lives in fct_test_runner /
    fct_exec);
  * no passwords in code — whatever the operator types travels with
    the project YAML they own (console creds stay OUT; the Wi-Fi
    password is the DUT AP password the station needs to join).

YAML shape (product YAML `fct_test_config:` node):

    fct_test_config:
      dut_type: "linux"
      console:
        enabled: true
        port: "/dev/cu.usbmodem53930099631"
        baudrate: 115200
        login_sequence:            # wait_for / send pairs
          - {wait_for: "login:", send: "root"}
        test_commands:             # name/send/expect/timeout rows
          - {name: Kernel check, send: "uname -a",
             expect_pass: "Linux imx93frdm", timeout: 5}
      wifi:
        enabled: true
        interface: "mlan0"          # DUT wireless interface
        driver_load_cmd: ""        # optional DUT-side driver script
        # 1. Scan / RSSI  (both Linux and bare-metal/RTOS DUTs)
        scan_enabled: true
        scan_ssid: "FRDM-AP"       # DUT Wi-Fi endpoint the Host scans
        scan_via: "host"           # host | dut_console
        rssi_min: -70
        scan_timeout: 15
        # 2. Connect & Ping  (Linux DUT only)
        ping_enabled: false
        ping_ssid: "FRDM-AP"
        ping_password: ""
        ping_count: 20             # PASS if >=1 reply (loss < 100%)
        ping_timeout: 15
        # 3. iPerf throughput: Host server -> DUT client (Linux only)
        iperf_enabled: false
        iperf_tool: "iperf3"       # iperf2 | iperf3
        iperf_min_mbps: 10
        iperf_server_ip: ""        # empty = auto-detect Host LAN IP
        iperf_duration: 10
        iperf_timeout: 15
      bluetooth:
        enabled: true
        # 1. RSSI discovery (both Linux and bare-metal/RTOS DUTs)
        rssi_enabled: true
        expected_name: "FRDM-IMX93-DUT"
        rssi_min: -70
        rssi_timeout: 15
        # 2. Pair & connect, optional L2CAP ping (Linux DUT only)
        pair_enabled: false
        pair_timeout: 15
        l2ping_count: 0
        # 3. Tone / music over A2DP, Host source -> DUT sink (Linux only)
        tone_enabled: false
        audio_confirm: true
        tone_timeout: 15
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..gui.yamlbuild.fct_build import (
    STEP_EXTERNAL_TOOL,
    STEP_GUI_CONFIRM,
    STEP_MESSAGE_CHECK,
    FctStep,
)

BAUDRATES = (9600, 19200, 38400, 57600, 115200)
#: adapter modes (rf_adapters) reused by the per-sub-test orchestration
WIFI_MODES = ("rssi_only", "full_stack")
BT_MODES = ("rssi_only", "pair_connect", "a2dp_sink")
BW_TOOLS = ("iperf2", "iperf3")
#: how the Wi-Fi scan/RSSI is read
WIFI_SCAN_VIA = ("host", "dut_console")
#: default per-sub-test timeout (seconds); minimum 1 s
DEFAULT_RF_TIMEOUT = 15.0

#: FCT DUT power source (block 07 setup):
#:   psu    - the rack PSU (N5747A) powers the DUT, same Power On/Off
#:            operations as ICT;
#:   manual - no PSU: a MessageGoStop prompts the operator to connect the
#:            wall adapter / USB cable before the tests and remove it
#:            afterwards;
#:   none   - the DUT is already powered (no power action at all).
POWER_PSU = "psu"
POWER_MANUAL = "manual"
POWER_NONE = "none"
FCT_POWER_MODES = (POWER_PSU, POWER_MANUAL, POWER_NONE)

DEFAULT_MANUAL_ON_MSG = (
    "Connect the power adapter / USB cable to the DUT, then press GO "
    "to start FCT.")
DEFAULT_MANUAL_OFF_MSG = (
    "FCT finished. Disconnect the power adapter / USB cable, then press "
    "GO.")

#: default per-command timeout (spec §4.1: commands 5 s, driver load
#: 15 s, Wi-Fi join 30 s — configured per row)
DEFAULT_CMD_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------
@dataclass
class LoginStep:
    """One console login pair: wait for `wait_for`, then `send`."""

    wait_for: str = ""
    send: str = ""

    def to_dict(self) -> dict:
        return {"wait_for": self.wait_for, "send": self.send}


#: console command kinds (P3-B5 v2: the three primitives)
KIND_WAIT = "wait"              # capture until expect_pass matches
KIND_SEND = "send"              # write line(s); verdict Pass ("sent")
KIND_CAPTURE = "capture"        # judge output (send optional); fail-wins
KIND_SFTP_PUT = "sftp_put"      # ssh file transfer DUT <- Host
KIND_SFTP_GET = "sftp_get"      # ssh file transfer DUT -> Host
CONSOLE_KINDS = (KIND_WAIT, KIND_SEND, KIND_CAPTURE,
                 KIND_SFTP_PUT, KIND_SFTP_GET)


@dataclass
class ConsoleCommand:
    """One console test step (model v2): a Wait / Send / Capture
    primitive, or an SSH file-transfer row (sftp_put/sftp_get)."""

    kind: str = "send"              # wait | send | capture | sftp_put | sftp_get
    name: str = ""
    transport: str = "serial"       # serial | ssh
    wait_enabled: bool = False      # Wait stage on/off
    send_enabled: bool = True       # Send stage on/off
    capture_enabled: bool = False   # Capture stage on/off
    send: str = ""                  # command line(s), \n separated; {{var}} rendered
    expect_pass: str = ""           # WaitFor pattern (exact default or regex)
    expect_fail: str = ""           # Capture pattern (exact default or regex)
    expect_pass_is_regex: bool = False   # False = exact substring match
    expect_fail_is_regex: bool = False
    case_sensitive: bool = True         # False = ignore case (PASS = pass)
    capture_is_expected: bool = False   # Capture: True = found=PASS, False = found=FAIL
    capture_end_line: str = ""          # end-of-range marker
    capture_forbid: str = ""            # optional negative keyword even when
                                        # expecting a positive (legacy migrate)
    timeout: float = 6.0            # capture timeout (overall judgement window)
    wait_timeout: float = 10.0      # wait-for-message timeout
    send_timeout: float = 4.0       # send command timeout
    retries: int = 0                # extra attempts on ANY fail (incl. timeout)
    extract: str = ""               # "name=regex" lines; group 1 -> variables
    action: str = ""                # sftp_put | sftp_get (transport=ssh rows)
    local: str = ""                 # sftp local path (Host PC)
    remote: str = ""                # sftp remote path (DUT)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name,
                "transport": self.transport,
                "wait_enabled": self.wait_enabled,
                "send_enabled": self.send_enabled,
                "capture_enabled": self.capture_enabled,
                "send": self.send,
                "expect_pass": self.expect_pass,
                "expect_fail": self.expect_fail,
                "expect_pass_is_regex": self.expect_pass_is_regex,
                "expect_fail_is_regex": self.expect_fail_is_regex,
                "case_sensitive": self.case_sensitive,
                "capture_is_expected": self.capture_is_expected,
                "capture_end_line": self.capture_end_line,
                "capture_forbid": self.capture_forbid,
                "timeout": float(self.timeout),
                "wait_timeout": float(self.wait_timeout),
                "send_timeout": float(self.send_timeout),
                "retries": int(self.retries),
                "extract": self.extract, "action": self.action,
                "local": self.local, "remote": self.remote}

    @staticmethod
    def _from_dict_v2(c: dict) -> "ConsoleCommand":
        """Build a ConsoleCommand, migrating the legacy single-window
        model (send + expect_pass/expect_fail judged together) to the
        Wait -> Send -> Capture pipeline.

        Legacy semantics: expect_pass = positive keyword expected AFTER
        send; expect_fail = negative keyword (fail wins). New rows carry
        explicit wait_enabled/send_enabled/capture_enabled flags.
        """
        legacy = not any(k in c for k in
                         ("wait_enabled", "send_enabled", "capture_enabled"))
        kind = str(c.get("kind", "send"))
        send = str(c.get("send", ""))
        old_pass = str(c.get("expect_pass", ""))
        old_fail = str(c.get("expect_fail", ""))

        if not legacy:
            return ConsoleCommand(
                kind=kind, name=str(c.get("name", "")),
                transport=str(c.get("transport", "serial")),
                wait_enabled=bool(c.get("wait_enabled", False)),
                send_enabled=bool(c.get("send_enabled", True)),
                capture_enabled=bool(c.get("capture_enabled", False)),
                send=send, expect_pass=old_pass, expect_fail=old_fail,
                expect_pass_is_regex=bool(c.get("expect_pass_is_regex", False)),
                expect_fail_is_regex=bool(c.get("expect_fail_is_regex", False)),
                case_sensitive=bool(c.get("case_sensitive", True)),
                capture_is_expected=bool(c.get("capture_is_expected", False)),
                capture_end_line=str(c.get("capture_end_line", "")),
                capture_forbid=str(c.get("capture_forbid", "")),
                timeout=float(c.get("timeout", 6.0)),
                wait_timeout=float(c.get("wait_timeout", 10.0)),
                send_timeout=float(c.get("send_timeout", 4.0)),
                retries=int(c.get("retries", 0) or 0),
                extract=str(c.get("extract", "")),
                action=str(c.get("action", "")),
                local=str(c.get("local", "")),
                remote=str(c.get("remote", "")))

        # ---- legacy migration ----
        if kind == "wait":
            return ConsoleCommand(
                kind="wait", name=str(c.get("name", "")),
                transport=str(c.get("transport", "serial")),
                wait_enabled=True, send_enabled=False, capture_enabled=False,
                send="", expect_pass=old_pass, expect_fail="",
                expect_pass_is_regex=bool(c.get("expect_pass_is_regex", False)),
                expect_fail_is_regex=bool(c.get("expect_fail_is_regex", False)),
                case_sensitive=bool(c.get("case_sensitive", True)),
                timeout=float(c.get("timeout", 6.0)),
                wait_timeout=float(c.get("timeout", 10.0)),
                send_timeout=float(c.get("send_timeout", 4.0)),
                retries=int(c.get("retries", 0) or 0))
        # send/capture: the old expect_pass becomes the Capture positive
        # keyword; old expect_fail becomes capture_forbid (or the main
        # negative pattern when no positive exists).
        capture_enabled = bool(old_pass or old_fail)
        if old_pass:
            main_pattern, is_expected, forbid = old_pass, True, old_fail
        else:
            main_pattern, is_expected, forbid = old_fail, False, ""
        return ConsoleCommand(
            kind=kind, name=str(c.get("name", "")),
            transport=str(c.get("transport", "serial")),
            wait_enabled=False,
            send_enabled=bool(send) or kind == "send",
            capture_enabled=capture_enabled,
            send=send, expect_pass="", expect_fail=main_pattern,
            expect_pass_is_regex=bool(c.get("expect_pass_is_regex", False)),
            expect_fail_is_regex=bool(c.get("expect_fail_is_regex", False)),
            case_sensitive=bool(c.get("case_sensitive", True)),
            capture_is_expected=is_expected,
            capture_end_line="", capture_forbid=forbid,
            timeout=float(c.get("timeout", 6.0)),
            wait_timeout=float(c.get("wait_timeout", 10.0)),
            send_timeout=float(c.get("send_timeout", 4.0)),
            retries=int(c.get("retries", 0) or 0),
            extract=str(c.get("extract", "")),
            action=str(c.get("action", "")),
            local=str(c.get("local", "")),
            remote=str(c.get("remote", "")))


@dataclass
class ConsoleCfg:
    enabled: bool = False
    port: str = ""
    baudrate: int = 115200
    newline: str = "lf"             # lf | crlf (send line ending)
    inter_cmd_delay_ms: int = 100   # settle time between command rows
    ssh_host: str = ""              # DUT SSH endpoint for ssh/sftp rows
    ssh_username: str = "root"
    test_commands: list = field(default_factory=list)    # [ConsoleCommand]

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled, "port": self.port,
            "baudrate": int(self.baudrate),
            "newline": self.newline,
            "inter_cmd_delay_ms": int(self.inter_cmd_delay_ms),
            "ssh_host": self.ssh_host, "ssh_username": self.ssh_username,
            "test_commands": [c.to_dict() for c in self.test_commands],
        }


@dataclass
class WifiCfg:
    """Wi-Fi FCT split into independently enabled sub-tests.

    Topology: the DUT advertises the RF endpoint (Wi-Fi AP / hotspot);
    the Host PC is the initiator.

    * Scan/RSSI test  - host scans the DUT SSID and reads RSSI; works on
      BOTH Linux and bare-metal/RTOS DUTs (firmware auto-broadcasts after
      power-up on bare metal).
    * Connect & Ping  - host associates to the DUT AP (SSID + password)
      and pings; PASS as soon as >=1 reply is received. Linux DUT only.
    * iPerf throughput- host is the iperf SERVER, DUT the client; PASS at
      or above ``iperf_min_mbps``; iperf2/iperf3 selectable. Linux only.

    ``interface`` / ``driver_load_cmd`` are base parameters (the driver
    load is a BSP deliverable; MTK only sends the editable command over
    the console). Each sub-test carries its own timeout (default 15 s)."""
    enabled: bool = False
    # base parameters
    interface: str = "mlan0"
    driver_load_cmd: str = ""
    # 1) scan / RSSI (both DUT kinds)
    scan_enabled: bool = True
    scan_ssid: str = ""
    rssi_min: int = -70
    scan_timeout: float = 15.0
    scan_via: str = "host"          # host | dut_console (station-mode DUT)
    # 2) connect & ping (Linux only)
    ping_enabled: bool = False
    ping_ssid: str = ""
    ping_password: str = ""
    ping_count: int = 20
    ping_timeout: float = 15.0
    # 3) iperf throughput (Linux only; host server / DUT client)
    iperf_enabled: bool = False
    iperf_tool: str = "iperf3"      # iperf2 | iperf3
    iperf_min_mbps: float = 10.0
    iperf_server_ip: str = ""       # host PC IP; empty = auto-detect
    iperf_duration: int = 10
    iperf_timeout: float = 15.0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "interface": self.interface,
            "driver_load_cmd": self.driver_load_cmd,
            "scan_enabled": self.scan_enabled, "scan_ssid": self.scan_ssid,
            "rssi_min": int(self.rssi_min),
            "scan_timeout": float(self.scan_timeout),
            "scan_via": self.scan_via,
            "ping_enabled": self.ping_enabled, "ping_ssid": self.ping_ssid,
            "ping_password": self.ping_password,
            "ping_count": int(self.ping_count),
            "ping_timeout": float(self.ping_timeout),
            "iperf_enabled": self.iperf_enabled,
            "iperf_tool": self.iperf_tool,
            "iperf_min_mbps": float(self.iperf_min_mbps),
            "iperf_server_ip": self.iperf_server_ip,
            "iperf_duration": int(self.iperf_duration),
            "iperf_timeout": float(self.iperf_timeout),
        }


@dataclass
class BluetoothCfg:
    """Bluetooth FCT split into independently enabled sub-tests.

    Topology: the Host PC is the A2DP SOURCE / initiator, the DUT is the
    sink / advertiser.

    * RSSI test         - host inquiry discovers the DUT by name and
      reads RSSI; works on BOTH Linux and bare-metal/RTOS DUTs.
    * Pair-Connect test - host pairs and connects to the DUT. Linux
      only; optional ``l2ping_count`` (0 = off) proves the data path both
      ways.
    * Tone/Music test   - host routes audio to the DUT A2DP sink and
      plays a test tone; operator GUI confirm. Linux only.

    Each sub-test carries its own timeout (default 15 s)."""
    enabled: bool = False
    # 1) RSSI / discovery (both DUT kinds)
    rssi_enabled: bool = True
    expected_name: str = ""
    rssi_min: int = -70
    rssi_timeout: float = 15.0
    # 2) pair & connect (Linux only)
    pair_enabled: bool = False
    pair_timeout: float = 15.0
    l2ping_count: int = 0           # optional L2CAP data-path proof, 0=off
    # 3) tone / music over A2DP (Linux only; host source -> DUT sink)
    tone_enabled: bool = False
    audio_confirm: bool = True
    tone_timeout: float = 15.0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "rssi_enabled": self.rssi_enabled,
            "expected_name": self.expected_name,
            "rssi_min": int(self.rssi_min),
            "rssi_timeout": float(self.rssi_timeout),
            "pair_enabled": self.pair_enabled,
            "pair_timeout": float(self.pair_timeout),
            "l2ping_count": int(self.l2ping_count),
            "tone_enabled": self.tone_enabled,
            "audio_confirm": self.audio_confirm,
            "tone_timeout": float(self.tone_timeout),
        }


@dataclass
class FctSetupCfg:
    """FCT fixture/power wrapper around the generated test body.

    Unlike ICT, FCT needs NO DAQ. The DUT is powered either by the rack
    PSU (Power On/Off operations) or by a wall adapter / USB cable the
    operator connects when prompted (MessageGoStop). The ATE fixture,
    when used, is driven through the U2355A DIO resource.
    """

    power_mode: str = POWER_MANUAL     # psu | manual | none
    use_fixture: bool = False
    manual_on_message: str = DEFAULT_MANUAL_ON_MSG
    manual_off_message: str = DEFAULT_MANUAL_OFF_MSG

    def to_dict(self) -> dict:
        return {
            "power_mode": self.power_mode,
            "use_fixture": bool(self.use_fixture),
            "manual_on_message": self.manual_on_message,
            "manual_off_message": self.manual_off_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FctSetupCfg":
        data = data or {}
        return cls(
            power_mode=str(data.get("power_mode", POWER_MANUAL)),
            use_fixture=bool(data.get("use_fixture", False)),
            manual_on_message=str(
                data.get("manual_on_message", DEFAULT_MANUAL_ON_MSG)),
            manual_off_message=str(
                data.get("manual_off_message", DEFAULT_MANUAL_OFF_MSG)),
        )

    def validate(self) -> list:
        errors: list = []
        if self.power_mode not in FCT_POWER_MODES:
            errors.append(f"setup.power_mode must be one of "
                          f"{FCT_POWER_MODES}")
        if self.power_mode == POWER_MANUAL and not \
                self.manual_on_message.strip():
            errors.append("setup.manual_on_message must not be empty "
                          "for manual power mode")
        return errors


@dataclass
class FctTestConfig:
    """The whole `fct_test_config:` node (block 07 three tabs)."""

    dut_type: str = "linux"              # bare_metal | linux
    console: ConsoleCfg = field(default_factory=ConsoleCfg)
    wifi: WifiCfg = field(default_factory=WifiCfg)
    bluetooth: BluetoothCfg = field(default_factory=BluetoothCfg)
    setup: FctSetupCfg = field(default_factory=FctSetupCfg)

    # ------------------------------------------------------------ YAML IO
    def to_dict(self) -> dict:
        return {
            "dut_type": self.dut_type,
            "console": self.console.to_dict(),
            "wifi": self.wifi.to_dict(),
            "bluetooth": self.bluetooth.to_dict(),
            "setup": self.setup.to_dict(),
        }

    def to_yaml_node(self) -> dict:
        return {"fct_test_config": self.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "FctTestConfig":
        """Tolerant restore (missing keys keep defaults)."""
        data = data or {}
        console = data.get("console") or {}
        wifi = data.get("wifi") or {}
        bt = data.get("bluetooth") or {}
        bw = wifi.get("bandwidth") or {}
        # ---- legacy single-mode migration ------------------------------
        wmode = wifi.get("mode")          # rssi_only | full_stack | None
        legacy_ssid = str(wifi.get("ssid", ""))
        bmode = bt.get("mode")            # rssi_only | pair_connect | a2dp_sink
        wifi_cfg = WifiCfg(
            enabled=bool(wifi.get("enabled", False)),
            interface=str(wifi.get("interface", "mlan0")),
            driver_load_cmd=str(wifi.get("driver_load_cmd", "")),
            scan_enabled=bool(wifi.get(
                "scan_enabled",
                wmode in (None, "rssi_only", "full_stack"))),
            scan_ssid=str(wifi.get("scan_ssid", legacy_ssid)),
            rssi_min=int(wifi.get("rssi_min", -70)),
            scan_timeout=float(wifi.get("scan_timeout",
                                       DEFAULT_RF_TIMEOUT)),
            scan_via=str(wifi.get("scan_via", "host")),
            ping_enabled=bool(wifi.get(
                "ping_enabled", wmode == "full_stack")),
            ping_ssid=str(wifi.get("ping_ssid", legacy_ssid)),
            ping_password=str(wifi.get("ping_password",
                                      wifi.get("password", ""))),
            ping_count=int(wifi.get("ping_count", 20)),
            ping_timeout=float(wifi.get("ping_timeout",
                                       DEFAULT_RF_TIMEOUT)),
            iperf_enabled=bool(wifi.get(
                "iperf_enabled", bool(bw.get("enabled", False)))),
            iperf_tool=str(wifi.get("iperf_tool",
                                   bw.get("tool", "iperf3"))),
            iperf_min_mbps=float(wifi.get(
                "iperf_min_mbps", bw.get("min_mbps", 10.0))),
            iperf_server_ip=str(wifi.get(
                "iperf_server_ip", bw.get("server_ip", ""))),
            iperf_duration=int(wifi.get(
                "iperf_duration", bw.get("duration", 10))),
            iperf_timeout=float(wifi.get("iperf_timeout",
                                        DEFAULT_RF_TIMEOUT)),
        )
        bt_cfg = BluetoothCfg(
            enabled=bool(bt.get("enabled", False)),
            rssi_enabled=bool(bt.get(
                "rssi_enabled",
                bmode in (None, "rssi_only", "pair_connect",
                          "a2dp_sink"))),
            expected_name=str(bt.get("expected_name", "")),
            rssi_min=int(bt.get("rssi_min", -70)),
            rssi_timeout=float(bt.get("rssi_timeout",
                                     DEFAULT_RF_TIMEOUT)),
            pair_enabled=bool(bt.get(
                "pair_enabled", bmode == "pair_connect")),
            pair_timeout=float(bt.get("pair_timeout",
                                     DEFAULT_RF_TIMEOUT)),
            l2ping_count=int(bt.get("l2ping_count", 0) or 0),
            tone_enabled=bool(bt.get(
                "tone_enabled", bmode == "a2dp_sink")),
            audio_confirm=bool(bt.get("audio_confirm", True)),
            tone_timeout=float(bt.get("tone_timeout",
                                     DEFAULT_RF_TIMEOUT)),
        )
        return cls(
            dut_type=str(data.get("dut_type", "linux")),
            console=ConsoleCfg(
                enabled=bool(console.get("enabled", False)),
                port=str(console.get("port", "")),
                baudrate=int(console.get("baudrate", 115200)),
                newline=str(console.get("newline", "lf")),
                inter_cmd_delay_ms=int(console.get("inter_cmd_delay_ms", 100)),
                ssh_host=str(console.get("ssh_host", "")),
                ssh_username=str(console.get("ssh_username", "root")),
                test_commands=[
                    ConsoleCommand._from_dict_v2(c)
                    for c in (console.get("test_commands") or [])],
            ),
            wifi=wifi_cfg,
            bluetooth=bt_cfg,
            setup=FctSetupCfg.from_dict(data.get("setup")),
        )

    # ---------------------------------------------------------- validation
    def validate(self) -> list:
        """Returns a list of error strings (empty = valid)."""
        errors: list = []
        c, w, b = self.console, self.wifi, self.bluetooth
        if self.dut_type not in ("bare_metal", "linux"):
            errors.append("dut_type must be bare_metal|linux")
        if c.enabled:
            if not c.port.strip():
                errors.append("console.enabled: port must not be empty")
            if int(c.baudrate) not in BAUDRATES:
                errors.append(f"console.baudrate must be one of "
                              f"{BAUDRATES}")
            if (self.dut_type == "bare_metal" and c.ssh_host.strip()):
                # no OS -> no shell -> no SSH
                errors.append("bare_metal DUT: ssh_host requires "
                              "a Linux shell - remove it")
            if self.dut_type == "bare_metal":
                # Bare metal/RTOS still interacts over SERIAL
                # (Wait->Send->Capture, e.g. a Button/LED prompt answered
                # with yes/no), but SSH and SFTP do not exist without an OS.
                for cmd in c.test_commands:
                    if cmd.transport == "ssh":
                        errors.append(
                            f"bare_metal DUT: command '{cmd.name}' uses SSH "
                            "- serial console is the only transport")
                    if cmd.kind in ("sftp_put", "sftp_get"):
                        errors.append(
                            f"bare_metal DUT: command '{cmd.name}' uses "
                            f"{cmd.kind} - SFTP requires a Linux shell")
        if w.enabled:
            if not (w.scan_enabled or w.ping_enabled or w.iperf_enabled):
                errors.append("wifi.enabled: enable at least one of "
                              "scan / ping / iperf")
            if w.scan_via not in WIFI_SCAN_VIA:
                errors.append(f"wifi.scan_via must be one of "
                              f"{WIFI_SCAN_VIA}")
            if w.scan_enabled and not w.scan_ssid.strip():
                errors.append("wifi scan: scan_ssid (DUT SSID) must not "
                              "be empty")
            if w.scan_timeout < 1 or w.ping_timeout < 1 \
                    or w.iperf_timeout < 1:
                errors.append("wifi timeouts must be >= 1 s")
            if w.ping_enabled:
                if self.dut_type == "bare_metal":
                    errors.append("bare_metal DUT: Wi-Fi connect & ping "
                                  "needs a Linux stack - disable it")
                elif not w.ping_ssid.strip():
                    errors.append("wifi ping: ping_ssid must not be empty")
                elif int(w.ping_count) < 1:
                    errors.append("wifi ping: ping_count must be >= 1")
            if w.iperf_enabled:
                if self.dut_type == "bare_metal":
                    errors.append("bare_metal DUT: iperf needs a Linux "
                                  "stack - disable it")
                elif w.iperf_tool not in BW_TOOLS:
                    errors.append(f"wifi iperf: tool must be one of "
                                  f"{BW_TOOLS}")
                elif float(w.iperf_min_mbps) <= 0:
                    errors.append("wifi iperf: iperf_min_mbps must be > 0")
        if b.enabled:
            if not (b.rssi_enabled or b.pair_enabled or b.tone_enabled):
                errors.append("bluetooth.enabled: enable at least one of "
                              "rssi / pair / tone")
            if b.rssi_timeout < 1 or b.pair_timeout < 1 \
                    or b.tone_timeout < 1:
                errors.append("bluetooth timeouts must be >= 1 s")
            if b.rssi_enabled and not b.expected_name.strip():
                errors.append("bluetooth rssi: expected_name (DUT BT name) "
                              "must not be empty")
            if self.dut_type == "bare_metal":
                if b.pair_enabled:
                    errors.append("bare_metal DUT: BT pair/connect needs a "
                                  "Linux stack - disable it")
                if b.tone_enabled:
                    errors.append("bare_metal DUT: BT A2DP tone needs a "
                                  "Linux stack - disable it")
                if b.l2ping_count > 0:
                    errors.append("bare_metal DUT: L2CAP ping runs on the "
                                  "DUT console - set l2ping_count to 0")
        errors.extend(self.setup.validate())
        return errors


# ---------------------------------------------------------------------------
# mapping to B4 FctStep markers (the runner executes THESE)
# ---------------------------------------------------------------------------
def build_fct_steps(cfg: FctTestConfig,
                    channel_key: str = "ser1") -> list:
    """FctTestConfig -> ordered list[FctStep] for the work flow.

    * console login pairs + test commands: MESSAGE_CHECK steps bound
      to `channel_key`; per-step data travels in params
      (``fct_console_cmd`` with regex expects, ``send`` payload);
    * Wi-Fi / Bluetooth: EXTERNAL_TOOL steps carrying the sub-config
      in params (``tool_family`` + ``fct_rf``) — executed by the B5
      runner branch through the B4 rf_adapters.
    """
    steps: list = []
    c = cfg.console
    if c.enabled:
        # console steps: Wait->Send->Capture primitives (v2 model).
        # Both DUT kinds use the SAME three-stage flow over serial; a
        # bare-metal/RTOS firmware can prompt and accept replies too
        # (e.g. Button/LED: wait for the prompt -> send yes/no ->
        # capture the result). The only console difference is that a
        # bare-metal DUT has no SSH/SFTP transport; RF stays RSSI-only.
        for cmd in c.test_commands:
            # SFTP file-transfer rows
            if cmd.kind in ("sftp_put", "sftp_get"):
                steps.append(FctStep(
                    name=cmd.name or cmd.kind,
                    step_type=STEP_MESSAGE_CHECK, channel=channel_key,
                    timeout_s=float(cmd.send_timeout),
                    retries=int(cmd.retries),
                    params={"fct_console": True, "kind": cmd.kind,
                            "action": cmd.kind,
                            "local": cmd.local, "remote": cmd.remote}))
                continue
            # Map the three-stage model to the MESSAGE_CHECK executor.
            #   WaitFor (wait-only row) -> positive pattern, found=PASS
            #   Capture expected=yes  -> positive=want, negative=forbid
            #   Capture expected=no   -> negative=bad msg, End Line bounds
            is_wait_only = (cmd.wait_enabled and not cmd.send_enabled)
            if is_wait_only:
                pass_pat, neg_pat = cmd.expect_pass, ""
                pass_regex = cmd.expect_pass_is_regex
                neg_regex = False
                is_expected = True
                end_line = ""
            else:
                if cmd.capture_enabled and cmd.capture_is_expected:
                    pass_pat, neg_pat = cmd.expect_fail, cmd.capture_forbid
                elif cmd.capture_enabled:
                    pass_pat, neg_pat = "", cmd.expect_fail
                else:
                    pass_pat, neg_pat = "", ""
                pass_regex = cmd.expect_fail_is_regex
                neg_regex = cmd.expect_fail_is_regex
                is_expected = (cmd.capture_is_expected
                               if cmd.capture_enabled else False)
                end_line = cmd.capture_end_line
            params: dict = {
                "fct_console": True,
                "kind": "wait" if is_wait_only else "send",
                "wait_enabled": cmd.wait_enabled,
                "send_enabled": cmd.send_enabled,
                "capture_enabled": cmd.capture_enabled,
                "wait_pattern": cmd.expect_pass,
                "wait_timeout": float(cmd.wait_timeout),
                "send_timeout": float(cmd.send_timeout),
                "capture_timeout": float(cmd.timeout),
                "capture_end_line": end_line,
                "capture_is_expected": is_expected,
                "case_sensitive": cmd.case_sensitive,
                "expect_pass_re": pass_pat,
                "expect_fail_re": neg_pat,
                "expect_pass_is_regex": pass_regex,
                "expect_fail_is_regex": neg_regex,
            }
            if cmd.send_enabled and (cmd.send or cmd.kind == "send"):
                params["send"] = cmd.send
            base_name = cmd.name or cmd.send or "Console step"
            # a row that both waits and sends becomes two ordered steps:
            # a pre-send WaitFor then the Send+Capture step
            if (not is_wait_only and cmd.wait_enabled
                    and cmd.expect_pass):
                steps.append(FctStep(
                    name=f"{base_name} (wait)",
                    step_type=STEP_MESSAGE_CHECK, channel=channel_key,
                    timeout_s=float(cmd.wait_timeout),
                    retries=int(cmd.retries),
                    params={"fct_console": True, "kind": "wait",
                            "wait_enabled": True, "send_enabled": False,
                            "capture_enabled": False,
                            "expect_pass_re": cmd.expect_pass,
                            "expect_pass_is_regex":
                                cmd.expect_pass_is_regex,
                            "capture_is_expected": True,
                            "case_sensitive": cmd.case_sensitive}))
            steps.append(FctStep(
                name=base_name,
                step_type=STEP_MESSAGE_CHECK, channel=channel_key,
                timeout_s=float(cmd.timeout), retries=int(cmd.retries),
                params=params))
    # Linux DUT only: load the Wi-Fi/BT RF drivers once (editable BSP
    # command; the driver script itself is a BSP deliverable) before any
    # RF sub-test runs.
    if cfg.dut_type == "linux" and (cfg.wifi.enabled or cfg.bluetooth.enabled) \
            and cfg.wifi.driver_load_cmd.strip():
        steps.append(FctStep(
            name="Load RF drivers",
            step_type=STEP_MESSAGE_CHECK, channel=channel_key,
            timeout_s=15.0,
            params={"fct_console": True,
                    "send": cfg.wifi.driver_load_cmd.strip()}))
    if cfg.wifi.enabled:
        w = cfg.wifi
        # 1) scan / RSSI (both DUT kinds). A station-mode Linux DUT can
        #    only report its own RSSI over the console; the default host
        #    scan discovers the DUT-advertised AP/hotspot.
        if w.scan_enabled:
            rf = {"mode": "rssi_only", "ssid": w.scan_ssid,
                  "expected_ssid": w.scan_ssid,
                  "rssi_min": int(w.rssi_min),
                  "interface": w.interface}
            if cfg.dut_type == "linux" and w.scan_via == "dut_console":
                steps.append(FctStep(
                    name="Wi-Fi Scan / RSSI (DUT console)",
                    step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                    timeout_s=float(w.scan_timeout),
                    params={"tool_family": "wifi",
                            "rssi_via": "dut_console", "fct_rf": rf}))
            else:
                steps.append(FctStep(
                    name="Wi-Fi Scan / RSSI",
                    step_type=STEP_EXTERNAL_TOOL, channel="",
                    timeout_s=float(w.scan_timeout),
                    params={"tool_family": "wifi", "fct_rf": rf}))
        # 2) connect & ping (Linux only): host associates to the DUT AP;
        #    PASS as soon as >=1 ping reply is received.
        if w.ping_enabled and cfg.dut_type == "linux":
            steps.append(FctStep(
                name="Wi-Fi Connect & Ping",
                step_type=STEP_EXTERNAL_TOOL, channel="",
                timeout_s=float(w.ping_timeout),
                params={"tool_family": "wifi", "fct_rf": {
                    "mode": "full_stack", "ssid": w.ping_ssid,
                    "expected_ssid": w.ping_ssid,
                    "password": w.ping_password,
                    "ssid_password": w.ping_password,
                    "rssi_min": int(w.rssi_min),
                    "ping_count": int(w.ping_count),
                    "iperf3": False, "any_reply": True,
                    "rf_timeout_s": float(w.ping_timeout)}}))
        # 3) iperf throughput (Linux only; host server / DUT client).
        if w.iperf_enabled and cfg.dut_type == "linux":
            steps.append(FctStep(
                name=f"Wi-Fi iPerf Throughput ({w.iperf_tool})",
                step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                timeout_s=float(w.iperf_timeout),
                params={"tool_family": "wifi",
                        "fct_wifi_iperf": {
                            "tool": w.iperf_tool,
                            "server_ip": w.iperf_server_ip,
                            "min_mbps": float(w.iperf_min_mbps),
                            "duration": int(w.iperf_duration)}}))
    if cfg.bluetooth.enabled:
        b = cfg.bluetooth
        # make the DUT discoverable FIRST (hciconfig piscan per the
        # board FCT_SETUP) - Linux console only.
        if cfg.dut_type == "linux":
            steps.append(FctStep(
                name="BT discoverable (piscan)",
                step_type=STEP_MESSAGE_CHECK, channel=channel_key,
                timeout_s=3.0,
                params={"fct_console": True,
                        "send": "hciconfig hci0 piscan"}))
        # 1) RSSI / discovery (both DUT kinds, host-side inquiry)
        if b.rssi_enabled:
            steps.append(FctStep(
                name="Bluetooth RSSI",
                step_type=STEP_EXTERNAL_TOOL, channel="",
                timeout_s=float(b.rssi_timeout),
                params={"tool_family": "bluetooth", "fct_rf": {
                    "mode": "rssi_only",
                    "expected_name": b.expected_name,
                    "rssi_min": int(b.rssi_min),
                    "rf_timeout_s": float(b.rssi_timeout)}}))
        # 2) pair & connect (Linux only)
        if b.pair_enabled and cfg.dut_type == "linux":
            steps.append(FctStep(
                name="Bluetooth Pair & Connect",
                step_type=STEP_EXTERNAL_TOOL, channel="",
                timeout_s=float(b.pair_timeout),
                params={"tool_family": "bluetooth", "fct_rf": {
                    "mode": "pair_connect",
                    "expected_name": b.expected_name,
                    "rssi_min": int(b.rssi_min),
                    "rf_timeout_s": float(b.pair_timeout)}}))
            # optional L2CAP data-path proof (DUT -> host BT address)
            if b.l2ping_count > 0:
                steps.append(FctStep(
                    name=f"BT L2CAP ping ({b.l2ping_count})",
                    step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                    timeout_s=float(b.pair_timeout),
                    params={"tool_family": "bluetooth",
                            "fct_bt_l2ping": {
                                "count": int(b.l2ping_count)}}))
        # 3) tone / music over A2DP (Linux only; host source -> DUT sink)
        if b.tone_enabled and cfg.dut_type == "linux":
            steps.append(FctStep(
                name="Bluetooth Tone / Music (A2DP)",
                step_type=STEP_EXTERNAL_TOOL, channel="",
                timeout_s=float(b.tone_timeout),
                params={"tool_family": "bluetooth", "fct_rf": {
                    "mode": "a2dp_sink",
                    "expected_name": b.expected_name,
                    "audio_confirm": bool(b.audio_confirm),
                    "rf_timeout_s": float(b.tone_timeout)}}))
    return steps


def _fct_op_step(name: str) -> "FctStep":
    """A standard-operation row (fixture / rack PSU) reused from the
    engine OP_STEPS catalog; ``params.op`` makes to_project_fct_cases
    emit an ``op`` row executed by the standard op runner."""
    return FctStep(name=name, step_type=STEP_GUI_CONFIRM, timeout_s=0.0,
                   params={"op": name})


def wrap_fct_setup(cfg: FctTestConfig, body: list,
                   channel_key: str = "ser1") -> list:
    """Wrap the generated FCT test body with the production spine.

    Order: optional fixture clamp/lock/E-Stop -> power on (rack PSU op OR
    a manual adapter/USB MessageGoStop OR nothing) -> body -> "FCT
    done." -> power off / manual remove prompt -> fixture unlock/release.

    FCT uses NO DAQ; the ATE fixture (when present) is driven through the
    U2355A DIO resource on the real rack (the op names are shared with
    ICT; the instrument routing is resolved at run time).
    """
    s = cfg.setup
    pre: list = []
    post: list = []
    if s.use_fixture:
        pre += [_fct_op_step("Fixture Clamp Down"),
                _fct_op_step("Fixture Lock"),
                _fct_op_step("Fixture E-Stop Healthy")]
        post += [_fct_op_step("Fixture Unlock"),
                 _fct_op_step("Fixture Release")]
    if s.power_mode == POWER_PSU:
        pre.append(_fct_op_step("Power On DUT"))
        post.insert(0, _fct_op_step("Power Off DUT"))
    elif s.power_mode == POWER_MANUAL:
        pre.append(FctStep(name=s.manual_on_message,
                           step_type=STEP_GUI_CONFIRM, timeout_s=0.0))
        post.insert(0, FctStep(name=s.manual_off_message,
                               step_type=STEP_GUI_CONFIRM, timeout_s=0.0))
    # power_mode == POWER_NONE: no power action
    done = FctStep(name="FCT done.", step_type=STEP_MESSAGE_CHECK,
                   expect_pass=["done"], timeout_s=0.0)
    return pre + list(body) + [done] + post

