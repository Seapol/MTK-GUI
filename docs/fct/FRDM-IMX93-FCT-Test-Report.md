# FCT Test Report - FRDM-IMX93 (P3-B5 real-machine acceptance)

```
=== FCT Test Report - FRDM-IMX93 ===
Date: 2026-10-09 13:24 (Asia/Shanghai)
DUT: imx93frdm (NXP i.MX93 FRDM, u-blox MAYA-W276, BD B8:F4:4F:59:51:A0)
Host: macOS 15.5, mtk-gui headless GUI stack (offscreen) + TestRunner
Project YAML: projects/FRDM-IMX93/FRDM-IMX93_i.MX93_EVT-(Proto-1)_rev1.1.yaml
              (built with the MTK GUI pipeline: scripts/build_frdm_imx93_yaml.py,
               0 ICT cases - FCT only, 12 FCT cases, console ser1 on
               /dev/cu.usbmodem53930099631 @ 115200)

1. Console Login
   - wait "login:" (probe newline first) ... PASS (shell prompt found -
     the DUT auto-logs in as root; the tolerance alt-match applies)
   - send "root" ... PASS (no Password stage on this image - autologin)
   - wait shell "root@imx93frdm" ... PASS
   Result: PASS

2. Kernel Check
   - send "uname -a" ... PASS
     (Linux imx93frdm 6.6.36-lts-next-g34fd186d1571 aarch64 GNU/Linux)
   Result: PASS

3. Load RF Drivers
   - send "/root/load_rf_drivers.sh" ... PASS ("RF drivers loaded OK",
     retries=2 configured: the FIRST modprobe after boot can race the
     BT UART - the retry absorbs it)
   Result: PASS

4. Wi-Fi RSSI (rssi_only, DUT console mode)
   - send "iw dev mlan0 link" ... PASS
   - RSSI: -55.0 dBm (threshold -70) ... PASS
   Result: PASS

5. Wi-Fi Ping Gateway (DUT side, Linux DUT)
   - send "ping -c 20 192.168.10.1" ... PASS
   - loss 0.0% (20/20) vs max 5% ... PASS
   Result: PASS

6. Wi-Fi iperf Throughput (DUT client -> host PC iperf3 server)
   - send "iperf3 -c 192.168.10.141 -t 10 -O 1" ... PASS
   - 2.1 Mbps vs min 2.0 Mbps ... PASS
     (bench calibration: BOTH ends are wireless on this bench - the
      airtime is shared, 1-4 Mbps is the physical bottleneck;
      RECALIBRATE for the production form: wireless DUT vs WIRED host
      measured ~17 Mbps with iperf2)
   Result: PASS

7. Bluetooth RSSI (rssi_only)
   - send "hciconfig hci0 piscan" (discoverable) ... PASS
   - host inquiry: blueutil found "FRDM-IMX93-DUT"
     (b8-f4-4f-59-51-a0) ... PASS
   - RSSI: not exposed by macOS for an unpaired discoverable device -
     verdict is DISCOVERY-based per the rssi_only policy
   Result: PASS

8. Bluetooth Data Transfer (L2CAP ping, DUT -> host PC)
   - send "l2ping -c 10 14:7D:DA:D2:BA:B4" (host PC BT address) ... PASS
   - 10 sent, 10 received, 0.0% loss ... PASS
     (L2CAP echo = real payload transferred both directions over the
      Bluetooth link - the functional data-path proof)
   Result: PASS

Overall Result: PASS  (cycle 79.7 s, ICT -> FCT all PASS)

Engine evidence (EventLog, [Station] [User] fields present):
  [..] Console wait 'login:': verdict PASS (keyword 'root@imx93frdm')
  [..] Kernel check: verdict PASS (matched 'Linux imx93frdm')
  [..] Load RF drivers: verdict PASS (matched 'RF drivers loaded OK')
  [..] Wi-Fi FCT (DUT RSSI): verdict PASS (RSSI -55.0 dBm vs min -70.0)
  [..] Wi-Fi DUT ping gateway: verdict PASS (loss 0.0% (20/20) vs max 5.0%)
  [..] Wi-Fi DUT iperf (iperf3): verdict PASS (2.1 Mbps vs min 2.0 Mbps)
  [..] BT discoverable (piscan): verdict PASS (output present)
  [..] Bluetooth FCT: verdict PASS ({})
  [..] BT L2CAP ping (10): verdict PASS (l2ping 14:7D:DA:D2:BA:B4: 10/10, 0.0% loss)
  [..] Overall flow: ICT -> FCT all PASS
```

## Findings baked into the implementation (all verified on the bench)

1. **Association/`login:` exit codes are not evidence** - the login
   chain tolerates an already-open session (alt final-prompt match) and
   the FIRST step probes with a bare newline to elicit a silent prompt.
2. **`SerialWorker` has no send/pop API** - the console adapter is
   `ConsoleBufferChannel` (write -> `mc.write_to_channel`, read ->
   `mc.get_read_buffer` with a line queue; the trailing partial prompt
   line stays visible to the judge).
3. **Queued-signal starvation** - the RX reaches the read buffer via
   queued Qt signals; a blocking capture loop in the GUI thread must
   pump the event loop (`pump=QApplication.processEvents` injected,
   engine stays Qt-free).
4. **Global keyword tables must not judge raw DUT output** - a boot log
   contains `timeout`/`error` words (false negatives); B5 console steps
   judge with their own regex/keywords only.
5. **`op_params` round-trip** - the project YAML save/load used to drop
   non-op `op_params` (the `fct_step` markers) on BOTH sides; fixed -
   this silently turned the whole B4/B5 engine path back into legacy
   placeholder verdicts (the original fake-PASS discovery).
6. **iperf note** - `iperf2` (DUT-side server per the board README) is
   the board's tool; the Wi-Fi full_stack bandwidth step on the host
   side uses `iperf3` (`bandwidth.tool` selects).
7. **DUT setup for rssi_only** (per /root/FCT_SETUP.md on the board):
   `load_rf_drivers.sh` after every boot; Wi-Fi station join via
   `wpa_supplicant -B -i mlan0 -c /etc/wpa_supplicant.conf` + `udhcpc`;
   BT discoverable via `hciconfig hci0 piscan` (+ name set once).

## Deliverables (P3-B5)

- `mtkgui/engine/fct_test_config.py` - YAML data model + FctStep builder
- `mtkgui/engine/fct_test_runner.py` - executor (timeout + output-stream
  matching) + report builder
- `mtkgui/gui/yamlbuild/FCTTestConfigWidget.py` - block 07 GUI (Console /
  Wi-Fi / Bluetooth tabs)
- Yaml Build block 07 integration + project YAML round-trip
  (`op_params.fct_step` markers preserved)
- `tests/engine/test_fct_test_config.py` (16) +
  `tests/yamlbuild/test_fct_test_panel.py` (3)
- `scripts/build_frdm_imx93_yaml.py` / `scripts/run_frdm_fct.py`
- Full regression: 1452 passed / 3 skipped / 0 failed
