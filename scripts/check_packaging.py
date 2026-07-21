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

    print(f"ok packaging checks (version {ver})")


if __name__ == "__main__":
    main()
