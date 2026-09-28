#!/usr/bin/env bash
# ============================================================
# MTK GUI - Linux build script
# Run from the project root:  bash scripts/build_linux.sh
# Output: dist/MTK_GUI/MTK_GUI
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
    --collect-submodules serial main.py

echo ""
echo "Build complete: dist/MTK_GUI/MTK_GUI"
echo "If the serial port is not accessible: sudo usermod -aG dialout \$USER"
