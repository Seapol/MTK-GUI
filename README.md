# MTK GUI — Manufacturing Test Kit

A cross-platform **manufacturing test tool** built with Python and PySide6. It covers the complete production flow **ICT → Flash FAT Firmware → FCT → Flash OOBE Firmware**, and also provides multi-channel **serial / SSH consoles** for embedded board bring-up. The same code runs on **Windows, macOS and Linux**, and PyInstaller packages it into a native executable for each platform.

Development happens on macOS while the real test station runs on Windows. To keep bring-up time on the production floor minimal, the application ships with a complete **Virtual mode** (virtual instruments, fixture, PSU, DUT, Wi-Fi/Bluetooth and fault injection) that reproduces the entire station behaviour without any hardware attached — see [Virtual mode](#virtual-mode).

## Final test rack

| Instrument | Role | Interface |
|---|---|---|
| **DAQ973A** mainframe | Built-in 6.5-digit DMM; 3 slots | GPIB (+ LAN/USB) |
| **DAQM908A #1 / #2** | 40-ch SE MUX each; CH101–140 / CH201–240 → TP_P1–P80; 2-wire Ω then DCV | inside DAQ973A |
| **DAQM907A** | Totalizer 0–100 kHz (CLK1 32.768 kHz); 2× 16-bit AO ±12 V → TP_ADC0/1; 16-ch open-drain DIO → fixture control board | inside DAQ973A |
| **U2355A** | 12-ch analog input capture of the power-rails up sequence (→ CSV + waveform); 2 counters ≤6 MHz (CLK2 4 MHz / CLK3 6 MHz); 24 TTL DIO → DUT GPIO | USB |
| **N5747A** | DC power supply, 60 V / 12.5 A / 750 W, 4-wire remote sense, 5/12/24/48 V profiles, hardware inhibit on E-Stop | LAN (+ USB/GPIB) |

The DUT and every instrument share a single-point star ground on the fixture probe board.

## Production flow

```
ICT ──► Flash FAT firmware ──► FCT ──► Flash OOBE firmware
```

- **ICT** (numeric tests, verdict from limits — in range ⇒ PASS, otherwise FAIL):
  fixture interlocks → 80-point 2-wire impedance shorts (R_min threshold, 1.5 Ω
  tolerance; catches low-impedance shorts before power is applied) → power on →
  12-channel power-rails up-sequence capture → 80-point DC voltage (±0.1 %) →
  three clocks (32.768 kHz / 4 MHz / 6 MHz) → AO→ADC stimulus → fixture DIO →
  24 DUT GPIO.
- **Flash FAT / OOBE firmware** are FCT steps. A third-party GUI flasher
  (e.g. J-Link Flash) is followed by an operator PASS/FAIL dialog; a CLI flasher
  is parsed automatically.
- **FCT** are *message tests*: text captured from a serial console, an operator
  dialog, or a CLI/PowerShell terminal is checked for the presence of
  `Pass` / `Success` (or the absence of `Fail` / `Error`). This covers core
  modules, peripherals and RF connectivity (Wi-Fi, Bluetooth, UWB, V2X, 5G
  modem, GNSS — RSSI and iperf throughput checks).
- The **OOBE** step additionally verifies fast boot and the correct software
  version.

## Virtual mode

Virtual mode is selected on the login dialog and is **Supervisor-only**;
Operators always run Real mode. It simulates the complete station so the whole
flow can be developed and regression-tested on a machine with no instruments.

### Virtual rack (`mtkgui/virtual_hardware.py`, no Qt dependency)

The method signatures deliberately mirror the future SCPI/IVI backend, so
bringing up the real drivers is a drop-in replacement:

- **VirtualDAQ973A** — 80 multiplexed points (CH101–140 / CH201–240) for
  2-wire Ω and DCV; DAQM907A totalizer (CLK1), ±12 V AO stimulus and open-drain
  DIO. Each test point gets a hash-seeded, deterministic baseline with
  lognormal unit-to-unit spread; healthy readings sit inside the limits,
  injected failures fall out of range. GND reference points read ~0 V.
- **VirtualU2355A** — 12-ch AI power-rails capture with per-rail rise time,
  overshoot, ripple and fresh random entropy on every capture; two counters
  (CLK2/CLK3); a 24-channel walking-pattern GPIO test that reports the failing
  channel number.
- **VirtualPSU (N5747A)** — output on/off, voltage/current programming with
  ~0.15 % readback error; the E-Stop hardware loop *inhibits* the output, so
  `OUTP ON` while the loop is open is rejected (Error) and the supply stays off.
- **VirtualFixture** — the four DAQM907A DIO interlocks (lid press, in-position
  lock, DUT presence active-low, E-Stop healthy active-low). Running without the
  fixture clamped down is refused; a simulated press fault reports DUT absence
  or clamp timeout.

### Virtual DUT (`mtkgui/virtual_dut.py`)

A background QThread simulates the serial DUT from an editable profile
(`mtkgui/config/virtual_dut.json`, built-in FRDM-IMX93 default): U-Boot/kernel
boot log, login prompt, and command replies including `wifi_test --scan`
(SSID + RSSI), `bt_test --scan`, `iperf3` throughput and `ping`. Injected
faults (no response / wrong reply) are **one-shot** — they affect a single
command and are then cleared, so they never latch the simulator.

### Fault injection (Settings → Virtual Fault Injection)

Two independent percentages, both **0 % by default**, persisted in
`mtkgui/config/virtual_fault.json`:

- **Test fail ratio** — a measurement or message test comes back out of range
  / failing (product FAIL).
- **Equipment error ratio** — an instrument, fixture, PSU or console reports an
  error (Virtual Error, station/equipment failure).

A single uniform random draw per faultable step makes the two classes mutually
exclusive, so the observed ratios match the configured percentages. The same
policy drives ICT measurements, rail capture, fixture/PSU/instrument ops,
console capture/wait steps, CLI steps and RF tests.

### Rails capture data

The 12-channel capture is written to `logs/` as a CSV with a timestamp column
and **real volts per rail** (not normalized fractions), sampled at the project
YAML's `sample_rate_hz` for `duration_s`. The Test Work Flow page plots the
waveform and an AI waveform review grades level, delay, rise time, overshoot,
settling and ripple. Injected rail faults include a stuck-at-0 rail or excessive
overshoot/ripple, and the CSV + review are marked FAIL; an equipment error
produces no CSV.

### Project YAML

`config/*.yaml` defines the product project: ICT and FCT rows (name, kind,
enable, timeout, unit, min/max limits, op parameters), the power-rail list and
the capture settings (`duration_s`, `sample_rate_hz`). Load a project from the
**File** menu; edits in the sequence editor are written back on save.

## Consoles

Any number of **serial** channels and **SSH** channels can be open at the same
time. The two production UARTs are:

| Port | Connects to |
|---|---|
| **DUT** (UART1) | the Device Under Test, primary UART |
| **AUX** (UART2 / Companion) | either the DUT second UART, or a companion / golden test board attached to the station |

Each channel has independent connection settings, a console with millisecond
timestamps, a send line, HEX display/send and TX/RX byte counters. A channel's
**Console** button opens a dedicated console window that keeps receiving
in the background when hidden.

Features:

- Adjustable console background (**View** menu, defaults to black); the text palette switches between dark and light for contrast
- **ANSI color rendering**: standard and bright colors, 256-color and true color, bold/italic/underline/reverse; non-color escapes are stripped
- Auto-enumerated serial ports with per-port refresh (pyserial; Windows/macOS/Linux)
- Per-port baud rate, data bits, parity, stop bits, hardware flow control
- Configurable **Quick Commands** panel with a destination selector (DUT / AUX / Both)
- Enter-to-send command line, optional CR+LF terminator, Up/Down history
- Per-console Clear and Save-log actions; status-bar connection state and byte counters
- Fully English UI, source and documentation

## Project layout

```
mtk-gui/
├── main.py                    # Entry point
├── requirements.txt
├── smoke_test.py              # Headless smoke / regression test
├── config/
│   ├── FRDM-IMX93_12345_Dev_rev1.1.yaml   # Demo project (ICT/FCT/rails)
│   ├── *_Nets.xlsx                         # Test-point net list
│   └── permissions.json
├── mtkgui/
│   ├── main_window.py         # Main window, menus, mode/role integration
│   ├── equipment_page.py      # Equipment block diagram + config dialogs
│   ├── test_workflow_page.py  # Flow tables, waveform, CSV, test engine
│   ├── project_config.py      # YAML project load / apply / save
│   ├── virtual_hardware.py    # Virtual DAQ973A / U2355A / PSU / fixture
│   ├── virtual_dut.py         # Virtual serial DUT (profile driven)
│   ├── virtual_mode.py        # Fault-injection settings dialog
│   ├── permissions.py         # Supervisor / Operator roles
│   ├── at_commands.py
│   ├── ansi.py                # ANSI SGR decoder
│   ├── theme.py / style.py    # Palettes and QSS
│   ├── serial_worker.py       # Background serial reader (QThread)
│   ├── ssh_worker.py          # Background SSH channel (paramiko, lazy import)
│   ├── serial_params.py / quick_commands.py
│   ├── config/
│   │   ├── virtual_fault.json # Fault ratios (created on first change)
│   │   └── virtual_dut.json   # Optional custom virtual DUT profile
│   └── widgets/
│       ├── multi_console.py     # Multi-channel console manager
│       ├── connection_panel.py
│       ├── console_widget.py
│       └── send_panel.py
├── scripts/
│   ├── capture_preview.py     # Offscreen page screenshots
│   ├── build_windows.bat
│   ├── build_macos.sh
│   └── build_linux.sh
└── preview/                   # Generated page previews
```

## Requirements

- Python **3.9 – 3.13** (3.11 / 3.12 recommended)
- Windows 10/11, macOS 11+ (Intel and Apple Silicon), or a mainstream Linux distribution (Ubuntu 20.04+, etc.)
- Python packages: `PySide6`, `pyserial`, `PyYAML`, `paramiko` (optional, SSH), `pyinstaller` (packaging only) — see `requirements.txt`

## Run from source

The virtual environment is named **`mtk_gui`** on every platform.

### Windows (CMD / PowerShell)

```bat
cd mtk-gui
py -3 -m venv mtk_gui
mtk_gui\Scripts\activate
pip install -r requirements.txt
python main.py
```

### macOS / Linux

```bash
cd mtk-gui
python3 -m venv mtk_gui
source mtk_gui/bin/activate
pip install -r requirements.txt
python main.py
```

On startup choose the role (Supervisor / Operator) and, for Supervisors,
**Real** or **Virtual** mode. Load a project YAML from **File**, then press
**Run**. In Virtual mode every instrument, the fixture and the DUT are
simulated; open a serial channel on the fake port to interact with the virtual
DUT directly.

## Pages

The window has two tabs; the consoles live inside the Test Work Flow page and
in per-channel popup windows.

| Tab | Purpose |
|---|---|
| **Test Work Flow** | Product/run control, overall flow table (ICT → Flash FAT → FCT → Flash OOBE), ICT measurement table (Ω · V · Hz with limits and live measured values), 12-channel power-rails waveform + CSV log + AI review, FCT message-test table, embedded console area, event log and yield/cycle-time summary. |
| **Equipment** | Block diagram of the final rack in four layers — HOST PC + peripherals / instruments (DAQ973A + DAQM908A×2 + DAQM907A, U2355A, N5747A) / ATE fixture / DUT board. Every block is clickable and opens its configuration and connection window. Color-coded trunks show measurement, up-sequence, clock, AO, DIO, power/sense and ground paths. Right-click copies the diagram as an image. |

Offscreen previews (no display needed):

```bash
QT_QPA_PLATFORM=offscreen ./mtk_gui/bin/python scripts/capture_preview.py
```

Output: `preview/equipment.png`, `preview/test_workflow.png`,
`preview/serial_console.png` (the last one shows the virtual DUT boot log).

## Quick command snippets

Quick commands are generic serial snippets, not tied to any particular command
set. Optionally create `config/commands.json` to match your board (built-in
defaults are used when the file is missing or invalid):

```json
[
    {"label": "AT", "command": "AT", "crlf": true},
    {"label": "Version", "command": "fw_version", "crlf": true},
    {"label": "Self Test", "command": "factory_selftest", "crlf": false}
]
```

- `label` is shown on the button; `command` is the text actually sent.
- `crlf` controls whether `\r\n` is appended.
- The destination is selected with the **Target** dropdown (DUT, AUX or Both).
- For a packaged app, place an edited copy in a `config/` folder next to the executable.

## Testing

No hardware is required. The headless smoke test covers window and role/mode
creation, both pages, a real mouse click on an Equipment block, port
enumeration, ANSI/HEX rendering, quick commands, dialogs, permissions, the full
Test Work Flow demo run (including the 12-channel CSV), plus the virtual-mode
regression suite:

- fault-policy statistics and fail/error mutual exclusion;
- the full virtual rack sequence (fixture interlocks, 80 Ω points, power on,
  80 voltage points, 3 clocks, AO→ADC, fixture DIO, 24 GPIO), unpowered
  failures, forced FAIL/Error and E-Stop inhibit;
- rails capture health/fault/error paths and CSV storing real volts;
- a 100 % equipment-error run and a 100 % fail run;
- one-shot virtual DUT fault behaviour (the command after a fault is answered
  normally again);
- pre-FCT connection gating and YAML round-trip.

```bash
QT_QPA_PLATFORM=offscreen ./mtk_gui/bin/python -u smoke_test.py
```

`ALL SMOKE TESTS PASSED` indicates success. On Windows use
`QT_QPA_PLATFORM=offscreen mtk_gui\Scripts\python.exe -u smoke_test.py`.

## Packaging with PyInstaller

> **PyInstaller cannot cross-compile.** Build the Windows `.exe` on Windows, the macOS `.app` on macOS, and the Linux binary on Linux.

### Option 1 — one-click scripts (recommended)

| Platform | Command | Output |
|---|---|---|
| Windows | `scripts\build_windows.bat` | `dist\MTK_GUI\MTK_GUI.exe` + `dist\MTK_GUI_win64.zip` |
| macOS | `bash scripts/build_macos.sh` | `dist/MTK_GUI.app` |
| Linux | `bash scripts/build_linux.sh` | `dist/MTK_GUI/MTK_GUI` |

Each script creates the `mtk_gui` virtual environment if needed, installs dependencies and runs the build. The Windows script builds from `MTK_GUI_windows.spec`, which **bundles the `config/` folder into the package** (`_internal/config/`, where the packaged app looks for it first) and also packs the distributable zip.

### Option 2 — manual build

Create and activate the `mtk_gui` environment and install the requirements first, then:

**Windows (recommended — bundles the `config/` folder):**

```bat
pyinstaller --noconfirm MTK_GUI_windows.spec
```

**macOS / Linux (generic):**

```bash
pyinstaller --noconfirm --windowed --name MTK_GUI --collect-submodules serial main.py
```

Flag reference:

- `--windowed` — GUI application with no console window (applies on Windows/macOS)
- `--name MTK_GUI` — executable/application name
- `--collect-submodules serial` — make sure every pyserial submodule (including port enumeration) is bundled
- The default is **onedir**: ship the whole `dist/MTK_GUI/` folder; it starts faster and is more robust.
- Add `--onefile` for a single executable (slower startup; unpacks to a temp directory on each run).
- Add an icon with `--icon=assets/icon.ico` on Windows or `--icon=assets/icon.icns` on macOS.

### Option 3 — cloud build with GitHub Actions

`.github/workflows/build_windows.yml` builds the Windows exe on GitHub's servers — no local Python setup needed on the build machine:

- **Manual run:** repo page → **Actions** → *Build Windows exe* → **Run workflow**; download `MTK_GUI_win64` (a zip of `MTK_GUI\`) from the run's artifacts.
- **Tag release:** push a `v*` tag and the zip is additionally attached to a GitHub Release:

  ```bash
  git tag v2.0.0 && git push origin v2.0.0
  ```

The workflow uses `MTK_GUI_windows.spec`, so the `config/` folder is bundled automatically.

### Distribution

- **Windows:** copy the entire `dist\MTK_GUI\` folder; users run `MTK_GUI.exe`.
- **macOS:** copy `MTK_GUI.app` to `/Applications`.
- **Linux:** copy the entire `dist/MTK_GUI/` folder and run the `MTK_GUI` binary (create a `.desktop` file if desired).

## Syncing code between the Mac (dev) and Windows (build) machines

The repository lives on GitHub; both machines share the same `main` branch. Core rule: **commit and push from whichever side you edited, then pull on the other.**

**after code changes:**

```bash
git add <changed files>
git commit -m "what changed"
git push
```

**on the other machine, to pick up the update:**

```bat
cd mtk-gui
git pull
scripts\build_windows.bat
```

`dist/` and `mtk_gui/` are not tracked by git (see `.gitignore`), so **re-run the build script after every pull** — the existing `.exe` still contains the old code until rebuilt.

Notes:

1. **Commit from both sides** when you change files there (e.g. a tuned `config/` project YAML), otherwise the two sides diverge and conflict.
2. **Edit one copy of a file on one side at a time.** The project YAMLs in `config/` may be touched on both machines — commit and push right after editing to avoid conflicts.
3. **Git on Windows** needs to be installed once: <https://git-scm.com/download/win> (default options are fine).
4. No Windows build machine at hand? Use the cloud build (**Option 3** above).

### Offline transfer without GitHub (git bundle)

When GitHub is unreachable (blocked network, no proxy, no hotspot), transfer the
branch as a **single bundle file** over USB stick / AirDrop / LAN share — no
network required.

**on the machine that has the code (e.g. the Mac):**

```bash
git bundle create mtk-gui-p3b2.bundle feature/p3-b2-core
```

Copy `mtk-gui-p3b2.bundle` (one file) to the other machine by any means.

**on the receiving machine (e.g. Windows):**

```bat
git clone mtk-gui-p3b2.bundle MTK-GUI -b feature/p3-b2-core
cd MTK-GUI
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

The bundle carries the full branch history, so the clone is a normal
repository — later you can add GitHub back as a remote and push/pull as usual:

```bash
git remote add origin https://github.com/Seapol/MTK-GUI.git
git push -u origin feature/p3-b2-core
```

To re-transfer newer commits, rebuild the bundle the same way (it always
contains everything reachable from the branch tip).

## Platform notes

### Windows

- Install the USB-UART driver for the board's bridge chip (CH340, CP2102, FTDI, etc.); confirm the COM port in Device Manager.
- The packaged executable does not require Python on the target machine.
- SmartScreen may show an "unknown publisher" warning (More info → Run anyway). Use a code-signing certificate for production deployment.
- Real instruments use their VISA/USBTMC/GPIB/LAN drivers; Virtual mode needs none of them.

### macOS

- USB-UART bridge chips may require drivers (CH340 / CP210x / FTDI); allow them under System Settings → Privacy & Security after installation.
- Both Intel and Apple Silicon are supported; the build matches the host architecture.
- If a local build is blocked by Gatekeeper:

  ```bash
  xattr -cr dist/MTK_GUI.app
  ```

- For public distribution, sign and notarize the app with a Developer ID.

### Linux

- Grant serial-port access by adding the user to the `dialout` group, then log out and back in:

  ```bash
  sudo usermod -aG dialout $USER
  ```

- If the app fails to start with an xcb error, install the Qt runtime dependencies (Ubuntu/Debian):

  ```bash
  sudo apt update
  sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0 libxcb1 \
       libxcb-xinerama0 libgl1 libegl1
  ```

- On a headless machine, self-check with the offscreen Qt platform: `QT_QPA_PLATFORM=offscreen python main.py`.

## Troubleshooting

1. **No port in the list.** Check the USB cable and drivers, then click Refresh; on Linux verify the `dialout` group membership. In Virtual mode the fake DUT port appears without any hardware.
2. **No response after sending.** Verify the baud rate matches the board (commonly 115200), keep CR+LF enabled for line-oriented CLIs, and enable echo on the board side if available. In Virtual mode, check the virtual DUT fault isn't set to *no response*.
3. **Unexpected failures in Virtual mode.** Open Settings → Virtual Fault Injection and confirm both ratios are 0 % (the default).
4. **Quick commands do not fit my board.** They are fully user-defined — edit `config/commands.json`.
5. **Packaged app exits immediately.** Rebuild without `--windowed` and run from a terminal to read the error, and make sure `--collect-submodules serial` is present.
6. **Large package size.** PySide6 bundles all Qt libraries; exclude unused Qt modules with `--exclude-module` (e.g. QtQml, QtQuick3D) to shrink it.
