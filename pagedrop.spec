# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PageDrop — one-file GUI executable."""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)
SRC = ROOT / "src"
ENTRY = SRC / "pagedrop" / "main.py"
ASSETS = SRC / "pagedrop" / "assets"

datas: list[tuple[str, str]] = [
    (str(ASSETS / "logo.png"), "pagedrop/assets"),
]
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "fitz",
    "pypdf",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
]

for package in ("PyQt6", "fitz", "pypdf"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("pagedrop")

a = Analysis(
    [str(ENTRY)],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
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
    a.binaries,
    a.datas,
    [],
    name="pagedrop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
