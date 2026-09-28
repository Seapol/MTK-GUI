#!/usr/bin/env bash
# ============================================================
# MTK GUI - macOS build script
# Run from the project root:  bash scripts/build_macos.sh
# Output: dist/MTK_GUI.app
# ============================================================
set -e
cd "$(dirname "$0")/.."

if [ ! -x "mtk_gui/bin/python" ]; then
    echo "[1/3] Creating virtual environment 'mtk_gui' ..."
    python3 -m venv mtk_gui
fi

echo "[2/3] Installing dependencies ..."
mtk_gui/bin/python -m pip install --upgrade pip
mtk_gui/bin/pip install -r requirements.txt

echo "[3/3] Building with PyInstaller ..."
mtk_gui/bin/pyinstaller --noconfirm --windowed --name MTK_GUI \
    --osx-bundle-identifier com.mtk.gui \
    --collect-submodules serial main.py

echo ""
echo "Build complete: dist/MTK_GUI.app"
echo "If Gatekeeper blocks the app on first run: xattr -cr dist/MTK_GUI.app"
