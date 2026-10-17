# MTK GUI Windows Deployment & Packaging Guide (exe named MTK_GUI.exe)

Complete steps to pull the code and build `MTK_GUI.exe` from scratch on a Windows PC.
Run all commands in CMD or PowerShell.

---

## 0. Deployment Architecture: Three Machines

| Machine | Role | What it needs |
|---|---|---|
| Mac | Dev machine | SSH key (already set up), `git push` / `git pull` |
| Windows PC | Build machine | This guide: HTTPS clone + venv + pyinstaller, produces `dist\MTK_GUI\` |
| Factory PC | Run | Nothing to install (no git, no Python), just copy the `dist\MTK_GUI\` folder |

---

## 1. Install Prerequisites (one-time)

| Software | Notes |
|---|---|
| Git for Windows | https://git-scm.com/download/win , default options all the way |
| Python 3.12 | https://www.python.org/downloads/ , **make sure to check "Add Python to PATH"** during install |

Verify after installing (open a new terminal):

```bat
git --version
python --version
```

## 2. Pull the Code

```bat
:: Pick a working directory, e.g. D:\work
D:
cd \work

:: Clone the repo (HTTPS, no SSH key needed)
git clone https://github.com/Seapol/MTK-GUI.git
cd MTK-GUI

:: Switch to the branch to deploy (deploy branch: develop)
git checkout develop

:: Pull the latest code
git pull origin develop
```

> If an SSH key is configured, you may use: `git clone git@github.com:Seapol/MTK-GUI.git`

## 3. Create a Virtual Environment and Install Dependencies

```bat
python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

> Every time you open a new terminal, run `.venv\Scripts\activate` first to activate the environment.

## 4. Check the Spec (no edit needed)

The exe name is controlled by `name=` in the spec file. The shipped
`MTK_GUI_windows.spec` is already configured as `MTK_GUI`:

> Notes:
> - `EXE(name='MTK_GUI')` determines the final exe file name → `MTK_GUI.exe`
> - `COLLECT(name='MTK_GUI')` determines the output folder name → `dist\MTK_GUI\`
> - **No manual edit is needed** — build directly (2026-10-15 correction:
>   an earlier revision of this guide told builders to rename `name` to
>   `mtk`, which never matched the actual product; that section is retired).

## 5. Build with PyInstaller

Run from the repo root:

```bat
pyinstaller --noconfirm MTK_GUI_windows.spec
```

> The spec pins `upx=False` (2026-10-15): UPX-compressed DLLs are fully
> decompressed and scanned by Windows Defender real-time protection on
> every launch, which once caused a 1+ minute wait for the main window
> after login. Do NOT switch back to `upx=True`; if the build/factory
> PC still starts slowly, add a Defender exclusion for the `dist\`
> folder.

Output location after the build:

```
dist\MTK_GUI\MTK_GUI.exe          <- main program
dist\MTK_GUI\_internal\       <- dependencies (must stay next to MTK_GUI.exe)
```

## 6. Verify

Double-click `dist\MTK_GUI\MTK_GUI.exe` (GUI app, no console window).

> Every launch writes `_startup_timing.log` next to the exe (the
> startup timing probe, kept for on-site diagnostics 2026-10-15;
> plain text, negligible overhead - may be kept or deleted). Large
> ICT plans (e.g. 96624, 517 KB) load through a staged chain: the
> status-bar progress bar tracks the stages, Run Control and the
> double-click table editing are disabled during the load and
> restored automatically; switching projects auto-closes the
> previous one first.

If copying to another machine, **always copy the whole `dist\MTK_GUI` folder** — never just MTK_GUI.exe.

## 7. Copy to Factory PCs (runtime deployment)

Factory PCs need **neither git nor Python**. Just copy the whole `dist\MTK_GUI\` folder from the build machine via USB drive or network share:

```
MTK_GUI\         <- copy the whole folder, nothing may be missing
├── MTK_GUI.exe  <- double-click to run
└── _internal\   <- all dependencies live here, never separate from MTK_GUI.exe
```

### Installation Checklist

**Basic operation — nothing to install.** Python, PySide6, serial (pyserial), SSH (paramiko) and all other dependencies are bundled in `_internal\`; `ping`, `netsh`, `powershell` ship with Windows.

**Install as needed:**

| Component | When needed | How |
|---|---|---|
| [VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) | Only if double-clicking MTK_GUI.exe reports a missing DLL (few stripped-down systems) | Download the x64 version, install once |
| iperf3 | The test plan enables a Wi-Fi throughput step (host-side `iperf3 -c` measurement or `iperf3 -s` as server) | Download the Windows iperf3.exe and drop it into the `MTK_GUI\` folder (next to MTK_GUI.exe) or `C:\Windows\`; not needed if no throughput step |
| USB serial driver | When connecting the DUT via a USB-to-serial cable | FTDI / CP210x usually auto-install on Win10/11; CH340-family chips typically need a one-time manual install |
| WLAN adapter | Host-side Wi-Fi scan / connect / throughput tests | The PC itself must have a working WLAN adapter |

**Two prerequisites + one note:**

- The test PC should run an **English Windows** locale: the Wi-Fi/throughput steps parse `netsh`/`ping` output expecting English text; other locales may fail to parse.
- User-created YAML test plans go into `MTK_GUI\yaml_plan\` (next to the exe); add them anytime without rebuilding.
- **Real mode requires the instruments to be connected before Run** (since 2026-10-14): establish the Instrument Gateway via Tools → Connect all first. Without it, ICT measurement rows / standard ops / the power-rails capture all report **Error** (equipment-fault stop policy) — a fake PASS with an empty Measured cell is no longer possible. Virtual mode is unaffected.
- **No sample plans / `yaml_plan\` ship with the repo anymore** (2026-10-14: `yaml_plan\` is now fully excluded from version control). Regenerate the FRDM-IMX93 FCT demo plan on demand with `python scripts\build_frdm_fct_demo_yaml.py` (writes `yaml_plan\examples\imx93frdm\FRDM-IMX93_FCT_Demo_v1.0.5.yaml`), or simply copy your own plan file; real product plans live under `projects\` (now versioned).

**Status bar shows v1.0.0.0?**

That is correct (since 2026-10-14): the version number is unified to THE single release version `mtkgui.__version__` (currently `v1.0.0.0`), shown in the status bar, login box and About alike. The packaging machine **no longer needs** the CI-generated `resources\version.json` — building straight from a source checkout is fine. `develop` commits never change the version number; only a Release commit bumps it (and records it under Help → Version History). Build facts (branch / commit) are visible under Help → About.

---

## Troubleshooting

**Build error: cannot find `config/permissions.json` etc.**
The spec references the following files; they must be pulled with the code (already in the git repo):
- `config/permissions.json`
- `config/FRDM-IMX93_Nets.xlsx`
- `config/12345_FRDM-IMX93_Nets_revA.xlsx`
- `yaml_plan/examples`
- `resources`

Make sure the build command is run from the repo root (the directory containing `MTK_GUI_windows.spec`).

**`pyinstaller` is not recognized as an internal or external command**
The virtual environment is not activated — run `.venv\Scripts\activate` first.

**User's own YAML plan files**
User-created test plans in `yaml_plan/` are not part of the build output; after deployment, place them manually in the `yaml_plan/` folder next to the exe. The packaged `yaml_plan/examples/` now only carries the DUT script assets (`dut_scripts/`, used by SFTP provisioning); demo plans are no longer bundled — regenerate with `scripts\build_frdm_fct_demo_yaml.py` when needed.

**Report output folders (since 2026-10-17)**
Every counted DUT run immediately generates its report next to the exe, under `MTK_GUI\DUT Report\`: each DUT gets an IDENTITY folder named `Part#_CoreID_Batch#_SN_<timestamp>` containing the raw DAQ waveform CSV, the certificate PDF and the MES detail CSV — every file name carries the same identity fields. Event logs live in `MTK_GUI\Event Report\` (one .log per session). The Report menu items **DUT Report / Event Log / DAQ CSV Data** open these folders directly; the folder names can be changed in **Report → Report Folder…** (persisted in `report_folders.json` next to the exe).

---

## Appendix: Mac Dev Machine SSH Key (already set up, for reference)

The Mac already has an SSH key configured (`~/.ssh/id_ed25519`, public key registered with GitHub). `git push` / `git pull` work out of the box — no action needed.

Backup steps for a new Mac:

```bash
ssh-keygen -t ed25519 -C "seapol@mac"        # press Enter all the way
pbcopy < ~/.ssh/id_ed25519.pub               # copy the public key to clipboard
# GitHub → Settings → SSH and GPG keys → New SSH key → paste and save
ssh -T git@github.com                        # "Hi Seapol!" means success
```

> The Windows build machine does not need an SSH key — use the HTTPS method from step 2 of this guide.
