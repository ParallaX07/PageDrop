#!/usr/bin/env python3
"""Run the full PageDrop test suite.

Usage (from project root, no manual venv activation):

    uv run python all_tests.py
    uv run python all_tests.py -x --tb=short

New phase tests under tests/ are included automatically.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    cmd = [sys.executable, "-m", "pytest", "tests", "-v", *sys.argv[1:]]
    print("Running all tests…")
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
