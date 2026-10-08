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

In a frozen onedir bundle the mtkgui modules live in _internal/, so
the bundled folders land where permissions.py / quick_commands.py
look first (candidate_paths() -> pkg_root/config).
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('serial')

datas = [
    ('config/permissions.json', 'config'),
    ('config/FRDM-IMX93_Nets.xlsx', 'config'),
    ('config/12345_FRDM-IMX93_Nets_revA.xlsx', 'config'),
    ('yaml_plan/examples', 'yaml_plan/examples'),
    ('resources', 'resources'),
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
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MTK_GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='MTK_GUI',
)
