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
        mode: "rssi_only"          # rssi_only | full_stack
        ssid: "FRDM-IMX93-DUT"     # scanned (rssi_only) or joined
        password: ""               # full_stack join password
        gateway: "192.168.10.1"
        ping_count: 20
        loss_max: 5
        rssi_min: -70
        bandwidth: {enabled: false, tool: iperf2, min_mbps: 10}
      bluetooth:
        enabled: true
        mode: "rssi_only"          # rssi_only | pair_connect | a2dp_sink
        expected_name: "FRDM-IMX93-DUT"
        rssi_min: -70
        audio_confirm: true
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..gui.yamlbuild.fct_build import (
    STEP_EXTERNAL_TOOL,
    STEP_MESSAGE_CHECK,
    FctStep,
)

BAUDRATES = (9600, 19200, 38400, 57600, 115200)
WIFI_MODES = ("rssi_only", "full_stack")
BT_MODES = ("rssi_only", "pair_connect", "a2dp_sink")
BW_TOOLS = ("iperf2", "iperf3")

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
    send: str = ""                  # command line(s), \n separated; {{var}} rendered
    expect_pass: str = ""           # exact match (default) or regex
    expect_fail: str = ""           # exact match (default) or regex, wins over expect_pass
    expect_pass_is_regex: bool = False   # False = exact substring match
    expect_fail_is_regex: bool = False
    timeout: float = DEFAULT_CMD_TIMEOUT
    retries: int = 0                # extra attempts on FAIL (fct_exec)
    extract: str = ""               # "name=regex" lines; group 1 -> variables
    action: str = ""                # sftp_put | sftp_get (transport=ssh rows)
    local: str = ""                 # sftp local path (Host PC)
    remote: str = ""                # sftp remote path (DUT)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name,
                "transport": self.transport, "send": self.send,
                "expect_pass": self.expect_pass,
                "expect_fail": self.expect_fail,
                "expect_pass_is_regex": self.expect_pass_is_regex,
                "expect_fail_is_regex": self.expect_fail_is_regex,
                "timeout": float(self.timeout),
                "retries": int(self.retries),
                "extract": self.extract, "action": self.action,
                "local": self.local, "remote": self.remote}


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
class BandwidthCfg:
    enabled: bool = False
    tool: str = "iperf2"
    min_mbps: float = 10.0
    server_ip: str = ""             # host PC running the iperf server

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "tool": self.tool,
                "min_mbps": float(self.min_mbps),
                "server_ip": self.server_ip}


@dataclass
class WifiCfg:
    enabled: bool = False
    mode: str = "rssi_only"
    interface: str = "mlan0"
    driver_load_cmd: str = ""
    rssi_min: int = -70
    # full_stack only
    ssid: str = ""
    password: str = ""
    gateway: str = ""
    ping_count: int = 20
    loss_max: float = 5.0
    bandwidth: BandwidthCfg = field(default_factory=BandwidthCfg)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled, "mode": self.mode,
            "interface": self.interface,
            "driver_load_cmd": self.driver_load_cmd,
            "rssi_min": int(self.rssi_min),
            "ssid": self.ssid, "password": self.password,
            "gateway": self.gateway, "ping_count": int(self.ping_count),
            "loss_max": float(self.loss_max),
            "bandwidth": self.bandwidth.to_dict(),
        }


@dataclass
class BluetoothCfg:
    enabled: bool = False
    mode: str = "rssi_only"
    expected_name: str = ""
    rssi_min: int = -70
    audio_confirm: bool = True
    # data-transfer proof (Linux DUT): L2CAP ping DUT -> host PC BT
    # address (BlueZ l2ping, real echo both ways); 0 = off
    l2ping_count: int = 10

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled, "mode": self.mode,
            "expected_name": self.expected_name,
            "rssi_min": int(self.rssi_min),
            "audio_confirm": self.audio_confirm,
            "l2ping_count": int(self.l2ping_count),
        }


@dataclass
class FctTestConfig:
    """The whole `fct_test_config:` node (block 07 three tabs)."""

    dut_type: str = "linux"              # bare_metal | linux
    console: ConsoleCfg = field(default_factory=ConsoleCfg)
    wifi: WifiCfg = field(default_factory=WifiCfg)
    bluetooth: BluetoothCfg = field(default_factory=BluetoothCfg)

    # ------------------------------------------------------------ YAML IO
    def to_dict(self) -> dict:
        return {
            "dut_type": self.dut_type,
            "console": self.console.to_dict(),
            "wifi": self.wifi.to_dict(),
            "bluetooth": self.bluetooth.to_dict(),
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
                    ConsoleCommand(
                        kind=str(c.get("kind", "send")),
                        name=str(c.get("name", "")),
                        transport=str(c.get("transport", "serial")),
                        send=str(c.get("send", "")),
                        expect_pass=str(c.get("expect_pass", "")),
                        expect_fail=str(c.get("expect_fail", "")),
                        expect_pass_is_regex=bool(c.get("expect_pass_is_regex", False)),
                        expect_fail_is_regex=bool(c.get("expect_fail_is_regex", False)),
                        timeout=float(c.get("timeout",
                                            DEFAULT_CMD_TIMEOUT)),
                        retries=int(c.get("retries", 0) or 0),
                        extract=str(c.get("extract", "")),
                        action=str(c.get("action", "")),
                        local=str(c.get("local", "")),
                        remote=str(c.get("remote", "")))
                    for c in (console.get("test_commands") or [])],
            ),
            wifi=WifiCfg(
                enabled=bool(wifi.get("enabled", False)),
                mode=str(wifi.get("mode", "rssi_only")),
                interface=str(wifi.get("interface", "mlan0")),
                driver_load_cmd=str(wifi.get("driver_load_cmd", "")),
                rssi_min=int(wifi.get("rssi_min", -70)),
                ssid=str(wifi.get("ssid", "")),
                password=str(wifi.get("password", "")),
                gateway=str(wifi.get("gateway", "")),
                ping_count=int(wifi.get("ping_count", 20)),
                loss_max=float(wifi.get("loss_max", 5.0)),
                bandwidth=BandwidthCfg(
                    enabled=bool(bw.get("enabled", False)),
                    tool=str(bw.get("tool", "iperf2")),
                    min_mbps=float(bw.get("min_mbps", 10.0)),
                    server_ip=str(bw.get("server_ip", ""))),
            ),
            bluetooth=BluetoothCfg(
                enabled=bool(bt.get("enabled", False)),
                mode=str(bt.get("mode", "rssi_only")),
                expected_name=str(bt.get("expected_name", "")),
                rssi_min=int(bt.get("rssi_min", -70)),
                audio_confirm=bool(bt.get("audio_confirm", True)),
                l2ping_count=int(bt.get("l2ping_count", 10) or 0),
            ),
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
        if w.enabled:
            if w.mode not in WIFI_MODES:
                errors.append(f"wifi.mode must be one of {WIFI_MODES}")
            if w.mode == "full_stack":
                if not w.ssid.strip():
                    errors.append("wifi.full_stack: ssid must not be "
                                  "empty")
            if w.bandwidth.enabled and not w.bandwidth.server_ip.strip():
                errors.append("wifi.bandwidth.enabled: server_ip (the "
                              "host PC running the iperf server) is "
                              "required")
            if (self.dut_type == "bare_metal"
                    and w.bandwidth.enabled):
                errors.append("bare_metal DUT: bandwidth iperf runs on "
                              "the DUT console - not available")
        if b.enabled:
            if b.mode not in BT_MODES:
                errors.append(f"bluetooth.mode must be one of {BT_MODES}")
            if not b.expected_name.strip():
                errors.append("bluetooth.expected_name must not be "
                              "empty")
            if self.dut_type == "bare_metal" and b.l2ping_count > 0:
                errors.append("bare_metal DUT: L2CAP ping runs on the "
                              "DUT console - set l2ping_count to 0")
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
        # console steps: wait/send/capture primitives (v2 model)
        # bare metal: capture-only unless the firmware defines a
        # command protocol ("send" is optional per row)
        for cmd in c.test_commands:
            params: dict = {"fct_console": True,
                            "expect_pass_re": cmd.expect_pass,
                            "expect_fail_re": cmd.expect_fail,
                            "kind": cmd.kind}
            # send: kind=send always sends (even empty newline);
            # kind=capture sends only if non-empty; kind=wait never sends
            if cmd.kind == "send":
                params["send"] = cmd.send
            elif cmd.kind == "capture" and cmd.send:
                params["send"] = cmd.send
            steps.append(FctStep(
                name=cmd.name or cmd.send or "Console step",
                step_type=STEP_MESSAGE_CHECK, channel=channel_key,
                timeout_s=float(cmd.timeout), retries=int(cmd.retries),
                params=params))
    if cfg.wifi.enabled:
        if cfg.wifi.mode == "rssi_only" and cfg.dut_type == "linux":
            # station-mode Linux DUT: the RSSI is read ON THE DUT over
            # the console (iw dev <interface> link -> "signal: -X dBm";
            # the board's own FCT_SETUP.md defines this interface) - a
            # host-side scan cannot see a station
            steps.append(FctStep(
                name="Wi-Fi FCT (DUT RSSI)",
                step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                timeout_s=15.0,
                params={"tool_family": "wifi",
                        "rssi_via": "dut_console",
                        "fct_rf": cfg.wifi.to_dict()}))
        elif cfg.wifi.mode == "rssi_only":
            # bare metal: HOST-side discovery of the DUT-advertised
            # SSID (B4 WifiAdapter rssi_only, discovery-based verdict)
            steps.append(FctStep(
                name="Wi-Fi FCT (host scan)",
                step_type=STEP_EXTERNAL_TOOL, channel="",
                timeout_s=30.0,
                params={"tool_family": "wifi",
                        "fct_rf": cfg.wifi.to_dict()}))
        else:
            steps.append(FctStep(
                name="Wi-Fi FCT", step_type=STEP_EXTERNAL_TOOL,
                channel="", timeout_s=60.0,
                params={"tool_family": "wifi",
                        "fct_rf": cfg.wifi.to_dict()}))
        # Linux DUT connectivity + throughput: ping the gateway and run
        # iperf (DUT client -> host PC server) over the console
        w = cfg.wifi
        if w.gateway and cfg.dut_type == "linux":
            steps.append(FctStep(
                name="Wi-Fi DUT ping gateway",
                step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                timeout_s=float(w.ping_count) + 10.0,
                params={"tool_family": "wifi",
                        "fct_wifi_ping": {
                            "gateway": w.gateway,
                            "count": w.ping_count,
                            "loss_max": w.loss_max}}))
        if w.bandwidth.enabled and cfg.dut_type == "linux":
            steps.append(FctStep(
                name=f"Wi-Fi DUT iperf ({w.bandwidth.tool})",
                step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                timeout_s=60.0,
                params={"tool_family": "wifi",
                        "fct_wifi_iperf": {
                            "tool": w.bandwidth.tool,
                            "server_ip": w.bandwidth.server_ip,
                            "min_mbps": w.bandwidth.min_mbps,
                            "duration": 10}}))
    if cfg.bluetooth.enabled:
        # make the DUT discoverable FIRST (hciconfig piscan per the
        # board FCT_SETUP) - hci0 UP RUNNING PSCAN alone is invisible
        # to a host-side inquiry.  Linux console only.
        if cfg.dut_type == "linux":
            steps.append(FctStep(
                name="BT discoverable (piscan)",
                step_type=STEP_MESSAGE_CHECK, channel=channel_key,
                timeout_s=3.0,
                params={"fct_console": True,
                        "send": "hciconfig hci0 piscan"}))
        steps.append(FctStep(
            name="Bluetooth FCT", step_type=STEP_EXTERNAL_TOOL,
            channel="", timeout_s=60.0,
            params={"tool_family": "bluetooth",
                    "fct_rf": cfg.bluetooth.to_dict()}))
        # data-transfer proof: L2CAP ping DUT -> host PC BT address
        # (BlueZ l2ping echoes real payload both ways)
        if cfg.bluetooth.l2ping_count > 0 and cfg.dut_type == "linux":
            steps.append(FctStep(
                name=f"BT L2CAP ping ({cfg.bluetooth.l2ping_count})",
                step_type=STEP_EXTERNAL_TOOL, channel=channel_key,
                timeout_s=float(cfg.bluetooth.l2ping_count) * 3.0 + 10.0,
                params={"tool_family": "bluetooth",
                        "fct_bt_l2ping": {
                            "count": cfg.bluetooth.l2ping_count}}))
    return steps
