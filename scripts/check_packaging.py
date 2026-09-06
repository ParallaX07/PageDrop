"""Assert packaging helpers stay consistent with pyproject.toml.

  uv run python scripts/check_packaging.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from read_version import read_version  # noqa: E402

NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
SPEC = ROOT / "pagedrop.spec"
LICENSE = ROOT / "LICENSE"


def _assert_notices_content(text: str) -> None:
    """PyQt6 is GPLv3/commercial — not LGPL. Qt remains LGPL; PyMuPDF is AGPL."""
    lower = text.lower()
    assert "pyqt6" in lower, "notices must mention PyQt6"
    assert "gplv3" in lower or "gpl v3" in lower or "gpl-3" in lower, (
        "notices must state PyQt6 as GPLv3"
    )
    # Guard the old mistake: PyQt **License:** line claiming LGPL.
    assert "## PyQt6" in text, "notices must have a PyQt6 section"
    pyqt_section = text.split("## PyQt6", 1)[1].split("\n## ", 1)[0]
    license_lines = [
        ln for ln in pyqt_section.splitlines() if ln.strip().lower().startswith("- **license:**")
    ]
    assert license_lines, "PyQt6 section must include a License line"
    assert "lgpl" not in license_lines[0].lower(), (
        "PyQt6 License line must not claim LGPL (Qt may; PyQt must not)"
    )
    assert "gpl" in license_lines[0].lower(), "PyQt6 License line must state GPL"
    assert "agpl" in lower, "notices must mention PyMuPDF AGPL"
    assert "artifex" in lower, "notices must mention Artifex commercial option"


def _assert_notices_in_spec(spec_text: str) -> None:
    assert "THIRD_PARTY_NOTICES.md" in spec_text, (
        "pagedrop.spec must bundle THIRD_PARTY_NOTICES.md in datas"
    )


def _assert_icons_in_spec(spec_text: str) -> None:
    assert "assets/icons" in spec_text or 'ASSETS / "icons"' in spec_text, (
        "pagedrop.spec must bundle Phosphor SVG icons under pagedrop/assets/icons"
    )
    assert "PyQt6.QtSvg" in spec_text, (
        "pagedrop.spec must collect PyQt6.QtSvg for SVG toolbar icons"
    )


def _assert_onedir_spec(spec_text: str) -> None:
    assert "exclude_binaries=True" in spec_text, (
        "pagedrop.spec must use a thin EXE (exclude_binaries=True) for onedir"
    )
    assert "COLLECT(" in spec_text, "pagedrop.spec must COLLECT into dist/pagedrop/"
    assert "PyQt6.QtPrintSupport" in spec_text, (
        "pagedrop.spec must collect PyQt6.QtPrintSupport for frozen print"
    )


def _onedir_data_root(bundle: Path) -> Path:
    """PyInstaller 6+ puts COLLECT datas under `_internal/`; older layouts use the bundle root."""
    internal = bundle / "_internal"
    return internal if internal.is_dir() else bundle


def _assert_onedir_dist_if_present() -> None:
    """When dist/pagedrop/ exists with an exe, require notices + Phosphor icons."""
    bundle = ROOT / "dist" / "pagedrop"
    if not bundle.is_dir():
        return
    exe_candidates = [bundle / "pagedrop.exe", bundle / "pagedrop"]
    if not any(p.is_file() for p in exe_candidates):
        return
    data_root = _onedir_data_root(bundle)
    notices = data_root / "THIRD_PARTY_NOTICES.md"
    assert notices.is_file() and notices.stat().st_size > 0, (
        f"onedir bundle must include non-empty {notices} "
        f"(rebuild with current pagedrop.spec)"
    )
    icons = data_root / "pagedrop" / "assets" / "icons"
    assert icons.is_dir() and any(icons.iterdir()), (
        f"onedir bundle must include Phosphor icons under {icons}"
    )


def main() -> None:
    ver = read_version()
    assert re.fullmatch(r"\d+\.\d+\.\d+", ver), f"unexpected semver: {ver!r}"

    ico = ROOT / "src" / "pagedrop" / "assets" / "app-icon.ico"
    assert ico.is_file() and ico.stat().st_size > 0, f"missing {ico}"

    iss = ROOT / "installer" / "windows.iss"
    iss_text = iss.read_text(encoding="utf-8")
    assert "pagedrop.exe" in iss_text
    assert "CurrentVersion\\Run" not in iss_text  # no autostart
    assert "AppVersion" in iss_text
    assert "recursesubdirs" in iss_text.lower(), (
        "windows.iss must install the onedir tree (recursesubdirs)"
    )
    assert "dist\\pagedrop" in iss_text or "dist/pagedrop" in iss_text, (
        "windows.iss must source from dist/pagedrop/ onedir output"
    )

    assert NOTICES.is_file() and NOTICES.stat().st_size > 0, f"missing {NOTICES}"
    license_text = LICENSE.read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text, (
        "PageDrop source must be licensed under AGPL-3.0-or-later"
    )
    notices_text = NOTICES.read_text(encoding="utf-8")
    _assert_notices_content(notices_text)

    assert SPEC.is_file(), f"missing {SPEC}"
    spec_text = SPEC.read_text(encoding="utf-8")
    _assert_notices_in_spec(spec_text)
    _assert_icons_in_spec(spec_text)
    _assert_onedir_spec(spec_text)
    _assert_onedir_dist_if_present()

    assert "THIRD_PARTY_NOTICES.md" in iss_text, (
        "windows.iss must install THIRD_PARTY_NOTICES.md beside the exe"
    )

    print(f"ok packaging checks (version {ver})")


if __name__ == "__main__":
    main()
