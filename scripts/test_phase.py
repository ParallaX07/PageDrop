#!/usr/bin/env python3
"""Run cumulative PageDrop tests through a given phase.

Usage (from project root, no manual venv activation):

    uv run python scripts/test_phase.py 1
    uv run python scripts/test_phase.py 2
    uv run python scripts/test_phase.py 3
    uv run python scripts/test_phase.py 4

Each phase runs that phase's tests plus all prior phases.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PHASE_PATHS: dict[int, list[str]] = {
    1: [
        "tests/smoke/test_phase1_boot.py",
    ],
    2: [
        "tests/smoke/test_phase1_boot.py",
        "tests/core/test_pdf_loader.py",
        "tests/smoke/test_phase2_pdf_loader.py",
    ],
    3: [
        "tests/smoke/test_phase1_boot.py",
        "tests/core/test_pdf_loader.py",
        "tests/smoke/test_phase2_pdf_loader.py",
        "tests/ui/test_main_window.py",
        "tests/smoke/test_phase3_main_window.py",
    ],
    4: [
        "tests/smoke/test_phase1_boot.py",
        "tests/core/test_pdf_loader.py",
        "tests/smoke/test_phase2_pdf_loader.py",
        "tests/ui/test_main_window.py",
        "tests/smoke/test_phase3_main_window.py",
        "tests/ui/test_page_card.py",
        "tests/ui/test_thumbnail_grid.py",
        "tests/smoke/test_phase4_thumbnail_grid.py",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        type=int,
        choices=sorted(PHASE_PATHS),
        help="Highest phase to include (1–4); earlier phases are included too.",
    )
    parser.add_argument(
        "pytest_args",
        nargs="*",
        help="Extra arguments forwarded to pytest (e.g. -x --tb=short)",
    )
    args = parser.parse_args()

    paths = PHASE_PATHS[args.phase]
    cmd = [sys.executable, "-m", "pytest", *paths, "-v", *args.pytest_args]
    print(f"Running phase {args.phase} gate ({len(paths)} modules)…")
    print(" ", " ".join(paths))
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
