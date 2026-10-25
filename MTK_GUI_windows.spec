# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows build (onedir, windowed).

Run on a Windows machine:
    pyinstaller --noconfirm MTK_GUI_windows.spec

Bundled data (only the runtime-needed files - the user's own YAML
plans live in yaml_plan/ OUTSIDE the package and are NOT shipped):

* config/permissions.json          -> _internal/config
* config/*.xlsx (sample netlists)  -> _internal/config
* yaml_plan/examples               -> _internal/yaml_plan/examples
* resources (logo / version.json)  -> _internal/resources
* docs/help (14 guide chapters, images, version history)
                                   -> _internal/docs/help

In a frozen onedir bundle the mtkgui modules live in _internal/, so
the bundled folders land where permissions.py / quick_commands.py
look first (candidate_paths() -> pkg_root/config).  help_content.py
resolves HELP_ROOT through sys._MEIPASS, i.e. the same _internal/
folder, so Help > User Guide is not empty on the deployment.
"""

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
# the example tree.  Those are gitignored runtime products that must never
# ship in the Windows package, so drop them from the collected TOC here as
# a safety net on top of the source-tree cleanup.  PyInstaller 6 TOC entries
# are (dest_name, src_name, typecode), so the bundle-relative path is d[0].
a.datas = [d for d in a.datas
           if not (d[0].startswith("yaml_plan/examples")
                   and (d[0].endswith(".json")
                        or "/_run_work/" in d[0]
                        or "/reports/" in d[0]))]

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
