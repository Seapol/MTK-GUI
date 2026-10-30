# build_windows.ps1 - one-shot Windows package build for MTK_GUI.
#
# Usage:
#   .\build_windows.ps1                          # default: dist\MTK_GUI\
#   .\build_windows.ps1 -OutDir D:\release\v1.9  # package anywhere
#   .\build_windows.ps1 -SkipProjects            # exclude projects data
#   .\build_windows.ps1 -KeepRunning             # don't stop a running GUI
#
# Notes:
#   * Any running MTK_GUI.exe is force-stopped first so PyInstaller can
#     replace the locked onedir bundle (permission error otherwise).
#   * projects/ is bundled into _internal\projects by default (M19);
#     -SkipProjects sets MTKGUI_SHIP_PROJECTS=0 for the spec.
#   * -OutDir accepts a relative or absolute path; the exe lands at
#     <OutDir>\MTK_GUI\MTK_GUI.exe.

param(
    [string]$OutDir = "dist",
    [switch]$SkipProjects,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not $KeepRunning) {
    Get-Process -Name "MTK_GUI" -ErrorAction SilentlyContinue |
        Stop-Process -Force
    Start-Sleep -Seconds 2
}

$env:MTKGUI_SHIP_PROJECTS = if ($SkipProjects) { "0" } else { "1" }

$distAbs = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::Combine($root, $OutDir))
$workAbs = [System.IO.Path]::Combine($root, ".build_tmp")

Write-Host "==> dist path : $distAbs"
Write-Host "==> projects  : $(if ($SkipProjects) { 'EXCLUDED' } else { 'bundled' })"

Push-Location $root
try {
    # PyInstaller logs INFO to stderr; pwsh 7 turns native stderr into
    # an error record that aborts under $ErrorActionPreference=Stop,
    # so lower the preference for the build call only.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $buildLog = & ".venv\Scripts\pyinstaller.exe" `
            --clean --noconfirm `
            --distpath $distAbs `
            --workpath $workAbs `
            MTK_GUI_windows.spec 2>&1
        $buildExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prevEap
    }
    $buildLog | Select-Object -Last 6 | Out-Host
    if ($buildExit -ne 0) {
        throw "pyinstaller failed (exit $buildExit)"
    }
}
finally {
    Pop-Location
}

$exe = Join-Path $distAbs "MTK_GUI\MTK_GUI.exe"
if (Test-Path -LiteralPath $exe) {
    $file = Get-Item -LiteralPath $exe
    $internal = Join-Path $distAbs "MTK_GUI\_internal"
    $projOk = if ($SkipProjects) { $false } else {
        Test-Path -LiteralPath (Join-Path $internal "projects")
    }
    # M46: the project-assets template must reach _internal\assets
    $assetsDir = Join-Path $internal "assets"
    $assetsOk = Test-Path -LiteralPath $assetsDir
    $sizeTxt = "{0:N0} bytes ({1:N1} MB)" -f $file.Length, ($file.Length / 1MB)
    Write-Host "==> OK: $exe"
    Write-Host "    size    : $sizeTxt"
    Write-Host "    built-in projects: $projOk"
    Write-Host "    assets template  : $assetsOk"
    if ($assetsOk) {
        $af = (Get-ChildItem -LiteralPath $assetsDir -Recurse -File |
            Measure-Object).Count
        Write-Host "    assets files     : $af"
    }
    if ($projOk) {
        $pj = (Get-ChildItem -LiteralPath (Join-Path $internal "projects") -Recurse -File |
            Measure-Object -Property Length -Sum).Sum
        $pjTxt = "{0:N1} MB" -f ($pj / 1MB)
        Write-Host "    projects payload : $pjTxt"
    }
} else {
    Write-Host "==> ERROR: exe not found at $exe"
    exit 1
}
