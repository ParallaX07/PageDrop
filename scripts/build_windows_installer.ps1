# PageDrop Windows installer (Inno Setup)
#
# Prerequisites:
#   - uv + Python 3.11+
#   - Inno Setup 6+ (iscc on PATH, or set $env:ISCC)
#
# Usage:
#   .\scripts\build_windows_installer.ps1
#   .\scripts\build_windows_installer.ps1 -SkipBuild   # local-only: reuse dist/pagedrop/

[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$Release
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($Release -and $SkipBuild) {
    throw "-SkipBuild is not permitted for a release build."
}

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

$Version = (& uv run --locked python scripts/read_version.py).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Version reading failed with exit code $LASTEXITCODE"
}
if (-not $Version) {
    throw "Could not read version from pyproject.toml"
}
Write-Host "PageDrop version: $Version"

$Ico = Join-Path $Root "src\pagedrop\assets\app-icon.ico"
if (-not (Test-Path -LiteralPath $Ico)) {
    Write-Host "Generating app-icon.ico..."
    & uv run --with pillow python scripts/generate_icons.py
    if ($LASTEXITCODE -ne 0) {
        throw "Icon generation failed with exit code $LASTEXITCODE"
    }
}

if (-not $SkipBuild) {
    Write-Host "Building PyInstaller onedir..."
    & uv sync --locked --group dev
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency sync failed with exit code $LASTEXITCODE"
    }
    & uv run pyinstaller --noconfirm pagedrop.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}

$Exe = Join-Path $Root "dist\pagedrop\pagedrop.exe"
if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Missing $Exe - run without -SkipBuild or build with pyinstaller first."
}

$Iscc = Get-Iscc
$Iss = Join-Path $Root "installer\windows.iss"
$Out = Join-Path $Root "installer\Output\PageDrop-$Version-Setup.exe"
if (Test-Path -LiteralPath $Out) {
    Remove-Item -LiteralPath $Out -Force
}
Write-Host "Compiling installer with $Iscc ..."
& $Iscc "/DAppVersion=$Version" $Iss
if ($LASTEXITCODE -ne 0) {
    throw "iscc failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $Out) -or (Get-Item -LiteralPath $Out).Length -le 0) {
    throw "Expected new non-empty output missing: $Out"
}
Write-Host "Installer ready: $Out"
