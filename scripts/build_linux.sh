#!/usr/bin/env bash
# ============================================================
# MTK GUI - Linux build script
# Run from the project root:  bash scripts/build_linux.sh
# Output: dist/MTK_GUI/MTK_GUI
# ============================================================
set -e
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
    echo "[1/3] Creating virtual environment '.venv' ..."
    python3 -m venv .venv
fi

echo "[2/3] Installing dependencies ..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "[3/3] Building with PyInstaller ..."
.venv/bin/pyinstaller --noconfirm --windowed --name MTK_GUI \
    --collect-submodules serial main.py

echo ""
echo "Build complete: dist/MTK_GUI/MTK_GUI"
echo "If the serial port is not accessible: sudo usermod -aG dialout \$USER"
