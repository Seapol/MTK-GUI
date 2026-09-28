# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows build (onedir, windowed).

Run on a Windows machine:
    pyinstaller --noconfirm MTK_GUI_windows.spec

The project "config" folder (permissions.json, sample project YAML /
netlist workbooks) is bundled into the package.  In a frozen onedir
bundle the mtkgui modules live in _internal/, so the bundled folder
lands at _internal/config - exactly where permissions.py and
quick_commands.py look first (candidate_paths() -> pkg_root/config).
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('serial')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('config', 'config')],   # bundled at _internal/config
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
