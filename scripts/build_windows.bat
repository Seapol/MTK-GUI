@echo off
REM ============================================================
REM MTK GUI - Windows build script
REM Run from the project root:  scripts\build_windows.bat
REM Output: dist\MTK_GUI\MTK_GUI.exe   (config folder bundled)
REM         dist\MTK_GUI_win64.zip     (ready-to-copy package)
REM ============================================================
cd /d "%~dp0\.."

if not exist "mtk_gui\Scripts\python.exe" (
    echo [1/4] Creating virtual environment "mtk_gui" ...
    py -3 -m venv mtk_gui
    if errorlevel 1 (
        echo Failed to create the virtual environment. Install Python 3.9+ first.
        pause
        exit /b 1
    )
)

echo [2/4] Installing dependencies ...
mtk_gui\Scripts\python -m pip install --upgrade pip
mtk_gui\Scripts\pip install -r requirements.txt

echo [3/4] Building with PyInstaller (spec bundles the config folder) ...
mtk_gui\Scripts\pyinstaller --noconfirm MTK_GUI_windows.spec
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)

echo [4/4] Packing distributable zip ...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\MTK_GUI' -DestinationPath 'dist\MTK_GUI_win64.zip' -Force"

echo.
echo Build complete:
echo   dist\MTK_GUI\MTK_GUI.exe      (run MTK_GUI.exe from this folder)
echo   dist\MTK_GUI_win64.zip        (copy this to the test station)
pause
