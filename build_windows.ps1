# build_windows.ps1 - one-shot Windows package build for MTK_GUI.
#
# Usage:
#   .\build_windows.ps1                          # default: dist\MTK_GUI\
#   .\build_windows.ps1 -OutDir D:\release\v1.9  # package anywhere
#   .\build_windows.ps1 -KeepRunning             # don't stop a running GUI
#
# Notes:
#   * Any running MTK_GUI.exe is force-stopped first so PyInstaller can
#     replace the locked onedir bundle (permission error otherwise).
#   * v2/C3: no project data ships in the package any more.  ``_internal\
#     config`` carries the FACTORY DEFAULTS only; the first launch seeds
#     the writable ``config\`` folder beside the exe.
#   * -OutDir accepts a relative or absolute path; the exe lands at
#     <OutDir>\MTK_GUI\MTK_GUI.exe.

param(
    [string]$OutDir = "dist",
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not $KeepRunning) {
    Get-Process -Name "MTK_GUI" -ErrorAction SilentlyContinue |
        Stop-Process -Force
    Start-Sleep -Seconds 2
}

$distAbs = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::Combine($root, $OutDir))
$workAbs = [System.IO.Path]::Combine($root, ".build_tmp")

Write-Host "==> dist path : $distAbs"
Write-Host "==> config    : factory defaults in _internal\config (seeded on first launch)"

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
    # v2/C3: _internal\config must carry the four factory seeds and
    # _internal\projects must NOT exist any more
    $configDir = Join-Path $internal "config"
    $configOk = (Test-Path -LiteralPath (Join-Path $configDir "permissions.json")) -and
        (Test-Path -LiteralPath (Join-Path $configDir "settings.json")) -and
        (Test-Path -LiteralPath (Join-Path $configDir "report_paths.json")) -and
        (Test-Path -LiteralPath (Join-Path $configDir "rules\base.v2.json"))
    $projOk = Test-Path -LiteralPath (Join-Path $internal "projects")
    # M46: the project-assets template must reach _internal\assets
    $assetsDir = Join-Path $internal "assets"
    $assetsOk = Test-Path -LiteralPath $assetsDir
    $sizeTxt = "{0:N0} bytes ({1:N1} MB)" -f $file.Length, ($file.Length / 1MB)
    Write-Host "==> OK: $exe"
    Write-Host "    size    : $sizeTxt"
    Write-Host "    config seeds     : $configOk"
    Write-Host "    assets template  : $assetsOk"
    if (-not $configOk) {
        Write-Host "==> ERROR: _internal\config is missing a factory seed"
        exit 1
    }
    if ($projOk) {
        Write-Host "==> ERROR: _internal\projects must not ship (runtime data only)"
        exit 1
    }
    if ($assetsOk) {
        $af = (Get-ChildItem -LiteralPath $assetsDir -Recurse -File |
            Measure-Object).Count
        Write-Host "    assets files     : $af"
    }
} else {
    Write-Host "==> ERROR: exe not found at $exe"
    exit 1
}
