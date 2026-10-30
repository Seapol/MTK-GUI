# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows build (onedir, windowed).

Run on a Windows machine:
    pyinstaller --noconfirm MTK_GUI_windows.spec

Bundled data:

* config/permissions.json          -> _internal/config
* config/*.xlsx (sample netlists)  -> _internal/config
* yaml_plan/examples               -> _internal/yaml_plan/examples
* resources (logo / version.json)  -> _internal/resources
* docs/help (16 guide chapters, images, version history)
                                   -> _internal/docs/help
* projects (ALL projects, M19)     -> _internal/projects
    Set env MTKGUI_SHIP_PROJECTS=0 to skip (build_windows.ps1
    -SkipProjects).  Run-artifacts (pyc / __pycache__ / _run_work /
    reports / fat_result.json / fat.log) are stripped from the
    collected TOC so they never ship.

In a frozen onedir bundle the mtkgui modules live in _internal/, so
the bundled folders land where permissions.py / quick_commands.py
look first (candidate_paths() -> pkg_root/config).  help_content.py
resolves HELP_ROOT through sys._MEIPASS, i.e. the same _internal/
folder, so Help > User Guide is not empty on the deployment.
resolve_tenant_base() (mtkgui/gui/shell.py) picks the projects
workspace as: MTKGUI_TENANT_BASE env -> exe-side projects/ ->
bundle _internal/projects -> CWD projects.
"""

import os

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('serial')
# QtWebEngine (M13): the SharePoint sign-in window creates
# QWebEngineProfile / QWebEnginePage / QWebEngineView at runtime, so the
# WebEngine modules must be traced into the frozen bundle.  The PySide6
# PyInstaller hook then collects the QtWebEngine binaries
# (QtWebEngineProcess.exe helper, qtwebengine_* resources) and plugins.
# QtWebEngineQuick is not used by this widgets-only app.
hiddenimports += [
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineCore',
]
# QtMultimedia (M45): the BT Tone editor previews the wav locally
# (QMediaPlayer / QAudioOutput / QAudioBufferOutput).  The PySide6 hook
# then collects the multimedia plugins + the ffmpeg media backend so the
# packaged exe can play wav on Windows.
hiddenimports += [
    'PySide6.QtMultimedia',
]
# Credentials layer (mtkgui/engine/credentials.py): the OS keyring backend
# must be traced explicitly, otherwise a frozen build raises
# CredentialUnavailable when a channel/login stores its password.
hiddenimports += ['keyring.backends.Windows']

datas = [
    ('config/permissions.json', 'config'),
    ('config/FRDM-IMX93_Nets.xlsx', 'config'),
    ('config/Nets_Template.xlsx', 'config'),
    ('yaml_plan/examples', 'yaml_plan/examples'),
    ('resources', 'resources'),
    ('docs/help', 'docs/help'),
]
# M19: projects travel with the package unless explicitly disabled
# (build_windows.ps1 -SkipProjects sets MTKGUI_SHIP_PROJECTS=0).
if os.environ.get("MTKGUI_SHIP_PROJECTS", "1") != "0":
    datas.append(('projects', 'projects'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Run-artifact guard (spec audit fix): real-board runs drop fat_result.json
# (and other .json dumps) plus the _run_work/ and reports/ run folders into
# the example tree, and Python writes __pycache__/*.pyc into projects.
# Those are gitignored runtime products that must never ship in the Windows
# package, so drop them from the collected TOC here as a safety net on top
# of the source-tree cleanup.  PyInstaller 6 TOC entries are
# (dest_name, src_name, typecode), so the bundle-relative path is d[0].


def _is_run_artifact(dest: str) -> bool:
    """True for bundle-relative paths that are runtime products, never
    source material."""
    low = dest.replace("\\", "/")
    if (low.startswith("yaml_plan/examples")
            and low.endswith(".json")):
        return True            # real-board dumps in the example tree
    return (low.endswith(".pyc")
            or "/__pycache__/" in low
            or "/_run_work/" in low
            or "/reports/" in low
            or low.endswith("fat_result.json")
            or low.endswith("fat.log"))


a.datas = [d for d in a.datas if not _is_run_artifact(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MTK_GUI',
    icon='resources/app_icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX slows every start under Defender scanning
    console=False,          # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MTK_GUI',
)
