# MTK GUI Windows Deployment & Packaging Guide (exe named mtk.exe)

Complete steps to pull the code and build `mtk.exe` from scratch on a Windows PC.
Run all commands in CMD or PowerShell.

---

## 0. Deployment Architecture: Three Machines

| Machine | Role | What it needs |
|---|---|---|
| Mac | Dev machine | SSH key (already set up), `git push` / `git pull` |
| Windows PC | Build machine | This guide: HTTPS clone + venv + pyinstaller, produces `dist\mtk\` |
| Factory PC | Run | Nothing to install (no git, no Python), just copy the `dist\mtk\` folder |

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

## 4. Edit the Spec to Rename the exe to mtk.exe

The exe name is controlled by `name=` in the spec file — two places to change.

Open `MTK_GUI_windows.spec` in the repo root with Notepad:

```bat
notepad MTK_GUI_windows.spec
```

Find in `EXE(...)`:

```python
    name='MTK_GUI',
```

Change it to:

```python
    name='mtk',
```

Then find in `COLLECT(...)`:

```python
    name='MTK_GUI',
```

Change it too:

```python
    name='mtk',
```

Save and close.

> Notes:
> - `EXE(name=...)` determines the final exe file name → `mtk.exe`
> - `COLLECT(name=...)` determines the output folder name → `dist\mtk\`
> - Change both; the final product is `dist\mtk\mtk.exe`

## 5. Build with PyInstaller

Run from the repo root:

```bat
pyinstaller --noconfirm MTK_GUI_windows.spec
```

Output location after the build:

```
dist\mtk\mtk.exe          <- main program
dist\mtk\_internal\       <- dependencies (must stay next to mtk.exe)
```

## 6. Verify

Double-click `dist\mtk\mtk.exe` (GUI app, no console window).

If copying to another machine, **always copy the whole `dist\mtk` folder** — never just mtk.exe.

## 7. Copy to Factory PCs (runtime deployment)

Factory PCs need **neither git nor Python**. Just copy the whole `dist\mtk\` folder from the build machine via USB drive or network share:

```
mtk\            <- copy the entire folder, nothing can be missing
├── mtk.exe     <- double-click to run
└── _internal\  <- all dependencies live here, never separate from mtk.exe
```

### Installation Checklist

**Basic operation — nothing to install.** Python, PySide6, serial (pyserial), SSH (paramiko) and all other dependencies are bundled in `_internal\`; `ping`, `netsh`, `powershell` ship with Windows.

**Install as needed:**

| Component | When needed | How |
|---|---|---|
| [VC++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe) | Only if double-clicking mtk.exe reports a missing DLL (few stripped-down systems) | Download the x64 version, install once |
| iperf3 | The test plan enables a Wi-Fi throughput step (host-side `iperf3 -c` measurement or `iperf3 -s` as server) | Download the Windows iperf3.exe and drop it into the `mtk\` folder (next to mtk.exe) or `C:\Windows\`; not needed if no throughput step |
| USB serial driver | When connecting the DUT via a USB-to-serial cable | FTDI / CP210x usually auto-install on Win10/11; CH340-family chips typically need a one-time manual install |
| WLAN adapter | Host-side Wi-Fi scan / connect / throughput tests | The PC itself must have a working WLAN adapter |

**Two prerequisites + one note:**

- The test PC should run an **English Windows** locale: the Wi-Fi/throughput steps parse `netsh`/`ping` output expecting English text; other locales may fail to parse.
- User-created YAML test plans go into `mtk\yaml_plan\` (next to the exe); add them anytime without rebuilding.
- The bundled FRDM-IMX93 FCT demo plans live in `mtk\_internal\yaml_plan\examples\imx93frdm\`; the latest is `FRDM-IMX93_FCT_Demo_v1.0.2.yaml` (v1.0.0 / v1.0.1 remain in the package).

**Status bar shows v4.1.1.0000?**

When the exe is built straight from a source checkout there is no CI-generated `resources\version.json`; the status bar falls back to the static version `v4.1.1.0000` with no functional impact. The CI packaging pipeline writes the real version number at build time.

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
User-created test plans in `yaml_plan/` are not part of the build output; after deployment, place them manually in the `yaml_plan/` folder next to the exe. The bundled demo plans (`yaml_plan/examples`) ship inside the package at `_internal\yaml_plan\examples\` — no manual placement needed.

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
