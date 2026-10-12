#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run FRDM-IMX93_FCT_Demo_v1.0.2.yaml on the REAL board, N units.

Loads the published project YAML (the file produced by Build FCT Test
Work Flow -> Apply and Save) and executes its ``fct_test_config`` with the
SAME engine the GUI calls (mtkgui.engine.fct_test_runner.FctTestRunner):

  * serial console adapter (pyserial) bound to the DUT UART;
  * the SFTP get/put rows run over paramiko SSH (key auth, no password in
    the YAML) to the DUT mlan0 address - resolved PER UNIT from the live
    ``ip -4 addr show mlan0`` console answer (DHCP-safe), with the yaml
    ssh_host as fallback;
  * HostCliRunner drives the host-side Wi-Fi/Bluetooth adapters (blueutil,
    SwitchAudioSource, afplay, system_profiler);
  * a host iperf3 server is started for the DUT-client throughput step;
  * operator confirms are REAL MessageYesNo dialogs (the fat.py prompts:
    setup / earphone tone / HDMI visible / RGB colors + the A2DP tone) -
    the operator clicks Yes after the physical check.  Set
    MTK_FCT_HEADLESS=1 to run offscreen with auto-Yes (CI/regression).

Each unit gets a unique random 12-char serial number, its
fat_result.json pulled back over SFTP, a DUT detail PDF + CSV; after N
units a batch summary PDF (+CSV, yield, failures-by-item ranking) is
written.

Usage:  python scripts/run_frdm_fct_demo.py [n_units]
"""
from __future__ import annotations

import os
import random
import re
import string
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

if os.environ.get("MTK_FCT_HEADLESS") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import serial  # pyserial
import paramiko
import yaml

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from mtkgui.engine.fct_test_config import FctTestConfig
from mtkgui.engine.fct_test_runner import FctTestRunner
from mtkgui.engine.host_cli import HostCliRunner
from mtkgui.engine.report import (
    DutReport, ReportItem, BatchSummary, save_dut_csv, save_batch_csv,
    CAT_FCT, CAT_RF)
from mtkgui.gui.report_export import export_pdf, console_log_html
from mtkgui.gui import identity

YAML_PATH = (ROOT / "yaml_plan" / "examples" / "imx93frdm"
             / "FRDM-IMX93_FCT_Demo_v1.0.2.yaml")
OUT_DIR = ROOT / "yaml_plan" / "examples" / "imx93frdm"
IPERF3 = "/usr/local/bin/iperf3"
HEADLESS = os.environ.get("MTK_FCT_HEADLESS") == "1"


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------
class SerialConsole:
    """pyserial-like console the FctTestRunner drives, plus paramiko
    SFTP for the sftp_put / sftp_get rows."""

    def __init__(self, port: str, baud: int, ssh_host: str,
                 ssh_user: str = "root"):
        self.ser = serial.Serial(port, baud, timeout=0.1,
                                 bytesize=8, parity="N", stopbits=1)
        self.write_timeout = 4.0
        # full console transcript of the current unit (raw bytes, ANSI
        # codes included) — dumped into the DUT report PDF after the
        # test table (ANSI stripped there)
        self.transcript = bytearray()
        # ssh_host is resolved LAZILY (first ssh/sftp use): probing the IP
        # at the pre-test login prompt would type the probe as a username
        # and leave getty at 'Password:', breaking the yaml's own login
        # step.  By the first ssh/sftp row the yaml has logged in, run
        # fat.py and started sshd, so the DUT sits at a root shell.
        self._ssh_host_cfg = ssh_host
        self._ssh_host_live = None
        self.ssh_user = ssh_user
        self.key = str(Path.home() / ".ssh" / "id_ed25519")
        self.prime()

    @property
    def ssh_host(self) -> str:
        if self._ssh_host_live is None:
            self._ssh_host_live = self._discover_ip()
            if self._ssh_host_live:
                print(f"[run] DUT mlan0 IP (lazy) = {self._ssh_host_live}")
            else:
                print(f"[run] DUT mlan0 IP probe failed, "
                      f"fallback {self._ssh_host_cfg}")
        return self._ssh_host_live or self._ssh_host_cfg

    @ssh_host.setter
    def ssh_host(self, v: str):
        self._ssh_host_live = v

    def reset_ssh_host(self):
        """Forget the per-unit discovered IP (next ssh/sftp use re-probes)."""
        self._ssh_host_live = None

    def _discover_ip(self):
        """Resolve the DUT mlan0 address from the live serial console
        (DHCP-safe); returns None when the answer is silent."""
        self.reset_input_buffer()
        self.write("\x03\n")             # fresh prompt at a shell
        time.sleep(0.4)
        self.write("ip -4 addr show mlan0\n")
        buf = b""
        deadline = time.time() + 8
        while time.time() < deadline:
            buf += self.ser.read(2048)
            if b"inet " in buf:
                time.sleep(0.3)          # let the answer settle
                buf += self.ser.read(2048)
                break
            time.sleep(0.2)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)",
                      buf.decode("utf-8", "replace"))
        return m.group(1) if m else None

    def prime(self):
        """Make the DUT reprint a fresh prompt so the first WaitFor has new
        bytes to match: Ctrl-C reprints '...#' at a shell or 'login:' at a
        login prompt, then a bare Enter reprints it again. Run once per
        unit because a reused serial port otherwise stays silent."""
        for _ in range(3):
            self.ser.write(b"\x03")
            time.sleep(0.2)
        self.ser.write(b"\n")
        time.sleep(0.4)

    def reset_input_buffer(self):
        self.ser.reset_input_buffer()

    def write(self, data) -> int:
        if isinstance(data, str):
            data = data.encode()
        n = self.ser.write(data)
        self.ser.flush()
        return n

    def read(self, n: int = 4096) -> bytes:
        chunk = self.ser.read(n)
        if chunk:
            self.transcript += chunk
        return chunk

    def transcript_reset(self):
        """Start a fresh transcript for the next unit."""
        self.transcript.clear()

    def transcript_text(self) -> str:
        return self.transcript.decode("utf-8", errors="replace")

    def flush(self):
        self.ser.flush()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def _ssh(self):
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(self.ssh_host, username=self.ssh_user,
                    key_filename=self.key, look_for_keys=True,
                    allow_agent=True, timeout=12, banner_timeout=12,
                    auth_timeout=12)
        return cli

    def get_file(self, remote: str, local: str):
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        cli = self._ssh()
        try:
            sftp = cli.open_sftp()
            sftp.get(remote, local)
            sftp.close()
        finally:
            cli.close()

    def put_file(self, local: str, remote: str):
        cli = self._ssh()
        try:
            sftp = cli.open_sftp()
            sftp.put(local, remote)
            sftp.close()
        finally:
            cli.close()


def random_sn() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(12))


def category_for(name: str) -> tuple:
    low = name.lower()
    if "wi-fi" in low or "wifi" in low or "iperf" in low:
        return CAT_RF, "wifi"
    if "bluetooth" in low or low.startswith("bt ") or "l2cap" in low \
            or "a2dp" in low or "tone" in low:
        return CAT_RF, "bluetooth"
    if "sftp" in low or "ssh" in low:
        return CAT_FCT, "ssh"
    return CAT_FCT, "serial"


def dut_html(product: dict, rep: DutReport) -> str:
    ok = "PASS" in rep.overall_result
    color = "#1d7a3c" if ok else "#b02a2a"
    meta = (
        "<table border='0' cellspacing='0' cellpadding='3'>"
        f"<tr><td>Product</td><td><b>{product['part']}</b></td>"
        f"<td style='padding-left:24px'>Core ID</td><td>{product['core']}</td></tr>"
        "<tr><td>Batch</td>"
        f"<td>{product['batch']}</td>"
        "<td style='padding-left:24px'>Serial Number</td>"
        f"<td><b>{rep.serial_no}</b></td></tr>"
        "<tr><td>Station</td>"
        f"<td>{rep.station_id}</td>"
        "<td style='padding-left:24px'>Operator</td>"
        f"<td>{rep.user}</td></tr>"
        "<tr><td>Time</td>"
        f"<td>{rep.timestamp}</td>"
        "<td style='padding-left:24px'>Overall Result</td>"
        f"<td><font color='{color}'><b>{rep.overall_result}</b></font></td></tr>"
        "</table>")
    def _item_color(result: str) -> str:
        up = (result or "").upper()
        if "PASS" in up:
            return "#1d7a3c"
        if any(k in up for k in ("FAIL", "TIMEOUT", "ERROR")):
            return "#b02a2a"
        return "#555555"        # INFO / WARN / SKIP: neutral
    rows = "".join(
        f"<tr><td>{i.test_name}</td><td>{i.category}</td><td>{i.channel}</td>"
        f"<td align='center'>{i.duration if i.duration else '-'}</td>"
        f"<td align='center'><font color='{_item_color(i.result)}'>"
        f"<b>{'PASS' if 'PASS' in i.result else i.result}</b>"
        f"</font></td></tr>"
        for i in rep.items)
    body = (
        "<table border='1' cellspacing='0' cellpadding='5' width='100%'>"
        "<colgroup>"
        "<col width='270'><col width='70'><col width='85'>"
        "<col width='90'><col width='70'></colgroup>"
        "<tr>"
        "<th bgcolor='#e6ebf0'>Test Item</th>"
        "<th bgcolor='#e6ebf0'>Category</th>"
        "<th bgcolor='#e6ebf0'>Channel</th>"
        "<th bgcolor='#e6ebf0'>Duration (s)</th>"
        "<th bgcolor='#e6ebf0'>Result</th></tr>"
        f"{rows}</table>")
    # full console transcript after the test table (ANSI stripped)
    log_html = console_log_html(rep.console_log) if rep.console_log else ""
    return (
        "<html><head><meta charset='utf-8'></head><body>"
        f"<h2>DUT FCT Test Report &mdash; {product['part']}</h2>"
        f"{meta}<br>{body}{log_html}</body></html>")


def batch_html(product: dict, summary: BatchSummary) -> str:
    rank = "".join(
        f"<tr><td>{n}</td><td align='center'>{c}</td></tr>"
        for n, c in summary.failures_by_item()) or \
        "<tr><td colspan='2'>No failures</td></tr>"
    rows = "".join(
        f"<tr><td>{r.serial_no}</td><td>{r.timestamp}</td>"
        f"<td align='center'><font color='"
        f"{'#1d7a3c' if 'PASS' in r.overall_result else '#b02a2a'}'>"
        f"<b>{r.overall_result}</b></font></td>"
        f"<td align='center'>{sum(1 for i in r.items if 'PASS' in i.result)}/"
        f"{len(r.items)}</td></tr>" for r in summary.reports)
    return (
        "<html><head><meta charset='utf-8'></head><body>"
        f"<h2>Batch FCT Summary &mdash; {product['part']}</h2>"
        "<table border='0' cellspacing='0' cellpadding='3'>"
        f"<tr><td>Core ID</td><td>{product['core']}</td>"
        f"<td style='padding-left:24px'>Batch</td><td>{product['batch']}</td></tr>"
        "<tr><td>Generated</td>"
        f"<td>{datetime.now():%Y-%m-%d %H:%M:%S}</td></tr></table>"
        "<h3>Yield</h3>"
        "<table border='1' cellspacing='0' cellpadding='5'>"
        f"<tr><th bgcolor='#e6ebf0'>Total</th><th bgcolor='#e6ebf0'>PASS</th>"
        f"<th bgcolor='#e6ebf0'>FAIL</th><th bgcolor='#e6ebf0'>Yield</th></tr>"
        f"<tr><td align='center'><b>{summary.n_total}</b></td>"
        f"<td align='center'>{summary.n_pass}</td>"
        f"<td align='center'>{summary.n_fail}</td>"
        f"<td align='center'><b>{summary.yield_pct}%</b></td></tr></table>"
        "<h3>Units</h3>"
        "<table border='1' cellspacing='0' cellpadding='5' width='100%'>"
        "<colgroup><col width='200'><col width='200'><col width='120'>"
        "<col width='120'></colgroup>"
        "<tr><th bgcolor='#e6ebf0'>Serial Number</th>"
        "<th bgcolor='#e6ebf0'>Time</th><th bgcolor='#e6ebf0'>Overall</th>"
        "<th bgcolor='#e6ebf0'>Items Passed</th></tr>"
        f"{rows}</table>"
        "<h3>Failures by item</h3>"
        "<table border='1' cellspacing='0' cellpadding='5'>"
        "<tr><th bgcolor='#e6ebf0'>Test Item</th>"
        "<th bgcolor='#e6ebf0'>Fail Count</th></tr>"
        f"{rank}</table></body></html>")


def gui_ask(question: str) -> bool:
    """REAL operator confirm (MessageYesNo): a modal Yes/No dialog for
    the fat.py interactive prompts (setup / earphone tone / HDMI visible
    / RGB colors) and the A2DP tone - the operator clicks Yes only after
    the physical check.  HEADLESS runs answer Yes automatically.

    When the harness runs in an operator terminal (stdin is a TTY), the
    confirm is a plain y/n prompt instead: a CLI-launched Qt process has
    a Prohibited activation policy on macOS, where dialog clicks are
    unreliable (invisible windows / swallowed Yes events)."""
    if HEADLESS:
        print(f"  [GUI_CONFIRM auto-Yes (headless)] {question}")
        return True
    if sys.stdin.isatty():
        print(f"\n  [CONFIRM] {question}")
        ans = ""
        while ans not in ("y", "n"):
            ans = input("  Type y (confirm) / n (fail): ").strip().lower()
        return ans == "y"
    app = QApplication.instance()
    # No bundle / no TTY: dialog fallback - always-on-top + raise + beep.
    # Mouse clicks on Yes/No work under Prohibited; only key focus is
    # unavailable.
    box = QMessageBox(QMessageBox.Question, "FCT operator confirm",
                      question, QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    box.show()
    box.activateWindow()
    box.raise_()
    app.processEvents()
    QApplication.beep()
    return box.exec() == QMessageBox.Yes


def main() -> int:
    n_units = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    app = QApplication.instance() or QApplication([])

    data = yaml.safe_load(open(YAML_PATH, encoding="utf-8"))
    product = {
        "part": data.get("product", {}).get("part", "FRDM-IMX93"),
        "core": data.get("product", {}).get("core", "94611"),
        "batch": data.get("product", {}).get("batch", "Demo FCT"),
    }
    cfg_data = data.get("fct_test_config")
    if cfg_data is None:
        # published project yaml: the console config lives in the GUI
        # build state's embedded fct_test_config_yaml string (a full
        # yaml doc with a top-level fct_test_config key)
        marks = data.get("yaml_build_state", {}).get("modules", {})
        emb = (marks.get("fct_build", {}).get("params", {})
               .get("fct_test_config_yaml", ""))
        parsed = yaml.safe_load(emb) if emb else None
        if isinstance(parsed, dict) and "fct_test_config" in parsed:
            parsed = parsed["fct_test_config"]
        cfg_data = parsed or {}
    cfg = FctTestConfig.from_dict(cfg_data or {})
    errs = cfg.validate()
    if errs:
        print("[FAIL] yaml fct_test_config invalid:", errs)
        return 1
    print(f"[run] {YAML_PATH.name}  product={product}  units={n_units}")

    station = identity.get_station_id()
    user = identity.get_user()
    print(f"[run] station={station} user={user}")

    con = SerialConsole(cfg.console.port, cfg.console.baudrate,
                        cfg.console.ssh_host, cfg.console.ssh_username)
    host = HostCliRunner(log_sink=lambda m: print("  [host]", m),
                         station_id=station, user=user)

    # host iperf3 server (persistent for all units)
    srv = None
    if cfg.wifi.iperf_enabled:
        srv = subprocess.Popen([IPERF3, "-s", "-p", "5201"],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        print("[run] host iperf3 server started on :5201")

    reports: list = []
    try:
        for u in range(1, n_units + 1):
            sn = random_sn()
            print(f"\n===== UNIT {u}/{n_units}  SN={sn} =====")
            con.transcript_reset()  # full console log for THIS unit
            con.prime()   # fresh prompt for this unit's first WaitFor
            con.reset_ssh_host()   # re-probe IP lazily at first ssh/sftp use
            runner = FctTestRunner(
                cfg, log_sink=lambda m: print("  [fct]", m),
                station_id=station, user=user)
            t0 = time.time()
            out = runner.run(con, host, human_confirm=gui_ask)
            dt = time.time() - t0
            print(f"[run] unit {sn} -> {out['overall']} in {dt:.0f}s")

            rep = DutReport(serial_no=sn, station_id=station, user=user,
                            overall_result=out["overall"],
                            console_log=con.transcript_text())
            for r in out["results"]:
                cat, chan = category_for(r.name)
                rep.items.append(ReportItem(
                    test_name=r.name, category=cat, channel=chan,
                    duration=(f"{r.duration:.1f}" if r.duration else ""),
                    result=r.verdict))
            reports.append(rep)

            # per-unit artefacts
            udir = OUT_DIR / "reports" / sn
            udir.mkdir(parents=True, exist_ok=True)
            pdf = udir / f"FRDM-IMX93_{sn}_FCT.pdf"
            export_pdf(dut_html(product, rep), pdf)
            csv_path = save_dut_csv(rep, udir, batch=product["batch"])
            print(f"[run]   PDF: {pdf}")
            print(f"[run]   CSV: {csv_path}")
            print(f"[run]   items: "
                  f"{sum(1 for i in rep.items if i.result == 'PASS')}"
                  f"/{len(rep.items)} PASS")
            for r in out["results"]:
                if not r.passed:
                    print(f"          FAIL: {r.name} - {r.detail}")
    finally:
        con.close()
        if srv is not None:
            srv.terminate()

    # batch summary
    summary = BatchSummary(reports=reports)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bpdf = OUT_DIR / "reports" / f"FRDM-IMX93_FCT_BatchSummary_{stamp}.pdf"
    export_pdf(batch_html(product, summary), bpdf)
    save_batch_csv(summary, OUT_DIR / "reports", batch=product["batch"])

    print("\n===== BATCH SUMMARY =====")
    print(f"total={summary.n_total} pass={summary.n_pass} "
          f"fail={summary.n_fail} yield={summary.yield_pct}%")
    print(f"batch PDF: {bpdf}")
    for name, cnt in summary.failures_by_item():
        print(f"  FAILED x{cnt}: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
