"""Read canonical app version from pyproject.toml (stdlib only)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def read_version(pyproject: Path = PYPROJECT) -> str:
    text = pyproject.read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    if not match:
        raise SystemExit(f"No version= in {pyproject}")
    return match.group(1)


def msix_version(semver: str) -> str:
    """MSIX Identity Version needs four parts: Major.Minor.Build.Revision."""
    parts = semver.split(".")
    while len(parts) < 4:
        parts.append("0")
    if len(parts) > 4:
        parts = parts[:4]
    return ".".join(parts)


if __name__ == "__main__":
    ver = read_version()
    if len(sys.argv) > 1 and sys.argv[1] == "--msix":
        print(msix_version(ver))
    else:
        print(ver)
