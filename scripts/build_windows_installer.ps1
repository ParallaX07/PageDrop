# PageDrop Windows installer (Inno Setup)
#
# Prerequisites:
#   - uv + Python 3.11+
#   - Inno Setup 6+ (iscc on PATH, or set $env:ISCC)
#
# Usage:
#   .\scripts\build_windows_installer.ps1
#   .\scripts\build_windows_installer.ps1 -SkipBuild   # reuse existing dist/pagedrop.exe

[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Get-Iscc {
    if ($env:ISCC -and (Test-Path -LiteralPath $env:ISCC)) {
        return $env:ISCC
    }
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }
    throw "Inno Setup compiler (iscc) not found. Install Inno Setup 6+ or set `$env:ISCC`."
}

$Version = (& uv run python scripts/read_version.py).Trim()
if (-not $Version) {
    throw "Could not read version from pyproject.toml"
}
Write-Host "PageDrop version: $Version"

$Ico = Join-Path $Root "src\pagedrop\assets\app-icon.ico"
if (-not (Test-Path -LiteralPath $Ico)) {
    Write-Host "Generating app-icon.ico..."
    & uv run --with pillow python scripts/generate_icons.py
}

if (-not $SkipBuild) {
    Write-Host "Building PyInstaller onefile..."
    & uv sync --group dev
    & uv run pyinstaller --noconfirm pagedrop.spec
}

$Exe = Join-Path $Root "dist\pagedrop.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Missing $Exe - run without -SkipBuild or build with pyinstaller first."
}

$Iscc = Get-Iscc
$Iss = Join-Path $Root "installer\windows.iss"
Write-Host "Compiling installer with $Iscc ..."
& $Iscc "/DAppVersion=$Version" $Iss
if ($LASTEXITCODE -ne 0) {
    throw "iscc failed with exit code $LASTEXITCODE"
}

$Out = Join-Path $Root "installer\Output\PageDrop-$Version-Setup.exe"
if (-not (Test-Path -LiteralPath $Out)) {
    throw "Expected output missing: $Out"
}
Write-Host "Installer ready: $Out"
