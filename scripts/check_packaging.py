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


def _assert_notices_in_dist_if_present() -> None:
    """Onefile embeds notices in the archive; optional loose copy beside the exe is fine.

    When a onefile binary exists under dist/, do not require an unpacked tree.
    If a loose THIRD_PARTY_NOTICES.md sits next to the exe (installer staging), require it non-empty.
    """
    dist = ROOT / "dist"
    onefile_candidates = [dist / "pagedrop", dist / "pagedrop.exe"]
    if not any(p.is_file() for p in onefile_candidates):
        return
    loose = dist / "THIRD_PARTY_NOTICES.md"
    if loose.is_file():
        assert loose.stat().st_size > 0, f"{loose} is empty"


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

    assert NOTICES.is_file() and NOTICES.stat().st_size > 0, f"missing {NOTICES}"
    notices_text = NOTICES.read_text(encoding="utf-8")
    _assert_notices_content(notices_text)

    assert SPEC.is_file(), f"missing {SPEC}"
    _assert_notices_in_spec(SPEC.read_text(encoding="utf-8"))
    _assert_notices_in_dist_if_present()

    assert "THIRD_PARTY_NOTICES.md" in iss_text, (
        "windows.iss must install THIRD_PARTY_NOTICES.md beside the exe"
    )

    print(f"ok packaging checks (version {ver})")


if __name__ == "__main__":
    main()
