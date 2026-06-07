"""Phase 7 smoke tests — temp file lifecycle and cleanup."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from pagedrop.core.page_extractor import extract_pages_to_files
from pagedrop.utils.temp_manager import TempManager


def _count_pagedrop_dirs() -> int:
    temp_root = Path(tempfile.gettempdir())
    return sum(
        1
        for entry in temp_root.iterdir()
        if entry.is_dir() and entry.name.startswith("pagedrop_")
    )


def test_five_simulated_extractions_per_drag_cleanup(five_page_pdf):
    tm = TempManager()
    temp_dir = tm.get_dir()
    try:
        for drag_num in range(1, 6):
            drag_dir = tm.create_drag_dir()
            paths = extract_pages_to_files(
                str(five_page_pdf),
                [0],
                drag_dir,
                five_page_pdf.stem,
            )
            assert all(path.exists() for path in paths)
            assert drag_dir.exists()

            tm.cleanup_paths(paths)

            assert not any(path.exists() for path in paths)
            assert not drag_dir.exists()
            assert temp_dir.exists()

        drag_subdirs = list(temp_dir.glob("drag_*"))
        assert drag_subdirs == []
    finally:
        tm.cleanup()


def test_cleanup_removes_run_orphans_from_system_temp():
    tm = TempManager()
    run_dir = tm.get_dir()
    run_name = run_dir.name
    assert run_dir.exists()

    tm.cleanup()

    temp_root = Path(tempfile.gettempdir())
    matching = [d for d in temp_root.iterdir() if d.name == run_name]
    assert matching == []


def test_subprocess_normal_exit_cleans_temp_dir():
    before = _count_pagedrop_dirs()
    code = """
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from pagedrop.ui.main_window import MainWindow

app = QApplication([])
window = MainWindow()
print(window._temp_manager.get_dir())
QTimer.singleShot(50, window.close)
QTimer.singleShot(100, app.quit)
app.exec()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    created_dir = Path(result.stdout.strip())
    assert not created_dir.exists()

    after = _count_pagedrop_dirs()
    assert after <= before


def test_subprocess_force_kill_may_leave_orphan():
    """Document baseline: SIGKILL/taskkill skips atexit, so one orphan may remain."""
    before = _count_pagedrop_dirs()
    code = """
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from pagedrop.ui.main_window import MainWindow

app = QApplication([])
window = MainWindow()
print(window._temp_manager.get_dir(), flush=True)
sys.stdout.flush()
time.sleep(60)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line
        orphan_dir = Path(line)
        assert orphan_dir.exists()

        proc.kill()
        proc.wait(timeout=10)

        after_kill = _count_pagedrop_dirs()
        # Force-kill prevents atexit cleanup; count may increase by one.
        assert after_kill >= before
        assert orphan_dir.exists()

        import shutil

        if orphan_dir.exists():
            shutil.rmtree(orphan_dir, ignore_errors=True)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
