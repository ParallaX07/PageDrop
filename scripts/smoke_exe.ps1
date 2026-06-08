# Build PageDrop and smoke-test the executable (Windows).
# Usage (from project root):
#   .\scripts\smoke_exe.ps1
#   .\scripts\smoke_exe.ps1 -SkipBuild

param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if (-not $SkipBuild) {
    Write-Host "Building executable via pagedrop.spec..."
    Push-Location $Root
    try {
        uv run pyinstaller --noconfirm pagedrop.spec
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    }
    finally {
        Pop-Location
    }
}

$Exe = Join-Path $Root "dist\pagedrop\pagedrop.exe"
if (-not (Test-Path $Exe)) {
    throw "Expected executable not found: $Exe"
}

Write-Host "Launching $Exe (5s alive check)..."
$env:QT_QPA_PLATFORM = "offscreen"
$proc = Start-Process -FilePath $Exe -PassThru -WindowStyle Hidden

try {
    Start-Sleep -Seconds 5
    if ($proc.HasExited) {
        throw "Executable exited immediately with code $($proc.ExitCode)"
    }
    Write-Host "OK: process stayed alive for 5 seconds."
}
finally {
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Manual verification (clean machine without Python):"
Write-Host "  1. Copy dist\pagedrop\ to a VM or PC without Python."
Write-Host "  2. Open a PDF via File -> Open PDF."
Write-Host "  3. Drag a page thumbnail into Explorer and confirm a file is created."
Write-Host ""
Write-Host "Run pytest smoke test:"
Write-Host "  `$env:PAGEDROP_EXE = `"$Exe`""
Write-Host "  uv run pytest tests/smoke/test_phase16_executable.py -v"
