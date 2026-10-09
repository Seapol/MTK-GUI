# DUT Types for FCT Testing

This document describes the two DUT (Device Under Test) categories supported by the mtk-gui FCT test framework, their differences in testing, and the software configuration required on each DUT side.

---

## 1. Overview

FCT (Functional Circuit Test) supports two DUT categories:

| Type | Description | Typical Platform |
|---|---|---|
| **Bare Metal / RTOS** | No operating system, no shell, no filesystem, no network stack | i.MX RT series MCU, NXP Kinetis, STM32 |
| **Full Stack Linux** | Complete Linux BSP with shell, filesystem, network stack | i.MX 8M/93, NXP FRDM boards, Raspberry Pi |

The DUT type is declared in the product YAML under `dut.type` and automatically determines which test capabilities are available.

```yaml
dut:
  type: "linux"        # "bare_metal" | "linux"
```

---

## 2. Capability Matrix

| Capability | Bare Metal / RTOS | Full Stack Linux |
|---|---|---|
| Serial Console | ✅ | ✅ |
| Interactive serial test (Wait→Send→Capture, e.g. Button/LED) | ✅ | ✅ |
| SSH Connection | ❌ | ✅ |
| SCP/SFTP File Transfer | ❌ | ✅ |
| Host CLI (subprocess) | ❌ | ✅ |
| Wi-Fi `rssi_only` | ✅ | ✅ |
| Wi-Fi `full_stack` (connect + ping + iperf3) | ❌ | ✅ |
| Bluetooth `rssi_only` | ✅ | ✅ |
| Bluetooth `a2dp_sink` (audio playback) | ❌ | ✅ |
| Firmware Flashing | J-Link / Debug Probe | SSH/SCP + shell command |
| Message Judgment Channel | Serial only | Serial + SSH |
| GPIO Test | Direct hardware access | sysfs / libgpiod |

---

## 3. Bare Metal / RTOS DUT

### 3.1 Testing Characteristics

- After power-on, the firmware automatically enters **advertising / discoverable mode** for Wi-Fi and Bluetooth
- Host PC only scans RSSI; no connection, no ping, no audio playback
- All communication goes through the debug serial port
- The serial port still supports the full **Wait → Send → Capture** flow: the firmware may print a prompt (e.g. `PRESS BUTTON 1 THEN CONFIRM`), the host sends a reply (e.g. `y`/`n`), then captures the result (e.g. `LED1 OK`) — used for interactive tests such as Button & LED. Each stage can be enabled/disabled per command, exactly like a Linux DUT.
- No SSH, no SFTP/SCP, no remote shell, no file transfer

### 3.2 DUT Software Configuration Required

The DUT firmware must:

1. **Wi-Fi/Bluetooth advertising**
   - After boot, automatically initialize the Wi-Fi and Bluetooth modules
   - Enter advertising/inquiry mode with a fixed, known SSID / device name
   - Example SSID: `DUT-WIFI-<serial>`
   - Example BT name: `DUT-BT-<serial>`

2. **Serial console output**
   - Print test progress and results to the debug serial port
   - Emit `[PASS]` / `[FAIL]` keywords for FCT message judgment
   - Example:
     ```
     [FCT] Wi-Fi module initialized
     [FCT] Bluetooth advertising started
     [PASS] Boot self-test OK
     ```

3. **Power-on delay**
   - The firmware should complete module initialization within 5–10 seconds
   - The Host PC waits `power_on_delay_sec` (default 8s) before scanning

4. **No network services**
   - No SSH, no SCP, no web server required
   - The test framework disables these capabilities automatically

5. **Firmware flashing (two paths)**

   **Path A: Third-party GUI tool (J-Link / PEmicro / Lauterbach)**
   - Operator runs the debugger GUI manually (documented separately for operators)
   - mtk-gui does not control the flashing process
   - After operator finishes, GUI_CONFIRM dialog asks: "Flash PASS or FAIL?"
   - Operator selects PASS/FAIL; if FAIL, test stops immediately

   **Path B: CLI script / exe (blhost.exe, program.bat, etc.)**
   - mtk-gui executes the CLI command via Host CLI runner
   - Parses stdout/stderr for configurable keywords:
     - Expected PASS message (e.g., "Flash succeeded", "Programming completed")
     - Expected FAIL message (e.g., "Error", "Failed", "Connection failed")
   - Keywords are user-configurable in product YAML
   - Timeout and retry supported

### 3.3 FCT Test Flow

```
Power on DUT
    ↓
Wait power_on_delay_sec (8s)
    ↓
Host PC scans Wi-Fi → read RSSI → judge
Host PC scans Bluetooth → read RSSI → judge
    ↓
Serial tests over the debug port (Wait → Send → Capture):
  read autonomous boot log ([PASS]/[FAIL]) and/or answer firmware
  prompts (e.g. Button/LED: wait prompt → send y/n → capture result)
    ↓
Firmware flash (Path A: GUI tool + operator confirm, or Path B: CLI script auto-parse)
    ↓
Test complete
```

---

## 4. Full Stack Linux DUT

### 4.1 Testing Characteristics

- Complete Linux BSP with shell, filesystem, network stack
- Host PC can SSH in, transfer files, execute commands
- Wi-Fi can be configured as AP (hostapd) or station
- Bluetooth supports A2DP sink profile (audio output via headphone jack)

### 4.2 DUT Software Configuration Required

#### 4.2.1 Driver Loading (BSP Team Responsibility)

The Linux BSP must ensure Wi-Fi and Bluetooth drivers are loaded after boot. Two options:

**Option A: Auto-load at boot (recommended)**
- Add driver modules to `/etc/modules-load.d/`
- Or add to init script

**Option B: Manual load via Host PC**
- BSP team provides a shell script, e.g. `/opt/load_rf_drivers.sh`
- Host PC sends command via SSH/serial:
  ```bash
  sh /opt/load_rf_drivers.sh
  ```
- Wait for drivers to be ready before running RF tests

#### 4.2.2 Network Configuration

- DUT connects to the same network as the Host PC (ethernet or Wi-Fi station mode)
- Record DUT IP address for SSH/SCP
- SSH server enabled (`sshd` running)

#### 4.2.3 Wi-Fi Test Modes

**Mode 1: DUT as AP (Host PC connects to DUT)**
- DUT runs `hostapd` + `dnsmasq` to create a hotspot
- Example configuration:
  ```ini
  # /etc/hostapd.conf
  interface=wlan0
  ssid=DUT-AP-XXXX
  hw_mode=g
  channel=6
  wpa=2
  wpa_passphrase=<password>
  ```
- Host PC connects to this SSID, pings DUT gateway

**Mode 2: DUT as Station (connects to router)**
- DUT connects to factory router
- Host PC pings DUT IP address

#### 4.2.4 Bluetooth A2DP Sink

- Install BlueZ with A2DP sink profile
- Enable audio output via headphone jack
- Example:
  ```bash
  # Check Bluetooth device
  hciconfig

  # A2DP sink should be available
  pactl list sinks | grep -i bluetooth
  ```
- Host PC connects via Bluetooth, switches audio output to DUT, plays test tone
- Human confirms audio from DUT headphone jack (GUI_CONFIRM)

#### 4.2.5 Firmware Flashing (OOBE only)

Linux image (u-boot, flash.bin, dtb, kernel, rootfs) is pre-flashed to SD card or eMMC; DUT boots via bootstrap pins.

**FAT image (not shipped with DUT):**
- Prepared on SD card by test engineers; no MTK tool involvement
- Used for FAT-phase testing only

**OOBE image (shipped on eMMC):**
- Flashed via Host PC CLI using third-party **uuu.exe** (NXP Unified Update Utility) with parameters
- Each DUT must be flashed individually, then power-cycled and verified
- Flow:
  1. Boot DUT into USB download mode (via bootstrap pins / button)
  2. Host PC executes:
     ```bash
     uuu.exe -b oobe_image.sd
     ```
  3. Wait for flash complete, power cycle DUT
  4. Boot into OOBE image and verify

- This is a **CLI_RUN step** in FCT: command template, output parsing (PASS/FAIL keywords), timeout/retry
- No SCP/SSH needed for OOBE flashing itself (uuu.exe drives the DUT over USB)

### 4.3 FCT Test Flow

```
Power on DUT
    ↓
Wait Linux boot complete (10–30s)
    ↓
SSH connect to DUT (keyring credentials)
    ↓
[Optionally] Load RF drivers: sh /opt/load_rf_drivers.sh
    ↓
Wi-Fi test: connect AP / ping / iperf3
Bluetooth test: connect + A2DP audio playback + GUI_CONFIRM
    ↓
Serial: read boot log → PASS/FAIL keywords
    ↓
OOBE flash: uuu.exe via CLI (USB download mode) → verify boot
    ↓
Test complete, report generated
```

---

## 5. YAML Configuration Examples

### 5.1 Bare Metal DUT

```yaml
dut:
  type: "bare_metal"

rf:
  wifi:
    mode: "rssi_only"
    expected_ssid: "DUT-WIFI-XXXX"
    rssi_min: -70
    power_on_delay_sec: 8
  bluetooth:
    mode: "rssi_only"
    expected_name: "DUT-BT-XXXX"
    rssi_min: -70
    power_on_delay_sec: 8

flash:
  # Path A: GUI debugger (J-Link/PEmicro/Lauterbach) + operator confirm
  # Path B: CLI script/exe (blhost.exe, program.bat) + auto-parse
  mode: "cli"               # "gui_confirm" | "cli"
  cli:
    cmd: "blhost.exe -p usb0 -- flash-program /path/firmware.bin"
    expect_pass: "Flash succeeded"
    expect_fail: "Error|Failed"
    timeout_sec: 60

# SSH/SCP sections are ignored automatically
```

### 5.2 Full Stack Linux DUT (e.g., FRDM-IMX93)

```yaml
dut:
  type: "linux"

rf:
  wifi:
    mode: "full_stack"
    expected_ssid: "DUT-AP-XXXX"
    gateway: "192.168.1.1"
    rssi_min: -70
    ping_count: 20
    warmup_packets: 3
  bluetooth:
    mode: "a2dp_sink"
    expected_name: "DUT-BT-XXXX"
    rssi_min: -70

console:
  ssh:
    host: "<dut_ip>"
    port: 22
    username: "root"
    remote_dir: "/tmp/"
    # password stored in OS keyring, not in YAML

flash:
  oobe:
    tool: "uuu"
    cmd_template: "uuu.exe -b {{image_path}}"
    image_path: "/opt/firmware/oobe_image.sd"
    expect_pass: "Success"
    expect_fail: "Error|Failed"
    timeout_sec: 120
```

---

## 6. FCT Test Configuration (Modular & GUI-editable)

All FCT test items are modular and independently configurable via YAML. Every field is editable in the MTK GUI (Equipment page / Yaml Build → Apply to YAML).

### 6.1 Test Item Categories

| Category | Items | Bare Metal | Linux |
|---|---|---|---|
| Basic | serial boot log, message test | ✅ | ✅ |
| Wi-Fi | rssi_only, full_stack (ping/iperf) | rssi_only only | both |
| Bluetooth | rssi_only, pair_connect, a2dp_sink | rssi_only only | all (BSP dependent) |
| Flash | gui_confirm, cli script | both supported | both supported |
| SSH/SCP | remote command, file transfer | ❌ | ✅ |

### 6.2 Serial Console Login Flow (configurable)

```yaml
fct_steps:
  - name: "Login root"
    console:
      port: "/dev/cu.usbmodem*"
      baudrate: 115200
      wait_for: "login:"
      send: "root"
      wait_for: "Password:"
      send: ""          # empty password
      wait_for: "root@"
      timeout: 10
```

### 6.3 Wi-Fi Test Configuration

```yaml
wifi:
  enabled: true
  mode: "rssi_only"           # rssi_only | full_stack
  interface: "mlan0"          # wlan0 | mlan0 (configurable)
  driver_load_cmd: "/root/load_rf_drivers.sh"
  rssi_min: -70
  # full_stack only:
  ssid: "TP-LINK_F68E_AP"
  password: "xxx"             # stored in keyring
  gateway: "192.168.10.1"
  ping_count: 20
  loss_max: 5
  bandwidth:
    enabled: false
    tool: "iperf2"             # iperf2 | iperf3
    min_mbps: 10
```

### 6.4 Bluetooth Test Configuration

```yaml
bluetooth:
  enabled: true
  mode: "rssi_only"            # rssi_only | pair_connect | a2dp_sink
  expected_name: "DUT-BT-XXXX"
  rssi_min: -70
  # pair_connect / a2dp_sink only:
  pair_with: "host"            # host | external_device
  audio_confirm: true          # GUI_CONFIRM for a2dp_sink
```

---

## 7. Validation Checklist

### Bare Metal DUT Validation
- [ ] Firmware auto-enters Wi-Fi/Bluetooth advertising after boot
- [ ] SSID / BT name matches expected configuration
- [ ] RSSI ≥ threshold detected by Host PC
- [ ] Serial output contains PASS/FAIL keywords
- [ ] No SSH/SCP/CLI capabilities required
- [ ] Flash Path A: GUI debugger workflow → operator confirms PASS/FAIL, FAIL stops test
- [ ] Flash Path B: CLI script executes, PASS/FAIL keywords correctly detected

### Full Stack Linux DUT Validation
- [ ] Linux boots and drivers loaded (Wi-Fi + Bluetooth)
- [ ] SSH connection successful (keyring credentials)
- [ ] SCP file upload and read-back verified
- [ ] Wi-Fi AP mode or station mode works
- [ ] Bluetooth A2DP sink: audio plays through headphone jack
- [ ] GUI_CONFIRM passes for audio test
- [ ] OOBE flash via uuu.exe CLI: command executes, PASS keyword detected, DUT boots after flash

---

## 7. Notes

- **Driver loading** for Linux DUT is the BSP team's responsibility. The mtk-gui only sends commands via Console/SSH; it does not implement driver logic.
- **Power-on delay** accounts for the time DUT firmware needs to initialize RF modules before advertising.
- **GUI_CONFIRM** steps require human operator judgment (e.g., "Can you hear audio from the DUT headphone jack?").
- All credentials (SSH passwords, API keys) are stored in the OS keyring, never in plaintext YAML.
