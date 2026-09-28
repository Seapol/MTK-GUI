# MTK GUI — Manufacturing Test Kit

A cross-platform **manufacturing test tool** built with Python and PySide6. It covers the complete production flow **ICT → Flash FAT Firmware → FCT → Flash OOBE Firmware**, and also provides a **dual-UART serial console** for embedded board bring-up. The same code runs on **Windows, macOS and Linux**, and PyInstaller packages it into a native executable for each platform.

## Final test rack

| Instrument | Role | Interface |
|---|---|---|
| **DAQ973A** mainframe | Built-in 6.5-digit DMM; 3 slots | GPIB (+ LAN/USB) |
| **DAQM908A #1 / #2** | 40-ch SE MUX each; CH101–140 / CH201–240 → TP_P1–P80; 2-wire Ω then DCV | inside DAQ973A |
| **DAQM907A** | Totalizer 0–100 kHz (CLK1 32.768 kHz); 2× 16-bit AO ±12 V → TP_ADC0/1; 16-ch open-drain DIO → fixture control board | inside DAQ973A |
| **U2355A** | 12-ch analog input capture of the power-rails up sequence (→ CSV + waveform); 2 counters ≤6 MHz (CLK2 4 MHz / CLK3 6 MHz); 24 TTL DIO → DUT GPIO | USB |
| **N5747A** | DC power supply, 60 V / 12.5 A / 750 W, 4-wire remote sense, 5/12/24/48 V profiles | LAN (+ USB/GPIB) |

The DUT and every instrument share a single-point star ground on the fixture probe board.

## Two serial ports

| Port | Connects to |
|---|---|
| **DUT** (UART1) | the Device Under Test, primary UART |
| **AUX** (UART2 / Companion) | either the DUT second UART, or a companion / golden test board attached to the station |

Both ports can be open at the same time. Each one has **independent** connection settings, console, send line and TX/RX byte counters, so interactions on the two ports can be observed side by side.

## Features

- Large, scalable window (2560×1600 default, clamped to the screen) with a relaid-out dual-console area
- Console background color is adjustable from the **View** menu and defaults to **black**; the text palette automatically switches between dark and light for contrast
- **ANSI color rendering**: device SGR sequences are shown in color — standard and bright colors, 256-color (`38;5;n`) and true color (`38;2;r;g;b`), plus bold, italic, underline and reverse video; non-color escape sequences are stripped
- Auto-enumerate serial ports with a per-port Refresh button (pyserial; works on all three OSes)
- Per-port settings: baud rate, data bits, parity, stop bits, hardware flow control
- Two independent consoles with color-coded TX / RX / SYS messages and millisecond timestamps
- HEX display and HEX send (per console / per send line)
- Configurable **Quick Commands** panel with a destination selector: DUT / AUX / Both
- Command line with Enter-to-send, optional CR+LF terminator, and Up/Down history (a half-typed line is kept while browsing history)
- Per-console Clear and Save-log (`.txt`) actions
- Status bar showing connection state and TX/RX byte counts per port
- No platform-specific code; fully English UI, source and documentation

## Project layout

```
mtk-gui/
├── main.py                  # Entry point
├── requirements.txt         # Python dependencies
├── smoke_test.py            # Headless smoke test
├── config/
│   └── commands.json        # User-editable quick-command snippets
├── mtkgui/
│   ├── __init__.py
│   ├── main_window.py       # Main window, three-tab integration
│   ├── equipment_page.py    # Equipment block diagram + config dialogs
│   ├── test_workflow_page.py # Flow tables, waveform, CSV logging
│   ├── ansi.py              # ANSI SGR decoder (colors, cross-chunk buffer)
│   ├── theme.py             # Dark/light palettes, background luminance
│   ├── serial_worker.py     # Background serial reader (QThread)
│   ├── serial_params.py     # Baud/parity/stop-bit option mappings
│   ├── quick_commands.py    # Snippet loader with built-in defaults
│   ├── style.py             # QSS stylesheet
│   └── widgets/
│       ├── connection_panel.py
│       ├── console_widget.py
│       └── send_panel.py
└── scripts/
    ├── build_windows.bat    # One-click Windows packaging
    ├── build_macos.sh       # One-click macOS packaging
    └── build_linux.sh       # One-click Linux packaging
```

## Requirements

- Python **3.9 – 3.13** (3.11 / 3.12 recommended)
- Windows 10/11, macOS 11+ (Intel and Apple Silicon), or a mainstream Linux distribution (Ubuntu 20.04+, etc.)
- Python packages: `PySide6`, `pyserial`, `pyinstaller` (see `requirements.txt`)

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

### Usage

1. Plug in the DUT and/or companion board and click **Refresh** on each panel.
2. Pick the port and serial settings (default 115200-8-N-1), then click **Connect**.
3. Type a command in the matching **Send** line (Enter to send), or use a **Quick Command** button after choosing its target (DUT / AUX / Both).
4. Use **Save** on a console to store its log; HEX checkboxes switch the display/send format.
5. To change the console background, use **View → Console Background Color…** (**Reset Background (Black)** restores the default). Colored output from the device follows ANSI SGR sequences automatically.

## Demo pages (first stage)

The window is organized as three tabs:

| Tab | Purpose |
|---|---|
| **Equipment** | Block diagram of the final rack, in four layers (HOST PC + Flash/Debug probes + Test peripherals / Instruments / ATE fixture / DUT board). Every block, sub-module and signal cell is clickable and opens its own configuration window. Color-coded trunks show measurement, up-sequence, clock, AO, power/sense and ground paths. Demo mode: no hardware connected. |
| **Test Work Flow** | Table-form overall flow (ICT → Flash FAT Firmware → FCT → Flash OOBE Firmware); ICT measurement table — 80-point impedance shorts (R_min threshold, 1.5 Ω tolerance), 80-point voltage (±0.1 %), three clocks (32.768 kHz / 4 MHz / 6 MHz), AO→ADC stimulus, fixture DIO and 24 DUT GPIO (ohm·V·Hz, in-range ⇒ PASS); 12-channel power-rails up-sequence waveform with CSV log; FCT message tests (serial / GUI dialog / CLI keyword rules). **Run Demo** simulates a full pass and writes a real CSV into `logs/`. |
| **Serial Console** | The dual-UART console (DUT / companion board). |

Offscreen previews of the three tabs (no display needed):

```bash
QT_QPA_PLATFORM=offscreen ./mtk_gui/bin/python scripts/capture_preview.py
```

Output: `preview/equipment.png`, `preview/test_workflow.png`, `preview/serial_console.png`.

## Quick command snippets

Quick commands are generic serial snippets, not tied to any particular command set. Edit `config/commands.json` to match your board:

```json
[
    {"label": "AT", "command": "AT", "crlf": true},
    {"label": "Version", "command": "fw_version", "crlf": true},
    {"label": "Self Test", "command": "factory_selftest", "crlf": false}
]
```

- `label` is shown on the button; `command` is the text actually sent.
- `crlf` controls whether `\r\n` is appended.
- The destination is selected with the **Target** dropdown in the panel (DUT, AUX or Both for broadcast).
- If the file is missing or invalid, built-in default snippets are used. For a packaged app, place an edited copy in a `config/` folder next to the executable.

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

```bash
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

The repository lives on GitHub; both machines share the same `main` branch. Core rule: **Mac pushes, Windows pulls — and always commit from whichever side you edited.**

**macOS side, after code changes:**

```bash
git add <changed files>
git commit -m "what changed"
git push
```

**Windows side, to pick up the update:**

```bat
cd MTK-GUI
git pull
scripts\build_windows.bat
```

`dist/` and `mtk_gui/` are not tracked by git (see `.gitignore`), so **re-run the build script after every pull** — the existing `.exe` still contains the old code until rebuilt.

Notes:

1. **Commit from Windows too** when you change files there (e.g. a tuned `config/` project YAML), otherwise the two sides diverge and conflict:

   ```bat
   git add .
   git commit -m "update from windows"
   git push
   ```

2. **Edit one copy of a file on one side at a time.** The project YAMLs in `config/` are touched on both machines — commit and push right after editing to avoid conflicts.
3. **Git on Windows** needs to be installed once: <https://git-scm.com/download/win> (default options are fine). Without git you can only re-download the ZIP from GitHub, which **loses local edits made on the Windows side**.
4. No Windows build machine at hand? Use the cloud build (**Option 3** above) — the exe comes back as a workflow artifact.

## Platform notes

### Windows

- Install the USB-UART driver for the board's bridge chip (CH340, CP2102, FTDI, etc.); confirm the COM port in Device Manager.
- The packaged executable does not require Python on the target machine.
- SmartScreen may show an "unknown publisher" warning (More info → Run anyway). Use a code-signing certificate for production deployment.

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

- On a headless machine you can self-check with the offscreen Qt platform: `QT_QPA_PLATFORM=offscreen python main.py`.

## Testing

No hardware is required for the smoke test, which covers window creation, the three tabs, port enumeration on both channels, RX rendering, HEX mode, quick-command dispatch, invalid input, ANSI color rendering (including a sequence split across reads), background-color switching, Up/Down history, a **real mouse click on an Equipment block** (verifying the config dialog opens) and the **full Test Work Flow demo run** including the 12-channel CSV:

```bash
QT_QPA_PLATFORM=offscreen python smoke_test.py
```

`ALL SMOKE TESTS PASSED` indicates success.

## Troubleshooting

1. **No port in the list.** Check the USB cable and drivers, then click Refresh; on Linux verify the `dialout` group membership.
2. **No response after sending.** Verify the baud rate matches the board (commonly 115200), keep CR+LF enabled for line-oriented CLIs, and enable echo on the board side if available.
3. **Quick commands do not fit my board.** They are fully user-defined — edit `config/commands.json`.
4. **Packaged app exits immediately.** Rebuild without `--windowed` and run from a terminal to read the error, and make sure `--collect-submodules serial` is present.
5. **Large package size.** PySide6 bundles all Qt libraries; exclude unused Qt modules with `--exclude-module` (e.g. QtQml, QtQuick3D) to shrink it.
