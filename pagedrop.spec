# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PageDrop — onedir GUI executable."""

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
    "PyQt6.sip",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
]

# PyQt6: widget stack only — skip WebEngine, Bluetooth, Multimedia, etc.
for qt_mod in ("PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets"):
    hiddenimports += collect_submodules(qt_mod)

# Qt DLLs, plugins (platforms/styles/imageformats), and translations are
# collected by PyInstaller's hook-PyQt6.Qt* hooks via add_qt6_dependencies.

# Native PDF lib (keep collect_all — bundled binaries).
for package in ("fitz",):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("pagedrop")
hiddenimports = list(dict.fromkeys(hiddenimports))

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
    [],
    exclude_binaries=True,
    name="pagedrop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="pagedrop",
)
